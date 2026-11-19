# Plearun — Incident Report Verification Tool

Incident reports and their machine records do not share a clock. This tool reconstructs the offsets, checks every factual claim in the report against the records, and prints one JSON finding per claim — with the exact row it relied on.

## Sample result

**7 claims: 5 `match`, 2 `not_checkable`, 0 `conflict`.**

| Claim | Verdict | Evidence |
|---|---|---|
| Observed at ~21:14 | `match` | notes N-1 (21:15; note clock +41 s) |
| 58 mph in a posted 45 | `match` | bodycam cue 1: "58 in a 45." |
| Stopped at ~21:16 | `match` | notes N-3: "Stopped at lot ~21:16" |
| 911 call at 21:11 | `match` | dispatch D-1001 |
| Unit on scene ~2 min after stop | `match` | dispatch D-1002 (exactly +2:00) |
| Near mile marker 4 | `not_checkable` | no location field in records |
| "Only car in the lane" | `not_checkable` | subjective; not recorded |

Claims abbreviated; exact text in `findings.json`. Full walkthrough with clock math: [DEMO.md](DEMO.md).

## Output format

Each finding is one JSON object. Four verdicts: `match` (records support the claim), `conflict` (records clearly contradict it), `not_settled` (evidence exists but is not decisive), `not_checkable` (records lack that kind of fact). `cite` and `quote` appear only for `match` and `conflict`.

`json
{
  "claim": "Officer Lee first observed the blue sedan at about 21:14 ...",
  "finding": "match",
  "cite": {"file": "notes_cp1252.csv", "row": 1},
  "quote": "N-1,Officer Lee,\"Vehicle observed, plate unknown\",21:15"
}
`

## Quick start

`bash
python3 plearun_cli.py reports/report_fictional_02.txt records > findings.json
 make test        # 30 offline tests; standard library only
`

Python 3.8+, stdlib only, no network, no LLM. (Windows: use `python`.) `--llm` enables the optional `mock_llm.py` tie-break; output is identical without it.

## How it works

1. **Load** every file in the records directory (`.csv`, `.json`, `.jsonl`, `.vtt`, `.txt`). Decode BOM, Windows-1252, and CRLF. Keep each event's file, row, and raw text.
2. **Parse timestamps** into seconds-of-day: epoch s/ms/µs, ISO with/without offset, naive ISO, `HH:MM`, dotted A.M./P.M., WebVTT cue times. Naive times stay wall-clock, never machine-local.
3. **Align clocks** (`clock.py`): dispatch is the reference. Notes shift via the shared 911 call. Camera skews come from zero-speed rows anchored to the corrected stop. Bodycam aligns only if its anchors agree; otherwise it stays unaligned.
4. **Extract claims** from the report (`claims.py`): speed/zone, clock times, elapsed delays, counts, mile markers.
5. **Verify** each claim against the aligned records (`verify.py`). Before any `match`/`conflict` is written, the quote is re-checked as an exact substring of the cited row; if it fails, the finding is downgraded to `not_settled` (`pipeline.py`).

Row numbering: 1-based data record for CSV/JSONL/TXT (marker/header excluded), event for JSON, cue for WebVTT.

## Three hardest decisions

- **Clock trust hierarchy.** Alignment needs a repeatable anchor; nearest-event guesses invent precision. The bodycam stays unaligned when its anchors contradict, and unaligned evidence can support a match, never a conflict.
- **Conservative conflicts.** A wrong conflict is worse than no answer. Nothing in the sample is clearly contradicted, so it yields zero conflicts while still confirming five claims.
- **Records are data.** Record text cannot steer the tool. The optional LLM only ranks pre-computed candidate row IDs; the quote gate re-checks its choice.

## What it gets wrong

- Subjective claims and non-mile-marker locations stay `not_checkable`.
- Multi-number sentences or typos like "85 in a 45" can bind the wrong candidate.
- A constant clock skew is assumed; drifting devices stay unaligned.

## What breaks first on real records

- **Schema drift** in camera logs or JSON keys: fails safely, coverage drops.
- **Clock drift** over long recordings, where one offset no longer fits.
- **Paraphrased or compound sentences** sharing one time context.

## Tools used

- **Qoder AI coding assistant** — implementation, tests, README.
- **Python standard library only**; no runtime network or model calls.
- **`mock_llm.py` / `schema.json`** — optional constrained tie-break.
