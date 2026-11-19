# Sample run — claim by claim

Reproduce with:

```bash
python3 plearun_cli.py reports/report_fictional_02.txt records > findings.json
```

The tool writes JSON to stdout and clock diagnostics to stderr. The sample produced **7 findings: 5 `match`, 2 `not_checkable`, 0 `conflict`**.

## Verdicts

| # | Claim from the report | Verdict | Citation | Quote |
|---|---|---|---|---|
| 1 | Officer Lee first observed the blue sedan at about 21:14… | `match` | `notes_cp1252.csv` row 1 (N-1) | `N-1,Officer Lee,"Vehicle observed, plate unknown",21:15` |
| 2 | near mile marker 4 | `not_checkable` | — | — |
| 3 | travelling 58 mph in a posted 45 zone. | `match` | `bodycam_transcript.vtt` cue 1 | `[SYNTHETIC] Officer Lee: 58 in a 45.` |
| 4 | The driver pulled into the Harbor Gas lot and stopped around 21:16. | `match` | `notes_cp1252.csv` row 3 (N-3) | `N-3,Officer Lee,Stopped at lot ~21:16,21:16` |
| 5 | A 911 call reporting the incident was logged at 21:11. | `match` | `dispatch.json` event 1 (D-1001) | `"logged": "2026-03-02 21:10:19"` |
| 6 | Dispatch records show a unit on scene roughly 2 minutes after the stop. | `match` | `dispatch.json` event 2 (D-1002) | `"logged": "2026-03-02T21:17:19-05:00"` |
| 7 | Officer Lee states the vehicle was the only car in the lane. | `not_checkable` | — | — |

Claim 1 is shortened with an ellipsis; the other claim texts match `findings.json`. Every `match` quote is re-checked by the program as an exact substring of the cited row before it is written. `not_checkable` means the records contain no field from which that claim could be judged, so no citation is possible.

## Why this is the point of the assignment

The sample is designed so that the naive approach fails in three different ways:

1. **The clocks are wrong, so raw timestamps cannot be compared directly.**
2. **Most claims are true, so a tool that guesses "conflict" looks productive but is wrong.**
3. **A citation is only useful if it can be checked, so quotes must be exact.**

The run demonstrates all three: it recovers the clock offsets, verifies five claims without inventing a single contradiction, and every quote is traceable.

## Clock reconstruction

| Source | Evidence | Estimated offset |
|---|---|---|
| Dispatch | Reference clock | 0 |
| Officer notes | 911 call says 21:11; dispatch says 21:10:19 | **+41 s** |
| CAM-03 | Zero-speed row at 21:15:18 vs corrected stop 21:15:19 | **−1 s** |
| CAM-07 | Zero-speed row at 21:16:48 vs corrected stop 21:15:19 | **+89 s** |
| Bodycam | Call anchor and self-stated stop anchor disagree by 338 s | **unaligned** |

Consequences:

- The note "Vehicle observed…" at 21:15 on the note clock is 21:14:19 true time, which matches "about 21:14".
- The notes' 911 time of 21:11 is 21:10:19 true time, which is exactly dispatch D-1001.
- The stop note at 21:16 on the note clock is 21:15:19 true time.
- D-1002 at 21:17:19 is exactly **2:00** after the corrected stop, matching "roughly 2 minutes".
- The bodycam is left unaligned because its anchors conflict. Its speed line is still usable because a speed reading does not depend on the absolute clock.

## Why zero conflicts is the correct answer

A conflict says the records clearly contradict the report. Nothing in this sample does. The conservative policy is not blanket abstention:

- 5 of 7 claims are affirmatively verified with citations.
- The 2 remaining claims are outside what the records can express.
- A conflict requires authoritative dispatch data or a clock-trusted camera reading close in time; no such contradiction exists here.

This is the intended trade-off: a false conflict costs more than several honest `not_settled` results.

## Reproduce and inspect

```bash
python3 plearun_cli.py reports/report_fictional_02.txt records > findings.json
python3 -c "import json; d=json.load(open('findings.json')); print(len(d['findings']))"
make test
```

Expected: `7` findings and `30` passing tests.
