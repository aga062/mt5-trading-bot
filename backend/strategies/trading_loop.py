import asyncio
import logging
from datetime import datetime, timezone

from strategies.entry_confirmation import evaluate_entry, TradeSignal
from risk.risk_manager import calculate_trade_params, can_open_trade, record_trade_time
from execution.trade_executor import execute_trade
from execution.trade_manager import trade_manager
from mt5.connector import is_connected, reconnect_mt5, get_account_info
from mt5.data_streamer import get_current_tick, get_open_positions
from websocket.ws_manager import ws_manager
from database.db import get_db
from config import DEFAULT_SYMBOL, TRADING_LOOP_INTERVAL_SECONDS, PENDING_ORDER_EXPIRY_MINUTES

logger = logging.getLogger("strategies.trading_loop")

_trading_active: dict[int, bool] = {}
_trading_symbols: dict[int, list[str]] = {}
_trading_manual_lot: dict[int, float | None] = {}
_last_decision: dict[tuple[int, str], str] = {}  # (user_id, symbol) -> last logged decision


def start_trading(user_id: int, symbols: list[str] = None, manual_lot: float | None = None):
    _trading_active[user_id] = True
    _trading_symbols[user_id] = symbols or [DEFAULT_SYMBOL]
    _trading_manual_lot[user_id] = manual_lot
    logger.info(f"Trading started for user {user_id} on {_trading_symbols[user_id]} (manual_lot={manual_lot})")


def stop_trading(user_id: int):
    _trading_active[user_id] = False
    logger.info(f"Trading stopped for user {user_id}")


def is_trading_active(user_id: int) -> bool:
    return _trading_active.get(user_id, False)


