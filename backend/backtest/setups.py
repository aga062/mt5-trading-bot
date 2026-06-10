"""
Candidate trading setups for backtesting — each is ONE clean, mechanical strategy.
A setup returns a signal dict or None (WAIT):
    {"action": "BUY"|"SELL", "order_type": "MARKET"|"LIMIT",
     "entry": float, "sl": float, "tp": float, "tag": str}

All read leak-free historical candles via `provider.get_candles` (same as live).
Tunable params are module-level so the backtest loop can sweep them.
"""
from typing import Optional

from ai.indicators import compute_ema, compute_atr, compute_macd, compute_rsi, compute_vwap

# --- Mean-reversion params (tunable) ---
MR_EMA_LEN = 20
MR_ATR_LEN = 14
MR_BAND_K = 2.0      # entry when price stretches this many ATRs from the EMA
MR_SL_ATR = 1.5      # stop distance in ATR
MR_RR = 1.0          # reward : risk


def _band_signal(provider, symbol, tag="MR_band") -> Optional[dict]:
    """Raw fade-the-stretch signal: price stretched 2 ATR from the 20-EMA, closed back inside."""
    df = provider.get_candles(symbol, "M5", 150)
    if df is None or len(df) < 40:
        return None
    closed = df.iloc[:-1]              # drop the forming bar (live convention)
    if len(closed) < MR_EMA_LEN + 5:
        return None

    ema = compute_ema(closed["close"], MR_EMA_LEN)
    atr = compute_atr(closed, MR_ATR_LEN)
    e, a = float(ema.iloc[-1]), float(atr.iloc[-1])
    e_prev, a_prev = float(ema.iloc[-2]), float(atr.iloc[-2])
    if a <= 0 or a_prev <= 0:
        return None

    c_last, c_prev = closed.iloc[-1], closed.iloc[-2]
    price = provider.current_price()
    if price is None:
        return None

    sl_dist = MR_SL_ATR * a

    if c_prev["close"] < (e_prev - MR_BAND_K * a_prev) and c_last["close"] > (e - MR_BAND_K * a):
        return {"action": "BUY", "order_type": "MARKET", "entry": price,
                "sl": price - sl_dist, "tp": price + MR_RR * sl_dist, "tag": tag}
    if c_prev["close"] > (e_prev + MR_BAND_K * a_prev) and c_last["close"] < (e + MR_BAND_K * a):
        return {"action": "SELL", "order_type": "MARKET", "entry": price,
                "sl": price + sl_dist, "tp": price - MR_RR * sl_dist, "tag": tag}
    return None


def mean_reversion(provider, symbol="XAUUSD") -> Optional[dict]:
    """Fade a 2-ATR stretch from the 20-EMA. Market entry, fixed-RR. (No trend filter.)"""
    ok, _ = provider.check_session_filter()
    if not ok:
        return None
    return _band_signal(provider, symbol, tag="MR_band")


def _h1_trend(provider, symbol):
    """Returns 'UP', 'DOWN', or None from H1 EMA50 vs EMA200."""
    h1 = provider.get_candles(symbol, "H1", 250)
    if h1 is None:
        return None
    h1c = h1.iloc[:-1]
    if len(h1c) < 200:
        return None
    fast = float(compute_ema(h1c["close"], 50).iloc[-1])
    slow = float(compute_ema(h1c["close"], 200).iloc[-1])
    if fast > slow:
        return "UP"
    if fast < slow:
        return "DOWN"
    return None


def mr_trend(provider, symbol="XAUUSD") -> Optional[dict]:
    """Trend-filtered mean reversion: fade the stretch ONLY in the H1 trend direction
    (buy dips in uptrends, sell rallies in downtrends)."""
    ok, _ = provider.check_session_filter()
    if not ok:
        return None
    sig = _band_signal(provider, symbol, tag="MR_trend")
    if sig is None:
        return None
    trend = _h1_trend(provider, symbol)
    if trend is None:
        return None
    if sig["action"] == "BUY" and trend != "UP":
        return None
    if sig["action"] == "SELL" and trend != "DOWN":
        return None
    return sig


# --- Breakout params (tunable) ---
BO_ATR_LEN = 14
BO_SL_ATR = 1.5
BO_RR = 2.0          # bigger target dilutes spread


