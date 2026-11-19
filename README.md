# Plearun — report vs. records checker

Checks every factual claim in an incident report against the machine records and prints one JSON finding per claim.

```bash
python3 plearun_cli.py reports/report_fictional_02.txt records > findings.json
make test        # 30 offline tests; standard library only
```

Python 3.8+. No network and no LLM are required. (On Windows without `python3`, use `python`.) `--llm` enables the optional `mock_llm.py` tie-break; the pipeline is identical and still passes everything without it.

## How it works

1. **Load** `.csv`, `.json`, `.jsonl`, `.vtt`, `.txt`, decoding `utf-8-sig` → `utf-8` → `cp1252` → `latin-1` and normalising CRLF. Each event keeps its file, row, and raw text.
2. **Parse timestamps** into seconds-of-day: epoch s/ms/µs, ISO 8601 with or without offsets, naive ISO, `HH:MM`, dotted A.M./P.M., WebVTT. Naive times stay wall-clock, never the machine's local timezone.
3. **Align clocks** (`plearun/clock.py`). Dispatch is the reference. Notes are shifted using the 911 call that appears in both notes and dispatch; camera skews come from zero-speed rows anchored to the corrected stop time. Bodycam is aligned only when its weighted anchors agree within 120 s (total weight ≥ 2); otherwise it stays unaligned rather than guessed.
4. **Extract claims** (`plearun/claims.py`): speed/zone, clock times, elapsed delays ("2 minutes after the stop"), counts, mile-marker/exits.
5. **Verify conservatively** (`plearun/verify.py`): 90 s tolerance for bare times (120 s hedged, 30 s when seconds are given), delays `max(60 s, 25%)`, speed ±0.5 mph. `conflict` requires an authoritative dispatch time (>300 s off) or a trusted nearby camera speed (>8 mph off); otherwise `not_settled`.
6. **Quote gate** (`plearun/pipeline.py`): each `match`/`conflict` quote must be an exact substring of the cited row's raw text, or it is downgraded to `not_settled`.

Row numbering: 1-based data record for CSV/JSONL/TXT (marker and header excluded), 1-based event for JSON, cue number for WebVTT.

## Three hardest decisions

- **Clock trust hierarchy.** Records differ by tens of seconds, so aligning everything to the nearest event invents precision. I align only clocks with a repeatable anchor, propagate the corrected stop time, and leave the bodycam unaligned when its anchors contradict. Unaligned evidence may support a match, never a conflict.
- **Conservative conflicts.** A wrong conflict is worse than no answer. Conflicts need authoritative dispatch data or clock-trusted camera evidence close in time. On the sample this correctly yields zero conflicts.
- **Records are data.** Nothing in a record can steer the tool. The optional LLM may only choose among pre-computed candidate row IDs and cannot create a finding; the quote gate re-checks even that choice.

## What it gets wrong

- Free-text meaning: subjective claims ("the only car in the lane") and locations other than mile markers/exits stay `not_checkable`.
- Lexical extraction: sentences with several numbers, or a typo such as "85 in a 45", can bind to the wrong candidate.
- Clock model: a constant skew is assumed; drifting or resyncing devices are left unaligned.

## What breaks first on real records

- **Schema drift** in camera logs or JSON keys. New formats fail safely (claims become `not_settled`) but coverage drops.
- **Clock drift** over long recordings, where one offset no longer fits the file.
- **Paraphrased or compound report sentences**, where one sentence carries several claims sharing one time context.

## Tools used

- **Qoder AI coding assistant** — implementation, test scaffolding, and README drafting.
- **Python standard library only** (`dataclasses`, `json`, `csv`, `re`, `datetime`, `bisect`, `statistics`); no runtime network or model calls.
- **`mock_llm.py` / `schema.json`** — optional, constrained LLM tie-break path.
