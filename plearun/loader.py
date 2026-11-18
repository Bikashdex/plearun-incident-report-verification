"""Load every record file in a directory into a uniform Event stream.

Each Event keeps the exact text it came from (``raw``) so the verifier can
prove that every quote really is a substring of the cited row.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .timestamps import (
    infer_default_offset,
    parse_timestamp,
    parse_vtt_time,
)

TEXT_EXTENSIONS = {".csv", ".json", ".jsonl", ".vtt", ".txt"}

TIME_KEYS = ("logged", "timestamp", "datetime", "ts", "time", "occurred", "recorded", "created")


@dataclass
class Event:
    file: str
    row: int
    raw: str
    kind: str
    source: str
    sod: Optional[float] = None
    rel: Optional[float] = None
    precision: str = "unknown"
    text: str = ""
    speed: Optional[float] = None
    zone: Optional[float] = None
    event_type: str = ""
    fields: Dict[str, str] = field(default_factory=dict)


def read_text(path: str) -> str:
    with open(path, "rb") as handle:
        data = handle.read()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _first_col(header, names) -> Optional[str]:
    for name in names:
        if name in header:
            return name
    for name in names:
        for col in header:
            if name in col:
                return col
    return None


def _number(text) -> Optional[float]:
    if text is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(text))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _split_csv_line(line: str) -> List[str]:
    try:
        return next(csv.reader(io.StringIO(line)))
    except (csv.Error, StopIteration):
        return []


def _load_csv(name: str, text: str, offset) -> List[Event]:
    lines = text.splitlines()
    header_index = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        header_index = index
        break
    if header_index is None:
        return []

    header = [cell.strip().lower() for cell in _split_csv_line(lines[header_index])]
    if not header:
        return []

    time_col = _first_col(header, ("timestamp", "time", "logged", "datetime", "date_time", "ts"))
    device_col = _first_col(header, ("device", "camera", "sensor", "unit", "source"))
    author_col = _first_col(header, ("author", "officer", "operator"))
    speed_col = _first_col(header, ("speed_mph", "speed", "mph"))
    zone_col = _first_col(header, ("zone_mph", "zone", "speed_limit", "limit", "posted"))
    note_col = _first_col(header, ("note", "notes", "description", "comment", "message", "detail", "text"))
    type_col = _first_col(header, ("type", "event", "kind", "category"))

    kind = "camera" if speed_col else ("note" if note_col else "generic")
    events: List[Event] = []
    data_row = 0

    for index in range(header_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = _split_csv_line(line)
        if not cells or not any(cell.strip() for cell in cells):
            continue
        data_row += 1
        record = {
            header[position]: (cells[position] if position < len(cells) else "")
            for position in range(len(header))
        }

        timestamp_cell = record.get(time_col, "") if time_col else ""
        parsed = parse_timestamp(timestamp_cell, offset)
        if not parsed.ok and time_col:
            for cell in cells:
                parsed = parse_timestamp(cell, offset)
                if parsed.ok:
                    break

        if kind == "camera":
            source = record.get(device_col, "") if device_col else ""
            source = source.strip() or "camera"
        elif kind == "note":
            source = record.get(author_col, "") if author_col else ""
            source = source.strip() or "notes"
        else:
            source = os.path.splitext(name)[0]

        if note_col:
            note_text = record.get(note_col, "")
        else:
            note_text = ""

        events.append(
            Event(
                file=name,
                row=data_row,
                raw=line,
                kind=kind,
                source=source,
                sod=parsed.sod,
                precision=parsed.precision,
                text=note_text,
                speed=_number(record.get(speed_col)) if speed_col else None,
                zone=_number(record.get(zone_col)) if zone_col else None,
                event_type=(record.get(type_col, "") if type_col else ""),
                fields=record,
            )
        )
    return events


def _object_spans(text: str):
    spans = []
    parents = {}
    stack = []
    in_string = False
    escaped = False
    for position, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            parents[position] = stack[-1] if stack else None
            stack.append(position)
        elif char == "}" and stack:
            start = stack.pop()
            spans.append((start, position + 1))
    return spans, parents


def _literal(value) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _enclosing_span(position: int, starts, span_by_start, parents):
    index = bisect_right(starts, position) - 1
    while index >= 0:
        start = starts[index]
        if start <= position < span_by_start[start]:
            return start
        parents_start = parents.get(start)
        if parents_start is None:
            return None
        index = bisect_left(starts, parents_start)
    return None


def _raw_for_object(obj, starts, span_by_start, parents, text: str) -> str:
    needles = []
    for key in ("id", "type"):
        if key in obj and isinstance(obj[key], (str, int)):
            needles.append(_literal(obj[key]))
    for key in TIME_KEYS:
        if key in obj and isinstance(obj[key], (str, int, float)):
            needles.append(_literal(obj[key]))
            break
    for needle in needles:
        if not needle:
            continue
        position = text.find(needle)
        if position < 0:
            continue
        start = _enclosing_span(position, starts, span_by_start, parents)
        if start is not None:
            return text[start:span_by_start[start]]
    return text


def _looks_like_event(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    keys = {str(key).lower() for key in obj}
    if keys & set(TIME_KEYS):
        return True
    return "id" in keys and ("type" in keys or "event" in keys)


def _iter_events(obj):
    if isinstance(obj, dict):
        if _looks_like_event(obj):
            yield obj
        for value in obj.values():
            yield from _iter_events(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_events(value)


def _load_json(name: str, text: str, offset) -> List[Event]:
    try:
        document = json.loads(text)
    except ValueError:
        return _load_jsonl(name, text, offset)

    spans, parents = _object_spans(text)
    span_by_start = dict(spans)
    starts = sorted(span_by_start)
    events: List[Event] = []
    seen = set()
    for obj in _iter_events(document):
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        row = len(events) + 1
        time_key = next((key for key in TIME_KEYS if key in obj), None)
        parsed = parse_timestamp(obj.get(time_key) if time_key else None, offset)
        event_type = str(
            obj.get("type")
            or obj.get("event_type")
            or obj.get("event")
            or obj.get("kind")
            or obj.get("category")
            or ""
        )
        speed = None
        zone = None
        for key, value in obj.items():
            lowered = str(key).lower()
            if speed is None and ("speed" in lowered or lowered == "mph"):
                speed = _number(value)
            if zone is None and ("zone" in lowered or "limit" in lowered):
                zone = _number(value)
        kind = "camera" if speed is not None else "dispatch"
        source = str(obj.get("unit") or obj.get("device") or obj.get("camera") or event_type or name)
        fields = {str(key): str(value) for key, value in obj.items()}
        events.append(
            Event(
                file=name,
                row=row,
                raw=_raw_for_object(obj, starts, span_by_start, parents, text),
                kind=kind,
                source=source,
                sod=parsed.sod,
                precision=parsed.precision,
                text=" ".join(str(value) for value in obj.values() if not isinstance(value, (dict, list))),
                speed=speed,
                zone=zone,
                event_type=event_type,
                fields=fields,
            )
        )
    return events


def _load_jsonl(name: str, text: str, offset) -> List[Event]:
    events: List[Event] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            obj = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        row = len(events) + 1
        time_key = next((key for key in TIME_KEYS if key in obj), None)
        parsed = parse_timestamp(obj.get(time_key) if time_key else None, offset)
        speed = None
        zone = None
        for key, value in obj.items():
            lowered = str(key).lower()
            if speed is None and ("speed" in lowered or lowered == "mph"):
                speed = _number(value)
            if zone is None and ("zone" in lowered or "limit" in lowered):
                zone = _number(value)
        events.append(
            Event(
                file=name,
                row=row,
                raw=line,
                kind="camera" if speed is not None else "dispatch",
                source=str(obj.get("unit") or obj.get("device") or obj.get("type") or name),
                sod=parsed.sod,
                precision=parsed.precision,
                text=" ".join(str(value) for value in obj.values() if not isinstance(value, (dict, list))),
                speed=speed,
                zone=zone,
                event_type=str(obj.get("type") or ""),
                fields={str(key): str(value) for key, value in obj.items()},
            )
        )
    return events


def _group_blocks(text: str):
    blocks = []
    current = []
    for line in text.splitlines(keepends=True):
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _load_vtt(name: str, text: str, offset) -> List[Event]:
    events: List[Event] = []
    cue_number = 0
    for block in _group_blocks(text):
        timing_index = None
        for index, line in enumerate(block):
            if "-->" in line:
                timing_index = index
                break
        if timing_index is None:
            continue
        timing_line = block[timing_index].strip()
        start_token = timing_line.split("-->")[0].strip()
        start = parse_vtt_time(start_token)
        if start is None:
            continue
        payload = [line.strip() for line in block[timing_index + 1:] if line.strip()]
        cue_number += 1
        events.append(
            Event(
                file=name,
                row=cue_number,
                raw="".join(block),
                kind="transcript",
                source=os.path.splitext(name)[0],
                rel=start,
                text=" ".join(payload),
            )
        )
    return events


def _load_text(name: str, text: str, offset) -> List[Event]:
    events: List[Event] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parsed = parse_timestamp(stripped.split()[0], offset)
        events.append(
            Event(
                file=name,
                row=len(events) + 1,
                raw=line,
                kind="generic",
                source=os.path.splitext(name)[0],
                sod=parsed.sod if parsed.ok else None,
                precision=parsed.precision,
                text=line,
            )
        )
    return events


def load_dir(directory: str) -> List[Event]:
    texts = {}
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    for name in names:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in TEXT_EXTENSIONS:
            continue
        try:
            texts[name] = read_text(path)
        except OSError:
            continue

    offset = infer_default_offset(texts.values())
    events: List[Event] = []
    for name, text in texts.items():
        extension = os.path.splitext(name)[1].lower()
        try:
            if extension == ".csv":
                events.extend(_load_csv(name, text, offset))
            elif extension == ".json":
                events.extend(_load_json(name, text, offset))
            elif extension == ".jsonl":
                events.extend(_load_jsonl(name, text, offset))
            elif extension == ".vtt":
                events.extend(_load_vtt(name, text, offset))
            else:
                events.extend(_load_text(name, text, offset))
        except Exception:
            # A malformed file must not take the whole run down.
            continue
    return events
