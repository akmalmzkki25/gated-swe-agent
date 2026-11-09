# Baseline results: mini-swe-agent 2.4.6, unmodified

Setup:
- Model: `gemini/gemini-3.5-flash-lite` with the decoding parameters in `configs/model.yaml`.
- Budget: 100 calls and $1 per task. Seeds 0, 1, 2.
- Scored by the SWE-bench harness `swebench==5.0.2` inside the Linux runner.
- Run on 2026-11-08 with `track3 baseline`.
- Evidence: `runs/baseline/` (trajectories, preds) and `eval/baseline/` (harness reports, test output).

## Eval (8 tasks)

| Task | seed 0 | seed 1 | seed 2 | Resolved |
|---|---|---|---|---|
| astropy__astropy-12907 | ✔ | ✔ | ✔ | 3/3 |
| django__django-11790 | ✘ | ✘ | ✔ | 1/3 |
| django__django-11848 | ✔ | ✔ | ✔ | 3/3 |
| django__django-11885 | ✘ | ✔ | ✔ | 2/3 |
| django__django-12209 | ✔ | ✔ | ✔ | 3/3 |
| sphinx-doc__sphinx-10323 | ✔ | ✔ | ✔ | 3/3 |
| sphinx-doc__sphinx-10435 | ✘ | ✘ | ✔ | 1/3 |
| sphinx-doc__sphinx-7757 | ✔ | ✔ | ✔ | 3/3 |
| **Resolved per seed** | **5/8** | **6/8** | **8/8** | |

- pass@1 (mean over seeds): **19/24 = 79.2%**. The seeds range from 62.5% to 100%.
- pass@3 (resolved by at least one seed): **8/8 = 100%**.
- Every run ended with `Submitted`. No run hit the step or cost limit: the most calls used was 76, and the highest cost $0.24.

## Dev (4 tasks)

12/12 runs resolved (4/4 on every seed).

## dev_hard (8 harder dev tasks, added after the runs above)

The harness sanity check passed: gold 8/8, null 0/8.

| Task | Difficulty | seed 0 | seed 1 | seed 2 | Resolved |
|---|---|---|---|---|---|
| django__django-12050 | 15 min–1 h | ✔ | ✔ | ✔ | 3/3 |
| django__django-12325 | 1–4 h | ✘ | ✘ | ✘ | 0/3 |
| django__django-12708 | 1–4 h | ✔ | ✔ | ✔ | 3/3 |
| django__django-12774 | 15 min–1 h | ✔ | ✔ | ✔ | 3/3 |
| sphinx-doc__sphinx-7985 | 15 min–1 h | ✘ | ✘ | ✘ | 0/3 |
| sphinx-doc__sphinx-8551 | 15 min–1 h | ✘ | ✘ | ✘ | 0/3 |
| sphinx-doc__sphinx-9229 | 1–4 h | ✘ | ✘ (empty patch) | ✘ | 0/3 |
| sphinx-doc__sphinx-9461 | 1–4 h | ✘ | ✘ | ✘ | 0/3 |
| **Resolved per seed** | | **3/8** | **3/8** | **3/8** | |

- pass@1: 9/24 = 37.5%.
- This is the failure signal the agent is developed against. Only dev and dev_hard trajectories are read for that; eval trajectories are not.

## Scoring fix (found on dev_hard)

- **What happened:** on dev_hard seed 1, mini-swe-agent submitted an empty patch for sphinx-9229. The harness writes no report for empty patches, and `collect` first counted only instances that had a report, which gave "3/7".
- **The fix:** every instance in the predictions file is now in the denominator. One without a report counts as unresolved, and the reason is written to `unscored.json`. All baseline scores were re-collected from the existing harness logs. Only that run changed.

## Cost

$2.87 for the 36 dev and eval task-runs, plus $2.39 for the 24 dev_hard task-runs.

## What this means for the comparison

- The baseline already solves every eval task at least once in 3 seeds. Any lift can only show up as **consistency** (pass@1), not as new tasks solved (pass@3).
- There is room for at most 5 more resolved runs out of 24.
- The dev set gives **no failure signal at all** (12/12), so it cannot guide agent development as PLAN.md intended.
- A success rate this high on 2019–2022 issues also makes the contamination check (PLAN.md section 6) more important.
