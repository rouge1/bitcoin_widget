import io
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")   # must be before pyplot import — no display needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
from matplotlib.ticker import FuncFormatter
from matplotlib.patches import Polygon

from gi.repository import GdkPixbuf

import config


def _kfmt(v, _):
    """Y-axis price → compact '60k' form."""
    return f"{v/1000:.0f}k"


def _draw_background_gradient(fig):
    """Full-figure vertical graphite gradient behind everything."""
    ax = fig.add_axes([0, 0, 1, 1], zorder=-10)
    ax.axis("off")
    grad = np.linspace(0, 1, 256).reshape(-1, 1)
    top = np.array(mcolors.to_rgb(config.GRAPH_BG_TOP))
    bottom = np.array(mcolors.to_rgb(config.GRAPH_BG_BOTTOM))
    img = bottom + (top - bottom) * grad   # bottom → top
    ax.imshow(np.repeat(img[:, None, :], 2, axis=1), aspect="auto",
              extent=[0, 1, 0, 1], origin="lower", interpolation="bilinear")


def _gradient_fill(ax, xn, ys, ybase, color):
    """Orange→transparent glow fill under a line, clipped to the line's area."""
    z = np.empty((256, 1, 4))
    z[:, :, :3] = mcolors.to_rgb(color)
    z[:, :, 3] = np.linspace(0.0, 0.42, 256).reshape(-1, 1)  # transparent bottom → tint top
    im = ax.imshow(z, aspect="auto", origin="lower",
                   extent=[xn[0], xn[-1], ybase, max(ys)], zorder=2)
    verts = list(zip(xn, ys)) + [(xn[-1], ybase), (xn[0], ybase)]
    im.set_clip_path(Polygon(verts, closed=True, transform=ax.transData))


def _draw_candles(ax, t_nums, opens, highs, lows, closes):
    """Candlesticks via matplotlib primitives (no mplfinance)."""
    if len(t_nums) >= 2:
        body_width = (t_nums[-1] - t_nums[0]) / (len(t_nums) - 1) * 0.7
    else:
        body_width = 0.01
    for t, o, h, l, c in zip(t_nums, opens, highs, lows, closes):
        color = config.CANDLE_UP_COLOR if c >= o else config.CANDLE_DOWN_COLOR
        ax.vlines(t, l, h, colors=color, linewidth=config.CANDLE_WICK_WIDTH, zorder=4, alpha=0.95)
        body_bottom = min(o, c)
        body_height = abs(c - o) or (h - l) * 0.01  # tiny height for doji
        ax.bar(t, body_height, bottom=body_bottom, width=body_width,
               color=color, edgecolor=color, linewidth=0.4, zorder=5)
    ax.set_xlim(t_nums[0] - body_width, t_nums[-1] + body_width)


def render_graph(points: list, width: int = config.GRAPH_WIDTH,
                 height: int = config.GRAPH_HEIGHT, days: int = 1,
                 show_candles: bool = False, header: bool = True) -> GdkPixbuf.Pixbuf:
    """Render the 'Treasury Terminal' price chart to a GdkPixbuf.
    points: list of [timestamp_ms, open, high, low, close].
    header=False omits the eyebrow (the web UI draws its own header in HTML)."""
    if not points:
        return None

    dpi = 96
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(config.GRAPH_BG_COLOR)
    _draw_background_gradient(fig)

    # Chart axes — explicit geometry (no tight_layout, which fights fixed regions);
    # leaves room for the eyebrow header above.
    ax = fig.add_axes([0.115, 0.155, 0.85, 0.715 if header else 0.80])
    ax.set_facecolor("none")

    local_tz = datetime.now().astimezone().tzinfo   # x-axis in local time
    times = [datetime.fromtimestamp(p[0] / 1000, tz=local_tz) for p in points]
    xn = mdates.date2num(times)
    closes = [p[4] for p in points]

    if show_candles:
        opens = [p[1] for p in points]
        highs = [p[2] for p in points]
        lows  = [p[3] for p in points]
        _draw_candles(ax, xn, opens, highs, lows, closes)
        ymin, ymax = min(lows), max(highs)
    else:
        ymin, ymax = min(closes), max(closes)

    span = (ymax - ymin) or (ymax * 0.01) or 1.0
    y0, y1 = ymin - span * 0.10, ymax + span * 0.13   # headroom for the live node
    ax.set_ylim(y0, y1)

    if not show_candles:
        _gradient_fill(ax, xn, closes, y0, config.GRAPH_LINE_COLOR)
        ax.plot(times, closes, color=config.GRAPH_LINE_COLOR, linewidth=1.9,
                zorder=4, solid_capstyle="round")

    # Live node — ambient glow + bright core at the latest point.
    ax.scatter([xn[-1]], [closes[-1]], s=110, color=config.GRAPH_LINE_COLOR,
               alpha=0.16, zorder=6, edgecolors="none")
    ax.scatter([xn[-1]], [closes[-1]], s=16, color=config.GRAPH_LINE_COLOR,
               alpha=0.9, zorder=7, edgecolors="none")

    # Axes styling — hairline y-grid, muted mono ticks, single faint baseline.
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(config.GRAPH_HAIR)
    ax.tick_params(colors=config.GRAPH_MUTE, labelsize=7.5, length=0, pad=4)
    ax.yaxis.set_major_formatter(FuncFormatter(_kfmt))
    ax.grid(axis="y", color=config.GRAPH_HAIR, linewidth=0.7, zorder=1)
    if days == 1:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=local_tz))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    elif days <= 7:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a", tz=local_tz))
        ax.xaxis.set_major_locator(mdates.DayLocator())
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d", tz=local_tz))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator())
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontfamily(config.GRAPH_MONO_FONT)

    # Eyebrow header — clean pair label (left) + timeframe (right).
    if header:
        tf = {1: "24H", 7: "7D", 30: "30D"}.get(days, f"{days}D")
        fig.text(0.115, 0.935, "BTC/USD", color=config.GRAPH_TEXT, fontsize=11.5,
                 fontfamily=config.GRAPH_DISPLAY_FONT, fontweight="bold", va="center", ha="left")
        fig.text(0.965, 0.935, tf, color=config.GRAPH_MUTE, fontsize=9,
                 fontfamily=config.GRAPH_MONO_FONT, va="center", ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=config.GRAPH_BG_COLOR)
    plt.close(fig)
    buf.seek(0)

    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(buf.getvalue())
    loader.close()
    return loader.get_pixbuf()
