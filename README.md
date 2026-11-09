# Does a verifier-gated harness beat mini-swe-agent? A SWE-bench Verified study

A research project on harness engineering for coding agents.
- **Question:** with the model held fixed, does an agent that gates every patch on measured evidence resolve more real GitHub issues than the reference agent, [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)?
- **Evidence the gated agent requires:** a reproduction that fails before the fix and passes after it, plus related repository tests that still pass.
- **Held equal:** model, budget and seeds.
- **AI use:** AI coding tools were used throughout. See [`AI_USAGE.md`](AI_USAGE.md).

## Result

Same model (`gemini/gemini-3.5-flash-lite`, decoding pinned in [`configs/model.yaml`](configs/model.yaml)), same budget (100 calls / $1 per task), seeds 0, 1, 2. Scored by the SWE-bench harness 5.0.2.

| Eval set: 8 SWE-bench Verified tasks × 3 seeds | mini-swe-agent 2.4.6 (reference) | Gated agent (`agent-v1`) |
|---|---|---|
| pass@1 (% resolved, mean over seeds) | **79.2%** (19/24) | **66.7%** (16/24) |
| pass@3 | 100% (8/8) | 75% (6/8) |
| Cost | $2.31 | $2.41 |
| **Lift** | | **−12.5 pts**; paired: 1 win, 4 losses, 19 ties; sign test p = 0.375 |

**My agent did not beat the reference on the eval set.** Here is what happened and why:
- On a harder development split (dev_hard, 8 other Verified Mini tasks), it scored 58.3% against the reference's 37.5% (+20.8 pts, 5 wins, 0 losses). Those numbers come from development, before the freeze.
- On eval, the regression gate rejected a correct fix that changes tested output (sphinx-10435). In django-11848 the agent's own reproduction accepted a `now()`/`utcnow()` mismatch.
- The reference already solves 79% of eval runs, so there was little headroom.
- Contamination check: no task shows clear signs of a memorised fix. django-11848 is ambiguous, and without it the lift is −4.8 pts.

Further reading:
- Per-task tables: [`results/summary.md`](results/summary.md), [`results/eval-comparison.md`](results/eval-comparison.md), [`results/per_task.csv`](results/per_task.csv)
- Design doc: [`docs/design-track3.md`](docs/design-track3.md)
- Contamination: [`results/contamination.md`](results/contamination.md)

## Run it

You need Docker (Linux x86_64 engine; Docker Desktop is fine) and about 30 GB of disk. Every command runs inside the Linux runner container.

```bash
cp .env.example .env              # put GEMINI_API_KEY=... (or MODEL_NAME/API_BASE for another endpoint)
docker compose build
docker compose run --rm runner python -m track3.images     # pull the 20 task images by pinned digest
```

**Regenerate the reported numbers.** This one command runs the reference, the agent, the contamination probes and the report, for 3 seeds on the eval set (about 2 hours, about $5):

```bash
docker compose run --rm runner track3 all --split eval --seeds 0,1,2
```

Or run the steps one at a time:

```bash
docker compose run --rm runner track3 baseline --split eval --seeds 0,1,2   # mini-swe-agent, then the harness
docker compose run --rm runner track3 agent    --split eval --seeds 0,1,2   # gated agent (checkout tag agent-v1), then the harness
docker compose run --rm runner python -m track3.contamination eval
docker compose run --rm runner track3 report
```

**Audit without an API key.** Every run's trajectories, predictions, harness reports and test output are committed in `runs/` and `eval/`:

```bash
docker compose run --rm runner track3 report                                          # rebuild all numbers from committed files
docker compose run --rm runner track3 eval --who agent --split eval --seeds 0,1,2     # re-grade committed predictions with the harness
```

**Other commands:**
- `python -m track3.sanity eval` runs the harness sanity check (gold 8/8, null 0/8).
- `python -m pytest` runs the tests: 112 tests, run inside the runner.

## What is pinned

| What | Pin |
|---|---|
| Model | `gemini/gemini-3.5-flash-lite`, temperature 1.0, top_p 0.95, max_tokens 16384, reasoning_effort low, seed per run (`configs/model.yaml`; accepted values checked in `configs/model_smoke.json`) |
| Reference agent | `mini-swe-agent==2.4.6`, built-in `swebench.yaml`; the override is only model, seed and budget (`runs/baseline/*/seed*/override.yaml`) |
| Gated agent | git tag `agent-v1` (`a32cbc7`). Trajectories record `fca69b3`, the same agent code before a history rewrite that changed wording only (see `results/eval-comparison.md`) |
| Harness | `swebench==5.0.2`, `litellm[mcp]==1.108.1`; everything else in `uv.lock` |
| Tasks | `configs/tasks.json`: 8 eval (3 anchor instances plus a seeded stratified draw from Verified Mini), 4 dev, 8 dev_hard; selection rule in `src/track3/select_tasks.py` |
| Images | by digest, `configs/images.lock` |
| Budget | 100 model calls and $1 per task, identical for both agents (`configs/budget.yaml`) |

## Repository layout

```
README.md  PLAN.md  AI_USAGE.md
docs/design-track3.md         design doc: what was built, why, trade-offs, limitations, next steps
docs/phase0.md                environment checks, deviations from the plan, eval exposure log
docs/dev-failure-analysis.md  why the reference fails on dev_hard
results/                      summary.md, per_task.csv, eval-comparison.md, contamination.md, baseline.md, dev-comparison.md
src/track3/                   cli, select_tasks, images, run_baseline, run_agent, evaluate, sanity, contamination, report
src/track3/agent/             loop (state machine), tools, model, workspace, validate, testsel, policy, loopguard, candidates, prompts
tests/                        unit and loop tests (scripted model on a real git repo)
configs/  data/               pinned config, tasks, image digests, SWE-bench rows
runs/  eval/                  trajectories and predictions; harness reports and test output, kept byte for byte
docker/  compose.yaml         Linux runner
```

## Time invested and scope cuts

Calendar: 2026-11-06 to 2026-11-09. Much of that was waiting on image downloads over a 0.1–0.7 MB/s link.

Hands-on time: about 6–8 hours of my own work (steering, decisions, review), plus waiting time for image downloads and benchmark runs. Model API cost for the whole project: about $11, summed from the committed trajectories plus the probes; a few early smoke calls are not logged.

**Scope cuts:**
- One question only: harness engineering with a fixed model, no training.
- The ablations in the plan (no-validate, bash-only) were not run.
- No post-hoc agent-v2: the frozen `agent-v1` result is reported as final.
- 8 eval tasks and 3 seeds, sized to run on a laptop. That is too few for statistical significance either way.
