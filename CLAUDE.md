# CLAUDE.md — Bitcoin Widget

## Project Overview
GTK3 system tray applet showing live BTC/USD price with a historical price graph popup. Runs on Linux with Ayatana AppIndicator3.

## File Structure
```
bitcoin_widget.py   # Main app: tray indicator, menu, orchestration, diag socket
price_fetcher.py    # Background polling thread, Coinbase → Kraken fallback (+ Yahoo equities)
graph_renderer.py   # matplotlib chart → GdkPixbuf (line + candlestick); now DIAG-ONLY
web_window.py       # The popup: a WebKit2.WebView hosting web/widget.html
web/widget.html     # The popup UI: price hero + JS/canvas chart + PROXIES ticker
                    #   (all rendering, type identity + interactivity — CSS/JS)
config.py           # All constants: URLs, intervals, colours, dimensions, persisted prefs
autostart.py        # XDG ~/.config/autostart/ .desktop file management
```

## Running
```bash
/usr/bin/python3 bitcoin_widget.py &
```
Use the **system** `python3` (`/usr/bin/python3`) — it has the `gi`/GTK bindings.
A bare `python3` may resolve to a conda/venv interpreter without PyGObject and
fail with `ModuleNotFoundError: No module named 'gi'`. Needs an X display
(`DISPLAY=:1` on this box).

## Dependencies
```
requests
matplotlib
pygobject          # gi: GTK3, GdkPixbuf, GLib, AyatanaAppIndicator3, WebKit2 4.1
```

Install:
```bash
sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1 gir1.2-webkit2-4.1
pip install requests matplotlib
```
The popup UI is a WebKit page, so `gir1.2-webkit2-4.1` (WebKitGTK for GTK3) is
required. On a headless X display WebKit logs a one-line "Disabled hardware
acceleration … Unable to create a GL context" warning and falls back to software
rendering — harmless.

## Architecture

### Threading model
- GTK main thread owns all UI
- `PriceFetcher` runs a daemon thread polling on `POLL_INTERVAL_SECONDS`
- All callbacks into GTK use `GLib.idle_add()` — never update UI from the fetch thread directly
- The popup chart is drawn **in the page** (canvas/JS), so history updates just push the
  raw series to the WebView — no matplotlib in the hot path, no render thread. `graph_renderer`
  (matplotlib) is now rendered lazily *only* for the diag `graph` command.

### Price fetching — Coinbase → Kraken fallback
Both price and history have independent try/except fallback:
```
_fetch_price()    → _coinbase_price()  → _kraken_price()
_fetch_history()  → _coinbase_history() → _kraken_history()
```
Any exception silently falls through to the next source.

### API endpoints
| Source | Endpoint | Data |
|--------|----------|------|
| Coinbase | `api.exchange.coinbase.com/products/BTC-USD/stats` | price + 24h open (for % change) |
| Coinbase | `api.exchange.coinbase.com/products/BTC-USD/candles` | OHLCV `[time_s, low, high, open, close, vol]` newest-first |
| Kraken | `api.kraken.com/0/public/Ticker?pair=XBTUSD` | price + 24h open |
| Kraken | `api.kraken.com/0/public/OHLC?pair=XBTUSD` | OHLC `[time_s, o, h, l, c, vwap, vol, count]` |
| Yahoo | `query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m` | equity price + prev close + intraday closes (quote block + sparkline) |
| mempool.space | `mempool.space/api/blocks/tip/height` | BTC chain tip height (plain int) for the header `as of · block` line |

Candle granularity auto-selects: 1d→`300s/5min`, 7d→`3600s/1h`, 30d→`86400s/1d`.

### Related equities (MSTR / STRC)
`price_fetcher._fetch_stocks()` polls Yahoo Finance (`config.STOCK_SYMBOLS`) for each ticker, yielding `{symbol: (price, change_pct, spark)}` — `price`/`change` from `meta.regularMarketPrice` + `chartPreviousClose`, and `spark` a ~32-point downsample (`_sparkline`, `config.SPARK_POINTS`) of the intraday `interval=5m` closes for the ticker sparkline. No API key; needs a `User-Agent` header or Yahoo 403s. Fetches are throttled to `STOCK_MIN_INTERVAL` (60s) so the fast 1d crypto poll (10s) doesn't hammer Yahoo. The widget *merges* quotes into `self._stock_quotes` (a transient failure keeps the last-known price rather than flashing `n/a`). The equities are the **proxies** row of the web ticker (BTC itself is the header hero, not in the tape).

