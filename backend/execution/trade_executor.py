import logging
from typing import Optional

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

from mt5.data_streamer import get_current_tick
from risk.risk_manager import TradeParameters

logger = logging.getLogger("execution.trade_executor")

MAGIC_NUMBER = 123456

RETCODE_MESSAGES = {
    10004: "Requote",
    10006: "Request rejected",
    10007: "Request canceled by trader",
    10010: "Request placed — only partial fill",
    10013: "Invalid request",
    10014: "Invalid volume",
    10015: "Invalid price",
    10016: "Invalid stops",
    10017: "Trade disabled",
    10018: "Market closed",
    10019: "Not enough money",
    10020: "Price changed",
    10021: "No quotes available",
    10024: "Too frequent requests",
    10027: "AutoTrading disabled by client — enable in MT5",
}


def execute_trade(symbol: str, action: str, params: TradeParameters) -> Optional[dict]:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return None
    tick = get_current_tick(symbol)
    if tick is None:
        logger.error(f"Cannot get tick for trade execution on {symbol}")
        return None

    if action == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick["ask"]
    elif action == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price = tick["bid"]
    else:
        logger.error(f"Invalid action: {action}")
        return None

    # Auto-detect supported filling mode
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error(f"Cannot get symbol info for {symbol}")
        return None

    # filling_mode bitmask: bit0=FOK(1), bit1=IOC(2), bit2=RETURN(4)
    filling_mode = symbol_info.filling_mode
    if filling_mode & 1:  # FOK supported
        filling_type = mt5.ORDER_FILLING_FOK
    elif filling_mode & 2:  # IOC supported
        filling_type = mt5.ORDER_FILLING_IOC
    else:
        filling_type = mt5.ORDER_FILLING_RETURN

    # Validate SL/TP against broker's minimum stop distance
    stops_level = symbol_info.trade_stops_level  # minimum points from price
    point = symbol_info.point
    min_distance = stops_level * point if stops_level > 0 else 0

    sl = params.stop_loss
    tp = params.take_profit

    if min_distance > 0:
        if action == "BUY":
            if sl > 0 and (price - sl) < min_distance:
                sl = round(price - min_distance, symbol_info.digits)
                logger.warning(f"SL adjusted for min stop distance: {params.stop_loss} -> {sl}")
            if tp > 0 and (tp - price) < min_distance:
                tp = round(price + min_distance, symbol_info.digits)
                logger.warning(f"TP adjusted for min stop distance: {params.take_profit} -> {tp}")
        else:
            if sl > 0 and (sl - price) < min_distance:
                sl = round(price + min_distance, symbol_info.digits)
                logger.warning(f"SL adjusted for min stop distance: {params.stop_loss} -> {sl}")
            if tp > 0 and (price - tp) < min_distance:
                tp = round(price - min_distance, symbol_info.digits)
                logger.warning(f"TP adjusted for min stop distance: {params.take_profit} -> {tp}")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": params.lot_size,
        "type": order_type,
        "price": price,
        "sl": sl,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": f"AI_Trade_{action}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_type,
    }
    # Only include TP if it's a fixed target (> 0); trailing mode omits it
    if tp > 0:
        request["tp"] = tp

    # Check if AutoTrading is enabled before sending
    terminal_info = mt5.terminal_info()
    if terminal_info and not terminal_info.trade_allowed:
        logger.error(f"AutoTrading is DISABLED in MT5 terminal — enable it in MT5 toolbar")
        return {
            "success": False,
            "retcode": 10027,
            "comment": "AutoTrading disabled — enable it in MT5 toolbar",
            "ticket": None,
        }

    result = mt5.order_send(request)

    # If SL/TP were rejected (invalid stops), try opening without them and modify after
    if result is not None and result.retcode == 10016:
        logger.warning(f"Invalid stops for {symbol} - opening without SL/TP, will modify after")
        request["sl"] = 0.0
        request["tp"] = 0.0
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            import time
            time.sleep(0.5)
            modify_request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": result.order,
                "symbol": symbol,
                "sl": sl,
                "tp": tp,
            }
            mod_result = mt5.order_send(modify_request)
            if mod_result is None or mod_result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Failed to set SL/TP for {symbol} ticket={result.order} — closing to avoid unprotected position")
                close_position(result.order)
                return {"success": False, "retcode": -1, "comment": "SL/TP modify failed — position closed", "ticket": None}
            else:
                logger.info(f"SL/TP set after open: SL={sl}, TP={tp}")
    if result is None:
        logger.error(f"Order send returned None for {symbol}: {mt5.last_error()}")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        msg = RETCODE_MESSAGES.get(result.retcode, result.comment)
        logger.error(f"Trade failed for {symbol}: [{result.retcode}] {msg}")
        return {
            "success": False,
            "retcode": int(result.retcode),
            "comment": msg,
            "ticket": None,
        }

    logger.info(f"Trade executed: {action} {params.lot_size} {symbol} @ {result.price}, "
                f"ticket={result.order}, SL={params.stop_loss}, TP={params.take_profit}")

    return {
        "success": True,
        "ticket": result.order,
        "price": result.price,
        "volume": result.volume,
        "symbol": symbol,
        "action": action,
        "sl": params.stop_loss,
        "tp": params.take_profit,
        "retcode": result.retcode,
        "comment": result.comment,
    }


