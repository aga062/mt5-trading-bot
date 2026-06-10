import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.auth import get_current_user
from config import BRIDGE_MODE
from database.db import get_db

logger = logging.getLogger("api.bridge")
router = APIRouter()


class HeartbeatPayload(BaseModel):
    pc_version: str = "1.0.0"


class TradeLogPayload(BaseModel):
    symbol: str
    action: str
    lot_size: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    ticket: Optional[int] = None
    status: str = "PENDING"
    profit: Optional[float] = 0
    h1_bias: Optional[str] = None
    ai_decision: Optional[str] = None
    m5_zone: Optional[str] = None


class AccountPayload(BaseModel):
    balance: float
    equity: float
    margin: float
    free_margin: float
    profit: float


class PositionsPayload(BaseModel):
    positions: list[dict]


@router.post("/heartbeat")
async def bridge_heartbeat(payload: HeartbeatPayload, user=Depends(get_current_user)):
    if not BRIDGE_MODE:
        raise HTTPException(status_code=403, detail="Bridge mode not enabled")
    user_id = user["id"]
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, "bridge_pc_connected", "true"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, "bridge_last_heartbeat", datetime.now(timezone.utc).isoformat()),
        )
    return {"status": "ok"}


@router.get("/poll")
async def bridge_poll(user=Depends(get_current_user)):
    if not BRIDGE_MODE:
        raise HTTPException(status_code=403, detail="Bridge mode not enabled")
    user_id = user["id"]
    with get_db() as conn:
        enabled_row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, "bridge_trading_enabled"),
        ).fetchone()
        symbols_row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, "bridge_symbols"),
        ).fetchone()
        lot_row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, "bridge_manual_lot"),
        ).fetchone()

    enabled = enabled_row["value"] == "true" if enabled_row else False
    symbols = json.loads(symbols_row["value"]) if symbols_row else ["XAUUSD"]
    manual_lot = float(lot_row["value"]) if lot_row else None

    return {
        "trading_enabled": enabled,
        "symbols": symbols,
        "manual_lot": manual_lot,
    }


@router.post("/trade-log")
async def bridge_trade_log(payload: TradeLogPayload, user=Depends(get_current_user)):
    if not BRIDGE_MODE:
        raise HTTPException(status_code=403, detail="Bridge mode not enabled")
    user_id = user["id"]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO trade_logs
            (user_id, symbol, action, lot_size, entry_price, stop_loss, take_profit,
             ticket, status, profit, h1_bias, ai_decision, m5_zone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload.symbol,
                payload.action,
                payload.lot_size,
                payload.entry_price,
                payload.stop_loss,
                payload.take_profit,
                payload.ticket,
                payload.status,
                payload.profit,
                payload.h1_bias,
                payload.ai_decision,
                payload.m5_zone,
            ),
        )
    return {"status": "logged"}


@router.post("/account")
async def bridge_account(payload: AccountPayload, user=Depends(get_current_user)):
    if not BRIDGE_MODE:
        raise HTTPException(status_code=403, detail="Bridge mode not enabled")
    user_id = user["id"]
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, "bridge_account", json.dumps(payload.dict())),
        )
    return {"status": "ok"}


@router.post("/positions")
async def bridge_positions(payload: PositionsPayload, user=Depends(get_current_user)):
    if not BRIDGE_MODE:
        raise HTTPException(status_code=403, detail="Bridge mode not enabled")
    user_id = user["id"]
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, "bridge_positions", json.dumps(payload.positions)),
        )
    return {"status": "ok"}


class MarketDataPayload(BaseModel):
    symbol: str
    tick: Optional[dict] = None
    scanner_status: Optional[str] = None
    direction: Optional[str] = None
    h1_bias: Optional[str] = None


@router.post("/market-data")
async def bridge_market_data(payload: MarketDataPayload, user=Depends(get_current_user)):
    if not BRIDGE_MODE:
        raise HTTPException(status_code=403, detail="Bridge mode not enabled")
    user_id = user["id"]
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, f"bridge_tick_{payload.symbol}", json.dumps(payload.tick) if payload.tick else ""),
        )
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, "bridge_scanner_status", payload.scanner_status or ""),
        )
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, "bridge_direction", payload.direction or ""),
        )
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, "bridge_h1_bias", payload.h1_bias or ""),
        )
    return {"status": "ok"}