### The popup is a WebKit page (chart drawn on a `<canvas>`)
The graph popup is a `WebKit2.WebView` (`web_window.py`) loading `web/widget.html`. Layout, top→bottom: a **header** (an eyebrow row — `BTC/USD` with **BTC** in gold + an `as of HH:MM · block N` ledger line + timeframe — over a **price hero**: the big BTC price with its % change), the **chart** (an HTML `<canvas>` the page draws itself), and a **`PROXIES` chyron** (fixed label + divider, then the scrolling MSTR/STRC). Data flows Python→page via `run_javascript`:
- `window.setSeries({points, days, candles, transition})` — the raw OHLCV (`[[ts_ms,o,h,l,c],…]`); the canvas draws it client-side (line+glow or candles). `transition:true` plays the left-to-right entrance sweep (timeframe switch / re-open); routine polls pass `false`.
- `window.setHero({price, change})` — the header hero BTC price (odometer roll) + timeframe-relative change. Driven from `_push_ticker` off `_ticker_rows()[0]`.
- `window.setQuotes([{sym,price,change,spark}, …])` — the **proxies** tape cells (MSTR/STRC only; `_push_ticker` passes `rows[1:]`). `spark` is a small close series; `price:null` → `n/a`.
- `window.setMeta({timeframe, live, asof, block})` — timeframe + the `as of HH:MM · block N` ledger line (replaces the old `● LIVE` dot; `live:false` dims it during a timeframe refetch). `_push_meta` supplies `asof` (`time.strftime("%H:%M")`) and `block` (`PriceFetcher.last_block_height`, throttled `mempool.space` fetch).

**Type identity**: data (hero, ticks, prices, tooltip) is **Source Code Pro**; uppercase instrument-panel labels (eyebrow, the `as of` line, `PROXIES`, ticker symbols) are **Ubuntu Condensed** — `--face-data` / `--face-label` in `:root`. Both are installed locally (no web-font fetch).

**Canvas chart** (all in `widget.html`): DPR-scaled for crispness, orange line with a gold→transparent glow-fill (or mint/coral candles), a live node at the latest point, hairline y-grid with compact `60k` labels, local-time x-axis. **Candle density**: raw candles are aggregated to ~`PW/6` buckets of real OHLC (`aggregate()` — first open, last close, bucket high/low) so 288 5-min bars don't become a 1px picket fence; the line uses every point. **Hover** draws a dashed crosshair + a ringed node + a floating price/time tooltip; **clicking the plot pins** it (filled node) so it survives mouse-leave — click again / Escape unpins, and `setSeries(transition)` clears the pin. Clicks *outside* the plot still bubble to the body → hide the window. (`__diagHover(frac)` / `__diagUnhover` drive hover for screenshots.) The entrance sweep clips the series to a growing left→right rect (candles also grow from their midline).

**Ticker** scrolls via `requestAnimationFrame` + `translate3d` (constant px/sec) inside a `.tape-view` viewport beside the fixed `PROXIES` label, under a CSS edge-fade `mask`. `buildTape` repeats the cell sequence into a "unit" ≥ the viewport width, then lays two units, so a short list (2 proxies) still wraps seamlessly. Prices are **odometer digit-rolls** (shared `applyRoll`, also used by the hero price): each price is a row of overflow-clipped `.slot`s; on change, changed digit slots roll vertically (`.roll` translateY, direction = price up/down) and the price flashes green/red. **`.roll` must be a `<div>`** — as a `<span>` the `.slot > span` digit rule also matches it, collapses it to one line height, and the two digits lay out inline (they bunch/cut instead of rolling; this was a real bug). Each row has an SVG **sparkline**. The tape only rebuilds when the symbol *set* changes; otherwise cells update in place — so cellHTML **always** emits `.spark-box`/`.ch` placeholders (even empty), or an `n/a→data` transition would have nothing to fill (was a real bug).

Calls before the page's `load-changed → FINISHED` are queued in `_pending` and flushed on load. The page posts a `control`/`hide` message on body click or Escape; `web_window._on_control` reads it via `value.get_js_value().to_string()` and hides.

### "Treasury Terminal" chart (`graph_renderer.py`) — diag-only
`render_graph` (matplotlib) is **no longer used by the popup** — the canvas draws the live chart. It survives as the diag `graph` command's on-demand render (rendered from `self._cached_points`), so it's a handy "reference" image. It builds just the plot with explicit `fig.add_axes` geometry: candles (mint `GRAPH_POS` up / coral `GRAPH_NEG` down) or a line with an orange→transparent gradient glow-fill (`_gradient_fill`), a layered-`scatter` live node, hairline y-grid, compact `60k` y-axis, local-time x-axis, full-figure vertical gradient (`_draw_background_gradient`). The canvas chart deliberately mirrors this look. Palette + type in `config.py` (`GRAPH_*`, Ubuntu / Ubuntu Mono). `header=True` re-adds the matplotlib eyebrow (standalone only).

### History data format
`price_fetcher` returns `[[timestamp_ms, open, high, low, close], ...]` — full OHLCV normalised from both Coinbase and Kraken formats. The line chart uses only `close`; candlestick mode uses all four price fields.

### Candlestick rendering
The **live** popup draws candles on the canvas (`widget.html` `drawCandles`) from the *aggregated* series (~`PW/6` buckets), so 1d/5-min data reads as ~60 chunky candles instead of a picket fence. The diag-only `graph_renderer._draw_candles()` still draws with matplotlib primitives (`ax.vlines` wicks, `ax.bar` bodies, body width = 70% of the average candle interval); no `mplfinance` dependency.

