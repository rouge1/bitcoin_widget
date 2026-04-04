import json
from pathlib import Path

POLL_INTERVAL_SECONDS = {1: 10, 7: 300, 30: 900}  # seconds per timeframe
GRAPH_HISTORY_DAYS = 1   # default timeframe

_SETTINGS_DIR = Path.home() / ".config" / "bitcoin-widget"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"


def load_graph_days() -> int:
    """Load saved timeframe, falling back to GRAPH_HISTORY_DAYS."""
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        days = data.get("graph_days", GRAPH_HISTORY_DAYS)
        if days in (1, 7, 30):
            return days
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return GRAPH_HISTORY_DAYS


def save_graph_days(days: int):
    """Persist the chosen timeframe."""
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    data["graph_days"] = days
    _SETTINGS_FILE.write_text(json.dumps(data))


def load_show_candles() -> bool:
    """Load saved candle preference, default False."""
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        return bool(data.get("show_candles", False))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return False


def save_show_candles(enabled: bool):
    """Persist the candle display preference."""
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    data["show_candles"] = enabled
    _SETTINGS_FILE.write_text(json.dumps(data))

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
