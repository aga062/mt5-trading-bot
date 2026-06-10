import asyncio
import logging
import sys
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import LOG_DIR, DEFAULT_SYMBOL, DAILY_LOSS_LIMIT
from database.db import init_db, get_db
from auth.auth import (
    UserRegister, UserLogin, Token, UserOut,
    register_user, login_user, get_current_user, get_current_admin,
    AdminUserCreate, AdminUserUpdate,
    admin_create_user, admin_list_users, admin_update_user, admin_delete_user
)
from mt5.connector import (
    MT5Credentials, MT5ConnectionStatus,
    connect_mt5, disconnect_mt5, is_connected, get_account_info, reconnect_mt5
)
from mt5.data_streamer import (
    get_candles, get_current_tick, get_symbol_info,
    get_open_positions, get_trade_history
)
from ai.trend_analyzer import analyze_h1_trend
from ai.decision_engine import make_decision
from ai.ob_fvg_detector import detect_zones
from ai.daily_bias import analyze_daily_bias
from strategies.entry_confirmation import evaluate_entry
from strategies.trading_loop import (
    start_trading, stop_trading, is_trading_active, trading_loop,
    _check_closed_trades, _sync_mt5_history
)
from risk.risk_manager import count_todays_losses
from websocket.ws_manager import ws_manager
from news.news_filter import is_news_blackout, get_upcoming_events

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "trading.log"),
    ]
)
logger = logging.getLogger("main")

