import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest.data_loader import HistoricalData, clock
import backtest.harness as harness
import strategies.entry_confirmation as ec
import ai.daily_bias as daily_bias
import pandas as pd

provider = HistoricalData(symbol='XAUUSD', spread=0.30)
h4 = provider.candles.get('H4')
print(f'H4 bars: {len(h4)}')

# Patch strategy
daily_bias.get_candles = provider.get_candles
ec.get_candles = provider.get_candles
ec.get_current_tick = provider.get_current_tick
ec.check_news_filter = lambda: (True, "news off (backtest)")
ec.check_session_filter = provider.check_session_filter
ec.check_spread_filter = lambda s: (True, "ok")

# Simulate backtest loop
SESSION_WINDOWS = [(13, 17)]
tf_dur = pd.Timedelta(minutes=240)
d1_ct = provider.close_times["D1"]
warmup_T = pd.Timestamp(d1_ct[49]) if len(d1_ct) > 50 else h4.iloc[0]["datetime"]
m1_start = pd.Timestamp(provider.candles["M1"]["datetime"].iloc[0])
start_T = max(warmup_T, m1_start)
print(f'start_T: {start_T}')

trades = 0
for i in range(len(h4)):
    T = h4.iloc[i]["datetime"] + tf_dur
    if T < start_T:
        continue
    clock.now = T
    
    # Check session filter
    hour = T.hour
    in_window = any(start <= hour <= end for start, end in SESSION_WINDOWS)
    if not in_window:
        continue
    
    sig = ec.evaluate_entry('XAUUSD')
    if sig.action in ('BUY', 'SELL'):
        trades += 1
        print(f'Trade {trades} at {T}: {sig.action} entry={sig.entry_price:.2f} sl={sig.sl_price:.2f}')
        if trades >= 10:
            break

print(f'Total trades found: {trades}')
