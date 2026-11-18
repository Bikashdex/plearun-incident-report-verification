"""Turn a free-text incident report into atomic factual claims."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .keywords import classify_time_subtype, word_to_number
from .timestamps import sod_from_parts

_SPEED_UNIT = r"(?:miles?\s+per\s+hour|m\.?p\.?h\.?|mph)(?!\w)"
SPEED_MPH_RE = re.compile(
    rf"(?<![\d.])(\d{{1,4}}(?:\.\d+)?)\s*{_SPEED_UNIT}", re.IGNORECASE
)
SPEED_OF_RE = re.compile(
    r"\bspeed(?:\s+of|\s+was|\s+at|=|:)?\s+(\d{1,3}(?:\.\d+)?)\b", re.IGNORECASE
)
SPEED_IN_RE = re.compile(
    rf"(?<![\d.])(\d{{1,4}}(?:\.\d+)?)(?:\s*{_SPEED_UNIT})?\s*in\s+a\s+(?:posted\s+)?(\d{{1,3}})\b",
    re.IGNORECASE,
)
ZONE_RE = re.compile(
    r"(?:posted(?:\s+(?:speed\s+)?limit)?|speed\s+limit(?:\s+of)?|limit\s+of)\s+(\d{1,3})\b",
    re.IGNORECASE,
)
ZONE_SUFFIX_RE = re.compile(
    rf"(?<![\d.])(\d{{1,3}})\s*(?:{_SPEED_UNIT}\s*)?(?:speed\s+)?zone\b",
    re.IGNORECASE,
)
_ZONE_TAIL_RE = re.compile(r"\s*(?:speed\s+)?(?:zone|limit)\b", re.IGNORECASE)
_PREPOSTED_RE = re.compile(r"\bposted\s*$", re.IGNORECASE)
TIME_RE = re.compile(
    r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?(?![\d:])"
)
DELAY_RE = re.compile(
    r"(?<![\d])(\d{1,3}(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|a\s+couple\s+of|a\s+few)"
    r"\s*(?:minutes?|mins?)\s+(?:after|following|before|within|of|from)\s+(?:the\s+)?"
    r"(stop|stoppage|call|dispatch|arrival|observation)\b",
    re.IGNORECASE,
)
COUNT_ONLY_RE = re.compile(
    r"\bonly\s+(?:one\s+)?(?:car|vehicle|sedan|truck|driver|occupant)s?\b",
    re.IGNORECASE,
)
COUNT_N_RE = re.compile(
    r"\b(one|two|three|four|five|\d+)\s+(?:other\s+)?"
    r"(?:cars|vehicles|sedans|trucks|occupants)\b",
    re.IGNORECASE,
)
LOCATION_MM_RE = re.compile(
    r"\b(?:near|at|by|around|just\s+past)\s+(?:mile\s+marker|MM)\s*\d+\b",
    re.IGNORECASE,
)
LOCATION_EXIT_RE = re.compile(r"\bexit\s+\d+\b", re.IGNORECASE)
HEDGE_RE = re.compile(
    r"\b(about|around|roughly|approximately|approx\.?|circa|nearly|just\s+about)\b|~",
    re.IGNORECASE,
)

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_FRAGMENT_BREAK = re.compile(r"[,;]")
_TITLE_RE = re.compile(r"\b(SYNTHETIC|FICTIONAL)\b", re.IGNORECASE)
_UNICODE_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)


@dataclass
class Claim:
    text: str
    kind: str
    pos: int
    line: int = 0
    seq: int = 0
    subtype: str = ""
    sod: Optional[float] = None
    precision: str = "min"
    hedge: bool = False
    speed: Optional[float] = None
    zone: Optional[float] = None
    delay_min: Optional[float] = None
    delay_ref: str = ""
    count: Optional[int] = None
    location: str = ""
    context_sod: Optional[float] = None


def _sentences(text: str):
    for line_index, line in enumerate(text.splitlines()):
        if _TITLE_RE.search(line):
            continue
        start = 0
        for match in _SENTENCE_BREAK.finditer(line):
            yield line_index, line[start:match.start()], start
            start = match.end()
        if start < len(line):
            yield line_index, line[start:], start


def _fragments(sentence: str, base: int):
    start = 0
    for match in _FRAGMENT_BREAK.finditer(sentence):
        yield sentence[start:match.start()], base + start
        start = match.start() + 1
    yield sentence[start:], base + start


def _trim(fragment: str, base: int):
    text = fragment.strip()
    if not text:
        return None, base
    leading = len(fragment) - len(fragment.lstrip())
    return text, base + leading


def _parse_clock(match) -> Optional[float]:
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    meridiem = re.sub(r"[^a-z]", "", (match.group(4) or "").lower())
    if minute > 59 or second > 59:
        return None
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    if hour > 23:
        return None
    return sod_from_parts(hour, minute, second)


def _speed_zone(norm: str):
    speed = None
    zone = None
    match = SPEED_IN_RE.search(norm)
    if match:
        speed = float(match.group(1))
        zone = int(match.group(2))
    if speed is None:
        for candidate in SPEED_MPH_RE.finditer(norm):
            tail = norm[candidate.end():]
            head = norm[:candidate.start()]
            if _ZONE_TAIL_RE.match(tail) or _PREPOSTED_RE.search(head):
                if zone is None:
                    zone = int(float(candidate.group(1)))
                continue
            speed = float(candidate.group(1))
            break
    if speed is None:
        match = SPEED_OF_RE.search(norm)
        if match:
            speed = float(match.group(1))
    if zone is None:
        match = ZONE_RE.search(norm) or ZONE_SUFFIX_RE.search(norm)
        if match:
            zone = int(match.group(1))
    if speed is None and zone is None:
        return None
    if speed is not None and not 0 <= speed <= 300:
        speed = None
    if zone is not None and not 1 <= zone <= 120:
        zone = None
    if speed is None and zone is None:
        return None
    return speed, zone


def extract_claims(report_text: str) -> List[Claim]:
    claims: List[Claim] = []
    sequence = 0
    for line_index, sentence, sentence_base in _sentences(report_text):
        norm_sentence = sentence.translate(_UNICODE_MAP)
        subtype = classify_time_subtype(norm_sentence)
        hedge = bool(HEDGE_RE.search(norm_sentence))
        sentence_claims: List[Claim] = []

        for fragment, fragment_base in _fragments(sentence, sentence_base):
            text, position = _trim(fragment, fragment_base)
            if text is None:
                continue

            speed = _speed_zone(text)
            if speed is not None:
                sequence += 1
                sentence_claims.append(
                    Claim(
                        text=text,
                        kind="speed",
                        pos=position,
                        line=line_index,
                        seq=sequence,
                        speed=speed[0],
                        zone=speed[1],
                        hedge=hedge,
                    )
                )

            for match in TIME_RE.finditer(text):
                sod = _parse_clock(match)
                if sod is None:
                    continue
                sequence += 1
                sentence_claims.append(
                    Claim(
                        text=text,
                        kind="time",
                        pos=position + match.start(),
                        line=line_index,
                        seq=sequence,
                        subtype=subtype,
                        sod=sod,
                        precision="sec" if match.group(3) is not None else "min",
                        hedge=hedge,
                    )
                )

            match = DELAY_RE.search(text)
            if match:
                amount = word_to_number(match.group(1))
                if amount is not None and 0 < amount <= 240:
                    sequence += 1
                    sentence_claims.append(
                        Claim(
                            text=text,
                            kind="delay",
                            pos=position + match.start(),
                            line=line_index,
                            seq=sequence,
                            delay_min=amount,
                            delay_ref=match.group(2).lower(),
                            hedge=hedge,
                        )
                    )

            match = COUNT_ONLY_RE.search(text)
            if match:
                sequence += 1
                sentence_claims.append(
                    Claim(
                        text=text,
                        kind="count",
                        pos=position + match.start(),
                        line=line_index,
                        seq=sequence,
                        count=1,
                    )
                )
            else:
                match = COUNT_N_RE.search(text)
                if match:
                    amount = word_to_number(match.group(1))
                    if amount is not None and 0 < amount <= 100:
                        sequence += 1
                        sentence_claims.append(
                            Claim(
                                text=text,
                                kind="count",
                                pos=position + match.start(),
                                line=line_index,
                                seq=sequence,
                                count=int(amount),
                            )
                        )

            match = LOCATION_MM_RE.search(text) or LOCATION_EXIT_RE.search(text)
            if match:
                sequence += 1
                sentence_claims.append(
                    Claim(
                        text=match.group(0).strip(),
                        kind="location",
                        pos=position + match.start(),
                        line=line_index,
                        seq=sequence,
                        location=match.group(0).strip(),
                    )
                )

        time_claims = [claim for claim in sentence_claims if claim.kind == "time" and claim.sod is not None]
        if time_claims:
            for claim in sentence_claims:
                if claim.kind == "speed":
                    nearest = min(time_claims, key=lambda item: abs(item.pos - claim.pos))
                    claim.context_sod = nearest.sod
        claims.extend(sentence_claims)

    unique: List[Claim] = []
    seen = set()
    for claim in claims:
        key = (
            claim.kind,
            claim.text.lower(),
            claim.speed,
            claim.zone,
            claim.sod,
            claim.delay_min,
            claim.count,
            claim.location.lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    unique.sort(key=lambda claim: (claim.line, claim.pos, claim.seq))
    return unique
