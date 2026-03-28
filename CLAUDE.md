# CLAUDE.md — Bitcoin Widget

## Project Overview
GTK3 system tray applet showing live BTC/USD price with a historical price graph popup. Runs on Linux with Ayatana AppIndicator3.

## File Structure
```
bitcoin_widget.py   # Main app: tray indicator, menu, graph window
price_fetcher.py    # Background polling thread, Coinbase → Kraken fallback
graph_renderer.py   # matplotlib graph → GdkPixbuf, cairo tray icon
config.py           # All constants: URLs, intervals, colours, dimensions
autostart.py        # XDG ~/.config/autostart/ .desktop file management
```

## Running
```bash
python3 bitcoin_widget.py &
```

## Dependencies
```
requests
matplotlib
pycairo
pygobject          # gi: GTK3, GdkPixbuf, GLib, AyatanaAppIndicator3
```

Install:
```bash
pip install requests matplotlib pycairo pygobject
# or
sudo apt install python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1
pip install requests matplotlib
```

## Architecture

### Threading model
- GTK main thread owns all UI
- `PriceFetcher` runs a daemon thread polling on `POLL_INTERVAL_SECONDS`
- All callbacks into GTK use `GLib.idle_add()` — never update UI from the fetch thread directly
- Graph rendering runs on a third daemon thread (matplotlib is slow) and posts result via `GLib.idle_add`

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

Candle granularity auto-selects: 1d→`3600s/1h`, 7d→`3600s/1h`, 30d→`86400s/1d`.

### Graph window behaviour
- Stays visible until dismissed (no auto-hide on focus-out)
- Click on graph → hides it
- Escape → hides it
- "Show Graph" menu item toggles visibility
- Position: just below the panel/taskbar, horizontally near mouse x
- Position is saved on first show and reused on timeframe switches (no jumping)
- `_auto_show_graph` flag: set when timeframe changes so graph re-opens after fetch completes

## Common Pitfalls

### Binance is geo-restricted
`api.binance.com` returns a 200 with `{"code": 0, "msg": "Service unavailable from a restricted location"}` — not an HTTP error. Don't use Binance as a fallback without geo-checking.

### Coinbase candles are newest-first
`/candles` returns `[[time_s, low, high, open, close, vol], ...]` with the most recent candle first. Reverse before plotting or passing to graph renderer.

### GTK focus-out hides graph when menu opens
Opening the AppIndicator menu causes a focus-out event on the graph window. If auto-hide on focus-out is enabled, the graph flickers when the user interacts with the menu. Solution: disable focus-out hide.

### Graph repositions on timeframe switch
When the user picks a new timeframe, the menu closes and the graph window hides (focus-out). By the time the async fetch completes and the graph re-renders, the mouse has moved — causing the graph to pop up in a different location. Solution: pass `reuse_pos=True` to `show_graph()` after a timeframe change so it moves back to `_last_pos`.

### GdkPixbuf colour channel order
Cairo renders ARGB32 (native endian: BGRA on little-endian). GdkPixbuf expects RGBA. When converting manually, swap channels. Using matplotlib's PNG output piped through `GdkPixbuf.new_from_stream` avoids this entirely.

### `render_tray_icon()` is defined twice in graph_renderer.py
The second definition shadows the first. Keep only one.
