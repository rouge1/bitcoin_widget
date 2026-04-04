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
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._history_days = config.GRAPH_HISTORY_DAYS
        self.last_price_source = None

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
