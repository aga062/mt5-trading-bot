"""
Backtest data layer
====================
Downloads historical candles from MT5 (run once) and serves them back to the
LIVE strategy code as "what it would have seen at simulated time T" — leak-free.

Leak-free design: at time T, each timeframe returns its fully-CLOSED bars before T
plus one flat "forming" bar (O=H=L=C = current price at T). This mirrors what the
live `get_candles` returns (last row = forming bar) without exposing any future
high/low/close. The strategy's `df.iloc[:-1]` and `iloc[-1].close` behave identically.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("backtest.data_loader")

CACHE_DIR = Path(__file__).resolve().parent / "data"
CACHE_DIR.mkdir(exist_ok=True)

SYMBOL = "XAUUSD"
TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
# FundedNext server ≈ UTC+3 (summer/EEST). ONLY used to convert sim time → true UTC
# for the London/NY session filter. All price analysis is timezone-agnostic.
SERVER_UTC_OFFSET_HOURS = 3
DEFAULT_SPREAD = 0.30  # modeled XAUUSD round-turn spread (price units)

_TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def download_history(months: int = 6, symbol: str = SYMBOL):
    """Pull history from the running MT5 terminal and cache to CSV. Run once."""
    import MetaTrader5 as mt5
    from mt5.data_streamer import TIMEFRAME_MAP

    if not mt5.initialize():
        raise RuntimeError(
            f"mt5.initialize() failed: {mt5.last_error()}. "
            f"Open and log into your MT5 terminal first, then re-run --download."
        )
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=months * 31)
    chunk = timedelta(days=20)  # pull in chunks; M1 over long ranges returns 'Invalid params'
    try:
        for tf in TIMEFRAMES:
            frames = []
            cs = start
            while cs < end:
                ce = min(cs + chunk, end)
                rates = mt5.copy_rates_range(symbol, TIMEFRAME_MAP[tf], cs, ce)
                if rates is not None and len(rates) > 0:
                    frames.append(pd.DataFrame(rates))
                cs = ce
            if not frames:
                print(f"{tf}: no data ({mt5.last_error()})")
                continue
            df = pd.concat(frames, ignore_index=True)
            df["datetime"] = pd.to_datetime(df["time"], unit="s")
            df = df.rename(columns={"tick_volume": "volume"})
            df = df[["datetime", "open", "high", "low", "close", "volume"]]
            df = df.drop_duplicates(subset="datetime").sort_values("datetime").reset_index(drop=True)
            path = CACHE_DIR / f"{symbol}_{tf}.csv"
            df.to_csv(path, index=False)
            print(f"{tf}: {len(df)} bars  {df['datetime'].iloc[0]} -> {df['datetime'].iloc[-1]}")
    finally:
        mt5.shutdown()


class SimClock:
    """Holds the simulated 'now' (a pandas Timestamp). The engine advances it."""
    now: pd.Timestamp = None


clock = SimClock()


class HistoricalData:
    def __init__(self, symbol: str = SYMBOL, spread: float = DEFAULT_SPREAD,
                 server_offset_hours: int = SERVER_UTC_OFFSET_HOURS):
        self.symbol = symbol
        self.spread = spread
        self.offset = server_offset_hours
        self.candles: dict[str, pd.DataFrame] = {}
        self.close_times: dict[str, np.ndarray] = {}
        for tf in TIMEFRAMES:
            path = CACHE_DIR / f"{symbol}_{tf}.csv"
            if not path.exists():
                continue
            df = pd.read_csv(path, parse_dates=["datetime"]).sort_values("datetime").reset_index(drop=True)
            self.candles[tf] = df
            dur = pd.Timedelta(minutes=_TF_MINUTES[tf])
            self.close_times[tf] = (df["datetime"] + dur).values
        if "M5" not in self.candles or "M1" not in self.candles:
            raise RuntimeError("Missing M5/M1 cache. Run with --download first.")

    def _completed_count(self, tf: str) -> int:
        """How many tf bars are fully closed as of clock.now."""
        return int(np.searchsorted(self.close_times[tf], np.datetime64(clock.now), side="right"))

    def current_price(self):
        k = self._completed_count("M1")
        if k == 0:
            return None
        return float(self.candles["M1"].iloc[k - 1]["close"])

    def get_candles(self, symbol, timeframe, count=100):
        df = self.candles.get(timeframe)
        if df is None:
            return None
        k = self._completed_count(timeframe)
        price = self.current_price()
        if k == 0 or price is None:
            return None
        completed = df.iloc[max(0, k - count + 1):k]
        forming = pd.DataFrame([{
            "datetime": clock.now, "open": price, "high": price,
            "low": price, "close": price, "volume": 0,
        }])
        return pd.concat([completed, forming], ignore_index=True)

    def get_current_tick(self, symbol):
        price = self.current_price()
        if price is None:
            return None
        half = self.spread / 2.0
        return {
            "symbol": symbol, "bid": price - half, "ask": price + half,
            "last": price, "volume": 0, "time": str(clock.now), "spread": self.spread,
        }

    def check_session_filter(self):
        from zoneinfo import ZoneInfo
        utc_now = (clock.now - pd.Timedelta(hours=self.offset)).tz_localize("UTC")
        london = utc_now.astimezone(ZoneInfo("Europe/London"))
        ny = utc_now.astimezone(ZoneInfo("America/New_York"))
        in_london = (4, 30) <= (london.hour, london.minute) < (11, 30)
        in_ny = (9, 0) <= (ny.hour, ny.minute) < (17, 30)
        if in_london or in_ny:
            return True, "session ok"
        return False, "Outside trading sessions"