def asian_breakout(provider, symbol="XAUUSD") -> Optional[dict]:
    """Break of the overnight (Asian, server 00:00-08:00) range during London/NY.
    Momentum/with-the-move, market entry, RR 2. Triggers on the breakout bar only."""
    ok, _ = provider.check_session_filter()
    if not ok:
        return None
    m5 = provider.get_candles(symbol, "M5", 150)
    if m5 is None or len(m5) < 40:
        return None
    closed = m5.iloc[:-1]
    if len(closed) < 30:
        return None
    price = provider.current_price()
    if price is None:
        return None

    m15 = provider.get_candles(symbol, "M15", 200)
    if m15 is None:
        return None
    m15c = m15.iloc[:-1]
    today = closed.iloc[-1]["datetime"].date()
    asian = m15c[(m15c["datetime"].dt.date == today) & (m15c["datetime"].dt.hour < 8)]
    if len(asian) < 4:
        return None
    a_high, a_low = float(asian["high"].max()), float(asian["low"].min())

    atr = float(compute_atr(closed, BO_ATR_LEN).iloc[-1])
    if atr <= 0:
        return None
    sl_dist = BO_SL_ATR * atr
    c_prev, c_last = closed.iloc[-2], closed.iloc[-1]

    if c_prev["close"] <= a_high and c_last["close"] > a_high:   # break up
        return {"action": "BUY", "order_type": "MARKET", "entry": price,
                "sl": price - sl_dist, "tp": price + BO_RR * sl_dist, "tag": "asian_BO"}
    if c_prev["close"] >= a_low and c_last["close"] < a_low:     # break down
        return {"action": "SELL", "order_type": "MARKET", "entry": price,
                "sl": price + sl_dist, "tp": price - BO_RR * sl_dist, "tag": "asian_BO"}
    return None


# ============================================================
# SMC SNIPER — user's 3-layer strategy (H1 narrative -> M15 sweep+CHoCH -> M5 entry)
# Faithful-as-practical. Approximations noted: CHoCH/MSS = sweep + break of opposing
# swing; POI = the sweep zone; premium/discount = 50% of recent H1 swing range.
# ============================================================
SMC_MIN_RR = 1.2


def _swings(df, lookback=2):
    h, l = df["high"].values, df["low"].values
    highs, lows = [], []
    for i in range(lookback, len(df) - lookback):
        if all(h[i] >= h[i - j] and h[i] >= h[i + j] for j in range(1, lookback + 1)):
            highs.append(float(h[i]))
        if all(l[i] <= l[i - j] and l[i] <= l[i + j] for j in range(1, lookback + 1)):
            lows.append(float(l[i]))
    return highs, lows