def execute_pending_order(symbol: str, action: str, limit_price: float,
                          params: TradeParameters) -> Optional[dict]:
    """Place a BUY/SELL LIMIT order at limit_price (the Order Block 50%).
    Placed GTC; expiry is enforced by the trading loop (_check_pending_orders),
    which avoids broker-specific 'invalid expiration' rejections (retcode 10022).
    On success the position is not open yet — it's a resting order that fills if
    price returns to the limit."""
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return None
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error(f"Cannot get symbol info for {symbol}")
        return None

    tick = get_current_tick(symbol)
    if tick is None:
        logger.error(f"Cannot get tick for pending order on {symbol}")
        return None

    point = symbol_info.point
    digits = symbol_info.digits
    limit_price = round(limit_price, digits)

    # A BUY LIMIT must sit below the ask; a SELL LIMIT above the bid.
    if action == "BUY":
        order_type = mt5.ORDER_TYPE_BUY_LIMIT
        if limit_price >= tick["ask"]:
            logger.warning(f"BUY limit {limit_price} not below ask {tick['ask']} — not placing")
            return {"success": False, "retcode": -2, "comment": "limit not below market", "ticket": None}
    elif action == "SELL":
        order_type = mt5.ORDER_TYPE_SELL_LIMIT
        if limit_price <= tick["bid"]:
            logger.warning(f"SELL limit {limit_price} not above bid {tick['bid']} — not placing")
            return {"success": False, "retcode": -2, "comment": "limit not above market", "ticket": None}
    else:
        logger.error(f"Invalid action: {action}")
        return None

    # Filling mode (same detection as market orders)
    filling_mode = symbol_info.filling_mode
    if filling_mode & 1:
        filling_type = mt5.ORDER_FILLING_FOK
    elif filling_mode & 2:
        filling_type = mt5.ORDER_FILLING_IOC
    else:
        filling_type = mt5.ORDER_FILLING_RETURN

    # Validate SL/TP against broker's minimum stop distance, relative to the limit price
    stops_level = symbol_info.trade_stops_level
    min_distance = stops_level * point if stops_level > 0 else 0
    sl = params.stop_loss
    tp = params.take_profit

    if min_distance > 0:
        if action == "BUY":
            if sl > 0 and (limit_price - sl) < min_distance:
                sl = round(limit_price - min_distance, digits)
                logger.warning(f"Pending SL adjusted to min stop distance: {params.stop_loss} -> {sl}")
            if tp > 0 and (tp - limit_price) < min_distance:
                tp = round(limit_price + min_distance, digits)
                logger.warning(f"Pending TP adjusted to min stop distance: {params.take_profit} -> {tp}")
        else:
            if sl > 0 and (sl - limit_price) < min_distance:
                sl = round(limit_price + min_distance, digits)
                logger.warning(f"Pending SL adjusted to min stop distance: {params.stop_loss} -> {sl}")
            if tp > 0 and (limit_price - tp) < min_distance:
                tp = round(limit_price - min_distance, digits)
                logger.warning(f"Pending TP adjusted to min stop distance: {params.take_profit} -> {tp}")

    terminal_info = mt5.terminal_info()
    if terminal_info and not terminal_info.trade_allowed:
        logger.error("AutoTrading is DISABLED in MT5 terminal — enable it in MT5 toolbar")
        return {"success": False, "retcode": 10027,
                "comment": "AutoTrading disabled — enable it in MT5 toolbar", "ticket": None}

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": params.lot_size,
        "type": order_type,
        "price": limit_price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": f"AI_Limit_{action}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_type,
    }

    result = mt5.order_send(request)
    if result is None:
        logger.error(f"Pending order send returned None for {symbol}: {mt5.last_error()}")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        msg = RETCODE_MESSAGES.get(result.retcode, result.comment)
        logger.error(f"Pending order failed for {symbol}: [{result.retcode}] {msg}")
        return {"success": False, "retcode": int(result.retcode), "comment": msg, "ticket": None}

    logger.info(f"Limit order placed (GTC): {action} {params.lot_size} {symbol} @ {limit_price}, "
                f"ticket={result.order}, SL={sl}, TP={tp}")

    return {
        "success": True,
        "ticket": result.order,
        "price": limit_price,
        "volume": params.lot_size,
        "symbol": symbol,
        "action": action,
        "sl": sl,
        "tp": tp,
        "retcode": int(result.retcode),
        "comment": result.comment,
        "pending": True,
    }


def modify_position(ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> bool:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return False
    position = mt5.positions_get(ticket=ticket)
    if not position:
        logger.error(f"Position {ticket} not found")
        return False

    pos = position[0]
    new_sl = sl if sl is not None else pos.sl
    new_tp = tp if tp is not None else pos.tp

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": pos.symbol,
        "sl": new_sl,
        "tp": new_tp,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Failed to modify position {ticket}: {result}")
        return False

    logger.info(f"Position {ticket} modified: SL={new_sl}, TP={new_tp}")
    return True


def close_position(ticket: int) -> bool:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return False
    position = mt5.positions_get(ticket=ticket)
    if not position:
        logger.error(f"Position {ticket} not found for closing")
        return False

    pos = position[0]
    tick = get_current_tick(pos.symbol)
    if tick is None:
        return False

    if pos.type == mt5.ORDER_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick["bid"]
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = tick["ask"]

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": "AI_Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Failed to close position {ticket}: {result}")
        return False

    logger.info(f"Position {ticket} closed at {price}")
    return True
