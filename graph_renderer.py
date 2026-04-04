import io
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")   # must be before pyplot import — no display needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

from gi.repository import GdkPixbuf
import config


def _draw_candles(ax, t_nums, opens, highs, lows, closes):
    """Draw candlestick chart using matplotlib primitives."""
    if len(t_nums) >= 2:
        body_width = (t_nums[-1] - t_nums[0]) / (len(t_nums) - 1) * 0.7
    else:
        body_width = 0.01

    for t, o, h, l, c in zip(t_nums, opens, highs, lows, closes):
        color = config.CANDLE_UP_COLOR if c >= o else config.CANDLE_DOWN_COLOR
        ax.vlines(t, l, h, colors=color, linewidth=config.CANDLE_WICK_WIDTH, zorder=3)
        body_bottom = min(o, c)
        body_height = abs(c - o) or (h - l) * 0.01  # tiny height for doji
        ax.bar(t, body_height, bottom=body_bottom, width=body_width,
               color=color, edgecolor=color, linewidth=0.5, zorder=4)

    ax.set_xlim(t_nums[0] - body_width, t_nums[-1] + body_width)


def render_graph(points: list, width: int = config.GRAPH_WIDTH,
                 height: int = config.GRAPH_HEIGHT, days: int = 1,
                 live_price: float = None, live_change: float = None,
                 show_candles: bool = False) -> GdkPixbuf.Pixbuf:
    """Render a price chart to a GdkPixbuf.
    points: list of [timestamp_ms, open, high, low, close]."""
    if not points:
        return None

    dpi = 96
    fig_w = width / dpi
    fig_h = height / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor(config.GRAPH_BG_COLOR)
    ax.set_facecolor(config.GRAPH_BG_COLOR)

    times = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in points]
    closes = [p[4] for p in points]

    if show_candles:
        t_nums = mdates.date2num(times)
        opens = [p[1] for p in points]
        highs = [p[2] for p in points]
        lows  = [p[3] for p in points]
        _draw_candles(ax, t_nums, opens, highs, lows, closes)
    else:
        ax.plot(times, closes, color=config.GRAPH_LINE_COLOR, linewidth=1.8, zorder=3)
        ax.fill_between(times, closes, min(closes), color=config.GRAPH_LINE_COLOR,
                        alpha=0.18, zorder=2)

    # Axes styling
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#444444")
    ax.spines["bottom"].set_color("#444444")
    ax.tick_params(colors="#aaaaaa", labelsize=8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))

    if days == 1:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=timezone.utc))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    elif days <= 7:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a", tz=timezone.utc))
        ax.xaxis.set_major_locator(mdates.DayLocator())
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d", tz=timezone.utc))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator())

    ax.grid(axis="y", color="#2a2a2a", linewidth=0.6, zorder=1)

    # Price annotation — use live spot price if available, else last candle
    display_price = live_price if live_price is not None else closes[-1]
    display_change = live_change if live_change is not None else (
        (closes[-1] - closes[0]) / closes[0] * 100
    )
    color = "#33dd33" if display_change >= 0 else "#ee4444"
    arrow = "▲" if display_change >= 0 else "▼"
    label = f"  ${display_price:,.0f}  {arrow}{abs(display_change):.1f}%"
    ax.annotate(label, xy=(times[-1], display_price),
                color=color, fontsize=8.5, fontweight="bold",
                xytext=(-5, 6), textcoords="offset points")

    timeframe_label = {1: "24h", 7: "7d", 30: "30d"}.get(days, f"{days}d")
    ax.set_title(f"Bitcoin / USD  ({timeframe_label})",
                 color="#cccccc", fontsize=9, pad=4)

    fig.tight_layout(pad=0.6)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    data = buf.getvalue()

    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(data)
    loader.close()
    return loader.get_pixbuf()


