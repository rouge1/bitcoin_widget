import io
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")   # must be before pyplot import — no display needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

import cairo
from gi.repository import GdkPixbuf
import config


def render_graph(points: list, width: int = config.GRAPH_WIDTH,
                 height: int = config.GRAPH_HEIGHT, days: int = 1,
                 live_price: float = None, live_change: float = None) -> GdkPixbuf.Pixbuf:
    """Render a price chart to a GdkPixbuf. Always call with data from CoinGecko
    (list of [timestamp_ms, price])."""
    if not points:
        return None

    dpi = 96
    fig_w = width / dpi
    fig_h = height / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor(config.GRAPH_BG_COLOR)
    ax.set_facecolor(config.GRAPH_BG_COLOR)

    times = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in points]
    prices = [p[1] for p in points]

    # Line + gradient fill
    ax.plot(times, prices, color=config.GRAPH_LINE_COLOR, linewidth=1.8, zorder=3)
    ax.fill_between(times, prices, min(prices), color=config.GRAPH_LINE_COLOR,
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
    display_price = live_price if live_price is not None else prices[-1]
    display_change = live_change if live_change is not None else (
        (prices[-1] - prices[0]) / prices[0] * 100
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


def render_tray_icon(price: float, change_24h: float,
                     width: int = config.TRAY_ICON_WIDTH,
                     height: int = config.TRAY_ICON_HEIGHT) -> GdkPixbuf.Pixbuf:
    """Render 'BTC $84,231 ▲0.3%' as a cairo surface → GdkPixbuf."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)

    # Transparent background
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()

    ctx.select_font_face(config.FONT_FACE,
                         cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(config.FONT_SIZE)

    price_text = f"BTC ${price:,.0f}"
    arrow = "▲" if change_24h >= 0 else "▼"
    delta_text = f" {arrow}{abs(change_24h):.1f}%"

    # Measure so we can vertically center
    ext = ctx.text_extents(price_text + delta_text)
    y = (height + ext.height) / 2 - ext.y_bearing - ext.height

    # White price
    ctx.set_source_rgb(*config.TEXT_COLOR)
    ctx.move_to(2, y)
    ctx.show_text(price_text)

    # Colored delta
    color = config.UP_COLOR if change_24h >= 0 else config.DOWN_COLOR
    ctx.set_source_rgb(*color)
    ctx.show_text(delta_text)

    # cairo ARGB32 → raw bytes → GdkPixbuf (RGBA)
    data = bytes(surface.get_data())
    # cairo stores BGRA; GdkPixbuf expects RGBA — swap channels
    import array
    arr = array.array("B", data)
    for i in range(0, len(arr), 4):
        b, g, r, a = arr[i], arr[i+1], arr[i+2], arr[i+3]
        arr[i],   arr[i+1], arr[i+2], arr[i+3] = r, g, b, a
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib_bytes_from_array(arr),
        GdkPixbuf.Colorspace.RGB, True, 8, width, height, width * 4
    )
    return pixbuf


def _cairo_surface_to_pixbuf(surface: cairo.ImageSurface) -> GdkPixbuf.Pixbuf:
    """Convert a cairo ARGB32 surface to a GdkPixbuf (RGBA)."""
    import array
    from gi.repository import GLib as _GLib

    width = surface.get_width()
    height = surface.get_height()
    data = bytes(surface.get_data())

    # cairo ARGB32 is native-endian; on little-endian (x86) memory order is B G R A.
    arr = array.array("B", data)
    for i in range(0, len(arr), 4):
        b, g, r, a = arr[i], arr[i+1], arr[i+2], arr[i+3]
        arr[i], arr[i+1], arr[i+2], arr[i+3] = r, g, b, a

    gbytes = _GLib.Bytes.new(arr.tobytes())
    return GdkPixbuf.Pixbuf.new_from_bytes(
        gbytes,
        GdkPixbuf.Colorspace.RGB,
        True,   # has_alpha
        8,
        width, height,
        width * 4
    )


def render_tray_icon(price: float, change_24h: float,
                     width: int = config.TRAY_ICON_WIDTH,
                     height: int = config.TRAY_ICON_HEIGHT) -> GdkPixbuf.Pixbuf:
    """Render 'BTC $84,231 ▲0.3%' as a cairo surface → GdkPixbuf."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)

    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()

    ctx.select_font_face(config.FONT_FACE,
                         cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(config.FONT_SIZE)

    price_text = f"BTC ${price:,.0f}"
    arrow = "▲" if change_24h >= 0 else "▼"
    delta_text = f" {arrow}{abs(change_24h):.1f}%"

    ext = ctx.text_extents(price_text + delta_text)
    y = (height + ext.height) / 2 - ext.y_bearing - ext.height

    ctx.set_source_rgb(*config.TEXT_COLOR)
    ctx.move_to(2, y)
    ctx.show_text(price_text)

    color = config.UP_COLOR if change_24h >= 0 else config.DOWN_COLOR
    ctx.set_source_rgb(*color)
    ctx.show_text(delta_text)

    return _cairo_surface_to_pixbuf(surface)


if __name__ == "__main__":
    # Test: save a graph PNG to disk
    import requests as req
    url = config.COINGECKO_HISTORY_URL.format(days=1)
    data = req.get(url, timeout=10).json()["prices"]
    pixbuf = render_graph(data, days=1)
    pixbuf.savev("/tmp/btc_graph_test.png", "png", [], [])
    print("Saved /tmp/btc_graph_test.png")
