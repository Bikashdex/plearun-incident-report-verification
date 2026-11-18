# Plearun — report vs. records checker

Checks each factual claim in an incident report against the machine records and writes one JSON finding per claim to stdout.

```bash
python3 plearun_cli.py reports/report_fictional_02.txt records > findings.json
make test        # 30 offline tests, stdlib only, no network, no LLM
```

Python 3.8+. Nothing outside the standard library is required. `--llm` enables the optional `mock_llm.py` path; the pipeline still works and passes all tests without it.

## How it works

1. **Load** every file in the records directory (`.csv`, `.json`, `.jsonl`, `.vtt`, `.txt`). Text is decoded as `utf-8-sig`, then `utf-8`, then `cp1252`, then `latin-1`; CRLF is normalised. Every event keeps its file, row number, and raw source text.
2. **Parse timestamps** into seconds-of-day (circular arithmetic), supporting epoch seconds/ms/µs, ISO 8601 with or without offsets, naive ISO, `HH:MM`, dotted A.M./P.M., and WebVTT cue times. Naive times are treated as wall-clock, never as the machine's local timezone.
3. **Estimate clock offsets** (`plearun/clock.py`): dispatch is the reference. The note clock is shifted using the 911-call event that appears in both notes and dispatch. Camera skews come from zero-speed rows, anchored to the corrected stop time. The bodycam clock is aligned only if its weighted anchors agree within 120 s with total weight ≥ 2; otherwise it is left unaligned rather than guessed.
4. **Extract claims** (`plearun/claims.py`): speed/zone, clock times, elapsed delays ("2 minutes after the stop"), counts, and location fragments such as "mile marker 4".
5. **Verify conservatively** (`plearun/verify.py`): tolerance is 90 s for bare times (120 s when hedged with "about/roughly", 30 s when seconds are stated); delays allow `max(60 s, 25%)`; speeds match within 0.5 mph. `conflict` is only emitted from an authoritative dispatch time (>300 s off) or a trusted nearby camera speed (>8 mph off). Everything else is `not_settled`.
6. **Final quote gate** (`plearun/pipeline.py`): before output, each `match`/`conflict` quote must be an exact substring of the cited row's raw text; if not, it is downgraded to `not_settled`.

Row numbering: 1-based data-record index for CSV/JSONL/TXT (marker and header lines excluded), 1-based event index for JSON, cue number for WebVTT.

## Three hardest decisions

- **Trust hierarchy for clocks.** Records disagree by tens of seconds, so aligning everything "to the nearest event" invents precision. I align only clocks with a repeatable anchor, propagate the corrected stop time, and refuse to align the bodycam when its anchors contradict each other. Unaligned evidence can support a match, never a conflict.
- **Conflict policy.** A wrong conflict is worse than no answer. I require corroboration from authoritative dispatch types or a clock-trusted camera row close in time; otherwise the result is `not_settled`. On the sample this yields zero conflicts, which is the correct outcome.
- **Records are data.** Report and record text never selects behaviour. The optional LLM is restricted to choosing among pre-computed candidate row IDs and cannot create findings; even then, the quote-substring gate re-checks the result.

## What it gets wrong

- Free-text semantics: "the only car in the lane", subjective or inferred statements, and locations other than mile markers/exits stay `not_checkable`. A claim written very differently from the record wording (no shared number, time, or keyword) can be missed.
- Speed reads are lexically scoped: a sentence with multiple speed-like numbers, or a typo such as "85 in a 45", may be paired with the wrong candidate row.
- Elapsed-time claims are checked against the stop, call, or dispatch time only; long chains of events are not modelled.
- Clock alignment assumes a small constant skew. A device with drifting or resyncing clocks will be left unaligned, not corrected.

## What breaks first on real records

- **Schema drift**: camera logs with a different column layout or nested JSON keys, and CSV files with quoted multi-line fields. New formats fail safely (records load, claims become `not_settled`) rather than crash, but matching coverage drops.
- **Clock drift over long recordings**, where a single offset no longer fits the whole file.
- **Natural-language reports** with paraphrase, negation, or compound sentences, where one sentence carries several claims that share one time context.

## Tools used

- **Qoder (AI coding assistant)** for implementation, test scaffolding, and README drafting.
- Python standard library only (`dataclasses`, `json`, `csv`, `re`, `datetime`, `bisect`, `statistics`); no network or model calls at runtime.
- `mock_llm.py` / `schema.json` for the optional, constrained LLM tie-break path.
