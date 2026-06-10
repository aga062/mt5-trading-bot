import pandas as pd
from pathlib import Path
p = Path('C:/Users/adaga/OneDrive/Desktop/MT5/backend/backtest/data')
for tf in ['M1','M5','M15','H1','H4','D1']:
    f = p / f'XAUUSD_{tf}.csv'
    if f.exists():
        df = pd.read_csv(f)
        print(f'{tf}: {len(df):>7} bars  {df["datetime"].iloc[0]}')
    else:
        print(f'{tf}: not found')
