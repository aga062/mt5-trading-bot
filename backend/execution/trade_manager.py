import logging
import asyncio
from typing import Optional

from ai.indicators import compute_atr
from mt5.data_streamer import get_candles, get_current_tick, get_open_positions
from risk.risk_manager import should_move_to_breakeven, check_tp_profit_lock, calculate_trailing_stop
from execution.trade_executor import modify_position, close_position, MAGIC_NUMBER
from database.db import get_db

logger = logging.getLogger("execution.trade_manager")


class TradeManager:
    def __init__(self):
        self._running = False

    def manage_positions(self, user_id: int):
        positions = get_open_positions()
        if positions is None:
            logger.warning("get_open_positions returned None. Skipping position management.")
            return
        ai_positions = [p for p in positions if p.get("magic") == MAGIC_NUMBER]

        for pos in ai_positions:
            try:
                self._manage_single_position(user_id, pos)
            except Exception as e:
                logger.error(f"Error managing position {pos['ticket']}: {e}")

    def _manage_single_position(self, user_id: int, position: dict):
        symbol = position["symbol"]
        ticket = position["ticket"]

        tick = get_current_tick(symbol)
        if tick is None:
            return

        current_price = tick["bid"] if position["type"] == "BUY" else tick["ask"]

        # Calculate current ATR
        df = get_candles(symbol, "M5", 100)
        if df is None or len(df) < 20:
            return

        atr_series = compute_atr(df, 14)
        current_atr = atr_series.iloc[-1]

        # Check TP profit lock — move SL to 25% or 50% of TP based on current profit
        lock_result = check_tp_profit_lock(position, current_price)
        if lock_result is not None:
            new_sl, level_label = lock_result
            if modify_position(ticket, sl=new_sl):
                logger.info(f"{level_label} TP lock for {ticket} ({symbol}): SL moved to {new_sl}")
                self._log_trade_event(user_id, ticket, symbol, "TP_PROFIT_LOCK",
                                      f"SL moved to {level_label} TP: {new_sl}")

        # Check trailing stop (only kicks in above the locked SL)
        new_trailing_sl = calculate_trailing_stop(position, current_price, current_atr)
        if new_trailing_sl is not None:
            if modify_position(ticket, sl=new_trailing_sl):
                logger.info(f"Trailing stop updated for {ticket}: SL={new_trailing_sl}")
                self._log_trade_event(user_id, ticket, symbol, "TRAILING_STOP", f"SL trailed to {new_trailing_sl}")

    def _log_trade_event(self, user_id: int, ticket: int, symbol: str, event: str, message: str):
        try:
            with get_db() as conn:
                conn.execute(
                    """INSERT INTO ai_decision_logs (user_id, symbol, ai_decision, created_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                    (user_id, symbol, f"{event}: {message}")
                )
        except Exception as e:
            logger.error(f"Failed to log trade event: {e}")


trade_manager = TradeManager()
