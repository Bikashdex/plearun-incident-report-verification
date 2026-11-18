"""Pipeline entry point used by the CLI and the tests."""

from __future__ import annotations

from typing import Dict, Tuple

from . import llm_hint
from .claims import extract_claims
from .clock import ClockModel
from .loader import load_dir, read_text
from .verify import Finding, speed_candidate_ids, verify_claim


def _final_check(finding: Finding, event_map) -> Finding:
    if finding.status not in ("match", "conflict"):
        return finding
    if not finding.cite or not finding.quote:
        return Finding(finding.claim, "not_settled")
    key = (finding.cite["file"], finding.cite["row"])
    event = event_map.get(key)
    if event is None or finding.quote not in (event.raw or ""):
        return Finding(finding.claim, "not_settled")
    return finding


def analyze(report_path: str, records_dir: str, use_llm: bool = False) -> Tuple[Dict, ClockModel]:
    report_text = read_text(report_path)
    events = load_dir(records_dir)
    clock = ClockModel.estimate(events)
    claims = extract_claims(report_text)

    event_map = {(event.file, event.row): event for event in events}
    findings = []
    for claim in claims:
        preferred = None
        if use_llm and claim.kind == "speed":
            candidate_ids = speed_candidate_ids(claim, events, clock)
            if len(candidate_ids) > 1:
                preferred = llm_hint.select(
                    llm_hint.build_prompt(claim.text, candidate_ids), candidate_ids
                )
        finding = verify_claim(
            claim,
            events,
            clock,
            context_sod=claim.context_sod,
            preferred_id=preferred,
        )
        findings.append(_final_check(finding, event_map))

    return {"findings": [finding.to_dict() for finding in findings]}, clock
