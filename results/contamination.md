# Contamination check (eval set, both agents, all seeds)

- **How to regenerate:** `python -m track3.contamination eval`. The raw signals are in `results/contamination-eval.json`, and the probe responses are in `runs/probes/eval/`.
- **Probe cost:** $0.022 for 16 calls.
- **Why it matters:** every eval task is a 2017–2022 GitHub issue, older than the model, so memorisation is possible for all of them. The checks below look for fixes that came from memory rather than from reading the code.

## Signals (fixed in PLAN.md before computing)

| Task | First edit to a source file (median / min step) | Edited a file it had not read | Max overlap with gold (final patches) | Probe: id only | Probe: issue only |
|---|---|---|---|---|---|
| astropy__astropy-12907 | 9 / 7 | 0 of 6 runs | 1.0 | 0.0 | 0.0 |
| django__django-11790 | 24 / 18 | 0 | 0.667 | 0.0 | 0.0 |
| django__django-11848 | 13 / 9 | 0 | 0.2 | 0.0 | **0.2** |
| sphinx-doc__sphinx-10435 | 25 / 14 | 0 | 0.333 | 0.0 | 0.0 |
| sphinx-doc__sphinx-10323 | 12.5 / 12 | 0 | 1.0 | 0.0 | 0.0 |
| django__django-12209 | 29.5 / 15 | 0 | 0.0 | 0.0 | 0.0 |
| sphinx-doc__sphinx-7757 | 15 / 11 | 0 | 0.188 | 0.0 | 0.0 |
| django__django-11885 | 26 / 24 | 0 | 0.037 | 0.0 | 0.0 |

**Column notes:**
- **Overlap** is the share of the gold patch's added lines (normalised) that a patch reproduces.
- **Probes** use the same model and decoding with no repository: "id only" gets just the instance id; "issue only" gets the issue text and base commit. The column shows the probe patch's overlap with gold.

**Heuristic fix found while checking flags:** the first version also flagged 3 runs for editing an unread file. All 3 were edits to scratch scripts (`reproduce_issue.py`, `update.py`, `/tmp/repro_issue.py`), not to the repository. Only edits to files in the submitted patch now count, and the code is covered by tests.

## Manual verdict per flag

| Task | Flag | Verdict |
|---|---|---|
| astropy-12907 | overlap 1.0 in all 6 runs | **Not memorised.** The gold fix is one line (`= 1` → `= right`), so any correct fix equals it. Every run read `separable.py` first (first edit at step 7 or later), and both probes produced nothing like it. |
| sphinx-10323 | overlap 1.0 in all 6 runs | **Not memorised.** The gold fix only swaps the order of two filters, so the same reasoning applies. Both probes scored 0. |
| django-11790, sphinx-7757, sphinx-10435, django-11885 | single "gold line not in the issue" hits | **Not memorised.** Each matched line is a small rewrite of code already in the same function (e.g. `self.username_field.max_length or 254` is in the line being replaced). Reading the file is enough to produce them. |
| **django-11848** | `current_year = datetime.datetime.utcnow().year` in 3/3 baseline runs, 1/3 agent runs, **and in the issue-only probe** | **Ambiguous.** The model writes this line without repository access. The issue does not mention `utcnow`, but HTTP dates are UTC, so choosing it is also good reasoning. Baseline seed 0 ran `git grep "utcnow" django/utils/` before writing it. Prior knowledge cannot be ruled out, so the lift is also reported without this task. |

No run edited a file before reading it, and no id-only probe reproduced any gold line. **No task shows clear signs of a memorised fix.**

## Lift with and without the ambiguous task

| Set | Baseline | Gated agent | Lift |
|---|---|---|---|
| All 8 tasks (headline) | 19/24 = 79.2% | 16/24 = 66.7% | **−12.5 pts** |
| Without django-11848 (7 tasks) | 16/21 = 76.2% | 15/21 = 71.4% | −4.8 pts |

## Limits of this check

- Overlap means little for one-line fixes.
- A model could recall the idea of a fix without reproducing its exact lines.
- One probe per mode at seed 0 is a small sample.
- The checks rule out obvious copy-from-memory; they cannot prove that no knowledge was recalled.