def smc_sniper(provider, symbol="XAUUSD") -> Optional[dict]:
    ok, _ = provider.check_session_filter()
    if not ok:
        return None
    price = provider.current_price()
    if price is None:
        return None

    # ---- LAYER 1: H1 narrative (bias + premium/discount) ----
    h1 = provider.get_candles(symbol, "H1", 250)
    if h1 is None:
        return None
    h1c = h1.iloc[:-1]
    if len(h1c) < 200:
        return None
    ema200 = float(compute_ema(h1c["close"], 200).iloc[-1])
    bias = "BULLISH" if price > ema200 else "BEARISH"
    recent = h1c.tail(50)
    sw_hi, sw_lo = float(recent["high"].max()), float(recent["low"].min())
    mid = (sw_hi + sw_lo) / 2
    zone = "PREMIUM" if price > mid else "DISCOUNT"
    # Buy only bullish+discount; sell only bearish+premium (trade with bias, from value)
    if bias == "BULLISH" and zone != "DISCOUNT":
        return None
    if bias == "BEARISH" and zone != "PREMIUM":
        return None

    # ---- LAYER 2: M15 liquidity sweep + CHoCH ----
    m15 = provider.get_candles(symbol, "M15", 200)
    if m15 is None:
        return None
    m15c = m15.iloc[:-1]
    if len(m15c) < 40:
        return None
    hi, lo = _swings(m15c, 2)
    if len(hi) < 1 or len(lo) < 1:
        return None
    last_sh, last_sl = hi[-1], lo[-1]
    recent = m15c.tail(10)                       # relaxed: sweep window (sequence, not 1 bar)
    last_close = float(m15c.iloc[-1]["close"])

    if bias == "BULLISH":
        # swept a recent swing low and reclaimed it (liquidity grab + reversal)
        swept = float(recent["low"].min()) < last_sl and last_close > last_sl
        if not swept:
            return None
        swept_level = float(recent["low"].min())
    else:
        swept = float(recent["high"].max()) > last_sh and last_close < last_sh
        if not swept:
            return None
        swept_level = float(recent["high"].max())

    # ---- LAYER 3: M5 confirmation + indicator alignment ----
    m5 = provider.get_candles(symbol, "M5", 150)
    if m5 is None:
        return None
    m5c = m5.iloc[:-1]
    if len(m5c) < 40:
        return None
    macd = compute_macd(m5c["close"])
    macd_line, macd_sig = float(macd["macd_line"].iloc[-1]), float(macd["signal_line"].iloc[-1])
    rsi = float(compute_rsi(m5c["close"], 14).iloc[-1])
    vwap = float(compute_vwap(m5c).iloc[-1])
    atr = float(compute_atr(m5c, 14).iloc[-1])
    if atr <= 0:
        return None
    c_last, c_prev = m5c.iloc[-1], m5c.iloc[-2]
    rng = c_last["high"] - c_last["low"]
    if rng <= 0:
        return None

    if bias == "BULLISH":
        engulf = (c_last["close"] > c_last["open"] and c_prev["close"] < c_prev["open"]
                  and c_last["close"] > c_prev["open"] and c_last["open"] <= c_prev["close"])
        rej = (min(c_last["open"], c_last["close"]) - c_last["low"]) > 0.5 * rng and c_last["close"] > c_last["open"]
        if not (engulf or rej):
            return None
        if not (macd_line > macd_sig and rsi > 50 and price > vwap):
            return None
        sl = swept_level - 0.2 * atr
        tp = sw_hi                                  # opposite liquidity (H1 swing high)
        if (tp - price) < SMC_MIN_RR * (price - sl):
            return None
        return {"action": "BUY", "order_type": "MARKET", "entry": price, "sl": sl, "tp": tp, "tag": "SMC"}
    else:
        engulf = (c_last["close"] < c_last["open"] and c_prev["close"] > c_prev["open"]
                  and c_last["close"] < c_prev["open"] and c_last["open"] >= c_prev["close"])
        rej = (c_last["high"] - max(c_last["open"], c_last["close"])) > 0.5 * rng and c_last["close"] < c_last["open"]
        if not (engulf or rej):
            return None
        if not (macd_line < macd_sig and rsi < 50 and price < vwap):
            return None
        sl = swept_level + 0.2 * atr
        tp = sw_lo
        if (price - tp) < SMC_MIN_RR * (sl - price):
            return None
        return {"action": "SELL", "order_type": "MARKET", "entry": price, "sl": sl, "tp": tp, "tag": "SMC"}


# ============================================================
# POI TOUCH — H1 bias + fast M5 entry on first touch of a POI level.
# BUY (bullish H1): price pulls back to a support-type POI (PDL/PSL/H1 swing low/EQL/HL).
# SELL (bearish H1): price pulls back to a resistance-type POI (PDH/PSH/H1 swing high/EQH/LH).
# Market entry on the FIRST M5 bar that touches the level (no waiting). ATR-based 2R.
# (OB approximated by the swing-level set; premium/discount not used.)
# ============================================================
POI_TOL_ATR = 0.30     # "at the POI" tolerance
POI_SL_ATR = 1.0       # stop beyond the level
POI_RR = 2.0


def _poi_levels(provider, symbol, side):
    """Consolidated support (BUY) or resistance (SELL) levels with tags."""
    levels = []
    d1 = provider.get_candles(symbol, "D1", 5)
    if d1 is not None and len(d1) >= 3:
        pd_bar = d1.iloc[-2]   # previous completed day
        levels.append((float(pd_bar["low"] if side == "BUY" else pd_bar["high"]),
                       "PDL" if side == "BUY" else "PDH"))
    m15 = provider.get_candles(symbol, "M15", 200)
    if m15 is not None:
        m15c = m15.iloc[:-1]
        if len(m15c) > 4:
            today = m15c.iloc[-1]["datetime"].date()
            asian = m15c[(m15c["datetime"].dt.date == today) & (m15c["datetime"].dt.hour < 8)]
            if len(asian) >= 4:
                levels.append((float(asian["low"].min() if side == "BUY" else asian["high"].max()),
                               "PSL" if side == "BUY" else "PSH"))
    h1 = provider.get_candles(symbol, "H1", 120)
    if h1 is not None:
        h1c = h1.iloc[:-1]
        if len(h1c) > 10:
            hi, lo = _swings(h1c, 3)
            src = lo if side == "BUY" else hi
            for v in src[-5:]:
                levels.append((v, "H1_swing"))
    return levels


