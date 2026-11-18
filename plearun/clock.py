"""Estimate per-device clock offsets from events that appear in several sources.

The dispatch system is treated as the operational reference clock.  Notes and
cameras are aligned to it only when a shared event (a 911 call or the stop) can
be identified in both places.  The body-camera transcript is aligned only if
all of its anchors imply the same recording start; otherwise it stays
unaligned, so its relative cue times are never used as absolute times.
"""

from __future__ import annotations

from typing import List, Optional

from .keywords import CALL_RE, STOP_RE, STRONG_CALL_RE, event_type_matches
from .loader import Event
from .timestamps import (
    clock_spread,
    fmt_sod,
    median_offset,
    median_sod,
    parse_clock_text,
    sod_delta,
)


class ClockModel:
    def __init__(self) -> None:
        self.skews = {}
        self.note_skew = 0.0
        self.transcript_start: Optional[float] = None
        self.ref_stop: Optional[float] = None
        self.stop_source: Optional[str] = None
        self.camera_absolute = False
        self.diagnostics: List[str] = []

    def true_sod(self, event: Event) -> Optional[float]:
        if event.kind == "transcript":
            if self.transcript_start is None or event.rel is None:
                return None
            return (self.transcript_start + event.rel) % 86400.0
        if event.sod is None:
            return None
        if event.kind == "camera":
            if event.source not in self.skews:
                return None
            return (event.sod - self.skews[event.source]) % 86400.0
        if event.kind == "note":
            return (event.sod - self.note_skew) % 86400.0
        return event.sod

    def trusted_for_conflict(self, event: Event) -> bool:
        if event.kind == "dispatch":
            return True
        if event.kind == "note":
            return True
        if event.kind == "camera":
            return self.camera_absolute and event.source in self.skews
        if event.kind == "transcript":
            return self.transcript_start is not None
        return True

    def describe(self) -> str:
        parts = [
            f"note_skew={self.note_skew:+.0f}s",
            f"ref_stop={fmt_sod(self.ref_stop)} ({self.stop_source or 'none'})",
            "camera_skews={"
            + ", ".join(f"{key}:{value:+.0f}s" for key, value in sorted(self.skews.items()))
            + "}",
            f"bodycam_start={fmt_sod(self.transcript_start)}",
        ]
        if self.diagnostics:
            parts.append("anchors: " + " | ".join(self.diagnostics))
        return "; ".join(parts)

    @classmethod
    def estimate(cls, events: List[Event]) -> "ClockModel":
        model = cls()
        notes = [event for event in events if event.kind == "note" and event.sod is not None]
        cues = [event for event in events if event.kind == "transcript"]
        cameras = [event for event in events if event.kind == "camera" and event.sod is not None]
        dispatch = [event for event in events if event.kind == "dispatch" and event.sod is not None]

        call = None
        for event in dispatch:
            if event_type_matches(event.event_type, "call") or STRONG_CALL_RE.search(event.text):
                call = event
                break

        note_call = None
        for event in notes:
            if STRONG_CALL_RE.search(event.text):
                note_call = event
                break

        if call is not None and note_call is not None:
            delta = sod_delta(note_call.sod, call.sod)
            if abs(delta) <= 300:
                model.note_skew = delta
                model.diagnostics.append(
                    f"notes call {fmt_sod(note_call.sod)} vs dispatch "
                    f"{fmt_sod(call.sod)} -> note skew {delta:+.0f}s"
                )
            else:
                model.diagnostics.append(
                    f"notes call differs from dispatch by {delta:+.0f}s; not applying"
                )

        stop_note_times = [
            (event.sod - model.note_skew) % 86400.0
            for event in notes
            if STOP_RE.search(event.text)
        ]
        if stop_note_times:
            model.ref_stop = median_sod(stop_note_times)
            model.stop_source = "notes"
        else:
            cue_stop_times = []
            for cue in cues:
                if STOP_RE.search(cue.text):
                    stated = parse_clock_text(cue.text)
                    if stated is not None:
                        cue_stop_times.append(stated)
            if cue_stop_times:
                model.ref_stop = median_sod(cue_stop_times)
                model.stop_source = "transcript text"
            else:
                zero_times = [event.sod for event in cameras if event.speed == 0]
                if zero_times:
                    model.ref_stop = median_sod(zero_times)
                    model.stop_source = "camera zero-speed rows"
                    model.camera_absolute = False

        if model.ref_stop is not None:
            for device in sorted({event.source for event in cameras}):
                zeros = [
                    event.sod
                    for event in cameras
                    if event.source == device and event.speed == 0
                ]
                if not zeros:
                    continue
                deltas = [sod_delta(value, model.ref_stop) for value in zeros]
                near = [delta for delta in deltas if abs(delta) <= 900]
                skew = median_offset(near if near else deltas)
                if abs(skew) > 7200:
                    model.diagnostics.append(
                        f"{device} implied skew {skew:+.0f}s is implausible; not aligning"
                    )
                    continue
                model.skews[device] = skew
                model.diagnostics.append(
                    f"{device} zero-speed vs ref stop -> skew {skew:+.0f}s"
                )
            if model.stop_source == "notes":
                model.camera_absolute = True

        start_anchors = []
        if call is not None:
            for cue in cues:
                if cue.rel is not None and STRONG_CALL_RE.search(cue.text):
                    start_anchors.append(((call.sod - cue.rel) % 86400.0, 1))
        for cue in cues:
            if cue.rel is not None and STOP_RE.search(cue.text):
                stated = parse_clock_text(cue.text)
                if stated is not None:
                    # A cue that states its own clock time is a strong anchor.
                    start_anchors.append(((stated - cue.rel) % 86400.0, 2))
        if start_anchors:
            starts = [value for value, _ in start_anchors]
            weight = sum(weight for _, weight in start_anchors)
            spread = clock_spread(starts)
            if spread <= 120 and weight >= 2:
                model.transcript_start = median_sod(starts)
                model.diagnostics.append(
                    f"bodycam anchors agree within {spread:.0f}s -> start "
                    f"{fmt_sod(model.transcript_start)}"
                )
            else:
                model.diagnostics.append(
                    f"bodycam anchors disagree by {spread:.0f}s (weight {weight}); "
                    "leaving bodycam unaligned"
                )

        return model
