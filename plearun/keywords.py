"""Keyword detectors shared by claim extraction and clock alignment."""

from __future__ import annotations

import re

STOP_RE = re.compile(
    r"\b(stopped|stopping|stop|pulled\s+(?:in|into|over)|pulling\s+(?:in|into|over)"
    r"|pulls\s+(?:in|into|over)|halted|parked|detained)\b",
    re.IGNORECASE,
)
CALL_RE = re.compile(
    r"\b(911|call|caller|called|phone|phoned|reported|reporting)\b",
    re.IGNORECASE,
)
STRONG_CALL_RE = re.compile(
    r"\b(911|call|caller|called|phone|phoned)\b",
    re.IGNORECASE,
)
OBSERVED_RE = re.compile(
    r"\b(observed|observe|saw|seen|spotted|noticed|detected)\b",
    re.IGNORECASE,
)
SCENE_RE = re.compile(r"\b(on\s+scene|arrived|arrival|on-scene)\b", re.IGNORECASE)
DISPATCH_RE = re.compile(r"\b(dispatched|dispatch)\b", re.IGNORECASE)

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def word_to_number(text):
    lowered = str(text).strip().lower()
    if lowered in ("a couple of", "couple of", "couple", "a couple"):
        return 2.0
    if lowered in ("a few", "few"):
        return 3.0
    if lowered in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[lowered])
    try:
        return float(lowered)
    except ValueError:
        return None


def classify_time_subtype(sentence: str) -> str:
    lowered = sentence.lower()
    if re.search(r"\b911\b", lowered) or CALL_RE.search(lowered):
        return "call"
    if STOP_RE.search(lowered):
        return "stop"
    if OBSERVED_RE.search(lowered):
        return "observed"
    if SCENE_RE.search(lowered):
        return "scene"
    if DISPATCH_RE.search(lowered):
        return "dispatched"
    return "generic"


def event_type_matches(event_type: str, subtype: str) -> bool:
    value = (event_type or "").lower().replace("-", "_").replace(" ", "_")
    if subtype == "call":
        return "911" in value or "call" in value or "phone" in value
    if subtype == "scene":
        return "scene" in value or "arriv" in value
    if subtype == "dispatched":
        return "dispatch" in value
    if subtype == "stop":
        return "stop" in value
    return True
