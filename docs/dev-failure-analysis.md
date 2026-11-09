# Why the baseline fails on dev_hard (dev data only)

- **Source:** mini-swe-agent runs on dev_hard, seeds 0–2. A subagent analysed them on 2026-11-08, reading the dev_hard trajectories, harness reports, gold patches and tests. No eval data was read.
- **Tasks:** the 5 tasks that failed on every seed: django-12325, sphinx-7985, sphinx-8551, sphinx-9229, sphinx-9461. That is 15 failed runs.

## Failure classes (15 runs)

| Class | Runs |
|---|---|
| Right place, wrong or incomplete fix | 12 |
| Wrong location | 2 (9229 seeds 0 and 2: patched the parser although its own script showed the parser was fine) |
| Empty patch | 1 (9229 seed 1, after 83 steps: the issue's example does not reproduce on Python 3.9) |
| Regression in previously passing tests | **0** |
| Real loops | none (at most 9 repeated commands, from rewriting quoted `python -c` edits) |

## Patterns

1. **The hidden tests ask for more than the issue text says.** Examples: the django-12325 semantics change, linkcheck's ignore order and output format, 9461's directive option and wording, 9229's class-alias case. Most patches still make the issue's own example pass.
2. **Existing repository tests pass before and after every edit.** None of them covers the changed behaviour. In django-12325 one of them asserts the old behaviour.
3. **Fixes were rarely checked end to end.** 8551 and 7985 never ran the issue's example. In 9229 the agent's own script contradicted its theory and it patched anyway. 9461 seed 0 crashes on the path it edited, and the agent never re-ran it.

## What this means for the gated agent

- **The required failing reproduction is the main lever.** It plausibly recovers 9229 seeds 0 and 2, 9461 seeds 0–1 and 8551: a patch that does nothing, or that crashes, cannot turn a failing assertion into a passing one.
- **Revisions only help where the reproduction gives a failing signal.**
- **The regression gate catches nothing here.** It stays as a safety net, but it is not where any lift on these tasks would come from.
- **Loop detection is marginal here.**
- **Not reachable by any gate:** about 7 of 15 runs, where the expected behaviour is not in the issue (django-12325, 7985, 9461 wording). A generated reproduction passes on them.
- **Expected effect:** roughly 4–6 of the 15 failed runs look recoverable. The real numbers come from the agent's own dev_hard run, not from this estimate.
