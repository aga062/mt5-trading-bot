import numpy as np
import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
    }


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx


def compute_stochastic_rsi(series: pd.Series, rsi_period: int = 5,
                           k_period: int = 3, d_period: int = 3) -> dict:
    """Stochastic RSI: applies stochastic formula to RSI values.
    Returns dict with 'k' and 'd' Series."""
    rsi = compute_rsi(series, rsi_period)
    rsi_min = rsi.rolling(window=k_period).min()
    rsi_max = rsi.rolling(window=k_period).max()
    stoch_rsi_k = ((rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)) * 100
    stoch_rsi_k = stoch_rsi_k.fillna(50)
    stoch_rsi_d = stoch_rsi_k.rolling(window=d_period).mean()
    return {"k": stoch_rsi_k, "d": stoch_rsi_d}


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """Compute VWAP (Volume Weighted Average Price), reset daily.
    Requires 'high', 'low', 'close', 'volume', and 'datetime' columns."""
    df = df.copy()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, 1)  # avoid division by zero
    # Group by date for daily reset
    if "datetime" in df.columns:
        dates = df["datetime"].dt.date
    else:
        dates = pd.Series(0, index=df.index)  # no reset if no datetime
    cum_tp_vol = (tp * vol).groupby(dates).cumsum()
    cum_vol = vol.groupby(dates).cumsum()
    vwap = cum_tp_vol / cum_vol
    return vwap


def compute_momentum(series: pd.Series, period: int = 10) -> pd.Series:
    return series - series.shift(period)


def compute_volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(window=period).mean()


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema8"] = compute_ema(df["close"], 8)
    df["ema21"] = compute_ema(df["close"], 21)
    df["rsi"] = compute_rsi(df["close"], 14)

    macd = compute_macd(df["close"])
    df["macd_line"] = macd["macd_line"]
    df["macd_signal"] = macd["signal_line"]
    df["macd_histogram"] = macd["histogram"]

    df["atr"] = compute_atr(df, 14)
    df["adx"] = compute_adx(df, 14)
    df["momentum"] = compute_momentum(df["close"], 10)
    df["volume_sma"] = compute_volume_sma(df["volume"], 20)

    return df
