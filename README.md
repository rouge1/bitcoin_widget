# Bitcoin Widget

Live BTC/USD price in your Linux system tray with a historical price graph.

## Features

- Real-time price and 24h change in the tray label
- Click **Show Graph** to pop up a price chart
- Switch between **1 Day / 7 Day / 30 Day** history — graph updates in place
- Click the graph to dismiss it
- **Start on Login** toggle (XDG autostart)
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

# Python packages
pip install requests matplotlib
```

## Usage

```bash
python3 bitcoin_widget.py &
```

To autostart on login, enable **Start on Login** from the tray menu.

## Configuration

Edit `config.py` to change:

| Setting | Default | Description |
|---------|---------|-------------|
| `POLL_INTERVAL_SECONDS` | `60` | How often to fetch new price data |
| `GRAPH_HISTORY_DAYS` | `1` | Default timeframe shown |
| `GRAPH_WIDTH` / `GRAPH_HEIGHT` | `600×350` | Graph popup size |

## Data Sources

| Priority | Source | Notes |
|----------|--------|-------|
| Primary | Coinbase Exchange | `api.exchange.coinbase.com` |
| Fallback | Kraken | `api.kraken.com` |