def poi_entry(provider, symbol="XAUUSD") -> Optional[dict]:
    ok, _ = provider.check_session_filter()
    if not ok:
        return None
    price = provider.current_price()
    if price is None:
        return None

    h1 = provider.get_candles(symbol, "H1", 250)
    if h1 is None or len(h1.iloc[:-1]) < 200:
        return None
    ema200 = float(compute_ema(h1.iloc[:-1]["close"], 200).iloc[-1])
    side = "BUY" if price > ema200 else "SELL"

    m5 = provider.get_candles(symbol, "M5", 60)
    if m5 is None:
        return None
    m5c = m5.iloc[:-1]
    if len(m5c) < 20:
        return None
    atr = float(compute_atr(m5c, 14).iloc[-1])
    if atr <= 0:
        return None
    tol = POI_TOL_ATR * atr
    curr, prev = m5c.iloc[-1], m5c.iloc[-2]

    for lvl, tag in _poi_levels(provider, symbol, side):
        if side == "BUY":
            # prior bar was above the level; current bar just dipped into the zone (first touch)
            if prev["close"] > lvl + tol and curr["low"] <= lvl + tol:
                sl = min(lvl, float(curr["low"])) - POI_SL_ATR * atr
                tp = price + POI_RR * atr
                if price - sl <= 0:
                    continue
                return {"action": "BUY", "order_type": "MARKET", "entry": price, "sl": sl, "tp": tp, "tag": tag}
        else:
            if prev["close"] < lvl - tol and curr["high"] >= lvl - tol:
                sl = max(lvl, float(curr["high"])) + POI_SL_ATR * atr
                tp = price - POI_RR * atr
                if sl - price <= 0:
                    continue
                return {"action": "SELL", "order_type": "MARKET", "entry": price, "sl": sl, "tp": tp, "tag": tag}
    return None


# ============================================================
# POI + REJECTION + STRUCTURE — user's refined setup (the hand-drawn diagram rule)
# H1 bias -> M5 rejection candle EXACTLY at a POI -> ONLY at a Higher Low (BUY) /
# Lower High (SELL), never at HH/LL -> fast market entry right after the rejection.
# POI set (PDL/PSL/H1-swing-low for BUY; mirror for SELL) approximates EQL/HL/Support/OB.
# TP = 2R (my choice; not in spec). All candles are real MT5 history (leak-free).
# ============================================================
PR_TOL_ATR = 0.35       # "exactly at the POI" tolerance
PR_MIN_RISK_ATR = 0.8   # floor on risk so spread doesn't dominate
PR_RR = 2.0


def poi_reject(provider, symbol="XAUUSD") -> Optional[dict]:
    ok, _ = provider.check_session_filter()
    if not ok:
        return None
    price = provider.current_price()
    if price is None:
        return None

    # ---- H1 bias ----
    h1 = provider.get_candles(symbol, "H1", 250)
    if h1 is None or len(h1.iloc[:-1]) < 200:
        return None
    ema200 = float(compute_ema(h1.iloc[:-1]["close"], 200).iloc[-1])
    side = "BUY" if price > ema200 else "SELL"

    # ---- M5 rejection candle (just closed) ----
    m5 = provider.get_candles(symbol, "M5", 100)
    if m5 is None:
        return None
    m5c = m5.iloc[:-1]
    if len(m5c) < 30:
        return None
    atr = float(compute_atr(m5c, 14).iloc[-1])
    if atr <= 0:
        return None
    tol = PR_TOL_ATR * atr
    cur = m5c.iloc[-1]
    o, h, l, c = float(cur["open"]), float(cur["high"]), float(cur["low"]), float(cur["close"])
    rng = h - l
    if rng <= 0:
        return None
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)

    # ---- M5 structure (exclude the rejection bar) ----
    hi, lo = _swings(m5c.iloc[:-1], 2)
    levels = _poi_levels(provider, symbol, side)
    if not levels:
        return None

    if side == "BUY":
        if not (lower_wick >= 0.5 * rng and c > o):     # bullish rejection candle
            return None
        if not lo or l <= lo[-1]:                       # must be a HIGHER LOW (diagram rule)
            return None
        for lvl, tag in levels:
            if abs(l - lvl) <= tol:                     # rejection low EXACTLY at the POI
                struct_sl = min(l, lvl) - 0.3 * atr
                risk = max(price - struct_sl, PR_MIN_RISK_ATR * atr)
                return {"action": "BUY", "order_type": "MARKET", "entry": price,
                        "sl": price - risk, "tp": price + PR_RR * risk, "tag": tag}
    else:
        if not (upper_wick >= 0.5 * rng and c < o):     # bearish rejection candle
            return None
        if not hi or h >= hi[-1]:                       # must be a LOWER HIGH (diagram rule)
            return None
        for lvl, tag in levels:
            if abs(h - lvl) <= tol:
                struct_sl = max(h, lvl) + 0.3 * atr
                risk = max(struct_sl - price, PR_MIN_RISK_ATR * atr)
                return {"action": "SELL", "order_type": "MARKET", "entry": price,
                        "sl": price + risk, "tp": price - PR_RR * risk, "tag": tag}
    return None


