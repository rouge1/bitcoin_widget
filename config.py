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

GRAPH_WIDTH = 420
GRAPH_HEIGHT = 230

FONT_FACE = "Monospace"
FONT_SIZE = 11

# Colors (R, G, B) 0.0–1.0
TEXT_COLOR  = (1.0,  1.0,  1.0)
UP_COLOR    = (0.2,  0.88, 0.2)
DOWN_COLOR  = (0.95, 0.3,  0.3)

GRAPH_LINE_COLOR = "#F7931A"   # Bitcoin orange
GRAPH_BG_COLOR   = "#111111"

CANDLE_UP_COLOR   = "#26a69a"
CANDLE_DOWN_COLOR = "#ef5350"
CANDLE_WICK_WIDTH = 1.0

# Coinbase (primary)
COINBASE_STATS_URL  = "https://api.exchange.coinbase.com/products/BTC-USD/stats"
COINBASE_CANDLES_URL = (
    "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    "?granularity={granularity}&start={start}&end={end}"
)

# Kraken (fallback)
KRAKEN_TICKER_URL  = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"
KRAKEN_OHLC_URL    = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval={interval}&since={since}"
