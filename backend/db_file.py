"""
Database utility queries for the trading bot.
Run: python db_file.py <command>
Commands: status, clear_decisions, clear_trades, clear_errors, clear_all, vacuum
"""
import sqlite3
import sys

DB_PATH = "trading.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def status():
    """Show row counts for all tables."""
    conn = get_conn()
    tables = ["users", "mt5_credentials", "trade_logs", "ai_decision_logs",
              "error_logs", "performance_metrics", "user_settings"]
    print("\n  TABLE                    ROWS")
    print("  " + "-" * 35)
    for t in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:<25} {count}")
        except Exception:
            print(f"  {t:<25} (not found)")
    conn.close()


def clear_decisions():
    """Clear ai_decision_logs table."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM ai_decision_logs")
    conn.commit()
    print(f"Deleted {cur.rowcount} rows from ai_decision_logs")
    conn.close()


def clear_trades():
    """Clear trade_logs table."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM trade_logs")
    conn.commit()
    print(f"Deleted {cur.rowcount} rows from trade_logs")
    conn.close()


def clear_errors():
    """Clear error_logs table."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM error_logs")
    conn.commit()
    print(f"Deleted {cur.rowcount} rows from error_logs")
    conn.close()


def clear_all():
    """Clear all log tables (keeps users and credentials)."""
    conn = get_conn()
    for table in ["ai_decision_logs", "trade_logs", "error_logs"]:
        cur = conn.execute(f"DELETE FROM {table}")
        print(f"  Deleted {cur.rowcount} rows from {table}")
    conn.execute("UPDATE performance_metrics SET total_trades=0, winning_trades=0, "
                 "losing_trades=0, total_profit=0, max_drawdown=0, win_rate=0")
    conn.commit()
    print("  Reset performance_metrics")
    conn.close()


def vacuum():
    """Reclaim disk space after deletions."""
    conn = get_conn()
    conn.execute("VACUUM")
    conn.close()
    print("Database vacuumed (disk space reclaimed)")


if __name__ == "__main__":
    commands = {
        "status": status,
        "clear_decisions": clear_decisions,
        "clear_trades": clear_trades,
        "clear_errors": clear_errors,
        "clear_all": clear_all,
        "vacuum": vacuum,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python db_file.py <command>")
        print(f"Commands: {', '.join(commands.keys())}")
        sys.exit(1)

    commands[sys.argv[1]]()