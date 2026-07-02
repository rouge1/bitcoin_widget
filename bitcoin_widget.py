#!/usr/bin/env python3
"""Bitcoin price widget — AppIndicator3 tray label with graph popup."""

import argparse
import sys
import os
import base64
import json
import socket
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
from gi.repository import AyatanaAppIndicator3 as AppIndicator3

import config
import autostart
from price_fetcher import PriceFetcher
from graph_renderer import render_graph
from web_window import WebGraphWindow

ICON_NAME = "utilities-system-monitor"


SOCKET_PATH = str(config._SETTINGS_DIR / "diag.sock")

# Abstract-namespace socket name (leading NUL) used purely as a single-instance
# lock. Abstract sockets are released automatically when the process exits, so
# there is no stale file to clean up after a crash.
_LOCK_ADDR = "\0bitcoin-widget.lock"
_lock_sock = None


def acquire_single_instance() -> bool:
    """Return True if we are the only instance; False if one is already running."""
    global _lock_sock
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(_LOCK_ADDR)
    except OSError:
        sock.close()
        return False
    _lock_sock = sock  # keep alive so the lock is held until exit
    return True


class BitcoinWidget:
    def __init__(self, diag=False):
        self._diag = diag
        self._sock = None
        self._cached_points = None
        # Per-timeframe cache: {days: points} — survives day switches, so a
        # switch back re-draws instantly while the fresh fetch lands.
        self._tf_cache: dict[int, list] = {}
        # Last-known equity quotes {symbol: (price, change_pct)} for the graph
        self._stock_quotes: dict[str, tuple] = {}
        self._graph_days = config.load_graph_days()
        self._show_candles = config.load_show_candles()
        self._auto_show_graph = False
        self._graph_window = WebGraphWindow()

        # --- Diagnostic state (single source of truth for live values) ---
        self._debug_log = []
        self._state = {
            "label": {"text": "BTC …", "price": None, "change": None, "updated": None},
            "graph": {"price": None, "change": None, "points": 0, "days": self._graph_days, "updated": None},
            "api": {"price": None, "change": None, "source": None, "updated": None},
            "stocks": {"quotes": {}, "updated": None},
        }

        # --- Price fetcher (created before menu so handlers can reference it) ---
        self._fetcher = PriceFetcher(
            price_callback=self._on_price_update,
            history_callback=self._on_history_update,
            stocks_callback=self._on_stocks_update,
        )

        # --- AppIndicator ---
        self._indicator = AppIndicator3.Indicator.new(
            "bitcoin-widget",
            ICON_NAME,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_label("BTC …", "BTC $999,999 ▼99.9%")
        self._indicator.set_menu(self._build_menu())

        # --- Diagnostic socket (only with --diag) ---
        if self._diag:
            self._start_socket_server()

    def _log(self, msg):
        entry = {"t": round(time.time(), 3), "msg": msg}
        self._debug_log.append(entry)
        if len(self._debug_log) > 50:
            self._debug_log.pop(0)

    # ------------------------------------------------------------------ #
    #  Menu                                                                #
    # ------------------------------------------------------------------ #

    def _build_menu(self):
        menu = Gtk.Menu()

        group = []
        for label, days in [("1 Day", 1), ("7 Days", 7), ("30 Days", 30)]:
            item = Gtk.RadioMenuItem.new_with_label(group, label)
            group = item.get_group()
            if days == self._graph_days:
                item.set_active(True)
            item.connect("activate", self._on_timeframe_activated, days)
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        self._item_candle_toggle = Gtk.MenuItem(
            label="Show Lines" if self._show_candles else "Show Candles"
        )
        self._item_candle_toggle.connect("activate", self._on_candles_toggled)
        menu.append(self._item_candle_toggle)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_quit)
        menu.append(item_quit)

        menu.show_all()
        return menu

    def _toggle_graph(self):
        visible = self._graph_window.get_visible()
        has_graph = self._cached_points is not None
        self._log(f"toggle_graph visible={visible} has_cached={has_graph}")
        if visible:
            self._graph_window.hide()
        elif has_graph:
            self._push_series()
            self._graph_window.show_at(reuse_pos=False)
        return False

    # ------------------------------------------------------------------ #
    #  Price / history callbacks (run on GTK main thread via idle_add)    #
    # ------------------------------------------------------------------ #

    def _on_price_update(self, price: float, change_24h: float):
        arrow = "▲" if change_24h >= 0 else "▼"
        label = f"BTC ${price:,.0f} {arrow}{abs(change_24h):.1f}%"
        self._indicator.set_label(label, "BTC $999,999 ▼99.9%")
        now = time.time()
        self._state["label"] = {"text": label, "price": price, "change": round(change_24h, 2), "updated": now}
        self._state["api"] = {"price": price, "change": round(change_24h, 2), "source": self._fetcher.last_price_source, "updated": now}
        self._push_ticker()
        self._push_meta(live=True)
        return False

    def _on_history_update(self, points: list):
        days = self._graph_days
        self._cached_points = points
        self._tf_cache[days] = points
        live_price = self._state["api"]["price"]
        endpoint = live_price if live_price is not None else points[-1][4]
        baseline = points[0][4]
        tf_change = (endpoint - baseline) / baseline * 100 if baseline else 0.0
        self._state["graph"] = {
            "price": round(endpoint, 2), "change": round(tf_change, 2),
            "points": len(points), "days": days, "updated": time.time(),
        }
        self._log(f"history days={days} points={len(points)}")
        # Push the raw series to the canvas (it draws client-side — no matplotlib
        # in the hot path). Sweep the entrance in only when re-opening the popup.
        self._graph_window.set_series(points, days, self._show_candles,
                                      transition=self._auto_show_graph)
        self._push_meta(live=True)
        self._push_ticker()   # BTC baseline / sparkline may have shifted
        if self._auto_show_graph:
            self._auto_show_graph = False
            self._graph_window.show_at(reuse_pos=True)
        return False

    def _on_stocks_update(self, quotes: dict):
        # Merge (don't replace) so a transient fetch failure keeps last-known
        # prices instead of flashing "n/a".
        self._stock_quotes.update(quotes)
        self._state["stocks"] = {
            "quotes": {s: [round(v[0], 2), round(v[1], 2)] for s, v in self._stock_quotes.items()},
            "updated": time.time(),
        }
        self._push_ticker()
        return False

    @staticmethod
    def _downsample(vals, n):
        """Thin a value list down to ~n evenly-spaced points (for a sparkline)."""
        if len(vals) <= n:
            return [round(float(v), 2) for v in vals]
        step = len(vals) / n
        return [round(float(vals[min(len(vals) - 1, int(i * step))]), 2) for i in range(n)]

    def _ticker_rows(self):
        """Rows for the scrolling tape: (sym, price, change, spark).
        BTC's change is timeframe-relative; its sparkline is the chart series."""
        price = self._state["api"]["price"]
        btc_spark = (self._downsample([p[4] for p in self._cached_points], config.SPARK_POINTS)
                     if self._cached_points else None)
        if price is None:
            rows = [("BTC", None, 0.0, None)]
        elif self._cached_points:
            base = self._cached_points[0][4]
            rows = [("BTC", price, (price - base) / base * 100 if base else 0.0, btc_spark)]
        else:
            rows = [("BTC", price, self._state["api"]["change"] or 0.0, None)]
        for symbol in config.STOCK_SYMBOLS:
            q = self._stock_quotes.get(symbol)
            rows.append((symbol, q[0] if q else None, q[1] if q else None,
                         q[2] if q and len(q) > 2 else None))
        return rows

    def _push_ticker(self):
        rows = self._ticker_rows()
        _, price, change, _ = rows[0]   # BTC → the header hero (not the tape)
        self._graph_window.set_hero(price, change if price is not None else None)
        # The tape carries only the proxies (MSTR/STRC) — BTC is the hero now.
        quotes = [{"sym": s, "price": p, "change": c, "spark": sp} for s, p, c, sp in rows[1:]]
        self._graph_window.set_quotes(quotes)

    def _push_series(self, transition=False):
        """(Re)draw the popup's canvas chart from the cached points."""
        if self._cached_points:
            self._graph_window.set_series(
                self._cached_points, self._graph_days, self._show_candles, transition=transition)

    def _push_meta(self, live=True):
        """Header meta: timeframe, freshness, and the 'as of HH:MM · block' line."""
        tf = {1: "24H", 7: "7D", 30: "30D"}.get(self._graph_days, f"{self._graph_days}D")
        self._graph_window.set_meta(
            timeframe=tf, live=live,
            asof=time.strftime("%H:%M"),
            block=self._fetcher.last_block_height,
        )

    # ------------------------------------------------------------------ #
    #  Menu callbacks                                                      #
    # ------------------------------------------------------------------ #

    def _on_candles_toggled(self, _):
        self._show_candles = not self._show_candles
        config.save_show_candles(self._show_candles)
        self._item_candle_toggle.set_label(
            "Show Lines" if self._show_candles else "Show Candles"
        )
        # Canvas re-draws from cached points instantly — no re-fetch, no re-render.
        self._push_series()

    def _on_timeframe_activated(self, item, days):
        if days != self._graph_days:
            self._graph_days = days
            config.save_graph_days(days)
            self._fetcher.set_history_days(days)
            self._push_meta(live=False)  # stale until refetch lands
            cached = self._tf_cache.get(days)
            if cached:
                # Show cached instantly (entrance sweep), then refresh in background
                self._cached_points = cached
                reuse = self._graph_window.get_visible()
                self._graph_window.set_series(cached, days, self._show_candles, transition=True)
                self._push_ticker()
                self._graph_window.show_at(reuse_pos=reuse)
                self._auto_show_graph = False
            else:
                self._cached_points = None
                self._auto_show_graph = True
            self._fetcher.refresh()
        elif self._cached_points is not None:
            reuse = self._graph_window.get_visible()
            self._push_series(transition=True)
            self._graph_window.show_at(reuse_pos=reuse)

    def _on_quit(self, _):
        self._fetcher.stop()
        Gtk.main_quit()

    # ------------------------------------------------------------------ #
    #  Diagnostic socket                                                   #
    # ------------------------------------------------------------------ #

    def _start_socket_server(self):
        config._SETTINGS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o600)
        self._sock.listen(4)
        threading.Thread(target=self._socket_loop, daemon=True).start()

    def _socket_loop(self):
        while True:
            try:
                conn, _ = self._sock.accept()
                with conn:
                    conn.settimeout(0.5)
                    try:
                        req = conn.recv(64).decode().strip()
                    except (OSError, socket.timeout):
                        req = ""
                    if req == "graph":
                        # The rendered chart pixbuf (plot only) as base64 PNG.
                        response = json.dumps({"graph_png_b64": self._graph_png_b64()}) + "\n"
                    elif req == "window":
                        # The whole live WebKit window (header + chart + ticker) as base64 PNG.
                        response = json.dumps({"window_png_b64": self._window_png_b64()}) + "\n"
                    elif req in ("show", "hide"):
                        response = json.dumps({req: self._diag_set_visible(req == "show")}) + "\n"
                    else:
                        out = dict(self._state)
                        out["debug_log"] = list(self._debug_log)
                        response = json.dumps(out, indent=2) + "\n"
                    conn.sendall(response.encode())
            except OSError:
                break

    def _graph_png_b64(self):
        """Base64 PNG of the chart, rendered on demand from cached points via
        matplotlib. The popup itself now draws on a canvas; this standalone
        'plot only' render is kept as a diagnostic. Returns None if no data."""
        points = self._cached_points
        if not points:
            return None
        try:
            pixbuf = render_graph(points, days=self._graph_days,
                                  show_candles=self._show_candles, header=False)
            if pixbuf is None:
                return None
            ok, data = pixbuf.save_to_bufferv("png", [], [])
        except Exception:
            return None
        return base64.b64encode(data).decode() if ok else None

    def _run_on_main(self, fn, timeout=4.0):
        """Run fn() on the GTK main thread and block for its result: (value, error).
        GTK/Gdk calls must not run on the socket's daemon thread."""
        box, done = {}, threading.Event()
        def wrapper():
            try:
                box["value"] = fn()
            except Exception as e:  # noqa: BLE001
                box["error"] = e
            done.set()
            return False
        GLib.idle_add(wrapper)
        done.wait(timeout)
        return box.get("value"), box.get("error")

    def _diag_set_visible(self, show):
        def do():
            if show:
                self._push_series()
                self._graph_window.show_at(reuse_pos=False)
            else:
                self._graph_window.hide()
            return True
        value, _ = self._run_on_main(do)
        return bool(value)

    def _window_png_b64(self):
        """Grab the actual on-screen window (chart + ticker child) as base64 PNG."""
        def grab():
            win = self._graph_window
            if not win.get_visible():
                return None
            gdkwin = win.get_window()
            if gdkwin is None:
                return None
            pb = Gdk.pixbuf_get_from_window(gdkwin, 0, 0, gdkwin.get_width(), gdkwin.get_height())
            if pb is None:
                return None
            ok, data = pb.save_to_bufferv("png", [], [])
            return base64.b64encode(data).decode() if ok else None
        value, _ = self._run_on_main(grab)
        return value

    # ------------------------------------------------------------------ #
    #  Run                                                                 #
    # ------------------------------------------------------------------ #

    def run(self):
        if not autostart._is_current():
            autostart.enable()
        self._fetcher.start()
        Gtk.main()
        if self._sock:
            try:
                self._sock.close()
                os.unlink(SOCKET_PATH)
            except OSError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bitcoin price tray widget")
    parser.add_argument("--diag", action="store_true",
                        help="Enable diagnostic socket at ~/.config/bitcoin-widget/diag.sock")
    args = parser.parse_args()
    if not acquire_single_instance():
        print("bitcoin-widget is already running; exiting.", file=sys.stderr)
        sys.exit(0)
    app = BitcoinWidget(diag=args.diag)
    app.run()
