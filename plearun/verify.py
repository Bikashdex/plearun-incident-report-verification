"""Decide match / conflict / not_settled / not_checkable for each claim.

Conflict is deliberately hard to earn: it needs an authoritative record whose
time is trusted and whose value differs by a wide margin.  Everything else
falls back to "not_settled".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .claims import SPEED_IN_RE, SPEED_MPH_RE, Claim
from .clock import ClockModel
from .keywords import (
    OBSERVED_RE,
    SCENE_RE,
    STOP_RE,
    STRONG_CALL_RE,
    event_type_matches,
)
from .loader import Event
from .timestamps import sod_absdiff, sod_delta

PRIORITY = {
    "call": {"dispatch": 0, "note": 1, "transcript": 2},
    "scene": {"dispatch": 0},
    "dispatched": {"dispatch": 0},
    "stop": {"note": 0, "camera": 1, "transcript": 2},
    "observed": {"note": 0, "transcript": 1},
}


@dataclass
class Finding:
    claim: str
    status: str
    cite: Optional[Dict[str, object]] = None
    quote: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {"claim": self.claim, "finding": self.status}
        if self.status in ("match", "conflict") and self.cite and self.quote:
            data["cite"] = {"file": self.cite["file"], "row": self.cite["row"]}
            data["quote"] = self.quote
        return data


def _clean_quote(event: Event) -> Optional[str]:
    raw = event.raw or ""
    quote = raw.rstrip("\r\n")
    if not quote.startswith(quote.strip()):
        quote = quote.lstrip()
    if not quote:
        return None
    if len(quote) > 900:
        for line in quote.splitlines():
            if line.strip():
                candidate = line.strip()
                if candidate in raw:
                    return candidate
        return None
    return quote if quote in raw else None


def _result(claim: Claim, status: str, event: Optional[Event] = None) -> Finding:
    if status in ("match", "conflict") and event is not None:
        quote = _clean_quote(event)
        if quote is not None:
            return Finding(claim.text, status, {"file": event.file, "row": event.row}, quote)
    return Finding(claim.text, "not_settled")


def _number(text) -> Optional[float]:
    cleaned = re.sub(r"[^0-9.\-]", "", str(text))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _text_speed(text: str):
    match = SPEED_IN_RE.search(text or "")
    if match:
        return float(match.group(1)), int(match.group(2)), match
    match = SPEED_MPH_RE.search(text or "")
    if match:
        return float(match.group(1)), None, match
    return None


def _speed_candidates(claim: Claim, events):
    speed = claim.speed
    zone = claim.zone
    camera_exact = []
    text_exact = []
    for event in events:
        if event.kind == "camera" and event.speed is not None:
            if speed is not None and abs(event.speed - speed) <= 0.5:
                if zone is None or (event.zone is not None and abs(event.zone - zone) <= 0.5):
                    camera_exact.append(event)
            elif speed is None and zone is not None and event.zone is not None:
                if abs(event.zone - zone) <= 0.5:
                    camera_exact.append(event)
        parsed = _text_speed(event.text)
        if parsed:
            text_speed, text_zone, _ = parsed
            if speed is not None and abs(text_speed - speed) <= 0.5:
                if zone is None or text_zone is None or text_zone == zone:
                    text_exact.append(event)
            elif speed is None and zone is not None and text_zone == zone:
                text_exact.append(event)
    return camera_exact, text_exact


def speed_candidate_ids(claim: Claim, events, clock: ClockModel) -> List[str]:
    camera_exact, text_exact = _speed_candidates(claim, events)
    return [f"{event.file}:{event.row}" for event in camera_exact + text_exact]


def _verify_speed(
    claim: Claim,
    events,
    clock: ClockModel,
    context_sod,
    preferred_id: Optional[str] = None,
) -> Finding:
    speed = claim.speed
    camera_exact, text_exact = _speed_candidates(claim, events)

    best = None
    best_score = None
    for event in camera_exact:
        score = 0
        corrected = clock.true_sod(event)
        if corrected is None:
            score += 1
        elif context_sod is not None and sod_absdiff(corrected, context_sod) > 180:
            score += 3
        if preferred_id == f"{event.file}:{event.row}":
            score -= 10
        if best_score is None or score < best_score:
            best, best_score = event, score
    for event in text_exact:
        score = 1
        if preferred_id == f"{event.file}:{event.row}":
            score -= 10
        if best_score is None or score < best_score:
            best, best_score = event, score

    if best is not None:
        return _result(claim, "match", best)

    if speed is not None and context_sod is not None:
        nearby = []
        for event in events:
            if event.kind != "camera" or event.speed is None:
                continue
            if not clock.trusted_for_conflict(event):
                continue
            corrected = clock.true_sod(event)
            if corrected is None:
                continue
            distance = sod_absdiff(corrected, context_sod)
            if distance <= 240:
                nearby.append((distance, event))
        if nearby:
            _, event = min(nearby, key=lambda item: (item[0], item[1].row))
            if abs(event.speed - speed) > 8:
                return _result(claim, "conflict", event)

    return Finding(claim.text, "not_settled")


def _time_matches(event: Event, subtype: str) -> bool:
    if subtype == "call":
        if event.kind == "dispatch":
            return event_type_matches(event.event_type, "call")
        if event.kind in ("note", "transcript"):
            return bool(STRONG_CALL_RE.search(event.text))
        return False
    if subtype == "stop":
        if event.kind in ("note", "transcript"):
            return bool(STOP_RE.search(event.text))
        if event.kind == "camera":
            return event.speed == 0
        return False
    if subtype == "observed":
        return event.kind in ("note", "transcript") and bool(OBSERVED_RE.search(event.text))
    if subtype == "scene":
        return event.kind == "dispatch" and event_type_matches(event.event_type, "scene")
    if subtype == "dispatched":
        return event.kind == "dispatch" and event_type_matches(event.event_type, "dispatched")
    return True


def _verify_time(claim: Claim, events, clock: ClockModel) -> Finding:
    if claim.sod is None:
        return Finding(claim.text, "not_settled")
    candidates = []
    for event in events:
        if not _time_matches(event, claim.subtype):
            continue
        corrected = clock.true_sod(event)
        if corrected is None:
            continue
        distance = sod_absdiff(claim.sod, corrected)
        priority = PRIORITY.get(claim.subtype, {}).get(event.kind, 5)
        candidates.append((priority, distance, event.row, event))

    if not candidates:
        return Finding(claim.text, "not_settled")

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    _, distance, _, event = candidates[0]

    tolerance = 30.0 if claim.precision == "sec" else 90.0
    if claim.hedge:
        tolerance = 120.0

    if distance <= tolerance:
        return _result(claim, "match", event)

    if (
        claim.subtype in ("call", "scene", "dispatched")
        and event.kind == "dispatch"
        and distance > 300
        and clock.trusted_for_conflict(event)
    ):
        return _result(claim, "conflict", event)

    return Finding(claim.text, "not_settled")


def _scene_event(events):
    for event in events:
        if event.kind == "dispatch" and event_type_matches(event.event_type, "scene"):
            return event
    for event in events:
        if SCENE_RE.search(event.text or ""):
            return event
    return None


def _dispatch_event(events, subtype):
    for event in events:
        if event.kind == "dispatch" and event_type_matches(event.event_type, subtype):
            return event
    return None


def _delay_reference(claim: Claim, events, clock: ClockModel):
    if claim.delay_ref == "stop":
        return clock.ref_stop
    if claim.delay_ref == "call":
        event = _dispatch_event(events, "call")
        return clock.true_sod(event) if event is not None else None
    if claim.delay_ref == "dispatch":
        event = _dispatch_event(events, "dispatched")
        return clock.true_sod(event) if event is not None else None
    if claim.delay_ref in ("observation", "arrival"):
        for event in events:
            if event.kind in ("note", "transcript") and OBSERVED_RE.search(event.text or ""):
                value = clock.true_sod(event)
                if value is not None:
                    return value
    return None


def _verify_delay(claim: Claim, events, clock: ClockModel) -> Finding:
    if claim.delay_ref == "stop" and clock.stop_source == "camera zero-speed rows":
        return Finding(claim.text, "not_settled")
    reference = _delay_reference(claim, events, clock)
    if reference is None:
        return Finding(claim.text, "not_settled")
    target = _scene_event(events)
    if target is None:
        return Finding(claim.text, "not_settled")
    target_sod = clock.true_sod(target)
    if target_sod is None:
        return Finding(claim.text, "not_settled")

    actual = sod_delta(target_sod, reference)
    if actual < 0:
        return Finding(claim.text, "not_settled")
    claimed = float(claim.delay_min) * 60.0
    tolerance = max(60.0, claimed * 0.25)
    if abs(actual - claimed) <= tolerance:
        return _result(claim, "match", target)
    if abs(actual - claimed) > max(180.0, claimed * 0.5):
        return _result(claim, "conflict", target)
    return Finding(claim.text, "not_settled")


def _verify_count(claim: Claim, events) -> Finding:
    for event in events:
        for key, value in event.fields.items():
            lowered = str(key).lower()
            if "count" in lowered or "occupant" in lowered:
                number = _number(value)
                if number is None:
                    continue
                if int(number) == claim.count:
                    return _result(claim, "match", event)
                return _result(claim, "conflict", event)
    return Finding(claim.text, "not_checkable")


def verify_claim(
    claim: Claim,
    events: List[Event],
    clock: ClockModel,
    context_sod: Optional[float] = None,
    preferred_id: Optional[str] = None,
) -> Finding:
    if claim.kind == "speed":
        return _verify_speed(claim, events, clock, context_sod, preferred_id)
    if claim.kind == "time":
        return _verify_time(claim, events, clock)
    if claim.kind == "delay":
        return _verify_delay(claim, events, clock)
    if claim.kind == "count":
        return _verify_count(claim, events)
    return Finding(claim.text, "not_checkable")
