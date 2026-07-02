import json
from pathlib import Path

POLL_INTERVAL_SECONDS = {1: 10, 7: 300, 30: 900}  # seconds per timeframe
GRAPH_HISTORY_DAYS = 1   # default timeframe

_SETTINGS_DIR = Path.home() / ".config" / "bitcoin-widget"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"


def _load_setting(key, default=None):
    try:
        return json.loads(_SETTINGS_FILE.read_text()).get(key, default)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return default


def _save_setting(key, value):
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    data[key] = value
    _SETTINGS_FILE.write_text(json.dumps(data))


def load_graph_days() -> int:
    days = _load_setting("graph_days", GRAPH_HISTORY_DAYS)
    return days if days in (1, 7, 30) else GRAPH_HISTORY_DAYS


def save_graph_days(days: int):
    _save_setting("graph_days", days)


def load_show_candles() -> bool:
    return bool(_load_setting("show_candles", False))


def save_show_candles(enabled: bool):
    _save_setting("show_candles", enabled)

TRAY_ICON_WIDTH = 150
TRAY_ICON_HEIGHT = 24

GRAPH_WIDTH = 440         # chart image rendered by matplotlib (plot only, no header)
GRAPH_HEIGHT = 240
# The popup is a WebKit page (see web/widget.html + web_window.py): HTML header +
# chart image + a requestAnimationFrame ticker. These are the window's outer size.
WEB_WIDTH = 452
WEB_HEIGHT = 320

# --- "Treasury Terminal" palette ---
GRAPH_LINE_COLOR = "#F7931A"   # Bitcoin orange — the single loud accent
GRAPH_BG_COLOR   = "#0C0D11"   # graphite base (figure facecolor)
GRAPH_BG_TOP     = "#0C0D11"   # background gradient: top …
GRAPH_BG_BOTTOM  = "#15171E"   # … to slightly warmer graphite at the bottom
GRAPH_POS   = "#37D6A0"   # positive change (mint)
GRAPH_NEG   = "#FB6E7E"   # negative change (coral)
GRAPH_TEXT  = "#ECE8DF"   # primary text (warm off-white)
GRAPH_MUTE  = "#767B86"   # axis / secondary labels
GRAPH_HAIR  = "#22252E"   # hairline grid + dividers

CANDLE_UP_COLOR   = GRAPH_POS
CANDLE_DOWN_COLOR = GRAPH_NEG
CANDLE_WICK_WIDTH = 0.9

# Type: Ubuntu (humanist sans, distinctive) for labels, Ubuntu Mono for data.
# Lists give a graceful fallback if the preferred face isn't installed.
GRAPH_DISPLAY_FONT = ["Ubuntu", "DejaVu Sans", "sans-serif"]
GRAPH_MONO_FONT    = ["Ubuntu Mono", "DejaVu Sans Mono", "monospace"]

# Coinbase (primary)
COINBASE_STATS_URL  = "https://api.exchange.coinbase.com/products/BTC-USD/stats"
COINBASE_CANDLES_URL = (
    "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    "?granularity={granularity}&start={start}&end={end}"
)

# Kraken (fallback)
KRAKEN_TICKER_URL  = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"
KRAKEN_OHLC_URL    = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval={interval}&since={since}"

# BTC chain tip height for the header "as of · block" ledger line (mempool.space,
# no key; returns the height as plain text). Blocks arrive ~10 min apart.
MEMPOOL_HEIGHT_URL = "https://mempool.space/api/blocks/tip/height"
BLOCK_MIN_INTERVAL = 120   # seconds between tip-height fetches

# Related equities shown on the graph (price + 24h change from previous close).
# Yahoo Finance v8 chart endpoint — no API key required.
STOCK_SYMBOLS = ["MSTR", "STRC"]
STOCK_MIN_INTERVAL = 60   # seconds; equities move slower than crypto — be gentle on Yahoo
SPARK_POINTS = 32         # intraday closes kept per equity for the ticker sparkline
# range=1d&interval=5m gives ~78 intraday closes (for the sparkline) alongside
# meta.regularMarketPrice / chartPreviousClose (for the price + % change).
YAHOO_QUOTE_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m"
)
