"""Translate a human cadence phrase into an fn2 ``schedule`` object.

The fn2 API accepts a schedule shaped like::

    {"frequency": "weekdays", "timezone": "UTC"}          # recurring
    {"frequency": "custom", "cron": "0 9 * * 1-5", ...}   # recurring, cron
    {"run_at": "2026-07-22T13:00:00Z", "timezone": "UTC"} # single future run

This module maps everyday phrasing onto exactly that. It leans on the server to
interpret recurring cron in the given timezone, and only does local timezone
maths for the plain ``run_at`` (single-run) case.

Market phrases are handed to the server as a market phase + signed offset
(``frequency: market_open`` / ``market_close`` for recurring, ``market_event``
for one-shot). The SERVER owns the XNYS calendar — holidays, early closes, and
DST are resolved there, so a holiday-scheduled run simply does not fire. The
client never computes a market date.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional, Tuple

try:  # stdlib since 3.9; effectively universal
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - ancient runtimes only
    ZoneInfo = None  # type: ignore

MARKET_TZ = "America/New_York"
DEFAULT_TZ = "UTC"

# Signed minutes relative to the session boundary the server resolves. "Before
# the open" = -30 (a brief is ready 30 min ahead of the 09:30 bell); "after the
# close" = +5 (just past the 16:00 close).
MARKET_OPEN_OFFSET = -30
MARKET_CLOSE_OFFSET = 5

_NAMED_FREQUENCIES = {
    "hourly": "hourly",
    "every hour": "hourly",
    "daily": "daily",
    "every day": "daily",
    "each day": "daily",
    "weekdays": "weekdays",
    "every weekday": "weekdays",
    "business days": "weekdays",
}


class ScheduleError(ValueError):
    """Raised when a cadence phrase cannot be understood."""


@dataclass(frozen=True)
class Schedule:
    """A parsed cadence: ``payload`` is ``None`` when the agent runs immediately."""

    kind: str  # "now" | "recurring" | "once"
    summary: str
    payload: Optional[dict] = None


def run_now() -> Schedule:
    return Schedule(kind="now", summary="run once, immediately", payload=None)


def parse_when(text: Optional[str], *, timezone: Optional[str] = None) -> Schedule:
    """Parse a cadence phrase into a :class:`Schedule`.

    An empty phrase means "run now". Otherwise the phrase is classified as a
    one-off (produces ``run_at``) or a recurring cadence (produces
    ``frequency``/``cron``).
    """
    if text is None or not text.strip():
        return run_now()

    phrase = re.sub(r"\s+", " ", text.strip().lower())

    if phrase.startswith("cron:"):
        return _from_cron(phrase[len("cron:"):].strip(), timezone)

    if _is_one_off(phrase):
        return _parse_once(phrase, timezone)

    return _parse_recurring(phrase, timezone)


# -- classification ------------------------------------------------------
def _is_one_off(phrase: str) -> bool:
    if phrase.startswith("once "):
        return True
    if re.search(r"\bnext\b", phrase):
        return True
    if re.match(r"(today|tomorrow)\b", phrase):
        return True
    if re.match(r"in \d+\s*(min|minute|hour|hr|day)", phrase):
        return True
    if _looks_like_datetime(phrase):
        return True
    return False


def _looks_like_datetime(phrase: str) -> bool:
    return bool(re.match(r"\d{4}-\d{2}-\d{2}([ t]\d{1,2}:\d{2})?", phrase))


# -- recurring -----------------------------------------------------------
def _parse_recurring(phrase: str, timezone: Optional[str]) -> Schedule:
    if "market open" in phrase or "premarket" in phrase or "pre-market" in phrase:
        tz = timezone or MARKET_TZ
        return Schedule("recurring",
                        f"every trading day, {abs(MARKET_OPEN_OFFSET)} min before the open ({tz})",
                        {"frequency": "market_open", "offset_minutes": MARKET_OPEN_OFFSET,
                         "timezone": tz})
    if "market close" in phrase or "at close" in phrase or "after close" in phrase:
        tz = timezone or MARKET_TZ
        return Schedule("recurring",
                        f"every trading day, {MARKET_CLOSE_OFFSET} min after the close ({tz})",
                        {"frequency": "market_close", "offset_minutes": MARKET_CLOSE_OFFSET,
                         "timezone": tz})

    time_part = _extract_time(phrase)
    base = _base_cadence(phrase)

    if time_part is None:
        if base is None:
            raise ScheduleError(
                f"could not understand cadence {phrase!r}. Try 'daily', "
                "'weekdays', 'hourly', 'before market open', 'weekdays at 8:30am', "
                "or 'cron:0 9 * * 1-5'."
            )
        tz = timezone or DEFAULT_TZ
        return Schedule("recurring", f"{base} ({tz})",
                        {"frequency": base, "timezone": tz})

    hour, minute = time_part
    day_field = "1-5" if base == "weekdays" else "*"
    cron = f"{minute} {hour} * * {day_field}"
    tz = timezone or DEFAULT_TZ
    label = "every weekday" if day_field == "1-5" else "every day"
    return Schedule("recurring", f"{label} at {hour:02d}:{minute:02d} {tz}",
                    {"frequency": "custom", "cron": cron, "timezone": tz})


def _base_cadence(phrase: str) -> Optional[str]:
    for needle, freq in _NAMED_FREQUENCIES.items():
        if needle in phrase:
            return freq
    if re.search(r"\bweekday", phrase):
        return "weekdays"
    if re.search(r"\bdaily\b|\bevery day\b", phrase):
        return "daily"
    # A bare time like "at 9am" defaults to a daily cadence.
    if _extract_time(phrase) is not None:
        return "daily"
    return None


def _from_cron(cron: str, timezone: Optional[str]) -> Schedule:
    fields = cron.split()
    if len(fields) != 5:
        raise ScheduleError(
            f"cron must have 5 fields (min hour dom month dow), got {len(fields)}: {cron!r}"
        )
    tz = timezone or DEFAULT_TZ
    return Schedule("recurring", f"cron '{cron}' ({tz})",
                    {"frequency": "custom", "cron": cron, "timezone": tz})


# -- one-off -------------------------------------------------------------
def _parse_once(phrase: str, timezone: Optional[str]) -> Schedule:
    phrase = phrase[len("once "):].strip() if phrase.startswith("once ") else phrase

    # Relative: "in 2 hours", "in 30 minutes", "in 1 day".
    rel = re.match(r"in (\d+)\s*(min|minute|minutes|hour|hours|hr|hrs|day|days)", phrase)
    if rel:
        amount = int(rel.group(1))
        unit = rel.group(2)
        delta = _delta(amount, unit)
        when = _now_utc() + delta
        return _once_from_utc(when, f"once, in {amount} {unit}")

    # Market one-shots: the SERVER resolves the next XNYS session (holidays,
    # early closes, DST). The client names only the phase + signed offset, so a
    # holiday never yields a run against a closed market.
    if "market open" in phrase or "premarket" in phrase or "pre-market" in phrase:
        return Schedule("once", "once, before the next market open (server calendar)",
                        {"market_event": "open", "offset_minutes": MARKET_OPEN_OFFSET,
                         "timezone": MARKET_TZ})
    if "market close" in phrase or "at close" in phrase:
        return Schedule("once", "once, after the next market close (server calendar)",
                        {"market_event": "close", "offset_minutes": MARKET_CLOSE_OFFSET,
                         "timezone": MARKET_TZ})

    tz = timezone or DEFAULT_TZ
    hm = _extract_time(phrase)

    # "today ..." / "tomorrow ..."
    day = None
    if phrase.startswith("today"):
        day = 0
    elif phrase.startswith("tomorrow"):
        day = 1
    if day is not None:
        hour, minute = hm if hm else (9, 0)
        when = _at_local_date(day, hour, minute, tz)
        return _once_from_utc(when, f"once, {'today' if day == 0 else 'tomorrow'} "
                                    f"at {hour:02d}:{minute:02d} {tz}")

    # Explicit datetime: "2026-07-22", "2026-07-22 13:00", "2026-07-22T13:00".
    iso = _parse_iso(phrase, tz)
    if iso is not None:
        return _once_from_utc(iso, f"once, at {iso.astimezone(dt.timezone.utc).isoformat()}")

    raise ScheduleError(
        f"could not parse the one-off time {phrase!r}. Try 'next market open', "
        "'tomorrow at 9am', 'in 2 hours', or an ISO date like '2026-07-22T13:00'."
    )


def _once_from_utc(when_utc: dt.datetime, summary: str) -> Schedule:
    iso = when_utc.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()
    iso = iso.replace("+00:00", "Z")
    return Schedule("once", summary, {"run_at": iso, "timezone": "UTC"})


# -- time / date helpers -------------------------------------------------
def _extract_time(phrase: str) -> Optional[Tuple[int, int]]:
    match = re.search(r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", phrase)
    if not match:
        match = re.search(r"\bat\s*(\d{1,2})(?::(\d{2}))?\b", phrase)
        if not match:
            match = re.search(r"\b(\d{1,2}):(\d{2})\b", phrase)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.lastindex and match.group(2) else 0
    meridiem = match.group(3) if match.re.groups >= 3 else None
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"invalid time in {phrase!r}: {hour:02d}:{minute:02d}")
    return hour, minute


def _delta(amount: int, unit: str) -> dt.timedelta:
    if unit.startswith("min"):
        return dt.timedelta(minutes=amount)
    if unit.startswith(("hour", "hr")):
        return dt.timedelta(hours=amount)
    return dt.timedelta(days=amount)


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _tzinfo(name: str):
    if ZoneInfo is None:
        raise ScheduleError(
            "this Python build lacks zoneinfo, so timezone-aware one-off runs "
            "are unavailable. Use a recurring cadence (server-side timezone) or "
            "an absolute UTC time instead."
        )
    try:
        return ZoneInfo(name)
    except Exception as exc:  # pragma: no cover - bad tz string
        raise ScheduleError(f"unknown timezone {name!r}") from exc


def _next_weekday_at(hour: int, minute: int, tz_name: str) -> dt.datetime:
    tz = _tzinfo(tz_name)
    now = _now_utc().astimezone(tz)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while candidate <= now or candidate.weekday() >= 5:  # 5,6 = Sat,Sun
        candidate += dt.timedelta(days=1)
        candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate.astimezone(dt.timezone.utc)


def _at_local_date(day_offset: int, hour: int, minute: int, tz_name: str) -> dt.datetime:
    tz = _tzinfo(tz_name)
    local = (_now_utc().astimezone(tz) + dt.timedelta(days=day_offset))
    local = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local.astimezone(dt.timezone.utc)


def _parse_iso(phrase: str, tz_name: str) -> Optional[dt.datetime]:
    match = re.match(r"(\d{4}-\d{2}-\d{2})(?:[ t](\d{1,2}):(\d{2}))?", phrase)
    if not match:
        return None
    date_str, hh, mm = match.group(1), match.group(2), match.group(3)
    year, month, day = (int(p) for p in date_str.split("-"))
    hour = int(hh) if hh else 9
    minute = int(mm) if mm else 0
    tz = _tzinfo(tz_name)
    local = dt.datetime(year, month, day, hour, minute, tzinfo=tz)
    return local.astimezone(dt.timezone.utc)