# --- App Lifecycle ---
_background_tasks: dict[int, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized")
    yield
    # Cleanup
    for uid, task in _background_tasks.items():
        task.cancel()
    logger.info("Shutting down")


app = FastAPI(
    title="AI Trading Platform",
    version="1.0.0",
    lifespan=lifespan
)

import os
_cors_origins = os.getenv("CORS_ORIGINS", "*")
allow_origins = [o.strip() for o in _cors_origins.split(",")] if _cors_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# AUTH ROUTES
# ============================================================

def _is_first_user() -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()
        return row["count"] == 0


# Register is admin-only — regular users cannot self-register.
# Exception: if no users exist, first registration becomes admin automatically.
@app.post("/api/auth/register", response_model=UserOut)
def api_register(data: UserRegister, admin=Depends(get_current_admin)):
    return admin_create_user(AdminUserCreate(**data.model_dump(), role="user"))


# Bootstrap endpoint — only works when zero users exist
@app.post("/api/auth/bootstrap", response_model=UserOut)
def api_bootstrap(data: UserRegister):
    if not _is_first_user():
        raise HTTPException(status_code=403, detail="Bootstrap only available when no users exist")
    return admin_create_user(AdminUserCreate(**data.model_dump(), role="admin"))


@app.post("/api/auth/login", response_model=Token)
def api_login(data: UserLogin):
    return login_user(data)


@app.get("/api/auth/me", response_model=UserOut)
def api_me(user=Depends(get_current_user)):
    return UserOut(**user)


# ============================================================
# ADMIN ROUTES
# ============================================================

@app.get("/api/admin/users")
def api_admin_list_users(admin=Depends(get_current_admin)):
    return admin_list_users()


@app.post("/api/admin/users", response_model=UserOut)
def api_admin_create_user(data: AdminUserCreate, admin=Depends(get_current_admin)):
    return admin_create_user(data)


@app.put("/api/admin/users/{user_id}", response_model=UserOut)
def api_admin_update_user(user_id: int, data: AdminUserUpdate, admin=Depends(get_current_admin)):
    return admin_update_user(user_id, data)


@app.delete("/api/admin/users/{user_id}")
def api_admin_delete_user(user_id: int, admin=Depends(get_current_admin)):
    return admin_delete_user(user_id)


# ============================================================
# MT5 CONNECTION ROUTES
# ============================================================

@app.post("/api/mt5/connect", response_model=MT5ConnectionStatus)
def api_mt5_connect(creds: MT5Credentials, user=Depends(get_current_user)):
    return connect_mt5(user["id"], creds)


@app.post("/api/mt5/disconnect")
def api_mt5_disconnect(user=Depends(get_current_user)):
    disconnect_mt5(user["id"])
    return {"status": "disconnected"}


@app.get("/api/mt5/status")
def api_mt5_status(user=Depends(get_current_user)):
    connected = is_connected(user["id"])
    account = get_account_info() if connected else None
    losses_today = count_todays_losses(user["id"])
    return {
        "connected": connected,
        "account": account,
        "trading_active": is_trading_active(user["id"]),
        "losses_today": losses_today,
        "daily_loss_limit": DAILY_LOSS_LIMIT,
        "halted": losses_today >= DAILY_LOSS_LIMIT,
    }


@app.post("/api/mt5/reconnect", response_model=MT5ConnectionStatus)
def api_mt5_reconnect(user=Depends(get_current_user)):
    return reconnect_mt5(user["id"])


# ============================================================
# MARKET DATA ROUTES
# ============================================================

@app.get("/api/market/tick")
def api_tick(symbol: str = DEFAULT_SYMBOL, user=Depends(get_current_user)):
    tick = get_current_tick(symbol)
    if tick is None:
        raise HTTPException(status_code=404, detail="Tick data unavailable")
    return tick


@app.get("/api/market/candles")
def api_candles(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = "H1",
    count: int = 100,
    user=Depends(get_current_user)
):
    df = get_candles(symbol, timeframe, count)
    if df is None:
        raise HTTPException(status_code=404, detail="Candle data unavailable")
    records = df.to_dict(orient="records")
    for r in records:
        r["datetime"] = str(r["datetime"])
        for k, v in r.items():
            if hasattr(v, 'item'):  # numpy scalar → native Python
                r[k] = v.item()
    return records


@app.get("/api/market/symbol-info")
def api_symbol_info(symbol: str = DEFAULT_SYMBOL, user=Depends(get_current_user)):
    info = get_symbol_info(symbol)
    if info is None:
        raise HTTPException(status_code=404, detail="Symbol info unavailable")
    return info


@app.get("/api/market/positions")
def api_positions(symbol: Optional[str] = None, user=Depends(get_current_user)):
    return get_open_positions(symbol)


@app.get("/api/market/history")
def api_trade_history(days: int = 30, user=Depends(get_current_user)):
    return get_trade_history(days)


# ============================================================
# AI / ANALYSIS ROUTES
# ============================================================

@app.get("/api/ai/daily-bias")
def api_daily_bias(symbol: str = DEFAULT_SYMBOL, user=Depends(get_current_user)):
    bias = analyze_daily_bias(symbol)
    if bias is None:
        raise HTTPException(status_code=500, detail="Daily bias analysis failed")
    return bias.to_dict()


@app.get("/api/ai/trend")
def api_trend(symbol: str = DEFAULT_SYMBOL, user=Depends(get_current_user)):
    trend = analyze_h1_trend(symbol)
    if trend is None:
        raise HTTPException(status_code=500, detail="Trend analysis failed")
    return trend.to_dict()


@app.get("/api/ai/decision")
def api_decision(symbol: str = DEFAULT_SYMBOL, user=Depends(get_current_user)):
    trend = analyze_h1_trend(symbol)
    if trend is None:
        raise HTTPException(status_code=500, detail="Trend analysis failed")
    decision = make_decision(symbol, trend)
    if decision is None:
        raise HTTPException(status_code=500, detail="Decision engine failed")
    return decision.to_dict()


@app.get("/api/ai/zones")
def api_zones(
    symbol: str = DEFAULT_SYMBOL,
    direction: str = "BULLISH",
    user=Depends(get_current_user)
):
    tick = get_current_tick(symbol)
    if tick is None:
        raise HTTPException(status_code=404, detail="No tick data")
    price = tick["ask"] if direction == "BULLISH" else tick["bid"]
    result = detect_zones(symbol, direction, price)
    return result.to_dict()


@app.get("/api/ai/signal")
def api_signal(symbol: str = DEFAULT_SYMBOL, user=Depends(get_current_user)):
    signal = evaluate_entry(symbol)
    return signal.to_dict()


# ============================================================
# TRADING CONTROL ROUTES
# ============================================================

class TradingControlRequest(BaseModel):
    symbols: list[str] = None
    manual_lot: float | None = None


@app.post("/api/trading/start")
async def api_start_trading(req: TradingControlRequest, user=Depends(get_current_user)):
    user_id = user["id"]

    if not is_connected(user_id):
        raise HTTPException(status_code=400, detail="MT5 not connected")

    if is_trading_active(user_id):
        raise HTTPException(status_code=400, detail="Trading already active")

    from config import DEFAULT_SYMBOLS
    symbols = req.symbols or DEFAULT_SYMBOLS
    start_trading(user_id, symbols, manual_lot=req.manual_lot)

    task = asyncio.create_task(trading_loop(user_id))
    _background_tasks[user_id] = task

    return {"status": "trading_started", "symbols": symbols, "manual_lot": req.manual_lot}


@app.post("/api/trading/stop")
async def api_stop_trading(user=Depends(get_current_user)):
    user_id = user["id"]
    stop_trading(user_id)

    task = _background_tasks.pop(user_id, None)
    if task:
        task.cancel()

    return {"status": "trading_stopped"}


@app.get("/api/trading/status")
def api_trading_status(user=Depends(get_current_user)):
    user_id = user["id"]
    return {
        "active": is_trading_active(user_id),
        "connected": is_connected(user_id),
    }


# ============================================================
# ANALYTICS / LOGS ROUTES
# ============================================================

@app.get("/api/analytics/performance")
def api_performance(user=Depends(get_current_user)):
    # Sync trades from MT5 before calculating — works even when AI is OFF
    if is_connected(user["id"]):
        try:
            _sync_mt5_history(user["id"])
            _check_closed_trades(user["id"])
        except Exception:
            pass

    with get_db() as conn:
        rows = conn.execute(
            "SELECT profit, status FROM trade_logs WHERE user_id = ? ORDER BY opened_at ASC",
            (user["id"],)
        ).fetchall()

    if not rows:
        return {
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "total_profit": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
        }

    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    total_profit = 0.0
    running_profit = 0.0
    peak_profit = 0.0
    max_drawdown = 0.0

    for row in rows:
        status = row["status"]
        profit = row["profit"] or 0.0

        # Count all executed trades (CLOSED or FILLED, not FAILED/PENDING)
        if status in ("CLOSED", "FILLED", "EXECUTED"):
            total_trades += 1
            total_profit += profit
            running_profit += profit

            if profit >= 0:
                winning_trades += 1
            else:
                losing_trades += 1

            # Track drawdown
            if running_profit > peak_profit:
                peak_profit = running_profit
            drawdown = peak_profit - running_profit
            if drawdown > max_drawdown:
                max_drawdown = drawdown

    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "total_profit": round(total_profit, 2),
        "max_drawdown": round(max_drawdown, 2),
        "win_rate": round(win_rate, 4),
    }


