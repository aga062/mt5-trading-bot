import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

logger = logging.getLogger("news.news_filter")

# ForexFactory public calendar feeds (no API key required)
_CALENDAR_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

# Only block on High-impact USD events (primary XAUUSD driver)
_HIGH_IMPACT_CURRENCIES = {"USD"}
BLACKOUT_MINUTES = 30       # block 30 min before and after event
_CACHE_TTL = timedelta(hours=4)

_lock = threading.Lock()
_cached_events: list[dict] = []
_cache_expires_at: datetime = datetime.min.replace(tzinfo=timezone.utc)


# ── Fetching & Caching ────────────────────────────────────────────────────────

def _fetch_calendar() -> list[dict]:
    events = []
    for url in _CALENDAR_URLS:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as resp:
                events.extend(json.loads(resp.read().decode()))
        except URLError as e:
            logger.warning(f"Calendar fetch failed ({url}): {e}")
        except Exception as e:
            logger.error(f"Calendar parse error ({url}): {e}")
    return events


def _refresh_if_stale():
    global _cached_events, _cache_expires_at
    now = datetime.now(timezone.utc)
    with _lock:
        if now < _cache_expires_at:
            return
        events = _fetch_calendar()
        _cached_events = events
        _cache_expires_at = now + _CACHE_TTL
        logger.info(f"News calendar refreshed — {len(events)} events loaded")


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_utc(date_str: str) -> datetime | None:
    """Parse ForexFactory ISO date string → UTC datetime."""
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            # ForexFactory dates without tz are US/Eastern
            dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_upcoming_events(hours: int = 24) -> list[dict]:
    """Return upcoming high-impact USD events within the next `hours` hours, sorted by time."""
    _refresh_if_stale()
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours)
    result = []

    for ev in _cached_events:
        if ev.get("impact") != "High":
            continue
        if ev.get("country") not in _HIGH_IMPACT_CURRENCIES:
            continue
        event_time = _parse_utc(ev.get("date", ""))
        if event_time is None or not (now <= event_time <= cutoff):
            continue
        minutes_away = int((event_time - now).total_seconds() / 60)
        result.append({
            "title": ev.get("title", ""),
            "country": ev.get("country", ""),
            "time_utc": event_time.isoformat(),
            "minutes_away": minutes_away,
            "impact": ev.get("impact", ""),
            "forecast": ev.get("forecast") or "",
            "previous": ev.get("previous") or "",
        })

    result.sort(key=lambda x: x["minutes_away"])
    return result


def is_news_blackout() -> tuple[bool, str, list[dict]]:
    """Check whether trading should be blocked due to an imminent or recent high-impact event.

    Scans a window of [now - BLACKOUT_MINUTES, now + BLACKOUT_MINUTES] across all
    high-impact USD events (both upcoming and recently past).

    Returns:
        (blocked, reason, upcoming_events)
        blocked=True  → do NOT trade
        blocked=False → clear to trade
    """
    _refresh_if_stale()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=BLACKOUT_MINUTES)
    window_end = now + timedelta(minutes=BLACKOUT_MINUTES)
    upcoming = get_upcoming_events(hours=24)

    # Scan all cached events (includes past ones) for the blackout window
    for ev in _cached_events:
        if ev.get("impact") != "High":
            continue
        if ev.get("country") not in _HIGH_IMPACT_CURRENCIES:
            continue
        event_time = _parse_utc(ev.get("date", ""))
        if event_time is None:
            continue
        if window_start <= event_time <= window_end:
            diff_minutes = (event_time - now).total_seconds() / 60
            title = ev.get("title", "event")
            if diff_minutes >= 0:
                reason = f"News blackout: {title} in {int(diff_minutes)}m"
            else:
                reason = f"News blackout: {title} ({int(abs(diff_minutes))}m ago)"
            return True, reason, upcoming

    return False, "No high-impact news nearby", upcoming
