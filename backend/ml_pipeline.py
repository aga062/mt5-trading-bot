"""
ML Pipeline — XGBoost filter for H1 breakout signals
=======================================================
1. Runs backtest with feature extraction at each signal
2. Trains XGBoost on 70% of signals
3. Evaluates threshold filters on holdout 30%
4. Reports metrics at various probability cutoffs
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from backtest.data_loader import HistoricalData, clock
from backtest.harness import _simulate_trade, patch_strategy
from ai.indicators import compute_ema, compute_atr
from strategies.entry_confirmation import evaluate_entry

# ── Config ───────────────────────────────────────────────────────────────────
SYMBOL = "XAUUSD"
SPREAD = 0.30
TRAIN_FRAC = 0.70
THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]

# ── Feature extraction ───────────────────────────────────────────────────────

def extract_features(provider, T):
    """Extract features at time T (no lookahead — only uses closed bars)."""
    feats = {}

    h4 = provider.get_candles(SYMBOL, "H4", 50)
    h1 = provider.get_candles(SYMBOL, "H1", 100)
    m15 = provider.get_candles(SYMBOL, "M15", 30)
    d1 = provider.get_candles(SYMBOL, "D1", 5)

    if h4 is None or h1 is None or len(h4) < 25 or len(h1) < 55:
        return None

    h1c = h1.iloc[:-1]  # strip forming bar
    h4c = h4.iloc[:-1]

    # EMA distances
    h4_ema20 = float(compute_ema(h4c["close"], 20).iloc[-1])
    h1_ema50 = float(compute_ema(h1c["close"], 50).iloc[-1])
    h1_ema20 = float(compute_ema(h1c["close"], 20).iloc[-1])
    mid = (h1["high"].iloc[-1] + h1["low"].iloc[-1]) / 2

    feats["h4_dist_ema20"] = (mid - h4_ema20) / h4_ema20 * 100
    feats["h1_dist_ema50"] = (mid - h1_ema50) / h1_ema50 * 100
    feats["h1_dist_ema20"] = (mid - h1_ema20) / h1_ema20 * 100

    # ATR
    atr = float(compute_atr(h1c, 14).iloc[-1])
    feats["h1_atr"] = atr
    feats["h1_atr_pct"] = atr / mid * 100

    # Current H1 candle
    cur = h1c.iloc[-1]
    prev = h1c.iloc[-2]
    prev2 = h1c.iloc[-3] if len(h1c) >= 3 else prev
    prev3 = h1c.iloc[-4] if len(h1c) >= 4 else prev2

    body = abs(float(cur["close"]) - float(cur["open"]))
    rng = float(cur["high"]) - float(cur["low"])
    feats["body_atr"] = body / atr if atr > 0 else 0
    feats["range_atr"] = rng / atr if atr > 0 else 0
    feats["body_range"] = body / rng if rng > 0 else 0

    close_pos = (float(cur["close"]) - float(cur["low"])) / rng if rng > 0 else 0.5
    feats["close_pos"] = close_pos

    # Lower/upper wick ratios
    if float(cur["close"]) >= float(cur["open"]):
        upper_wick = float(cur["high"]) - float(cur["close"])
        lower_wick = float(cur["open"]) - float(cur["low"])
    else:
        upper_wick = float(cur["high"]) - float(cur["open"])
        lower_wick = float(cur["close"]) - float(cur["low"])
    feats["upper_wick_range"] = upper_wick / rng if rng > 0 else 0
    feats["lower_wick_range"] = lower_wick / rng if rng > 0 else 0

    # Prior bar structure
    prev_body = abs(float(prev["close"]) - float(prev["open"]))
    feats["prev_body_atr"] = prev_body / atr if atr > 0 else 0
    feats["body_vs_prev"] = body / prev_body if prev_body > 0 else 1

    # 3-bar momentum
    bodies = []
    for c in [prev, prev2, prev3]:
        bodies.append(float(c["close"]) - float(c["open"]))
    feats["net_3bar"] = sum(bodies)
    feats["consecutive"] = sum(1 for b in bodies if b > 0) if float(cur["close"]) > float(cur["open"]) else sum(1 for b in bodies if b < 0)

    # Time features
    ts = pd.Timestamp(T)
    feats["hour"] = ts.hour
    feats["dayofweek"] = ts.dayofweek
    feats["month"] = ts.month

    # Volatility regime: ATR vs 50-bar average ATR
    atr_hist = float(compute_atr(h1c, 14).mean())
    feats["atr_vs_hist"] = atr / atr_hist if atr_hist > 0 else 1

    # H1 swing proximity
    hi, lo = [], []
    hvals = h1c["high"].values
    lvals = h1c["low"].values
    for i in range(3, len(h1c) - 3):
        if all(hvals[i] >= hvals[i-j] and hvals[i] >= hvals[i+j] for j in range(1,4)):
            hi.append(float(hvals[i]))
        if all(lvals[i] <= lvals[i-j] and lvals[i] <= lvals[i+j] for j in range(1,4)):
            lo.append(float(lvals[i]))

    if hi and float(cur["close"]) < float(cur["open"]):
        feats["dist_nearest_swing"] = min(abs(float(cur["close"]) - v) for v in hi[-3:]) / atr if atr > 0 else 0
    elif lo and float(cur["close"]) > float(cur["open"]):
        feats["dist_nearest_swing"] = min(abs(float(cur["close"]) - v) for v in lo[-3:]) / atr if atr > 0 else 0
    else:
        feats["dist_nearest_swing"] = 0

    # D1 PDL/PDH distance
    if d1 is not None and len(d1) >= 3:
        pd_bar = d1.iloc[-2]
        pd_low, pd_high = float(pd_bar["low"]), float(pd_bar["high"])
        if float(cur["close"]) > float(cur["open"]):
            feats["dist_pdl"] = (float(cur["close"]) - pd_low) / atr if atr > 0 else 0
        else:
            feats["dist_pdh"] = (pd_high - float(cur["close"])) / atr if atr > 0 else 0
    else:
        feats["dist_pdl"] = feats["dist_pdh"] = 0

    return feats


# ── Backtest with feature logging ───────────────────────────────────────────

def run_with_features():
    provider = HistoricalData(symbol=SYMBOL, spread=SPREAD)
    patch_strategy(provider)

    h1_raw = provider.candles["H1"]
    n = len(h1_raw)

    # Warmup
    d1_ct = provider.close_times["D1"]
    warmup_T = pd.Timestamp(d1_ct[49]) if len(d1_ct) > 50 else h1_raw.iloc[0]["datetime"]
    m1_start = pd.Timestamp(provider.candles["M1"]["datetime"].iloc[0])
    start_T = max(warmup_T, m1_start)

    records = []
    next_eval = start_T

    for i in range(n):
        T = h1_raw.iloc[i]["datetime"] + pd.Timedelta(minutes=60)
        if T < next_eval:
            continue
        clock.now = T

        # Try to get signal
        sig = evaluate_entry(SYMBOL)
        if sig.action == "WAIT" or sig.ict_setup is None:
            continue

        # Extract features
        feats = extract_features(provider, T)
        if feats is None:
            continue

        # Simulate trade
        entry = sig.entry_price
        sl = sig.ict_setup.sl_price
        tp = sig.ict_setup.tp_price
        result = _simulate_trade(provider, T, sig.action, entry, sl, tp, "MARKET", 15, 24)
        next_eval = result["exit_time"]

        if result["status"] == "CLOSED" and not np.isnan(result["r"]):
            feats["outcome"] = 1 if result["r"] > 0 else 0
            feats["r"] = result["r"]
            feats["time"] = str(T)
            feats["action"] = sig.action
            records.append(feats)

    return pd.DataFrame(records)


# ── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Running backtest with feature extraction...")
    df = run_with_features()
    if len(df) < 50:
        print(f"Only {len(df)} signals — insufficient for ML. Need >= 50.")
        sys.exit(1)

    print(f"Total signals: {len(df)}  Wins: {df['outcome'].sum()}  WR: {df['outcome'].mean()*100:.1f}%")

    # Save for inspection
    df.to_csv("ml_features.csv", index=False)
    print("Saved to ml_features.csv")

    # Split
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    split = int(len(df) * TRAIN_FRAC)
    train = df.iloc[:split]
    test = df.iloc[split:]
    print(f"Train: {len(train)}  Test: {len(test)}")

    # Features / target
    feature_cols = [c for c in df.columns if c not in ["outcome", "r", "time", "action"]]
    X_train = train[feature_cols].values
    y_train = train["outcome"].values
    X_test = test[feature_cols].values
    y_test = test["outcome"].values
    r_test = test["r"].values

    # Train XGBoost
    try:
        import xgboost as xgb
    except ImportError:
        print("xgboot not installed. Installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "xgboost"])
        import xgboost as xgb

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        use_label_encoder=False,
        random_state=42,
    )
    model.fit(X_train, y_train)

    # Predictions
    probs = model.predict_proba(X_test)[:, 1]
    test = test.copy()
    test["prob"] = probs

    print("\n=== Threshold Analysis on Holdout ===")
    print(f"{'Thresh':>7} {'Trades':>7} {'WR%':>6} {'PF':>6} {'TotalR':>8} {'AvgWin':>7} {'AvgLoss':>8} {'MaxDD':>7}")

    for thresh in THRESHOLDS:
        mask = test["prob"] >= thresh
        subset = test[mask]
        if len(subset) < 10:
            continue
        wins = subset[subset["outcome"] == 1]
        losses = subset[subset["outcome"] == 0]
        wr = len(wins) / len(subset) * 100
        gross_win = wins["r"].sum()
        gross_loss = abs(losses["r"].sum())
        pf = gross_win / gross_loss if gross_loss > 0 else 0
        total = subset["r"].sum()
        avg_win = wins["r"].mean() if len(wins) > 0 else 0
        avg_loss = losses["r"].mean() if len(losses) > 0 else 0
        # Max DD on cumulative R
        cum = 0.0; peak = 0.0; mdd = 0.0
        for r in subset["r"].values:
            cum += r; peak = max(peak, cum); mdd = max(mdd, peak - cum)
        print(f"{thresh:7.2f} {len(subset):7d} {wr:6.1f} {pf:6.2f} {total:+8.2f} {avg_win:7.2f} {avg_loss:8.2f} {mdd:7.2f}")

    # Feature importance
    importance = pd.DataFrame({
        "feature": feature_cols,
        "importance": model.feature_importances_,
    }).sort_values("importance", ascending=False)
    print("\n=== Top 10 Features ===")
    print(importance.head(10).to_string(index=False))

    # Save model
    model.save_model("h1_breakout_xgb.json")
    print("\nModel saved to h1_breakout_xgb.json")
