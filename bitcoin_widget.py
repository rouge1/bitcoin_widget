#!/usr/bin/env python3
"""Bitcoin price widget — AppIndicator3 tray label with graph popup."""

import argparse
import sys
import os
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

ICON_NAME = "utilities-system-monitor"


class GraphWindow(Gtk.Window):
    """Small popup window that shows the price graph, closes on focus loss."""

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._last_pos = None
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)

        self._image = Gtk.Image()
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        frame.add(self._image)
        self.add(frame)

        self.connect("focus-out-event", lambda *_: None)
        self.connect("key-press-event", self._on_key)
        self.connect("button-press-event", lambda *_: self.hide())

    def _on_key(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide()

    def update_pixbuf(self, pixbuf: GdkPixbuf.Pixbuf):
        """Update the image without stealing focus (for live refreshes)."""
        self._image.set_from_pixbuf(pixbuf)

    def show_graph(self, pixbuf: GdkPixbuf.Pixbuf, reuse_pos=False):
        """Display pixbuf. Repositions only when not reusing a saved position."""
        self._image.set_from_pixbuf(pixbuf)
        self.resize(pixbuf.get_width(), pixbuf.get_height())

        if not reuse_pos or self._last_pos is None:
            display = Gdk.Display.get_default()
            seat = display.get_default_seat()
            _, mx, _ = seat.get_pointer().get_position()
            monitor = display.get_monitor_at_point(mx, 0)
            workarea = monitor.get_workarea()  # excludes panels

            w, h = pixbuf.get_width(), pixbuf.get_height()
            x = max(workarea.x, min(mx - w // 2, workarea.x + workarea.width - w))
            y = workarea.y + 4  # just below the panel

            self._last_pos = (x, y)

        self.move(*self._last_pos)
        self.show_all()
        self.present()


SOCKET_PATH = str(config._SETTINGS_DIR / "diag.sock")


class BitcoinWidget:
    def __init__(self, diag=False):
        self._diag = diag
        self._sock = None
        self._cached_graph: GdkPixbuf.Pixbuf | None = None
        self._cached_points = None
        self._graph_days = config.load_graph_days()
        self._show_candles = config.load_show_candles()
        self._auto_show_graph = False
        self._graph_window = GraphWindow()

        # --- Diagnostic state (single source of truth for live values) ---
        self._state = {
            "label": {"text": "BTC …", "price": None, "change": None, "updated": None},
            "graph": {"price": None, "change": None, "points": 0, "days": self._graph_days, "updated": None},
            "api": {"price": None, "change": None, "source": None, "updated": None},
        }

        # --- AppIndicator ---
        self._indicator = AppIndicator3.Indicator.new(
            "bitcoin-widget",
            ICON_NAME,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_label("BTC …", "BTC $999,999 ▼99.9%")
        self._indicator.set_menu(self._build_menu())

        # --- Price fetcher ---
        self._fetcher = PriceFetcher(
            price_callback=self._on_price_update,
            history_callback=self._on_history_update,
        )

        # --- Diagnostic socket (only with --diag) ---
        if self._diag:
            self._start_socket_server()

    # ------------------------------------------------------------------ #
    #  Menu                                                                #
    # ------------------------------------------------------------------ #

    def _build_menu(self):
        menu = Gtk.Menu()

        self._item_show_graph = Gtk.MenuItem(label="Show Graph")
        self._item_show_graph.connect("activate", self._on_show_graph)
        self._item_show_graph.set_sensitive(False)  # until graph is ready
        menu.append(self._item_show_graph)

        menu.append(Gtk.SeparatorMenuItem())

        # Timeframe radio group
        tf_header = Gtk.MenuItem(label="Graph Timeframe")
        tf_header.set_sensitive(False)
        menu.append(tf_header)

        group = []
        for label, days in [("1 Day", 1), ("7 Days", 7), ("30 Days", 30)]:
            item = Gtk.RadioMenuItem.new_with_label(group, label)
            group = item.get_group()
            if days == self._graph_days:
                item.set_active(True)
            item.connect("toggled", self._on_timeframe_toggled, days)
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
        return False

    def _on_history_update(self, points: list):
        self._cached_points = points
        threading.Thread(
            target=self._render_graph_bg,
            args=(points, self._graph_days),
            daemon=True,
        ).start()
        return False

    def _render_graph_bg(self, points, days):
        live_price = self._state["api"]["price"]
        live_change = self._state["api"]["change"]
        pixbuf = render_graph(points, days=days,
                              live_price=live_price,
                              live_change=live_change,
                              show_candles=self._show_candles)
        if pixbuf:
            graph_state = {
                "price": round(live_price, 2) if live_price else round(points[-1][4], 2),
                "change": round(live_change, 2) if live_change else round((points[-1][4] - points[0][4]) / points[0][4] * 100, 2),
                "points": len(points),
                "days": days,
                "updated": time.time(),
            }
            GLib.idle_add(self._cache_graph, pixbuf, graph_state)

    def _cache_graph(self, pixbuf, graph_state):
        self._cached_graph = pixbuf
        self._item_show_graph.set_sensitive(True)
        self._state["graph"] = graph_state
        if self._auto_show_graph:
            self._auto_show_graph = False
            self._graph_window.show_graph(pixbuf, reuse_pos=True)
        elif self._graph_window.get_visible():
            self._graph_window.update_pixbuf(pixbuf)
        return False

    # ------------------------------------------------------------------ #
    #  Graph popup                                                         #
    # ------------------------------------------------------------------ #

    def _on_show_graph(self, _):
        if self._graph_window.get_visible():
            self._graph_window.hide()
        elif self._cached_graph:
            self._graph_window.show_graph(self._cached_graph, reuse_pos=False)

    # ------------------------------------------------------------------ #
    #  Menu callbacks                                                      #
    # ------------------------------------------------------------------ #

    def _on_candles_toggled(self, _):
        self._show_candles = not self._show_candles
        config.save_show_candles(self._show_candles)
        self._item_candle_toggle.set_label(
            "Show Lines" if self._show_candles else "Show Candles"
        )
        if self._cached_points:
            self._on_history_update(self._cached_points)

    def _on_timeframe_toggled(self, item, days):
        if item.get_active() and days != self._graph_days:
            self._graph_days = days
            config.save_graph_days(days)
            self._fetcher.set_history_days(days)
            self._cached_graph = None
            self._cached_points = None
            self._item_show_graph.set_sensitive(False)
            self._auto_show_graph = True
            self._fetcher.refresh()

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
                    response = json.dumps(self._state, indent=2) + "\n"
                    conn.sendall(response.encode())
            except OSError:
                break

    # ------------------------------------------------------------------ #
    #  Run                                                                 #
    # ------------------------------------------------------------------ #

    def run(self):
        if not autostart.is_enabled():
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
    app = BitcoinWidget(diag=args.diag)
    app.run()
