"""
Backtest harness — H1 50 EMA + M5 Pullback + Fixed TP at Key Zone + Profit Locks

Faithfulness: calls the real `evaluate_entry()` unchanged.
Profit locks: 25% → SL@25%, 50% → SL@50%, 75% → SL@75%. Past 75% → run to TP
or get stopped at 75% level.
"""
import logging

import numpy as np
import pandas as pd

from backtest.data_loader import HistoricalData, clock

logger = logging.getLogger("backtest.harness")


def patch_strategy(provider: HistoricalData):
    """Redirect every live data call in the strategy modules to the historical provider."""
    import ai.daily_bias as daily_bias
    import strategies.entry_confirmation as ec

    daily_bias.get_candles = provider.get_candles

    ec.get_candles = provider.get_candles                      # live entry engine reads candles directly
    ec.get_current_tick = provider.get_current_tick
    ec.check_news_filter = lambda: (True, "news off (backtest)")
    ec.check_session_filter = provider.check_session_filter
    ec.check_spread_filter = lambda s: (True, "ok")            # spread modeled in execution


def _close(action, entry, exit_price, risk, exit_time, reason, spread):
    r_gross = (exit_price - entry) / risk if action == "BUY" else (entry - exit_price) / risk
    r_net = r_gross - (spread / risk)   # round-turn spread cost
    return {"status": "CLOSED", "exit": round(exit_price, 3), "r": round(r_net, 3),
            "outcome": reason, "exit_time": exit_time}


def _finest_tf(provider):
    """Pick the finest available timeframe with at least ~6 months of data."""
    # 6 months ≈ 180 days; bars needed per TF:
    min_bars = {"M1": 180 * 24 * 60, "M5": 180 * 24 * 12, "M15": 180 * 24 * 4,
                "H1": 180 * 24, "H4": 180 * 6}
    for tf in ["M1", "M5", "M15", "H1"]:
        if tf in provider.candles and provider.candles[tf] is not None:
            bars = len(provider.candles[tf])
            if bars >= min_bars.get(tf, 0):
                return tf
    # Fallback to whatever is available
    for tf in ["M1", "M5", "M15", "H1", "H4"]:
        if tf in provider.candles and provider.candles[tf] is not None:
            return tf
    return "H4"


def _simulate_trade(provider, T, action, entry, sl, tp, order_type, expiry_minutes, max_hold_hours):
    sim_tf = _finest_tf(provider)
    bars = provider.candles[sim_tf]
    bar_open = bars["datetime"].values
    spread = provider.spread
    risk = abs(entry - sl)
    if risk <= 0:
        return {"status": "SKIP", "r": 0.0, "exit": None, "outcome": "bad_risk", "exit_time": T}

    n = len(bars)
    j = int(np.searchsorted(bar_open, np.datetime64(T), side="left"))

    if order_type == "LIMIT":
        expiry_time = T + pd.Timedelta(minutes=expiry_minutes)
        fill_time = None
        while j < n and bars.iloc[j]["datetime"] <= expiry_time:
            bar = bars.iloc[j]
            if action == "BUY" and bar["low"] <= entry:
                fill_time = bar["datetime"]; break
            if action == "SELL" and bar["high"] >= entry:
                fill_time = bar["datetime"]; break
            j += 1
        if fill_time is None:
            return {"status": "CANCELLED", "r": 0.0, "exit": None, "outcome": "no_fill", "exit_time": expiry_time}
    else:  # MARKET — fill immediately at the next bar
        if j >= n:
            return {"status": "SKIP", "r": 0.0, "exit": None, "outcome": "no_data", "exit_time": T}
        fill_time = bars.iloc[j]["datetime"]

    # ── Phase 2 — Fixed TP + profit-lock ratchet ──
    max_time = fill_time + pd.Timedelta(hours=max_hold_hours)

    # Profit-lock levels:
    #   25% of TP distance reached → move SL to 25% level
    #   50% of TP distance reached → move SL to 50% level
    #   75% of TP distance reached → move SL to 75% level
    #   Past 75% → continue to TP, or get stopped at 75% level
    PROFIT_LOCK_LEVELS = [0.25, 0.50, 0.75]

    if action == "BUY":
        profit_dist = tp - entry
        lock_prices = [entry + lvl * profit_dist for lvl in PROFIT_LOCK_LEVELS]
        lock_sl   = lock_prices                        # SL moves to the same level
    else:
        profit_dist = entry - tp
        lock_prices = [entry - lvl * profit_dist for lvl in PROFIT_LOCK_LEVELS]
        lock_sl   = lock_prices

    current_sl = sl
    lock_idx = 0

    while j < n and bars.iloc[j]["datetime"] <= max_time:
        bar = bars.iloc[j]
        high, low = bar["high"], bar["low"]

        # ── Profit-lock ratchet (fast, no delay) ──
        while lock_idx < len(lock_prices):
            if action == "BUY" and high >= lock_prices[lock_idx]:
                current_sl = max(current_sl, lock_sl[lock_idx])
                lock_idx += 1
            elif action == "SELL" and low <= lock_prices[lock_idx]:
                current_sl = min(current_sl, lock_sl[lock_idx])
                lock_idx += 1
            else:
                break

        # ── Fixed TP exit ──
        if action == "BUY":
            hit_sl, hit_tp = low <= current_sl, high >= tp
        else:
            hit_sl, hit_tp = high >= current_sl, low <= tp

        if hit_sl and hit_tp:
            return _close(action, entry, current_sl, risk, bar["datetime"], f"SL@{lock_idx}", spread)
        if hit_sl:
            return _close(action, entry, current_sl, risk, bar["datetime"], f"SL@{lock_idx}", spread)
        if hit_tp:
            return _close(action, entry, tp, risk, bar["datetime"], "TP", spread)

        j += 1

    last_px = float(bars.iloc[min(j, n - 1)]["close"])
    return _close(action, entry, last_px, risk, max_time, "TIME", spread)


