# Bitcoin Widget

Live BTC/USD price in your Linux system tray with a historical price graph.

## Features

- Real-time price and 24h change in the tray label
- Click **Show Graph** to pop up a price chart (line or candlestick)
- Toggle **Show Candles / Show Lines** to switch chart type (persisted across restarts)
- Switch between **1 Day / 7 Day / 30 Day** history — graph updates in place
- Click the graph to dismiss it
- Automatic XDG autostart on first run
- Data from Coinbase with automatic fallback to Kraken

## Requirements

- Linux with a panel supporting AppIndicator3 (GNOME + AppIndicator extension, XFCE, etc.)
- Python 3.10+

## Installation

```bash
# System GTK/AppIndicator libraries
sudo apt install python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 \
    gir1.2-ayatanaappindicator3-0.1

# Python packages (pycairo no longer required)
pip install requests matplotlib
```

## Usage

```bash
python3 bitcoin_widget.py &
```

## Run on Startup

Autostart is enabled automatically on first launch (creates `~/.config/autostart/bitcoin-widget.desktop`).

**Manual setup — From the command line**

```bash
python3 autostart.py
```

**Manual .desktop file**

Create `~/.config/autostart/bitcoin-widget.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Bitcoin Widget
Exec=/usr/bin/python3 /full/path/to/bitcoin_widget.py
X-GNOME-Autostart-enabled=true
StartupNotify=false
```

Replace `/full/path/to/` with the actual directory where the widget lives.

## Configuration

Edit `config.py` to change:

| Setting | Default | Description |
|---------|---------|-------------|
| `POLL_INTERVAL_SECONDS` | `{1: 10, 7: 300, 30: 900}` | Per-timeframe poll interval (seconds) |
| `GRAPH_HISTORY_DAYS` | `1` | Default timeframe shown |
| `GRAPH_WIDTH` / `GRAPH_HEIGHT` | `420×230` | Graph popup size |
| `CANDLE_UP_COLOR` / `CANDLE_DOWN_COLOR` | `#26a69a` / `#ef5350` | Candlestick colours |

## Data Sources

| Priority | Source | Notes |
|----------|--------|-------|
| Primary | Coinbase Exchange | `api.exchange.coinbase.com` |
| Fallback | Kraken | `api.kraken.com` |
