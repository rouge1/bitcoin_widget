"""The popup graph window, implemented as a WebKit page.

Hosts a `WebKit2.WebView` loading `web/widget.html` (HTML header + a JS/canvas
chart + a requestAnimationFrame ticker). Python pushes data into the page via JS:
`set_series` (raw OHLCV → the canvas draws it), `set_quotes`, `set_meta`. The page
posts a `control` message on click / Escape so we can hide, matching old behaviour."""
import os
import json

import gi
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, WebKit2

import config

_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "widget.html")
_BASE_URI = "file://" + os.path.dirname(_HTML_PATH) + "/"
_BG = Gdk.RGBA(0x0C / 255, 0x0D / 255, 0x11 / 255, 1.0)   # match page --ink, no white flash


class WebGraphWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._last_pos = None
        self._loaded = False
        self._pending = []          # JS queued until the page finishes loading
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.set_default_size(config.WEB_WIDTH, config.WEB_HEIGHT)

        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("control")
        ucm.connect("script-message-received::control", self._on_control)
        self._webview = WebKit2.WebView.new_with_user_content_manager(ucm)
        self._webview.set_background_color(_BG)
        self._webview.connect("load-changed", self._on_load)

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        frame.add(self._webview)
        self.add(frame)

        with open(_HTML_PATH) as f:
            self._webview.load_html(f.read(), _BASE_URI)

    # ------------------------------------------------------------------ #
    #  Page load / JS bridge                                              #
    # ------------------------------------------------------------------ #

    def _on_load(self, _view, event):
        if event == WebKit2.LoadEvent.FINISHED:
            self._loaded = True
            for js in self._pending:
                self._webview.run_javascript(js)
            self._pending = []

    def _on_control(self, _mgr, value):
        try:
            action = value.get_js_value().to_string()
        except Exception:
            action = ""
        if action == "hide":
            self.hide()

    def _js(self, js):
        if self._loaded:
            self._webview.run_javascript(js)
        else:
            self._pending.append(js)

    # ------------------------------------------------------------------ #
    #  Python → page                                                      #
    # ------------------------------------------------------------------ #

    def set_series(self, points, days, candles, transition=False):
        """Push the raw OHLCV series to the page; the canvas draws it client-side.
        transition=True plays the left-to-right entrance sweep (timeframe switch)."""
        payload = {"points": points or [], "days": days,
                   "candles": bool(candles), "transition": bool(transition)}
        self._js("window.setSeries(%s)" % json.dumps(payload))

    def set_quotes(self, quotes):
        self._js("window.setQuotes(%s)" % json.dumps(quotes))

    def set_hero(self, price, change):
        """Update the header hero price (odometer roll) + timeframe-relative change."""
        self._js("window.setHero(%s)" % json.dumps({"price": price, "change": change}))

    def set_meta(self, **meta):
        self._js("window.setMeta(%s)" % json.dumps(meta))

    # ------------------------------------------------------------------ #
    #  Window control                                                     #
    # ------------------------------------------------------------------ #

    def show_at(self, reuse_pos=False):
        """Position (below the panel, near the mouse x) and present the window."""
        if self.get_visible():
            self._last_pos = self.get_position()
        if not reuse_pos or self._last_pos is None:
            display = Gdk.Display.get_default()
            _, mx, _ = display.get_default_seat().get_pointer().get_position()
            workarea = display.get_monitor_at_point(mx, 0).get_workarea()
            w = config.WEB_WIDTH
            x = max(workarea.x, min(mx - w // 2, workarea.x + workarea.width - w))
            self._last_pos = (x, workarea.y + 4)
        self.move(*self._last_pos)
        self.show_all()
        self.present()

    def window_png(self):
        """PNG bytes of the live on-screen window (for diagnostics), or None."""
        gw = self.get_window()
        if gw is None:
            return None
        pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
        if pb is None:
            return None
        ok, data = pb.save_to_bufferv("png", [], [])
        return data if ok else None
