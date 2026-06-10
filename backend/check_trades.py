import csv
with open('C:/Users/adaga/OneDrive/Desktop/MT5/backend/backtest/data/XAUUSD_trades.csv') as f:
    r = list(csv.DictReader(f))
print(f'Total: {len(r)} trades')
for i, t in enumerate(r):
    print(f'{i+1:2}. {t["time"][:19]} {t["action"]:4} entry={t["entry"]:>7} exit={t["exit"]:>7} r={t["r"]:>6} outcome={t["outcome"]}')
