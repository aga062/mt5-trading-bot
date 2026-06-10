import logging
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

from ai.indicators import compute_atr
from mt5.data_streamer import get_candles, get_symbol_info, get_open_positions
from database.db import get_db
from config import (
    RISK_PER_TRADE_PERCENT,
    ATR_SL_MULTIPLIER,
    ATR_TP_MULTIPLIER,
    MAX_OPEN_TRADES,
    DAILY_LOSS_LIMIT,
    SESSION_FILTER_ENABLED,
)

# Adaptive lot sizing settings
LOT_INCREASE_PER_WIN_STREAK = 0.01   # +0.01 per streak of 3 wins
WIN_STREAK_THRESHOLD = 3
LOT_DECREASE_PER_LOSS_STREAK = 0.01  # -0.01 per streak of 2 losses
LOSS_STREAK_THRESHOLD = 2

logger = logging.getLogger("risk.risk_manager")


class TradeParameters:
    def __init__(self, lot_size: float, stop_loss: float, take_profit: float,
                 atr: float, risk_amount: float):
        self.lot_size = lot_size
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.atr = atr
        self.risk_amount = risk_amount

    def to_dict(self) -> dict:
        return {
            "lot_size": self.lot_size,
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "atr": round(self.atr, 6),
            "risk_amount": round(self.risk_amount, 2),
        }


def calculate_trade_params(
    symbol: str,
    action: str,
    entry_price: float,
    manual_lot: float | None = None,
    sl_price: float | None = None,
    tp_price: float | None = None,
) -> Optional[TradeParameters]:
    """If sl_price/tp_price are provided (structural levels from the ICT setup),
    they are used directly and position sizing is derived from the structural SL
    distance. Otherwise SL/TP fall back to ATR multiples from entry_price."""
    # Get ATR from M5 candles
    df = get_candles(symbol, "M5", 100)
    if df is None or len(df) < 20:
        logger.error(f"Insufficient data for risk calculation on {symbol}")
        return None

    atr_series = compute_atr(df, 14)
    current_atr = atr_series.iloc[-1]

    if current_atr <= 0:
        logger.error(f"ATR is zero or negative for {symbol}")
        return None

    # Get symbol info
    sym_info = get_symbol_info(symbol)
    if sym_info is None:
        logger.error(f"Cannot get symbol info for {symbol}")
        return None

    # Get account info
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return None
    account = mt5.account_info()
    if account is None:
        logger.error("Cannot get account info for position sizing")
        return None

    balance = account.balance
    point = sym_info["point"]
    digits = sym_info["digits"]
    tick_value = sym_info["trade_tick_value"]
    tick_size = sym_info["trade_tick_size"]
    contract_size = sym_info["trade_contract_size"]
    vol_min = sym_info["volume_min"]
    vol_max = sym_info["volume_max"]
    vol_step = sym_info["volume_step"]

    if action not in ("BUY", "SELL"):
        return None

    # Calculate SL and TP — structural (from setup) takes priority over ATR
    # tp_price == 0 means trailing stop mode (no fixed TP)
    if sl_price is not None and tp_price is not None and tp_price > 0:
        # Fixed structural TP
        stop_loss = round(sl_price, digits)
        take_profit = round(tp_price, digits)
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            logger.error(f"Invalid structural SL distance for {symbol}: entry={entry_price}, sl={stop_loss}")
            return None
    elif sl_price is not None and tp_price == 0:
        # Trailing stop mode: structural SL, no fixed TP
        stop_loss = round(sl_price, digits)
        take_profit = 0.0
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            logger.error(f"Invalid structural SL distance for {symbol}: entry={entry_price}, sl={stop_loss}")
            return None
    else:
        # ATR-based fallback
        sl_distance = current_atr * ATR_SL_MULTIPLIER
        tp_distance = current_atr * ATR_TP_MULTIPLIER
        if action == "BUY":
            stop_loss = round(entry_price - sl_distance, digits)
            take_profit = round(entry_price + tp_distance, digits)
        else:
            stop_loss = round(entry_price + sl_distance, digits)
            take_profit = round(entry_price - tp_distance, digits)

    # Position sizing
    if manual_lot is not None and manual_lot > 0:
        # Manual lot override — skip risk calc and adaptive sizing
        lot_size = max(vol_min, min(vol_max, round(manual_lot / vol_step) * vol_step))
        lot_size = round(lot_size, 2)
        risk_amount = 0.0  # manual mode, risk not calculated
        logger.info(f"Manual lot for {symbol} {action}: lot={lot_size}")
    else:
        # Risk-based position sizing
        risk_amount = balance * (RISK_PER_TRADE_PERCENT / 100.0)

        # Calculate lot size based on risk
        sl_points = sl_distance / tick_size
        if sl_points <= 0 or tick_value <= 0:
            logger.error(f"Invalid SL points or tick value: sl_points={sl_points}, tick_value={tick_value}")
            return None

        lot_size = risk_amount / (sl_points * tick_value)

        # Round to volume step
        lot_size = max(vol_min, min(vol_max, round(lot_size / vol_step) * vol_step))
        lot_size = round(lot_size, 2)

        # Adaptive lot adjustment based on win/loss streaks
        base_lot = lot_size
        lot_adjustment = _get_streak_lot_adjustment(symbol)
        lot_size = lot_size + lot_adjustment
        lot_size = max(vol_min, min(vol_max, round(lot_size / vol_step) * vol_step))
        lot_size = round(lot_size, 2)

        if lot_adjustment != 0:
            logger.info(f"Adaptive sizing for {symbol}: base={base_lot}, adj={lot_adjustment:+.2f}, final={lot_size}")

    logger.info(f"Risk params for {symbol} {action}: lot={lot_size}, SL={stop_loss}, "
                f"TP={take_profit}, ATR={current_atr:.5f}, risk=${risk_amount:.2f}")

    return TradeParameters(
        lot_size=lot_size,
        stop_loss=stop_loss,
        take_profit=take_profit,
        atr=current_atr,
        risk_amount=risk_amount
    )


