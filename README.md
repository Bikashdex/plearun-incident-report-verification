# Plearun — report vs. records checker

Checks every factual claim in an incident report against the machine records and prints one JSON finding per claim.

**Sample result — 7 claims: 5 `match`, 2 `not_checkable`, 0 `conflict`.** Every citation was re-verified as an exact substring of the cited row.

| Claim | Verdict | Evidence |
|---|---|---|
| Observed at ~21:14 | `match` | notes N-1 (21:15; note clock +41 s) |
| 58 mph in a posted 45 | `match` | bodycam cue 1: "58 in a 45." |
| Stopped at ~21:16 | `match` | notes N-3: "Stopped at lot ~21:16" |
| 911 call at 21:11 | `match` | dispatch D-1001 |
| Unit on scene ~2 min after stop | `match` | dispatch D-1002 (exactly +2:00) |
| Near mile marker 4 | `not_checkable` | no location field in records |
| "Only car in the lane" | `not_checkable` | subjective; not recorded |

Claim-by-claim detail and clock math: [DEMO.md](DEMO.md).

```bash
python3 plearun_cli.py reports/report_fictional_02.txt records > findings.json
make test        # 30 offline tests; standard library only
```

Python 3.8+, stdlib only; no network or LLM. (Windows: use `python`.) `--llm` enables the optional `mock_llm.py` tie-break; output is identical without it.

## How it works

1. **Load** `.csv`, `.json`, `.jsonl`, `.vtt`, `.txt` with `utf-8-sig → utf-8 → cp1252 → latin-1`, normalise CRLF, keep file/row/raw text.
2. **Parse** timestamps to seconds-of-day: epoch s/ms/µs, ISO with/without offset, naive ISO, `HH:MM`, dotted A.M./P.M., WebVTT. Naive times stay wall-clock, never machine-local.
3. **Align clocks** (`clock.py`): dispatch is the reference; notes shift on the shared 911 call; camera skews come from zero-speed rows anchored to the corrected stop. Bodycam aligns only if its weighted anchors agree within 120 s (weight ≥ 2), else it stays unaligned.
4. **Extract and verify** (`claims.py`, `verify.py`): speed/zone, times, delays, counts, mile markers. Tolerances: 90 s bare, 120 s hedged, 30 s with seconds; delay `max(60 s, 25%)`; speed ±0.5 mph. `conflict` needs authoritative dispatch (>300 s) or a trusted nearby camera (>8 mph).
5. **Quote gate** (`pipeline.py`): each `match`/`conflict` quote must be an exact substring of the cited row, else it is downgraded to `not_settled`.

Row numbering: 1-based data record for CSV/JSONL/TXT (marker/header excluded), event for JSON, cue for WebVTT.

## Three hardest decisions

- **Clock trust hierarchy.** Alignment needs a repeatable anchor; nearest-event guesses invent precision. The bodycam stays unaligned when its anchors contradict, and unaligned evidence can support a match, never a conflict.
- **Conservative conflicts.** A wrong conflict is worse than no answer. Conflicts need authoritative dispatch data or clock-trusted nearby camera evidence; the sample correctly yields zero.
- **Records are data.** Record text cannot steer the tool. The optional LLM only ranks pre-computed candidate row IDs; the quote gate re-checks its choice.

## What it gets wrong

- Subjective claims and non-mile-marker locations stay `not_checkable`.
- Multi-number sentences or typos like "85 in a 45" can bind the wrong candidate.
- A constant clock skew is assumed; drifting devices stay unaligned.

## What breaks first

- **Schema drift** in camera logs or JSON keys: fails safely, coverage drops.
- **Clock drift** over long recordings.
- **Paraphrased or compound sentences** sharing one time context.

## Tools used

- **Qoder AI coding assistant** — implementation, tests, README.
- **Python standard library only**; no runtime network or model calls.
- **`mock_llm.py` / `schema.json`** — optional constrained tie-break.
