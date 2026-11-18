"""Optional LLM tie-breaker.

The model may only pick from candidate IDs that the deterministic verifier has
already proved valid.  Its output can reorder those candidates; it can never
create a finding, a citation, or a quote.  The default run never imports this.
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Optional


def _provider():
    try:
        import mock_llm  # type: ignore
        return mock_llm
    except ImportError:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        import mock_llm  # type: ignore
        return mock_llm


def _valid_shape(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    if set(payload) != {"selected_row_ids", "quote", "reason"}:
        return False
    ids = payload["selected_row_ids"]
    quote = payload["quote"]
    reason = payload["reason"]
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        return False
    if quote is not None and not isinstance(quote, str):
        return False
    if not isinstance(reason, str) or len(reason) > 280:
        return False
    return True


def select(prompt: str, candidate_ids: List[str]) -> Optional[str]:
    if not candidate_ids:
        return None
    try:
        raw = _provider().complete(prompt, list(candidate_ids))
    except Exception:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not _valid_shape(payload):
        return None
    for selected in payload["selected_row_ids"]:
        if selected in candidate_ids:
            return selected
    return None


def build_prompt(claim_text: str, candidate_ids: List[str]) -> str:
    return (
        "Pick the single record row that best evidences this claim. "
        "Only choose from the given IDs; never invent one.\n"
        f"Claim: {claim_text}\n"
        f"Candidates: {', '.join(candidate_ids)}"
    )
