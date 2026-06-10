import sqlite3
import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta

mt5.initialize()

# Get last few trade logs
conn = sqlite3.connect('trading.db')
conn.row_factory = sqlite3.Row
logs = conn.execute("SELECT id, ticket, entry_price, profit, status FROM trade_logs ORDER BY id DESC LIMIT 5").fetchall()
print("=== DB Trade Logs ===")
for l in logs:
    print(f"  id={l['id']} ticket={l['ticket']} (type={type(l['ticket']).__name__}) entry={l['entry_price']} profit={l['profit']} status={l['status']}")

# Get MT5 deal history
now = datetime.now(timezone.utc)
deals = mt5.history_deals_get(now - timedelta(days=2), now)
if deals:
    print(f"\n=== MT5 Deals (last 10) ===")
    for d in deals[-10:]:
        print(f"  ticket={d.ticket} pos_id={d.position_id} (type={type(d.position_id).__name__}) entry={d.entry} price={d.price} profit={d.profit} comment={d.comment}")

    # Try matching
    if logs:
        test_ticket = logs[0]['ticket']
        print(f"\n=== Matching test for ticket={test_ticket} ===")
        for d in deals:
            if d.position_id == test_ticket:
                print(f"  MATCH (==): deal.ticket={d.ticket} entry={d.entry} profit={d.profit}")
            if str(d.position_id) == str(test_ticket):
                print(f"  MATCH (str): deal.ticket={d.ticket} entry={d.entry} profit={d.profit}")

conn.close()
mt5.shutdown()