# ============================================================
# POI_STRUCT — user's FINAL spec (to be wired live after validation):
# H1 bias -> M5 first-touch of a POI -> ONLY at Higher Low (BUY) / Lower High (SELL)
# per the diagram -> fast MARKET entry (no waiting) -> TP = NEAREST key level (closest,
# with a floor) -> structural SL. No rejection candle. Real MT5 data only.
# ============================================================
PS_TOL_ATR = 0.35
PS_SL_ATR = 0.5


def poi_struct(provider, symbol="XAUUSD") -> Optional[dict]:
    ok, _ = provider.check_session_filter()
    if not ok:
        return None
    price = provider.current_price()
    if price is None:
        return None

    h1 = provider.get_candles(symbol, "H1", 250)
    if h1 is None or len(h1.iloc[:-1]) < 200:
        return None
    ema200 = float(compute_ema(h1.iloc[:-1]["close"], 200).iloc[-1])
    side = "BUY" if price > ema200 else "SELL"

    m5 = provider.get_candles(symbol, "M5", 100)
    if m5 is None:
        return None
    m5c = m5.iloc[:-1]
    if len(m5c) < 30:
        return None
    atr = float(compute_atr(m5c, 14).iloc[-1])
    if atr <= 0:
        return None
    tol = PS_TOL_ATR * atr
    cur, prev = m5c.iloc[-1], m5c.iloc[-2]
    hi, lo = _swings(m5c.iloc[:-1], 2)

    poi = _poi_levels(provider, symbol, side)                              # entry POIs
    opp = _poi_levels(provider, symbol, "SELL" if side == "BUY" else "BUY")  # TP key levels
    if not poi:
        return None

    if side == "BUY":
        # POI = any of EQL/HL/Support/PDL/PSL/OB. Image rule = DON'T CHASE: skip only if
        # price is extended at a fresh Higher High (we enter on the pullback to a POI).
        if hi and float(cur["high"]) > hi[-1]:
            return None
        for lvl, tag in poi:
            if prev["close"] > lvl + tol and cur["low"] <= lvl + tol:   # fast first touch
                sl = min(float(cur["low"]), lvl) - PS_SL_ATR * atr
                risk = price - sl
                if risk <= 0:
                    continue
                cands = [p for p, _ in opp if p > price + max(risk, atr)]
                tp = min(cands) if cands else price + 2 * risk           # nearest key level above
                return {"action": "BUY", "order_type": "MARKET", "entry": price, "sl": sl, "tp": tp, "tag": tag}
    else:
        # POI = any of EQH/LH/Resistance/PDH/PSH/OB. Don't chase: skip only if price is
        # extended at a fresh Lower Low (we enter on the pullback up to a POI).
        if lo and float(cur["low"]) < lo[-1]:
            return None
        for lvl, tag in poi:
            if prev["close"] < lvl - tol and cur["high"] >= lvl - tol:
                sl = max(float(cur["high"]), lvl) + PS_SL_ATR * atr
                risk = sl - price
                if risk <= 0:
                    continue
                cands = [p for p, _ in opp if p < price - max(risk, atr)]
                tp = max(cands) if cands else price - 2 * risk           # nearest key level below
                return {"action": "SELL", "order_type": "MARKET", "entry": price, "sl": sl, "tp": tp, "tag": tag}
    return None
