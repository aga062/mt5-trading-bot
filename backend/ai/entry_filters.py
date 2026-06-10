import logging
from datetime import datetime, timezone

from mt5.data_streamer import get_current_tick, get_symbol_info
from news.news_filter import is_news_blackout
from config import (
    LONDON_SESSION_START, LONDON_SESSION_END,
    NY_SESSION_START, NY_SESSION_END,
    MAX_SPREAD_POINTS,
)

logger = logging.getLogger("ai.entry_filters")


def check_news_filter() -> tuple[bool, str]:
    """Returns (is_clear, reason). is_clear=False means trading is blocked."""
    blocked, reason, _ = is_news_blackout()
    if blocked:
        return False, reason
    return True, "No high-impact news"


def check_session_filter() -> tuple[bool, str]:
    """Returns (is_valid_session, reason)."""
    from zoneinfo import ZoneInfo

    now_utc = datetime.now(timezone.utc)
    london_now = now_utc.astimezone(ZoneInfo("Europe/London"))
    ny_now = now_utc.astimezone(ZoneInfo("America/New_York"))

    london_time = (london_now.hour, london_now.minute)
    ny_time = (ny_now.hour, ny_now.minute)

    in_london = (4, 30) <= london_time < (11, 30)
    in_ny = (9, 00) <= ny_time < (17, 30)

    if in_london and in_ny:
        return True, f"London/NY overlap (London {london_now.strftime('%H:%M')}, NY {ny_now.strftime('%H:%M')})"
    elif in_london:
        return True, f"London session ({london_now.strftime('%H:%M')})"
    elif in_ny:
        return True, f"New York session ({ny_now.strftime('%H:%M')})"
    else:
        return False, (f"Outside trading sessions. London: {london_now.strftime('%H:%M')} "
                       f"(need 04:30-11:30), NY: {ny_now.strftime('%H:%M')} (need 09:00-17:30)")


def check_spread_filter(symbol: str) -> tuple[bool, str]:
    """Returns (is_acceptable, reason)."""
    tick = get_current_tick(symbol)
    if tick is None:
        return False, "Cannot get tick data for spread check"

    sym_info = get_symbol_info(symbol)
    point = sym_info["point"] if sym_info else 0.01

    spread_points = (tick["ask"] - tick["bid"]) / point

    if spread_points <= MAX_SPREAD_POINTS:
        return True, f"Spread OK ({spread_points:.1f} points)"
    else:
        return False, f"Spread too wide ({spread_points:.1f} points > max {MAX_SPREAD_POINTS})"