async def trading_loop(user_id: int):
    logger.info(f"Trading loop started for user {user_id}")

    while _trading_active.get(user_id, False):
        try:
            # Check MT5 connection
            if not is_connected(user_id):
                logger.warning(f"MT5 disconnected for user {user_id}, attempting reconnect...")
                status = reconnect_mt5(user_id)
                if not status.connected:
                    await ws_manager.send_to_user(user_id, {
                        "type": "error",
                        "message": f"MT5 reconnection failed: {status.error}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    await asyncio.sleep(10)
                    continue

            symbols = _trading_symbols.get(user_id, [DEFAULT_SYMBOL])

            for symbol in symbols:
                if not _trading_active.get(user_id, False):
                    break

                await process_symbol(user_id, symbol)

            # Manage existing positions
            trade_manager.manage_positions(user_id)

            # Reconcile pending limit orders (filled → OPEN, expired → CANCELLED)
            _check_pending_orders(user_id)

            # Check for closed trades and update performance
            _check_closed_trades(user_id)

            # Send account update
            account = get_account_info()
            if account:
                positions = get_open_positions()
                await ws_manager.send_to_user(user_id, {
                    "type": "account_update",
                    "data": account,
                    "positions": positions,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        except Exception as e:
            logger.error(f"Trading loop error for user {user_id}: {e}", exc_info=True)
            log_error(user_id, "trading_loop", str(e))
            await ws_manager.send_to_user(user_id, {
                "type": "error",
                "message": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        await asyncio.sleep(TRADING_LOOP_INTERVAL_SECONDS)

    logger.info(f"Trading loop stopped for user {user_id}")


def _log_decision(user_id: int, symbol: str, signal: TradeSignal):
    """Log the funnel outcome for a symbol, but only when it changes — so the
    decision stream is readable instead of repeating every 3s."""
    summary = f"{signal.action} [daily={signal.daily_bias}] — {signal.reason}"
    key = (user_id, symbol)
    if _last_decision.get(key) != summary:
        _last_decision[key] = summary
        logger.info(f"[{symbol}] {summary}")


async def process_symbol(user_id: int, symbol: str):
    # Evaluate entry
    signal: TradeSignal = evaluate_entry(symbol)

    # Log the decision (only when it changes)
    _log_decision(user_id, symbol, signal)

    # Send signal to frontend
    await ws_manager.send_to_user(user_id, {
        "type": "signal_update",
        "data": signal.to_dict(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Log AI decision
    log_ai_decision(user_id, signal)

    if signal.action == "WAIT":
        return

    # Check if we can open a trade
    can_trade, reason = can_open_trade(symbol, user_id)
    if not can_trade:
        logger.info(f"Cannot open trade on {symbol}: {reason}")
        await ws_manager.send_to_user(user_id, {
            "type": "trade_blocked",
            "symbol": symbol,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return

    # Calculate risk parameters using the setup's structural SL/TP
    manual_lot = _trading_manual_lot.get(user_id)
    setup = signal.ict_setup
    params = calculate_trade_params(
        symbol, signal.action, signal.entry_price, manual_lot=manual_lot,
        sl_price=setup.sl_price if setup else None,
        tp_price=setup.tp_price if setup else None,
    )
    if params is None:
        logger.error(f"Risk calculation failed for {symbol}")
        return

    # Place a MARKET order — fast entry per spec, with structural SL + nearest-level TP
    result = execute_trade(symbol, signal.action, params)
    if result is None:
        logger.error(f"Trade execution returned None for {symbol}")
        return

    # If AutoTrading is disabled, don't log as FAILED — just warn and skip
    if not result["success"] and result.get("retcode") == 10027:
        logger.warning(f"AutoTrading disabled — skipping order for {symbol}. Enable AutoTrading in MT5!")
        return

    # Record trade time for cooldown (prevents re-placing while one is pending)
    if result["success"]:
        record_trade_time(symbol)

    # Log the pending order
    log_trade(user_id, symbol, signal, params, result)

    # Send result to frontend
    await ws_manager.send_to_user(user_id, {
        "type": "trade_executed" if result["success"] else "trade_failed",
        "data": result,
        "params": params.to_dict(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def log_ai_decision(user_id: int, signal: TradeSignal):
    try:
        ict_valid = 1 if (signal.ict_result and signal.ict_result.valid) else 0
        with get_db() as conn:
            conn.execute(
                """INSERT INTO ai_decision_logs 
                   (user_id, symbol, h1_bias, ai_decision, m5_zone_valid, 
                    rsi, macd_line, macd_signal, atr, ema8, ema21, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, signal.symbol, signal.h1_bias,
                    signal.ai_decision_str, ict_valid,
                    0, 0, 0, 0, 0, 0, 1.0 if ict_valid else 0
                )
            )
    except Exception as e:
        logger.error(f"Failed to log AI decision: {e}")


def log_trade(user_id: int, symbol: str, signal: TradeSignal,
              params, result: dict):
    # Market orders fill immediately -> logged OPEN; counted as a trade now.
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO trade_logs
                   (user_id, symbol, action, lot_size, entry_price, stop_loss,
                    take_profit, ticket, status, h1_bias, ai_decision, m5_zone)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, symbol, signal.action, params.lot_size,
                    result.get("price") or signal.entry_price,
                    params.stop_loss, params.take_profit,
                    result.get("ticket"), "OPEN" if result["success"] else "FAILED",
                    signal.h1_bias, signal.ai_decision_str, signal.m5_zone_str
                )
            )
            if result["success"]:
                conn.execute(
                    """UPDATE performance_metrics SET total_trades = total_trades + 1,
                       updated_at = CURRENT_TIMESTAMP WHERE user_id = ?""",
                    (user_id,)
                )
    except Exception as e:
        logger.error(f"Failed to log trade: {e}")


def _check_pending_orders(user_id: int):
    """Reconcile PENDING limit orders against MT5: mark filled ones OPEN, expired ones CANCELLED.

    We enforce at most one position/pending per symbol, so a PENDING whose order is
    gone can be matched to a new position on the same symbol (covers both hedging,
    where position ticket == order ticket, and netting, where it differs)."""
    try:
        import MetaTrader5 as mt5_mod
        with get_db() as conn:
            pend = conn.execute(
                """SELECT id, ticket, symbol,
                          CAST((julianday('now') - julianday(opened_at)) * 86400 AS INTEGER) AS age_sec
                   FROM trade_logs WHERE user_id = ? AND status = 'PENDING'""",
                (user_id,)
            ).fetchall()
            if not pend:
                return

            orders = mt5_mod.orders_get()
            order_tickets = {o.ticket for o in orders} if orders else set()

            positions = get_open_positions()
            if positions is None:
                logger.warning("get_open_positions returned None. Skipping pending check.")
                return
            pos_by_ticket = {p["ticket"]: p for p in positions}
            pos_by_symbol = {}
            for p in positions:
                pos_by_symbol.setdefault(p["symbol"], []).append(p)

            for row in pend:
                ticket = row["ticket"]
                symbol = row["symbol"]

                if ticket in order_tickets:
                    # still resting — cancel if older than the expiry window
                    age = row["age_sec"]
                    if age is not None and age > PENDING_ORDER_EXPIRY_MINUTES * 60:
                        mt5_mod.order_send({"action": mt5_mod.TRADE_ACTION_REMOVE, "order": ticket})
                        conn.execute("UPDATE trade_logs SET status = 'CANCELLED' WHERE id = ?", (row["id"],))
                        logger.info(f"Pending {ticket} expired after {age}s → CANCELLED ({symbol})")
                    continue

                # Order no longer pending → it filled or expired
                filled = pos_by_ticket.get(ticket)
                if filled is None and symbol in pos_by_symbol:
                    filled = pos_by_symbol[symbol][0]

                if filled is not None:
                    conn.execute(
                        """UPDATE trade_logs SET status = 'OPEN', ticket = ?, entry_price = ?,
                           opened_at = CURRENT_TIMESTAMP WHERE id = ?""",
                        (filled["ticket"], filled["price_open"], row["id"])
                    )
                    conn.execute(
                        """UPDATE performance_metrics SET total_trades = total_trades + 1,
                           updated_at = CURRENT_TIMESTAMP WHERE user_id = ?""",
                        (user_id,)
                    )
                    logger.info(f"Limit {ticket} FILLED → OPEN ({symbol}) position={filled['ticket']}")
                else:
                    conn.execute(
                        "UPDATE trade_logs SET status = 'CANCELLED' WHERE id = ?",
                        (row["id"],)
                    )
                    logger.info(f"Limit {ticket} expired/cancelled ({symbol})")
    except Exception as e:
        logger.error(f"Error checking pending orders: {e}", exc_info=True)


def _check_closed_trades(user_id: int):
    """Detect trades in DB with status OPEN that no longer exist as MT5 positions, update them."""
    try:
        with get_db() as conn:
            open_logs = conn.execute(
                "SELECT id, ticket, symbol, action, entry_price FROM trade_logs WHERE user_id = ? AND status = 'OPEN'",
                (user_id,)
            ).fetchall()

            if not open_logs:
                return

            # Get current open position tickets
            positions = get_open_positions()
            if positions is None:
                logger.warning("get_open_positions returned None (MT5 error/disconnected). Skipping closed trades check.")
                return
            open_tickets = {p["ticket"] for p in positions}

            for log in open_logs:
                ticket = log["ticket"]
                if ticket and ticket not in open_tickets:
                    # Trade has been closed (by SL, TP, or manually)
                    # Try to find the deal in history to get actual profit
                    import MetaTrader5 as mt5_mod
                    from datetime import timedelta
                    now = datetime.now(timezone.utc)
                    trade_profit = None  # None = not found yet

                    # Method 1: Try position-based lookup
                    deals = mt5_mod.history_deals_get(position=ticket)
                    if deals:
                        for deal in deals:
                            if deal.entry == 1:  # exit deal
                                trade_profit = float(deal.profit) + float(deal.swap) + float(deal.commission)
                                break

                    # Method 2: Fallback to time-based search with wider window
                    if trade_profit is None:
                        deals = mt5_mod.history_deals_get(now - timedelta(days=7), now)
                        if deals:
                            for deal in deals:
                                if deal.position_id == ticket and deal.entry == 1:
                                    trade_profit = float(deal.profit) + float(deal.swap) + float(deal.commission)
                                    break

                    # If we couldn't find the exit deal, skip — FundedNext may have a sync delay.
                    # The trade will be retried on the next cycle until the deal appears.
                    if trade_profit is None:
                        logger.warning(f"Trade {ticket} no longer open but exit deal not found in history yet. Will retry.")
                        continue

                    # Update trade log
                    status = "CLOSED"
                    conn.execute(
                        """UPDATE trade_logs SET status = ?, profit = ?, closed_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (status, trade_profit, log["id"])
                    )

                    # Update performance metrics
                    is_win = trade_profit >= 0
                    metrics = conn.execute(
                        "SELECT winning_trades, losing_trades, max_drawdown FROM performance_metrics WHERE user_id = ?",
                        (user_id,)
                    ).fetchone()
                    if metrics:
                        new_wins = metrics["winning_trades"] + (1 if is_win else 0)
                        new_losses = metrics["losing_trades"] + (0 if is_win else 1)
                        total = new_wins + new_losses
                        new_win_rate = new_wins / total if total > 0 else 0.0
                        new_drawdown = max(metrics["max_drawdown"], abs(trade_profit) if not is_win else 0)
                        conn.execute(
                            """UPDATE performance_metrics SET
                                winning_trades = ?,
                                losing_trades = ?,
                                total_profit = total_profit + ?,
                                win_rate = ?,
                                max_drawdown = ?,
                                updated_at = CURRENT_TIMESTAMP
                               WHERE user_id = ?""",
                            (new_wins, new_losses, trade_profit, new_win_rate, new_drawdown, user_id)
                        )

                    logger.info(f"Trade {ticket} closed for user {user_id}: profit={trade_profit:.2f}, {'WIN' if is_win else 'LOSS'}")

    except Exception as e:
        logger.error(f"Error checking closed trades: {e}", exc_info=True)


def _sync_mt5_history(user_id: int):
    """Import closed deals from MT5 history that are not yet in trade_logs.
    This ensures the Trade History dashboard shows all trades even after clearing
    or when trades were opened/closed while the AI was off."""
    try:
        import MetaTrader5 as mt5_mod
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        deals = mt5_mod.history_deals_get(now - timedelta(days=7), now)
        if not deals:
            return

        with get_db() as conn:
            # Check if user has a "history_cleared_at" setting — skip deals before that time
            cleared_row = conn.execute(
                "SELECT value FROM user_settings WHERE user_id = ? AND key = 'history_cleared_at'",
                (user_id,)
            ).fetchone()
            cleared_at = None
            if cleared_row and cleared_row["value"]:
                try:
                    cleared_at = datetime.fromisoformat(cleared_row["value"])
                except ValueError:
                    cleared_at = None

            # Get all ticket IDs already in trade_logs for this user
            existing = conn.execute(
                "SELECT ticket FROM trade_logs WHERE user_id = ? AND ticket IS NOT NULL",
                (user_id,)
            ).fetchall()
            existing_tickets = {row["ticket"] for row in existing}

            # Group deals by position_id to pair entry + exit
            positions = {}
            for deal in deals:
                if deal.symbol == "" or deal.volume == 0:
                    continue  # skip balance/commission-only deals
                pid = deal.position_id
                if pid not in positions:
                    positions[pid] = {"entry": None, "exit": None}
                if deal.entry == 0:  # entry deal
                    positions[pid]["entry"] = deal
                elif deal.entry == 1:  # exit deal
                    positions[pid]["exit"] = deal

            for pid, pair in positions.items():
                entry_deal = pair["entry"]
                exit_deal = pair["exit"]

                if entry_deal is None:
                    continue

                # Skip if already tracked (check both position_id and entry price+time combo)
                if pid in existing_tickets:
                    continue
                # Also skip if a trade with same entry_price and symbol exists within 60s
                dup = conn.execute(
                    """SELECT id FROM trade_logs WHERE user_id = ? AND symbol = ? 
                       AND entry_price = ? AND ABS(strftime('%s', opened_at) - ?) < 60""",
                    (user_id, entry_deal.symbol, float(entry_deal.price), entry_deal.time)
                ).fetchone()
                if dup:
                    continue

                # Skip deals that were opened before the last clear
                deal_time = datetime.fromtimestamp(entry_deal.time, tz=timezone.utc)
                if cleared_at and deal_time < cleared_at:
                    continue

                # Determine action
                action = "BUY" if entry_deal.type == 0 else "SELL"
                symbol = entry_deal.symbol
                lot_size = float(entry_deal.volume)
                entry_price = float(entry_deal.price)
                opened_at = deal_time.isoformat()

                if exit_deal:
                    profit = float(exit_deal.profit) + float(exit_deal.swap) + float(exit_deal.commission)
                    status = "CLOSED"
                    closed_at = datetime.fromtimestamp(exit_deal.time, tz=timezone.utc).isoformat()
                else:
                    profit = 0.0
                    status = "OPEN"
                    closed_at = None

                conn.execute(
                    """INSERT INTO trade_logs
                       (user_id, symbol, action, lot_size, entry_price, stop_loss, take_profit,
                        ticket, status, profit, h1_bias, ai_decision, m5_zone, opened_at, closed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, symbol, action, lot_size, entry_price,
                     0, 0, pid, status, profit,
                     "N/A", "MT5", "N/A", opened_at, closed_at)
                )

                logger.info(f"Synced MT5 deal {pid} ({symbol} {action}) for user {user_id}: "
                            f"status={status}, profit={profit:.2f}")

    except Exception as e:
        logger.error(f"Error syncing MT5 history: {e}", exc_info=True)


def log_error(user_id: int, module: str, message: str):
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO error_logs (user_id, module, error_type, message) VALUES (?, ?, ?, ?)",
                (user_id, module, "RUNTIME_ERROR", message)
            )
    except Exception:
        pass
