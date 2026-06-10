"""
Backtest reporting — overall metrics + attribution (the Tier-1 analysis for free).
P&L is reported in R (risk multiples), which is independent of lot sizing.
"""
import re


def _metrics(closed: list[dict]) -> dict:
    if not closed:
        return {"trades": 0, "win_rate": 0.0, "total_r": 0.0, "avg_r": 0.0,
                "profit_factor": 0.0, "max_dd_r": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    # max drawdown on the cumulative-R equity curve
    cum = 0.0; peak = 0.0; max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "trades": len(closed),
        "win_rate": round(len(wins) / len(closed), 3),
        "total_r": round(sum(rs), 2),
        "avg_r": round(sum(rs) / len(closed), 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_dd_r": round(max_dd, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
    }


def _level_type(zone: str) -> str:
    m = re.search(r"Sweep (\w+)", zone or "")
    return m.group(1) if m else "?"


def _table(closed: list[dict], key_fn, title: str) -> str:
    buckets: dict[str, list] = {}
    for t in closed:
        buckets.setdefault(key_fn(t), []).append(t)
    lines = [f"\n{title}", f"  {'bucket':<16}{'trades':>7}{'win%':>7}{'totalR':>9}{'avgR':>8}"]
    for name, ts in sorted(buckets.items(), key=lambda kv: -_metrics(kv[1])["total_r"]):
        m = _metrics(ts)
        flag = "  (low n)" if m["trades"] < 20 else ""
        lines.append(f"  {name:<16}{m['trades']:>7}{m['win_rate']*100:>6.0f}%{m['total_r']:>9}{m['avg_r']:>8}{flag}")
    return "\n".join(lines)


def build_report(trades: list[dict], risk_per_trade_usd: float = 100.0) -> str:
    closed = [t for t in trades if t["status"] == "CLOSED"]
    cancelled = [t for t in trades if t["status"] == "CANCELLED"]
    placed = len(closed) + len(cancelled)
    fill_rate = len(closed) / placed if placed else 0.0
    m = _metrics(closed)

    out = []
    out.append("=" * 60)
    out.append("BACKTEST REPORT")
    out.append("=" * 60)
    out.append(f"Orders placed : {placed}   (filled {len(closed)}, cancelled {len(cancelled)})")
    out.append(f"Fill rate     : {fill_rate*100:.0f}%")
    out.append(f"Win rate      : {m['win_rate']*100:.0f}%   ({m['trades']} closed trades)")
    out.append(f"Total         : {m['total_r']:+.1f}R   (~${m['total_r']*risk_per_trade_usd:,.0f} at ${risk_per_trade_usd:.0f}/trade)")
    out.append(f"Expectancy    : {m['avg_r']:+.3f}R per trade")
    out.append(f"Profit factor : {m['profit_factor']}")
    out.append(f"Avg win/loss  : +{m['avg_win']}R / {m['avg_loss']}R")
    out.append(f"Max drawdown  : -{m['max_dd_r']}R")

    out.append(_table(closed, lambda t: t.get("tag", "?"), "BY SETUP TAG:"))
    out.append(_table(closed, lambda t: t["action"], "BY DIRECTION:"))
    out.append("=" * 60)
    return "\n".join(out)
