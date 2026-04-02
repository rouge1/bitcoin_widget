#!/usr/bin/env python3
"""Bitcoin price widget — AppIndicator3 tray label with graph popup."""

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


SOCKET_PATH = "/tmp/bitcoin_widget.sock"


class BitcoinWidget:
    def __init__(self):
        self._cached_graph: GdkPixbuf.Pixbuf | None = None
        self._graph_days = config.load_graph_days()
        self._auto_show_graph = False
        self._graph_window = GraphWindow()

        # --- Live price (shared with graph renderer) ---
        self._live_price = None
        self._live_change = None

        # --- Diagnostic state ---
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

        # --- Diagnostic socket ---
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

        item_refresh = Gtk.MenuItem(label="Refresh Now")
        item_refresh.connect("activate", self._on_refresh)
        menu.append(item_refresh)

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

        self._item_autostart = Gtk.CheckMenuItem(label="Start on Login")
        self._item_autostart.set_active(autostart.is_enabled())
        self._item_autostart.connect("toggled", self._on_autostart_toggled)
        menu.append(self._item_autostart)

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
        self._live_price = price
        self._live_change = change_24h
        now = time.time()
        self._state["label"] = {"text": label, "price": price, "change": round(change_24h, 2), "updated": now}
        self._state["api"] = {"price": price, "change": round(change_24h, 2), "source": self._fetcher.last_price_source, "updated": now}
        return False

    def _on_history_update(self, points: list):
        self._last_history_points = points
        threading.Thread(
            target=self._render_graph_bg,
            args=(points, self._graph_days),
            daemon=True,
        ).start()
        return False

    def _render_graph_bg(self, points, days):
        pixbuf = render_graph(points, days=days,
                              live_price=self._live_price,
                              live_change=self._live_change)
        if pixbuf:
            GLib.idle_add(self._cache_graph, pixbuf, points, days)

    def _cache_graph(self, pixbuf, points=None, days=None):
        self._cached_graph = pixbuf
        self._item_show_graph.set_sensitive(True)
        if points:
            display_price = self._live_price if self._live_price is not None else points[-1][1]
            display_change = self._live_change if self._live_change is not None else (
                (points[-1][1] - points[0][1]) / points[0][1] * 100
            )
            self._state["graph"] = {
                "price": round(display_price, 2),
                "change": round(display_change, 2),
                "points": len(points),
                "days": days or self._graph_days,
                "updated": time.time(),
            }
        if self._auto_show_graph or self._graph_window.get_visible():
            self._auto_show_graph = False
            self._graph_window.show_graph(pixbuf, reuse_pos=True)
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

    def _on_timeframe_toggled(self, item, days):
        if item.get_active() and days != self._graph_days:
            self._graph_days = days
            config.save_graph_days(days)
            self._fetcher.set_history_days(days)
            self._cached_graph = None
            self._item_show_graph.set_sensitive(False)
            self._auto_show_graph = True
            self._fetcher.refresh()

    def _on_autostart_toggled(self, item):
        if item.get_active():
            autostart.enable()
        else:
            autostart.disable()

    def _on_refresh(self, _):
        self._indicator.set_label("BTC ↻ …", "BTC $999,999 ▼99.9%")
        self._fetcher.refresh()

    def _on_quit(self, _):
        self._fetcher.stop()
        Gtk.main_quit()

    # ------------------------------------------------------------------ #
    #  Diagnostic socket                                                   #
    # ------------------------------------------------------------------ #

    def _start_socket_server(self):
        # Clean up stale socket
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(SOCKET_PATH)
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
        self._fetcher.start()
        Gtk.main()
        # cleanup socket on exit
        try:
            self._sock.close()
            os.unlink(SOCKET_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    app = BitcoinWidget()
    app.run()