@app.get("/api/analytics/backtest")
def api_backtest(user=Depends(get_current_user)):
    """Return latest backtest summary from CSV if available."""
    import csv
    from pathlib import Path
    csv_path = Path(__file__).resolve().parent / "backtest" / "data" / "XAUUSD_trades.csv"
    if not csv_path.exists():
        return {"available": False}

    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return {"available": False}

    closed = [r for r in rows if r.get("status") == "CLOSED"]
    rs = [float(r["r"]) for r in closed if r.get("r")]
    if not rs:
        return {"available": False}

    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    # max drawdown on cumulative R curve
    cum = 0.0; peak = 0.0; max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        "available": True,
        "strategy": "H1 50-EMA + M5 Pullback + Key-Zone TP + Profit Locks",
        "trades": len(closed),
        "win_rate": round(len(wins) / len(closed), 3),
        "total_r": round(sum(rs), 2),
        "expectancy": round(sum(rs) / len(rs), 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "max_drawdown_r": round(max_dd, 2),
    }


@app.delete("/api/analytics/trade-logs")
def api_clear_trade_logs(user=Depends(get_current_user)):
    _clear_all_analytics(user["id"])
    return {"message": "Trade history cleared"}


@app.delete("/api/analytics/performance")
def api_clear_performance(user=Depends(get_current_user)):
    _clear_all_analytics(user["id"])
    return {"message": "Performance metrics cleared"}