def _ict_signal(provider, symbol):
    """Adapter: run the live ICT pipeline and return a setup signal dict (or None)."""
    from strategies.entry_confirmation import evaluate_entry
    sig = evaluate_entry(symbol)
    if sig.action == "WAIT" or sig.ict_setup is None:
        return None
    s = sig.ict_setup
    return {"action": sig.action, "order_type": getattr(sig, "order_kind", "MARKET"),
            "entry": sig.entry_price, "sl": s.sl_price, "tp": s.tp_price,
            "tag": getattr(sig, "m5_zone_str", "POI"),
            "max_hold_hours": getattr(sig, "max_hold_hours", 24)}


def run(provider: HistoricalData, symbol="XAUUSD", signal_fn=None, expiry_minutes=15,
        max_hold_hours=24, daily_loss_limit=5, progress=True, eval_tf="M5"):
    """Replay a setup over history. signal_fn(provider, symbol) -> signal dict or None.
    Defaults to the live ICT pipeline.

    eval_tf: timeframe to drive the evaluation loop ("M5" or "H1").
    """
    patch_strategy(provider)
    if signal_fn is None:
        signal_fn = _ict_signal

    tf_bars = provider.candles.get(eval_tf)
    if tf_bars is None:
        raise ValueError(f"No cached data for timeframe {eval_tf}")
    n = len(tf_bars)
    tf_dur = pd.Timedelta(minutes={"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}.get(eval_tf, 5))

    # Warm-up: need ≥50 D1 bars AND finest-TF coverage from the entry time.
    d1_ct = provider.close_times["D1"]
    warmup_T = pd.Timestamp(d1_ct[49]) if len(d1_ct) > 50 else tf_bars.iloc[0]["datetime"]
    sim_tf = _finest_tf(provider)
    sim_start = pd.Timestamp(provider.candles[sim_tf]["datetime"].iloc[0])
    start_T = max(warmup_T, sim_start)

    trades = []
    next_eval_time = start_T
    day_losses = {}

    for i in range(n):
        T = tf_bars.iloc[i]["datetime"] + tf_dur
        if T < next_eval_time:
            continue
        clock.now = T
        if day_losses.get(T.date(), 0) >= daily_loss_limit:
            continue

        sig = signal_fn(provider, symbol)
        if sig is None:
            continue

        result = _simulate_trade(provider, T, sig["action"], sig["entry"], sig["sl"], sig["tp"],
                                 sig.get("order_type", "LIMIT"), expiry_minutes,
                                 sig.get("max_hold_hours", max_hold_hours))
        next_eval_time = result["exit_time"]   # one trade at a time

        if result["status"] in ("CLOSED", "CANCELLED"):
            trades.append({
                "time": str(T), "action": sig["action"], "tag": sig.get("tag", ""),
                "entry": round(sig["entry"], 3), "sl": round(sig["sl"], 3), "tp": round(sig["tp"], 3),
                "status": result["status"], "outcome": result["outcome"],
                "exit": result["exit"], "r": result["r"],
            })
            if result["status"] == "CLOSED" and result["r"] < 0:
                day_losses[T.date()] = day_losses.get(T.date(), 0) + 1

        if progress and i % 1000 == 0:
            print(f"  ...{i}/{n} bars  ({T.date()})  trades={len(trades)}", flush=True)

    return trades
