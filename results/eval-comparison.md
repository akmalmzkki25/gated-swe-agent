# Eval result: frozen gated agent (`agent-v1`) vs mini-swe-agent 2.4.6

- Both agents: same model and decoding, budget 100 calls / $1 per task, seeds 0–2, images by digest, SWE-bench harness 5.0.2.
- The agent ran once, after the freeze, on 2026-11-09. Every trajectory reports `agent_version = fca69b3`.
- `fca69b3` is the commit the runs were made from. It was rewritten before publication to reword framing text only; the published tag `agent-v1` is `a32cbc7`. Its `src/track3/agent` tree is byte-identical (`git rev-parse agent-v1:src/track3/agent` = `de1bdbd`), and the only other changes are wording in docs, a package docstring and one renamed constant in `select_tasks.py`.
- No run errored or went unscored; `unscored.json` is empty for every seed.

| Task | Baseline | Gated agent |
|---|---|---|
| astropy__astropy-12907 | ✔✔✔ | ✔✔✔ |
| django__django-11790 | ✘✘✔ | ✘✘✘ |
| django__django-11848 | ✔✔✔ | ✘✘✔ |
| django__django-11885 | ✘✔✔ | ✔✔✔ |
| django__django-12209 | ✔✔✔ | ✔✔✔ |
| sphinx-doc__sphinx-10323 | ✔✔✔ | ✔✔✔ |
| sphinx-doc__sphinx-10435 | ✘✘✔ | ✘✘✘ |
| sphinx-doc__sphinx-7757 | ✔✔✔ | ✔✔✔ |
| **Resolved per seed** | 5 / 6 / 8 | 5 / 5 / 6 |
| **pass@1** | **19/24 = 79.2%** | **16/24 = 66.7%** |
| pass@3 | 8/8 | 6/8 |
| Cost / calls | $2.31 / 852 | $2.41 / 825 |

## Lift: **−12.5 points pass@1** (the agent is worse on eval)

**Paired by task and seed (24 pairs):**
- The agent wins 1: django-11885 seed 0.
- The agent loses 4: django-11848 seeds 0 and 1, django-11790 seed 2, sphinx-10435 seed 2.
- 19 ties.
- Exact two-sided sign test on the 5 discordant pairs: p = 0.375. Eight tasks cannot separate this from noise in either direction. Still, the eval run gives **no evidence that the gated agent is better**.

On dev_hard, during development and before the freeze, the agent scored 14/24 against the baseline's 9/24 (`results/dev-comparison.md`). The two splits point in opposite directions.

## Why the agent lost the 4 pairs

The eval trajectories were read after the run, for this analysis only.

1. **sphinx-10435, seed 2: the regression gate pushed the agent away from the right fix.**
   - The fix changes LaTeX output, and an existing test in `tests/test_build_latex.py` asserts the old output. The harness's FAIL_TO_PASS test is an updated version of a test in that same file.
   - So every candidate that changed the output "broke" a previously passing test, and the gate rejected it 3 times.
   - The agent then moved its edit to a `.sty` file, where no test notices it. That patch is wrong.
   - The dev failure analysis had already flagged this risk (django-12325: an existing test asserts the old behaviour). It is a design flaw: **a before/after regression gate cannot tell a regression from an intended behaviour change.**
2. **django-11848, seeds 0 and 1: right logic, wrong clock.**
   - The agent's patch uses `datetime.datetime.now()`. The hidden tests mock `datetime.datetime.utcnow`, as the gold patch does.
   - The agent's own reproduction passes with either, so its gates cannot tell the difference.
   - All 3 baseline runs, and the agent's seed 2, used `utcnow()`. HTTP dates are UTC, so `utcnow` is the better choice. Whether the baseline gets it right from reasoning or from memory is a question for the contamination check (PLAN.md section 6).
3. **django-11790, seed 2: no valid fix found.** The baseline solved this task in only 1 of 3 runs. The agent's reproduction kept failing over 3 revisions, and the final candidate still fails the hidden tests.

## The one win

django-11885 seed 0: the baseline submitted a wrong patch, and the agent resolved it.

## What this means

- The verifier-gated design helped on tasks where the baseline fails because it never checks its fix end to end (dev_hard: sphinx-8551, sphinx-7985).
- It did not help on the eval set, where the baseline already resolves 79%.
- The regression gate actively hurt one run on eval, by treating an intended output change as a regression.
- **The headline result stays agent-v1 on eval: −12.5 points.** Any later change to the agent is post hoc, made after seeing eval, and must be reported as such.