### Graph window behaviour
- The BTC price is the **header hero** (big, odometer-rolling); MSTR/STRC scroll below as the `PROXIES` row
- Stays visible until dismissed (no auto-hide on focus-out)
- Hovering the chart shows a crosshair + price/time tooltip
- Click *inside the plot* → pins that tooltip (filled node); click again / Escape unpins
- Click *elsewhere* (or Escape with nothing pinned) → hides the window
- "Show Candles" / "Show Lines" menu item toggles chart type (persisted in `settings.json`)
- Toggling chart type re-draws the canvas from cached OHLCV points instantly — no re-fetch, no re-render
- Position: just below the panel/taskbar, horizontally near mouse x
- Position is saved on first show and reused on timeframe switches (no jumping)
- `_auto_show_graph` flag: set when timeframe changes so graph re-opens (with the entrance sweep) after fetch completes

## Diagnostics (`--diag`)
Run `bitcoin_widget.py --diag` to expose a Unix socket at `~/.config/bitcoin-widget/diag.sock`
(dir `chmod 700`, socket `chmod 600`; opt-in, never exposes secrets). Connect and:
- send **nothing** → returns the full state JSON (`label`, `graph`, `api`, `stocks`, `debug_log`)
- send `graph` → `{"graph_png_b64": ...}` — the **chart** as base64 PNG, rendered on
  demand from cached points via matplotlib (`graph_renderer`). This is the *reference*
  render, not what the popup shows (the popup draws on a canvas); works while hidden.
  For the live canvas chart (incl. hover/sweep) use `window` while shown.
- send `show` / `hide` → drives the popup's visibility (needed before `window`).
- send `window` → `{"window_png_b64": ...}` — the whole **live** WebKit window
  (header + chart + scrolling ticker) via `Gdk.pixbuf_get_from_window`; only while shown.
  Grab twice ~0.5s apart to confirm the tape is actually scrolling.

GTK/Gdk calls run on the daemon socket thread would crash, so those commands hop to the
main loop via `_run_on_main` (GLib.idle_add + a threading.Event) and block for the result.
The server reads a request with a 0.5s timeout, so a client that just reads (sends nothing)
still gets state. Example: `sock.sendall(b"show")`, then `b"window"`, then `base64.b64decode`.

## Common Pitfalls

### No `gi↔cairo` bridge (why the ticker is web, not a DrawingArea)
The system python is missing `python3-gi-cairo` (`gi._gi_cairo`), so a `Gtk.DrawingArea`
"draw" handler can't marshal its cairo context to pycairo — it raises
`Couldn't find foreign struct converter for 'cairo.Context'` every frame. That killed
the original Cairo `DrawingArea` ticker (and a `Gtk.Image` re-render fallback looked
jumpy). The ticker now lives in the WebKit page as a `requestAnimationFrame` animation,
which sidesteps the issue entirely. If you ever add GTK-side cairo drawing, either install
the package or build the pycairo context yourself (self-created contexts work fine).

### Graph % change is timeframe-relative; tray label is always 24h
The tray label shows the fixed 24h change from `_fetch_price()`. The graph's BTC change is computed against the *first candle in the fetched window* (`(display_price - closes[0]) / closes[0]`), so it tracks the selected 1d/7d/30d timeframe. Don't pass the 24h `live_change` into `render_graph` — that was the old bug where the graph delta never changed across timeframes.

### Binance is geo-restricted
`api.binance.com` returns a 200 with `{"code": 0, "msg": "Service unavailable from a restricted location"}` — not an HTTP error. Don't use Binance as a fallback without geo-checking.

### Coinbase candles are newest-first
`/candles` returns `[[time_s, low, high, open, close, vol], ...]` with the most recent candle first. Reverse before plotting or passing to graph renderer.

### GTK focus-out hides graph when menu opens
Opening the AppIndicator menu causes a focus-out event on the graph window. If auto-hide on focus-out is enabled, the graph flickers when the user interacts with the menu. Solution: disable focus-out hide.

### Graph repositions on timeframe switch
When the user picks a new timeframe, the menu closes and the graph window hides (focus-out). By the time the async fetch completes and the graph re-renders, the mouse has moved — causing the graph to pop up in a different location. Solution: pass `reuse_pos=True` to `show_graph()` after a timeframe change so it moves back to `_last_pos`.

### GdkPixbuf colour channel order
Cairo renders ARGB32 (native endian: BGRA on little-endian). GdkPixbuf expects RGBA. When converting manually, swap channels. Using matplotlib's PNG output piped through `GdkPixbuf.PixbufLoader` avoids this entirely (current approach).

### Coinbase and Kraken OHLCV field order differs
Coinbase: `[time_s, low, high, open, close, vol]`. Kraken: `[time_s, open, high, low, close, ...]`. Both must be normalised to `[timestamp_ms, open, high, low, close]` in `price_fetcher.py`.
