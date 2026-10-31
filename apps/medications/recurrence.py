"""Recurrence calculations.

Schedules are expressed in the patient's IANA timezone. Fixed-time and weekday
schedules use local wall-clock times, so daylight-saving transitions are
handled by ``zoneinfo``. Interval schedules step by absolute elapsed hours from
the local anchor instant, which keeps the interval constant across DST.
All instants returned by this module are timezone-aware UTC datetimes.
"""

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class InvalidScheduleConfiguration(ValueError):
    pass


def validate_timezone(name: str) -> str:
    if not name or not isinstance(name, str):
        raise InvalidScheduleConfiguration("A valid IANA timezone is required.")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidScheduleConfiguration(f"Unknown timezone: {name}") from exc
    return name


def parse_time_string(value) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    try:
        parsed = time.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise InvalidScheduleConfiguration(
            f"Invalid time '{value}'. Use HH:MM (24-hour)."
        ) from exc
    if parsed.tzinfo is not None:
        raise InvalidScheduleConfiguration("Times must not include a timezone offset.")
    return parsed.replace(second=0, microsecond=0)


def normalise_times(values) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise InvalidScheduleConfiguration("Times must be a list.")
    normalised = []
    for value in values:
        parsed = parse_time_string(value)
        key = parsed.strftime("%H:%M")
        if key in normalised:
            raise InvalidScheduleConfiguration(f"Duplicate time: {key}")
        normalised.append(key)
    return sorted(normalised)


def normalise_weekdays(values) -> list[int]:
    if not isinstance(values, (list, tuple)):
        raise InvalidScheduleConfiguration("Weekdays must be a list.")
    weekdays = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidScheduleConfiguration("Weekdays must be integers from 0 to 6.")
        if value < 0 or value > 6:
            raise InvalidScheduleConfiguration("Weekdays must be between 0 and 6.")
        if value in weekdays:
            raise InvalidScheduleConfiguration(f"Duplicate weekday: {value}")
        weekdays.append(value)
    return sorted(weekdays)


def _utc(local_dt: datetime) -> datetime:
    return local_dt.astimezone(dt_timezone.utc)


def _fixed_occurrences(schedule, start_date, end_date):
    tz = ZoneInfo(schedule.timezone)
    times = [parse_time_string(value) for value in schedule.times]
    current = start_date
    while current <= end_date:
        for local_time in times:
            local_dt = datetime.combine(current, local_time, tzinfo=tz)
            yield _utc(local_dt), current
        current += timedelta(days=1)


def _weekday_occurrences(schedule, start_date, end_date):
    tz = ZoneInfo(schedule.timezone)
    times = [parse_time_string(value) for value in schedule.times]
    weekdays = set(schedule.weekdays)
    current = start_date
    while current <= end_date:
        if current.weekday() in weekdays:
            for local_time in times:
                local_dt = datetime.combine(current, local_time, tzinfo=tz)
                yield _utc(local_dt), current
        current += timedelta(days=1)


def _interval_occurrences(schedule, start_date, end_date):
    tz = ZoneInfo(schedule.timezone)
    medication = schedule.medication
    anchor_local = datetime.combine(
        medication.start_date, schedule.anchor_time, tzinfo=tz
    )
    anchor_utc = _utc(anchor_local)
    interval = timedelta(hours=schedule.interval_hours)

    window_start_utc = _utc(
        datetime.combine(start_date, time.min, tzinfo=tz)
    )
    window_end_utc = _utc(
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz)
    )

    current = anchor_utc
    if current < window_start_utc:
        elapsed = window_start_utc - current
        steps = elapsed // interval
        current += steps * interval
        while current < window_start_utc:
            current += interval

    while current < window_end_utc:
        local_date = current.astimezone(tz).date()
        if start_date <= local_date <= end_date:
            yield current, local_date
        current += interval


def iter_occurrences(schedule, start_date: date, end_date: date):
    """Yield ``(utc_instant, local_date)`` pairs within the given local dates."""
    medication = schedule.medication
    start_date = max(start_date, medication.start_date)
    if medication.end_date:
        end_date = min(end_date, medication.end_date)
    if start_date > end_date:
        return

    if schedule.schedule_type == schedule.ScheduleType.FIXED_TIMES:
        yield from _fixed_occurrences(schedule, start_date, end_date)
    elif schedule.schedule_type == schedule.ScheduleType.WEEKDAYS:
        yield from _weekday_occurrences(schedule, start_date, end_date)
    elif schedule.schedule_type == schedule.ScheduleType.INTERVAL_HOURS:
        yield from _interval_occurrences(schedule, start_date, end_date)
    else:
        raise InvalidScheduleConfiguration(
            f"Unsupported schedule type: {schedule.schedule_type}"
        )


def calculate_window_occurrences(schedule, window_days: int, now=None):
    """Return occurrences inside the future window ``[now, now + window)``.

    Occurrences strictly before ``now`` are never generated. This prevents a
    newly created or edited schedule from manufacturing missed doses for times
    that already passed today. Historical occurrences are preserved separately
    and are never regenerated.
    """
    from django.utils import timezone as django_timezone

    now = now or django_timezone.now()
    tz = ZoneInfo(schedule.timezone)
    end_date = (now + timedelta(days=window_days)).astimezone(tz).date()
    if schedule.medication.end_date:
        end_date = min(end_date, schedule.medication.end_date)
    start_date = max(
        schedule.medication.start_date, now.astimezone(tz).date()
    )
    if start_date > end_date:
        return []

    # Include the whole final local day so a 14-day window means 14 dates,
    # not 14 * 24 hours ending at the current clock time.
    window_end = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=tz
    )

    return [
        (instant, local_date)
        for instant, local_date in iter_occurrences(
            schedule, start_date, end_date
        )
        if now <= instant < window_end
    ]