def _get_streak_lot_adjustment(symbol: str) -> float:
    """Calculate lot adjustment based on recent consecutive wins/losses for a symbol.
    +0.01 for every 3 consecutive wins, -0.01 for every 2 consecutive losses."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT profit FROM trade_logs
                   WHERE symbol = ? AND status = 'CLOSED'
                   ORDER BY closed_at DESC
                   LIMIT 20""",
                (symbol,)
            ).fetchall()

        if not rows:
            return 0.0

        # Count current streak from most recent trade
        streak_type = None  # "win" or "loss"
        streak_count = 0

        for row in rows:
            profit = row["profit"]
            is_win = profit >= 0

            if streak_type is None:
                streak_type = "win" if is_win else "loss"
                streak_count = 1
            elif (streak_type == "win" and is_win) or (streak_type == "loss" and not is_win):
                streak_count += 1
            else:
                break  # streak broken

        if streak_type == "win" and streak_count >= WIN_STREAK_THRESHOLD:
            multiplier = streak_count // WIN_STREAK_THRESHOLD
            adjustment = multiplier * LOT_INCREASE_PER_WIN_STREAK
            logger.info(f"Win streak {streak_count} on {symbol}: lot +{adjustment:.2f}")
            return adjustment

        elif streak_type == "loss" and streak_count >= LOSS_STREAK_THRESHOLD:
            multiplier = streak_count // LOSS_STREAK_THRESHOLD
            adjustment = -(multiplier * LOT_DECREASE_PER_LOSS_STREAK)
            logger.info(f"Loss streak {streak_count} on {symbol}: lot {adjustment:.2f}")
            return adjustment

        return 0.0

    except Exception as e:
        logger.error(f"Error calculating streak adjustment: {e}")
        return 0.0


TRADE_COOLDOWN_SECONDS = 0  # cooldown disabled
_last_trade_time: dict[str, float] = {}

# Trading session windows (only trade during high-liquidity sessions)
LONDON_TZ = ZoneInfo("Europe/London")
NEW_YORK_TZ = ZoneInfo("America/New_York")
LONDON_OPEN_START = (4, 30)    # 04:30 AM London
LONDON_OPEN_END = (11, 30)     # 11:30 AM London
NY_OVERLAP_START = (9, 0)      # 09:00 AM New York
NY_OVERLAP_END = (17, 30)      # 05:30 PM New York


def record_trade_time(symbol: str):
    """Call after a trade is executed to start the cooldown."""
    import time
    _last_trade_time[symbol] = time.time()


def _is_within_trading_session() -> tuple[bool, str]:
    """Check if current time is within allowed trading sessions.

    Allowed sessions:
      - London Session: 04:30-11:30 London time
      - New York Session: 09:30-13:30 New York time
    Returns (True, "") if within session, (False, reason) if outside.
    """
    now_utc = datetime.now(ZoneInfo("UTC"))
    london_now = now_utc.astimezone(LONDON_TZ)
    ny_now = now_utc.astimezone(NEW_YORK_TZ)

    london_time = (london_now.hour, london_now.minute)
    ny_time = (ny_now.hour, ny_now.minute)

    in_london = LONDON_OPEN_START <= london_time < LONDON_OPEN_END
    in_ny = NY_OVERLAP_START <= ny_time < NY_OVERLAP_END

    if in_london or in_ny:
        return True, ""

    return False, (f"Outside trading sessions. London: {london_now.strftime('%H:%M')} "
                   f"(need 04:30-11:30), NY: {ny_now.strftime('%H:%M')} (need 09:30-13:30)")


