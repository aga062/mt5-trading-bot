import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest.data_loader import HistoricalData
from strategies.entry_confirmation import _detect_crossover, _compute_sma
from ai.indicators import compute_ema

provider = HistoricalData(symbol='XAUUSD', spread=0.30)
h4 = provider.candles.get('H4')
print(f'H4 bars: {len(h4) if h4 is not None else 0}')
if h4 is not None and len(h4) > 30:
    print(f'Date range: {h4["datetime"].iloc[0]} -> {h4["datetime"].iloc[-1]}')
    sma = _compute_sma(h4['close'], 9)
    ema = compute_ema(h4['close'], 20)
    print(f'SMA last 5: {list(sma.iloc[-5:].values)}')
    print(f'EMA last 5: {list(ema.iloc[-5:].values)}')
    
    bull_crosses = 0
    bear_crosses = 0
    for idx in range(1, len(sma) - 1):
        if sma.iloc[idx-1] <= ema.iloc[idx-1] and sma.iloc[idx] > ema.iloc[idx]:
            if sma.iloc[idx+1] > ema.iloc[idx+1]:
                bull_crosses += 1
        if sma.iloc[idx-1] >= ema.iloc[idx-1] and sma.iloc[idx] < ema.iloc[idx]:
            if sma.iloc[idx+1] < ema.iloc[idx+1]:
                bear_crosses += 1
    print(f'Bullish crossovers: {bull_crosses}, Bearish crossovers: {bear_crosses}')
    print('Last 10 bars:')
    for i in range(-10, 0):
        s = float(sma.iloc[i]); e = float(ema.iloc[i])
        print(f'  i={i:3d}: SMA={s:10.2f} EMA={e:10.2f}  {"BUY" if s>e else "SELL"}')
    result = _detect_crossover(h4)
    print(f'_detect_crossover result: {result}')
