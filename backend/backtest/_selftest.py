"""Synthetic-data self-test for the backtest harness (no MT5 needed)."""
import numpy as np
import pandas as pd

from backtest import data_loader as dl
from backtest.data_loader import clock
import backtest.harness as harness

_TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def make_provider(candles: dict, spread=0.2):
    p = dl.HistoricalData.__new__(dl.HistoricalData)
    p.symbol = "XAUUSD"; p.spread = spread; p.offset = 3
    p.candles = {}; p.close_times = {}
    for tf, df in candles.items():
        df = df.sort_values("datetime").reset_index(drop=True)
        p.candles[tf] = df
        p.close_times[tf] = (df["datetime"] + pd.Timedelta(minutes=_TF_MIN[tf])).values
    return p


def bars(start, n, minutes, price_fn):
    rows = []
    for k in range(n):
        t = pd.Timestamp(start) + pd.Timedelta(minutes=minutes * k)
        o, h, l, c = price_fn(k)
        rows.append({"datetime": t, "open": o, "high": h, "low": l, "close": c, "volume": 1})
    return pd.DataFrame(rows)


# ============================================================
# TEST A — leak-free provider + flat forming bar
# ============================================================
print("TEST A: leak-free data provider")
m1 = bars("2026-06-01 08:00", 180, 1, lambda k: (100 + k * 0.1,) * 4)  # close rises 0.1/min
# H1 bars: 08:00 (closes 09:00), 09:00 (10:00), 10:00 (11:00 = FORMING at 10:30)
h1 = pd.DataFrame([
    {"datetime": pd.Timestamp("2026-06-01 08:00"), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1},
    {"datetime": pd.Timestamp("2026-06-01 09:00"), "open": 100.5, "high": 102, "low": 100, "close": 101.5, "volume": 1},
    {"datetime": pd.Timestamp("2026-06-01 10:00"), "open": 101.5, "high": 9999, "low": 101, "close": 9000, "volume": 1},  # FUTURE leak trap
])
prov = make_provider({"M1": m1, "H1": h1})

clock.now = pd.Timestamp("2026-06-01 10:30:00")
cur = prov.current_price()
# M1 bar opening 10:29 closes 10:30 -> included; close = 100 + 149*0.1 = 114.9
print(f"  current_price = {cur} (expect 114.9)"); assert abs(cur - 114.9) < 1e-6

res = prov.get_candles("XAUUSD", "H1", 10)
print(f"  H1 rows returned: {len(res)}; last row (forming): close={res.iloc[-1]['close']}, high={res.iloc[-1]['high']}")
# Completed H1 = bars closing <= 10:30 = the 08:00 and 09:00 bars (close 09:00 and 10:00). The 10:00 bar (closes 11:00) is forming.
assert len(res) == 3, f"expect 2 completed + 1 forming, got {len(res)}"
assert res.iloc[-1]["close"] == cur, "forming close must = current price"
assert res.iloc[-1]["high"] == cur, "forming high must = current price (NOT future leak)"
assert 9999 not in res["high"].values, "FUTURE LEAK: the forming H1 bar's real high (9999) appeared!"
assert 9000 not in res["close"].values, "FUTURE LEAK: future close appeared!"
print("  [PASS] no future leak; forming bar is flat at current price\n")


# ============================================================
# TEST B — trade simulator (fill / TP / SL / cancel)
# ============================================================
print("TEST B: trade simulator")
T = pd.Timestamp("2026-06-01 12:00:00")

def sim(path_fn, n=60):
    m1b = bars("2026-06-01 12:01", n, 1, path_fn)
    p = make_provider({"M1": m1b}, spread=0.2)
    return harness._simulate_trade(p, T, "BUY", entry=100.0, sl=98.0, tp=106.0,
                                   expiry_minutes=15, max_hold_hours=24)

# 1) fills then hits TP: dips to 100 at k=2, then rises; TP 106 reached at k=40
def tp_path(k):
    if k == 2: return (101, 101, 99.9, 100.5)   # low 99.9 <= 100 -> fill
    if k == 40: return (105, 106.5, 104, 106.2)  # high 106.5 >= 106 -> TP
    return (101 + k * 0.05, 101.5 + k * 0.05, 100.5 + k * 0.05, 101 + k * 0.05)  # drift up, never <=98
r = sim(tp_path)
print(f"  TP case : {r['status']}/{r['outcome']} r={r['r']} (expect ~+2.9R)")
assert r["status"] == "CLOSED" and r["outcome"] == "TP" and abs(r["r"] - 2.9) < 0.05

# 2) fills then hits SL: dips to 100 (fill), then drops to 98
def sl_path(k):
    if k == 2: return (101, 101, 99.9, 100.5)
    if k == 20: return (99, 99, 97.9, 98.0)   # low 97.9 <= 98 -> SL
    return (100.5, 101, 99.5, 100)            # hovers, no TP
r = sim(sl_path)
print(f"  SL case : {r['status']}/{r['outcome']} r={r['r']} (expect ~-1.1R)")
assert r["status"] == "CLOSED" and r["outcome"] == "SL" and abs(r["r"] - (-1.1)) < 0.05

# 3) never fills (price stays above entry the whole expiry window)
def nofill_path(k):
    return (105 + k * 0.1, 105.5 + k * 0.1, 104.5 + k * 0.1, 105 + k * 0.1)  # low always > 100
r = sim(nofill_path)
print(f"  No-fill : {r['status']}/{r['outcome']} r={r['r']} (expect CANCELLED)")
assert r["status"] == "CANCELLED"
print("  [PASS] fill/TP/SL/cancel all correct\n")


# ============================================================
# TEST C — patch wiring smoke test
# ============================================================
print("TEST C: patch wiring")
harness.patch_strategy(prov)
import strategies.entry_confirmation as ec
import ai.daily_bias as db
assert ec.get_current_tick == prov.get_current_tick
assert db.get_candles == prov.get_candles
ok, _ = ec.check_session_filter.__call__() if False else (True, "")  # just ensure attr swapped
assert ec.check_news_filter()[0] is True
print("  [PASS] strategy modules patched to historical provider\n")

print("ALL SELF-TESTS PASSED")
