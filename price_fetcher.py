import threading
import time
import requests
from gi.repository import GLib
import config


def _get(url, **kwargs):
    return requests.get(url, timeout=8, **kwargs)


def _sparkline(result, n=config.SPARK_POINTS):
    """Downsample a Yahoo chart result's intraday closes to ~n points for a
    ticker sparkline. Drops nulls (gaps / pre-open); returns [] if too sparse."""
    try:
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    except (KeyError, IndexError, TypeError):
        return []
    if len(closes) < 3:
        return closes
    if len(closes) <= n:
        return [round(float(c), 4) for c in closes]
    step = len(closes) / n
    return [round(float(closes[min(len(closes) - 1, int(i * step))]), 4) for i in range(n)]


class PriceFetcher:
    def __init__(self, price_callback, history_callback, stocks_callback=None):
        self._price_cb = price_callback
        self._history_cb = history_callback
        self._stocks_cb = stocks_callback
        self._stop = threading.Event()
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._history_days = config.GRAPH_HISTORY_DAYS
        self._last_stock_fetch = 0.0
        self._last_block_fetch = 0.0
        self.last_price_source = None
        self.last_block_height = None   # BTC chain tip, for the "as of · block" line

    def start(self):
        self._thread.start()

    def stop(self):
        self._stopped = True
        self._stop.set()

    def set_history_days(self, days: int):
        self._history_days = days
        self._stop.set()  # wake the sleep so the new interval takes effect

    def refresh(self):
        threading.Thread(target=self._fetch_all, daemon=True).start()

    def _poll_interval(self):
        return config.POLL_INTERVAL_SECONDS.get(self._history_days, 30)

    def _run(self):
        self._fetch_all()
        while True:
            if self._stop.wait(self._poll_interval()):
                if self._stopped:
                    break
                # woken by set_history_days — reset and keep going
                self._stop.clear()
            self._fetch_all()

    def _fetch_all(self):
        price, change = self._fetch_price()
        if price is not None:
            GLib.idle_add(self._price_cb, price, change)

        self._maybe_fetch_block()   # cheap, throttled; feeds the "as of · block" line

        # Stocks are delivered before history so the widget has fresh quotes
        # cached by the time the history callback kicks off the graph render.
        if self._stocks_cb is not None:
            quotes = self._fetch_stocks()
            if quotes:
                GLib.idle_add(self._stocks_cb, quotes)

        points = self._fetch_history(self._history_days)
        if points:
            GLib.idle_add(self._history_cb, points)

    # ------------------------------------------------------------------ #
    #  Price + 24h change                                                  #
    # ------------------------------------------------------------------ #

    def _fetch_price(self):
        result = self._coinbase_price()
        if result[0] is not None:
            self.last_price_source = "coinbase"
            return result
        self.last_price_source = "kraken"
        return self._kraken_price()

    def _coinbase_price(self):
        try:
            r = _get(config.COINBASE_STATS_URL)
            r.raise_for_status()
            data = r.json()
            last = float(data["last"])
            open_ = float(data["open"])   # 24h open
            change = (last - open_) / open_ * 100
            return last, change
        except Exception:
            return None, None

    def _kraken_price(self):
        try:
            r = _get(config.KRAKEN_TICKER_URL)
            r.raise_for_status()
            data = r.json()
            ticker = next(iter(data["result"].values()))
            last = float(ticker["c"][0])
            open_ = float(ticker["o"])
            change = (last - open_) / open_ * 100
            return last, change
        except Exception:
            return None, None

    def _maybe_fetch_block(self):
        """Refresh the BTC chain tip height (throttled). Best-effort — on any
        failure we simply keep the last-known height (or None)."""
        now = time.time()
        if now - self._last_block_fetch < config.BLOCK_MIN_INTERVAL:
            return
        try:
            r = _get(config.MEMPOOL_HEIGHT_URL)
            r.raise_for_status()
            self.last_block_height = int(r.text.strip())
            self._last_block_fetch = now
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  History (returns [[timestamp_ms, open, high, low, close], ...])    #
    # ------------------------------------------------------------------ #

    def _fetch_history(self, days: int):
        result = self._coinbase_history(days)
        if result:
            return result
        return self._kraken_history(days)

    def _coinbase_history(self, days: int):
        try:
            # granularity: 1d→300s/5min (288 pts), 7d→3600s/1h (168 pts), 30d→86400s/1d
            granularity = 86400 if days >= 30 else (3600 if days >= 7 else 300)
            end = int(time.time())
            start = end - days * 86400
            url = config.COINBASE_CANDLES_URL.format(
                granularity=granularity, start=start, end=end
            )
            r = _get(url)
            r.raise_for_status()
            candles = r.json()  # [[time_s, low, high, open, close, volume], ...] newest first
            if not candles:
                return []
            # Reverse to chronological; Coinbase: [time_s, low, high, open, close, vol]
            return [[c[0] * 1000, c[3], c[2], c[1], c[4]] for c in reversed(candles)]
        except Exception:
            return []

    def _kraken_history(self, days: int):
        try:
            # interval in minutes: 5=5min, 60=1h, 1440=1d
            interval = 1440 if days >= 30 else (60 if days >= 7 else 5)
            since = int(time.time()) - days * 86400
            url = config.KRAKEN_OHLC_URL.format(interval=interval, since=since)
            r = _get(url)
            r.raise_for_status()
            data = r.json()
            candles = next(iter(data["result"].values()))
            # [time_s, open, high, low, close, vwap, volume, count]
            return [[c[0] * 1000, float(c[1]), float(c[2]), float(c[3]), float(c[4])] for c in candles]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    #  Related equities (Yahoo Finance) — {symbol: (price, change_pct)}   #
    # ------------------------------------------------------------------ #

    def _fetch_stocks(self):
        """Return {symbol: (price, change_pct, spark)} for successfully fetched
        symbols, or None if throttled / nothing fetched. `spark` is a short list
        of intraday closes for the ticker sparkline. Throttled so a fast crypto
        poll interval doesn't hammer Yahoo — equities move slowly."""
        now = time.time()
        if now - self._last_stock_fetch < config.STOCK_MIN_INTERVAL:
            return None
        quotes = {}
        for symbol in config.STOCK_SYMBOLS:
            q = self._yahoo_quote(symbol)
            if q is not None:
                quotes[symbol] = q
        if quotes:
            self._last_stock_fetch = now  # only reset on success, so failures retry
        return quotes or None

    def _yahoo_quote(self, symbol):
        try:
            url = config.YAHOO_QUOTE_URL.format(symbol=symbol)
            r = _get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            result = r.json()["chart"]["result"][0]
            meta = result["meta"]
            price = float(meta["regularMarketPrice"])
            prev = float(meta.get("chartPreviousClose") or meta["previousClose"])
            change = (price - prev) / prev * 100
            spark = _sparkline(result)
            return price, change, spark
        except Exception:
            return None


if __name__ == "__main__":
    def on_price(p, c):
        arrow = "▲" if c >= 0 else "▼"
        print(f"BTC ${p:,.0f}  {arrow}{abs(c):.2f}%")

    def on_history(pts):
        print(f"History: {len(pts)} points, latest ${pts[-1][4]:,.0f}")

    import gi
    gi.require_version("GLib", "2.0")

    fetcher = PriceFetcher(on_price, on_history)
    fetcher._fetch_all()