def _clear_all_analytics(user_id: int):
    """Clear all trade history, performance, and AI decision logs for a user."""
    with get_db() as conn:
        conn.execute("DELETE FROM trade_logs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM ai_decision_logs WHERE user_id = ?", (user_id,))
        conn.execute(
            """UPDATE performance_metrics SET 
                total_trades=0, winning_trades=0, losing_trades=0,
                total_profit=0, max_drawdown=0, win_rate=0,
                updated_at=CURRENT_TIMESTAMP
               WHERE user_id = ?""",
            (user_id,)
        )
        # Store the clear timestamp so MT5 history sync doesn't re-import old deals
        conn.execute(
            """INSERT OR REPLACE INTO user_settings (user_id, key, value)
               VALUES (?, 'history_cleared_at', ?)""",
            (user_id, datetime.now(timezone.utc).isoformat())
        )


@app.get("/api/analytics/trade-logs")
def api_trade_logs(limit: int = 50, user=Depends(get_current_user)):
    # Sync trades from MT5 before returning — works even when AI is OFF
    if is_connected(user["id"]):
        try:
            _sync_mt5_history(user["id"])
            _check_closed_trades(user["id"])
        except Exception:
            pass

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_logs WHERE user_id = ? AND DATE(opened_at) = DATE('now') ORDER BY opened_at DESC LIMIT ?",
            (user["id"], limit)
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/analytics/ai-decisions")
def api_ai_decisions(limit: int = 50, user=Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_decision_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user["id"], limit)
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/analytics/daily-profits")
def api_daily_profits(user=Depends(get_current_user)):
    """Return aggregated daily profit for each day that had trades."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT DATE(opened_at) as date, SUM(profit) as total_profit, COUNT(*) as trade_count
               FROM trade_logs
               WHERE user_id = ? AND status = 'CLOSED'
               GROUP BY DATE(opened_at)
               ORDER BY date DESC""",
            (user["id"],)
        ).fetchall()
        return [{"date": r["date"], "total_profit": r["total_profit"] or 0.0, "trade_count": r["trade_count"]} for r in rows]


@app.get("/api/analytics/fill-stats")
def api_fill_stats(user=Depends(get_current_user)):
    """Limit-order fill rate for bot-placed orders (excludes manually-synced MT5 trades).
    A bot order's lifecycle: PENDING → OPEN/CLOSED (filled) or CANCELLED (never filled)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT status, COUNT(*) AS c FROM trade_logs
               WHERE user_id = ? AND ai_decision = 'SWEEP_REVERSE'
               GROUP BY status""",
            (user["id"],)
        ).fetchall()
    counts = {r["status"]: r["c"] for r in rows}
    filled = counts.get("OPEN", 0) + counts.get("CLOSED", 0)
    cancelled = counts.get("CANCELLED", 0)
    pending = counts.get("PENDING", 0)
    failed = counts.get("FAILED", 0)
    resolved = filled + cancelled
    fill_rate = (filled / resolved) if resolved > 0 else 0.0
    return {
        "placed": filled + cancelled + pending,
        "filled": filled,
        "cancelled": cancelled,
        "pending": pending,
        "failed": failed,
        "fill_rate": round(fill_rate, 4),
    }


@app.get("/api/analytics/errors")
def api_errors(limit: int = 50, user=Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM error_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user["id"], limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# NEWS FILTER ROUTES
# ============================================================

@app.get("/api/news/status")
def api_news_status(user=Depends(get_current_user)):
    blocked, reason, upcoming = is_news_blackout()
    return {
        "blocked": blocked,
        "reason": reason,
        "upcoming_events": upcoming[:5],
    }


@app.get("/api/news/calendar")
def api_news_calendar(hours: int = 24, user=Depends(get_current_user)):
    return get_upcoming_events(hours=hours)


# ============================================================
# WEBSOCKET
# ============================================================

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int, token: str = Query(None)):
    # Validate token
    if token:
        try:
            import jwt as pyjwt
            from config import SECRET_KEY, ALGORITHM
            payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            token_user_id = payload.get("sub")
            if token_user_id != user_id:
                await websocket.close(code=4003)
                return
        except Exception:
            await websocket.close(code=4001)
            return

    await ws_manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await ws_manager.disconnect(websocket, user_id)


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
