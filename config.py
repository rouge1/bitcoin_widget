POLL_INTERVAL_SECONDS = 30
GRAPH_HISTORY_DAYS = 1   # default timeframe

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

# Coinbase (primary)
COINBASE_STATS_URL  = "https://api.exchange.coinbase.com/products/BTC-USD/stats"
COINBASE_CANDLES_URL = (
    "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    "?granularity={granularity}&start={start}&end={end}"
)

# Kraken (fallback)
KRAKEN_TICKER_URL  = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"
KRAKEN_OHLC_URL    = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval={interval}&since={since}"
