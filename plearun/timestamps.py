"""Timestamp parsing for the three formats used in the records pack.

All times are reduced to a *local wall-clock* number of seconds since midnight
(``sod``).  Absolute instants (epoch, ISO with offset) are converted into the
dataset's dominant UTC offset before the time of day is taken, so that a
22:00:00Z stamp and a 17:00:00-05:00 stamp compare equal.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:\.(\d{1,6}))?)?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)
TOD_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?$")
CLOCK_IN_TEXT_RE = re.compile(
    r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?(?![\d:])"
)
ISO_WITH_OFFSET_SCAN = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})"
)
INTEGER_RE = re.compile(r"^\d{10,16}$")


@dataclass
class Parsed:
    sod: Optional[float] = None
    precision: str = "unknown"
    ok: bool = False


def sod_from_parts(hour: int, minute: int, second: float = 0.0) -> float:
    return (hour * 3600 + minute * 60 + second) % 86400.0


def parse_offset(text: str) -> timezone:
    if text == "Z":
        return timezone.utc
    sign = 1 if text[0] == "+" else -1
    body = text[1:].replace(":", "")
    hours = int(body[:2])
    minutes = int(body[2:4]) if len(body) >= 4 else 0
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_clock_text(text: str) -> Optional[float]:
    """First clock time written inside free text, as seconds of day."""
    for m in CLOCK_IN_TEXT_RE.finditer(text or ""):
        hour = int(m.group(1))
        minute = int(m.group(2))
        second = int(m.group(3) or 0)
        meridiem = re.sub(r"[^a-z]", "", (m.group(4) or "").lower())
        if minute > 59 or second > 59:
            continue
        if meridiem:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        if hour > 23:
            continue
        return sod_from_parts(hour, minute, second)
    return None


def _epoch_to_sod(value: float, target: timezone) -> float:
    seconds = value
    if value > 1e14:
        seconds = value / 1e6
    elif value > 1e11:
        seconds = value / 1e3
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(target)
    return float(dt.hour * 3600 + dt.minute * 60 + dt.second) + dt.microsecond / 1e6


def parse_timestamp(value, target: timezone = timezone.utc) -> Parsed:
    if value is None or isinstance(value, bool):
        return Parsed()
    if isinstance(value, (int, float)):
        return Parsed(_epoch_to_sod(float(value), target), "sec", True)
    text = str(value).strip()
    if not text:
        return Parsed()
    if INTEGER_RE.match(text):
        return Parsed(_epoch_to_sod(float(text), target), "sec", True)

    m = ISO_RE.match(text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
        second = int(m.group(6) or 0)
        micro = int((m.group(7) or "0").ljust(6, "0")[:6])
        try:
            naive = datetime(year, month, day, hour, minute, second, micro)
        except ValueError:
            return Parsed()
        if m.group(8):
            aware = naive.replace(tzinfo=parse_offset(m.group(8)))
            local = aware.astimezone(target).replace(tzinfo=None)
        else:
            local = naive
        sod = local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6
        precision = "sec" if m.group(6) is not None else "min"
        return Parsed(sod, precision, True)

    m = TOD_RE.match(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        second = int(m.group(3) or 0)
        meridiem = re.sub(r"[^a-z]", "", (m.group(4) or "").lower())
        if meridiem:
            if not 1 <= hour <= 12:
                return Parsed()
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        if hour > 23 or minute > 59 or second > 59:
            return Parsed()
        precision = "sec" if m.group(3) is not None else "min"
        return Parsed(sod_from_parts(hour, minute, second), precision, True)

    return Parsed()


def infer_default_offset(texts) -> timezone:
    """Most common explicit UTC offset in the dataset (defaults to UTC)."""
    counts: Counter = Counter()
    for text in texts:
        for match in ISO_WITH_OFFSET_SCAN.finditer(text or ""):
            counts[match.group(1)] += 1
    if not counts:
        return timezone.utc
    return parse_offset(counts.most_common(1)[0][0])


def parse_vtt_time(text: str) -> Optional[float]:
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})$", text.strip())
    if not m:
        return None
    hour, minute, second = int(m.group(1)), int(m.group(2)), int(m.group(3))
    millis = int(m.group(4).ljust(3, "0")[:3])
    return hour * 3600 + minute * 60 + second + millis / 1000.0


def sod_delta(a: float, b: float) -> float:
    """Signed difference a-b on a 24h circle, in (-43200, 43200]."""
    return (a - b + 43200.0) % 86400.0 - 43200.0


def sod_absdiff(a: float, b: float) -> float:
    return abs(sod_delta(a, b))


def median_sod(values):
    """Median of absolute times-of-day, tolerant of values around midnight."""
    values = [v % 86400.0 for v in values]
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    base = values[0]
    deltas = sorted(sod_delta(v, base) for v in values)
    mid = len(deltas) // 2
    if len(deltas) % 2:
        offset = deltas[mid]
    else:
        offset = (deltas[mid - 1] + deltas[mid]) / 2.0
    return (base + offset) % 86400.0


def median_offset(values):
    values = sorted(values)
    if not values:
        return 0.0
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def clock_spread(values, base=None) -> float:
    """Max-min spread of times-of-day on the 24h circle."""
    if not values:
        return 0.0
    if len(values) == 1:
        return 0.0
    if base is None:
        base = median_sod(values)
    deltas = [sod_delta(v, base) for v in values]
    return max(deltas) - min(deltas)


def fmt_sod(sod: Optional[float]) -> str:
    if sod is None:
        return "??:??:??"
    total = int(round(sod)) % 86400
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
