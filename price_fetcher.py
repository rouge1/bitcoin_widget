import threading
import time
import requests
from gi.repository import GLib
import config


def _get(url, **kwargs):
    return requests.get(url, timeout=8, **kwargs)


class PriceFetcher:
    def __init__(self, price_callback, history_callback):
        self._price_cb = price_callback
        self._history_cb = history_callback
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._history_days = config.GRAPH_HISTORY_DAYS

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def set_history_days(self, days: int):
        self._history_days = days

    def refresh(self):
        threading.Thread(target=self._fetch_all, daemon=True).start()

    def _run(self):
        self._fetch_all()
        while not self._stop.wait(config.POLL_INTERVAL_SECONDS):
            self._fetch_all()

    def _fetch_all(self):
        price, change = self._fetch_price()
        if price is not None:
            GLib.idle_add(self._price_cb, price, change)

        points = self._fetch_history(self._history_days)
        if points:
            GLib.idle_add(self._history_cb, points)

    # ------------------------------------------------------------------ #
    #  Price + 24h change                                                  #
    # ------------------------------------------------------------------ #

    def _fetch_price(self):
        result = self._coinbase_price()
        if result[0] is not None:
            return result
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

    # ------------------------------------------------------------------ #
    #  History (returns [[timestamp_ms, close_price], ...])               #
    # ------------------------------------------------------------------ #

    def _fetch_history(self, days: int):
        result = self._coinbase_history(days)
        if result:
            return result
        return self._kraken_history(days)

    def _coinbase_history(self, days: int):
        try:
            # granularity in seconds: 1d→86400, 7d→3600 (168 pts), 1d→3600 (24 pts)
            granularity = 86400 if days >= 30 else 3600
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
            # Reverse to chronological, return [timestamp_ms, close]
            return [[c[0] * 1000, c[4]] for c in reversed(candles)]
        except Exception:
            return []

    def _kraken_history(self, days: int):
        try:
            # interval in minutes: 60=1h, 1440=1d
            interval = 1440 if days >= 30 else 60
            since = int(time.time()) - days * 86400
            url = config.KRAKEN_OHLC_URL.format(interval=interval, since=since)
            r = _get(url)
            r.raise_for_status()
            data = r.json()
            candles = next(iter(data["result"].values()))
            # [time_s, open, high, low, close, vwap, volume, count]
            return [[c[0] * 1000, float(c[4])] for c in candles]
        except Exception:
            return []


if __name__ == "__main__":
    def on_price(p, c):
        arrow = "▲" if c >= 0 else "▼"
        print(f"BTC ${p:,.0f}  {arrow}{abs(c):.2f}%")

    def on_history(pts):
        print(f"History: {len(pts)} points, latest ${pts[-1][1]:,.0f}")

    import gi
    gi.require_version("GLib", "2.0")

    fetcher = PriceFetcher(on_price, on_history)
    fetcher._fetch_all()