def count_todays_losses(user_id: int) -> int:
    """Number of trades that closed at a loss today (UTC)."""
    try:
        with get_db() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS c FROM trade_logs
                   WHERE user_id = ? AND status = 'CLOSED' AND profit < 0
                     AND DATE(closed_at) = DATE('now')""",
                (user_id,)
            ).fetchone()
            return row["c"] if row else 0
    except Exception as e:
        logger.error(f"Error counting today's losses: {e}")
        return 0


def can_open_trade(symbol: str, user_id: int) -> tuple[bool, str]:
    import time

    # Daily loss limit — hard stop on new entries for the rest of the day
    losses_today = count_todays_losses(user_id)
    if losses_today >= DAILY_LOSS_LIMIT:
        return False, f"Daily loss limit reached ({losses_today}/{DAILY_LOSS_LIMIT}) — halted for today"

    # Session time check — block all trades outside allowed windows (if enabled)
    if SESSION_FILTER_ENABLED:
        in_session, session_reason = _is_within_trading_session()
        if not in_session:
            return False, session_reason

    # Cooldown check
    last_time = _last_trade_time.get(symbol, 0)
    elapsed = time.time() - last_time
    if elapsed < TRADE_COOLDOWN_SECONDS:
        remaining = int(TRADE_COOLDOWN_SECONDS - elapsed)
        return False, f"Cooldown: {remaining}s remaining"

    positions = get_open_positions() or []

    # Pending limit orders count toward exposure and block stacking
    if mt5 is None:
        all_pending = []
        pending_count = 0
    else:
        all_pending = mt5.orders_get()
        pending_count = len(all_pending) if all_pending else 0

    if len(positions) + pending_count >= MAX_OPEN_TRADES:
        return False, f"Max open trades/orders reached ({MAX_OPEN_TRADES})"

    # Check for duplicate position on same symbol
    symbol_positions = [p for p in positions if p["symbol"] == symbol]
    if symbol_positions:
        return False, f"Already have an open position on {symbol}"

    # Check for existing pending limit order on same symbol
    if mt5 is not None:
        symbol_pending = mt5.orders_get(symbol=symbol)
        if symbol_pending:
            return False, f"Already have a pending order on {symbol}"

    return True, "OK"


def should_move_to_breakeven(position: dict, current_price: float, atr: float) -> bool:
    """Legacy breakeven check — kept for compatibility but replaced by should_move_sl_to_half_tp."""
    entry = position["price_open"]
    is_buy = position["type"] == "BUY"

    if is_buy:
        profit_distance = current_price - entry
    else:
        profit_distance = entry - current_price

    return profit_distance >= atr


def should_move_sl_to_half_tp(position: dict, current_price: float) -> Optional[float]:
    """Kept for backward compatibility — delegates to the multi-level version."""
    result = check_tp_profit_lock(position, current_price)
    return result[0] if result else None


# Profit-lock levels: (threshold %, SL move %)
# When price profit reaches threshold% of TP, move SL to move% of TP from entry
TP_LOCK_LEVELS = [
    (0.75, 0.75),  # at 75% of TP profit → SL locks 75% of profit
    (0.50, 0.50),  # at 50% of TP profit → SL locks 50% of profit
    (0.25, 0.25),  # at 25% of TP profit → SL locks 25% of profit
    (0.15, 0.25),  # at 15% of TP profit → SL to breakeven + 25% buffer
]


def check_tp_profit_lock(position: dict, current_price: float) -> Optional[tuple[float, str]]:
    """Multi-level SL lock based on TP progress.
    Checks from highest level down — returns the best applicable SL move.
    Returns (new_sl, level_label) or None."""
    entry = position["price_open"]
    tp = position["tp"]
    current_sl = position["sl"]
    is_buy = position["type"] == "BUY"

    if tp is None or tp == 0:
        return None

    tp_distance = abs(tp - entry)
    if tp_distance <= 0:
        return None

    if is_buy:
        profit_distance = current_price - entry
    else:
        profit_distance = entry - current_price

    # Check levels from highest to lowest — first match wins
    for threshold_pct, sl_pct in sorted(TP_LOCK_LEVELS, key=lambda x: -x[0]):
        threshold_distance = tp_distance * threshold_pct
        sl_move_distance = tp_distance * sl_pct

        if profit_distance >= threshold_distance:
            if is_buy:
                new_sl = round(entry + sl_move_distance, 5)
                if current_sl < new_sl:
                    label = f"{int(sl_pct * 100)}%"
                    return (new_sl, label)
            else:
                new_sl = round(entry - sl_move_distance, 5)
                if current_sl > new_sl:
                    label = f"{int(sl_pct * 100)}%"
                    return (new_sl, label)

    return None


def calculate_trailing_stop(position: dict, current_price: float, atr: float) -> Optional[float]:
    entry = position["price_open"]
    current_sl = position["sl"]
    is_buy = position["type"] == "BUY"

    trailing_distance = atr * 1.0

    if is_buy:
        new_sl = current_price - trailing_distance
        if new_sl > current_sl and new_sl > entry:
            return round(new_sl, 5)
    else:
        new_sl = current_price + trailing_distance
        if new_sl < current_sl and new_sl < entry:
            return round(new_sl, 5)

    return None
