import logging
from datetime import datetime, timezone
from typing import Optional

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

import pandas as pd

logger = logging.getLogger("mt5.data_streamer")

if mt5 is not None:
    TIMEFRAME_MAP = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
else:
    TIMEFRAME_MAP = {
        "M1": 1, "M5": 5, "M15": 15, "M30": 30,
        "H1": 60, "H4": 240, "D1": 1440,
    }


def get_candles(symbol: str, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return None
    tf = TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        logger.error(f"Invalid timeframe: {timeframe}")
        return None

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        logger.error(f"Failed to get candles for {symbol} {timeframe}: {mt5.last_error()}")
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={
        "time": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "tick_volume": "volume",
        "spread": "spread",
        "real_volume": "real_volume",
    }, inplace=True)
    return df


def get_current_tick(symbol: str) -> Optional[dict]:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return None
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"Failed to get tick for {symbol}: {mt5.last_error()}")
        return None
    return {
        "symbol": symbol,
        "bid": float(tick.bid),
        "ask": float(tick.ask),
        "last": float(tick.last),
        "volume": int(tick.volume),
        "time": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
        "spread": round(float(tick.ask - tick.bid), 6),
    }


def get_symbol_info(symbol: str) -> Optional[dict]:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return None
    info = mt5.symbol_info(symbol)
    if info is None:
        logger.error(f"Failed to get symbol info for {symbol}: {mt5.last_error()}")
        return None
    return {
        "symbol": info.name,
        "digits": int(info.digits),
        "point": float(info.point),
        "spread": int(info.spread),
        "trade_contract_size": float(info.trade_contract_size),
        "volume_min": float(info.volume_min),
        "volume_max": float(info.volume_max),
        "volume_step": float(info.volume_step),
        "trade_tick_value": float(info.trade_tick_value),
        "trade_tick_size": float(info.trade_tick_size),
    }


def get_open_positions(symbol: Optional[str] = None) -> Optional[list[dict]]:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return None
    if symbol:
        positions = mt5.positions_get(symbol=symbol)
    else:
        positions = mt5.positions_get()

    if positions is None:
        return None

    result = []
    for pos in positions:
        result.append({
            "ticket": int(pos.ticket),
            "symbol": pos.symbol,
            "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume": float(pos.volume),
            "price_open": float(pos.price_open),
            "price_current": float(pos.price_current),
            "sl": float(pos.sl),
            "tp": float(pos.tp),
            "profit": float(pos.profit),
            "swap": float(pos.swap),
            "time": datetime.fromtimestamp(pos.time, tz=timezone.utc).isoformat(),
            "magic": int(pos.magic),
            "comment": pos.comment,
        })
    return result


def get_trade_history(days: int = 30) -> list[dict]:
    if mt5 is None:
        logger.warning("MetaTrader 5 not available on this server.")
        return []
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    deals = mt5.history_deals_get(start, now)
    if deals is None:
        return []

    result = []
    for deal in deals:
        result.append({
            "ticket": int(deal.ticket),
            "order": int(deal.order),
            "symbol": deal.symbol,
            "type": int(deal.type),
            "volume": float(deal.volume),
            "price": float(deal.price),
            "profit": float(deal.profit),
            "swap": float(deal.swap),
            "commission": float(deal.commission),
            "time": datetime.fromtimestamp(deal.time, tz=timezone.utc).isoformat(),
            "comment": deal.comment,
        })
    return result
