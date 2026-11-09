# Study plan: a verifier-gated SWE agent vs. mini-swe-agent on the same model

Status: **draft, waiting for approval. No agent code is written yet.**
Question: does a harness that gates every patch on measured evidence (a failing-then-passing reproduction, related tests that still pass) resolve more real GitHub issues than the reference agent, with the same model, budget and seeds? Contamination has to be checked, and every number has to be reproducible from one command.

---

## 1. Decisions (confirmed with the user on 2026-11-06)

| Item | Decision | Why |
|---|---|---|
| Repo | this repository, public | |
| Model under test | `gemini-3.5-flash-lite` on the Gemini API, paid Tier 1 | $0.30 in / $2.50 out per 1M tokens. A weaker model leaves headroom for lift and is less likely to have memorised the fixes. Gemini 2.5 is avoided because it is deprecated and gets rerouted to other models on 2026-12-01. |
| Reference agent | `mini-swe-agent==2.4.6` (released 2026-07-23), its own `swebench.yaml` config, code unchanged | The standard minimal reference agent for SWE-bench |
| Tasks | 8 instances (section 2) | Small enough for 3 seeds × 2 agents on a laptop |
| Repeats | 3 seeds (0, 1, 2) per agent | One run of 8 tasks moves in 12.5-point steps, too coarse to separate lift from noise |
| Budget per task (both agents) | 100 model calls, $1.00 model cost, 60-minute safety timeout | Identical for both agents and enforced by the same model client |
| Scoring | Official SWE-bench harness, `swebench==5.0.2`, run locally in Docker | Gives per-test output as evidence |

### Decoding parameters (pinned in `configs/model.yaml`)

- `model: gemini/gemini-3.5-flash-lite` through LiteLLM, the same client class mini-swe-agent uses.
- `temperature`, `top_p`, `thinking_level`, `max_output_tokens` and `seed` are set explicitly.
- Phase 0 checks which of these the endpoint really accepts. Parameters that are dropped or ignored are written down, not assumed.
- The `modelVersion` field of every response is logged, so the pin can be audited afterwards.
- `seed` is passed, but Gemini does not guarantee determinism. That is why the plan uses 3 repeats instead of trusting a single run.

### Cost estimate

Assumptions per task-run: about 50 calls, about 1.5M input tokens in total because context grows each step, and about 100k output tokens including thinking.

| Item | Estimate |
|---|---|
| One task-run | about $0.45 input + $0.25 output, minus implicit caching: **about $0.4 to $0.7** |
| Final evaluation: 2 agents × 3 seeds × 8 tasks = 48 task-runs | **about $20 to $35** |
| Development on the dev tasks | about $15 |
| Contamination probes | under $1 |
| **Hard stop** | Tier 1 spend cap plus a global limit in our own call counter (`MSWEA_GLOBAL_COST_LIMIT` for the baseline) at **$80** |

### Machine

- Windows 11, Docker Desktop 28.0.4 (Linux x86_64 engine), 18 CPUs, 7.5 GiB visible to Docker. Docker's disk image is on C: (102 GB free).
- Each SWE-bench image is about 1.1 to 1.2 GB (checked on Docker Hub for astropy-12907 and django-11790), so the 8 images take about 10 GB.
- **RAM: 8 GB is enough** for 2 agent workers plus 2 harness workers, because each task is one container running one test suite. Raise it to 12 GB in Docker Desktop only if Phase 0 shows OOM kills when running 4 at a time.
- No GPU is needed: the model is behind an API.

---

## 2. Task set (frozen before any model run)

**Pool:** SWE-bench Verified (`princeton-nlp/SWE-bench_Verified`) and its 50-instance Verified Mini subset (`MariusHobbhahn/swe-bench-verified-mini`, revision `b316c349`).

**Finding:** Verified Mini contains only `django` and `sphinx` instances. The anchor instance `astropy__astropy-12907` is in Verified but **not** in Mini.

**Selection rule** (implemented in `src/track3/select_tasks.py`, output committed as `configs/tasks.json`):

1. Keep three anchor instances fixed up front: astropy-12907, django-11790, django-11848.
2. From Verified Mini minus those three, draw 5 instances with `random.Random(42)`, stratified by Verified's `difficulty` label and repo:
   - 2 × sphinx, under 15 minutes
   - 1 × django, under 15 minutes
   - 1 × sphinx, 15 minutes to 1 hour
   - 1 × django, 1 to 4 hours
3. The result is 3 easy, 4 medium and 1 hard task, close to Verified's mix (about 39% easy, 52% medium, 9% hard).

| # | instance_id | Difficulty | F2P | P2P | Source |
|---|---|---|---|---|---|
| 1 | astropy__astropy-12907 | 15 min to 1 h | 2 | 13 | anchor (Verified, not Mini) |
| 2 | django__django-11790 | 15 min to 1 h | 2 | 77 | anchor |
| 3 | django__django-11848 | 15 min to 1 h | 2 | 43 | anchor |
| 4 | sphinx-doc__sphinx-10435 | under 15 min | 1 | 74 | draw |
| 5 | sphinx-doc__sphinx-10323 | under 15 min | 1 | 40 | draw |
| 6 | django__django-12209 | under 15 min | 1 | 0 | draw (no P2P tests, so the regression check is empty; noted) |
| 7 | sphinx-doc__sphinx-7757 | 15 min to 1 h | 1 | 33 | draw |
| 8 | django__django-11885 | 1 to 4 h | 1 | 43 | draw |

F2P = FAIL_TO_PASS tests, P2P = PASS_TO_PASS tests.

These 8 tasks are never added to, substituted or dropped. If one cannot run here, it stays in the totals as "not run", with the reason.

**Dev set (separate from the eval set, to avoid tuning on the test set):**

- 4 more Verified Mini instances, drawn with `random.Random(7)` from the 42 remaining tasks, also stratified.
- All agent iteration happens on the dev set.
- The eval set is used only for the baseline run and the single final run of the frozen agent.
- If I ever look at an eval-set trajectory before the agent is frozen, it is written down in the design doc.

---

## 3. Phase 0: environment and harness sanity checks (day 1)

1. Set up the project: `uv` project with Python 3.12, `uv.lock` committed, and `.gitattributes` with `* text=auto eol=lf` so patches never pick up CRLF.
2. Pull the 8 eval images and 4 dev images, and record each image digest in `configs/images.lock`. Later runs pull by digest, not by `:latest`.
3. **Harness sanity check** (before any model run):
   - Score the **gold patches**: they must resolve 8/8.
   - Score **empty patches**: they must resolve 0/8.
   - Any task that fails this check is flagged as broken in this environment and reported, never silently removed.
4. Model smoke test: one call with every decoding parameter. Record what is accepted, `modelVersion`, token counts, and whether LiteLLM knows the price of `gemini-3.5-flash-lite`. If it does not, register the official price in a committed LiteLLM cost map so the $1 cap actually works for both agents.
5. Run mini-swe-agent on one dev task with a 5-step cap to prove Docker exec works on Windows.
   - Fallback if it does not: run everything inside a pinned Linux runner container with `/var/run/docker.sock` mounted. mini-swe-agent only uses `docker run` and `docker exec`, and the harness uses the Docker SDK, so both work over the socket.

---

## 4. Baseline run (day 1 to 2)

- `mini-extra swebench` from `mini-swe-agent==2.4.6` with its built-in `swebench.yaml`.
- An override file, `configs/baseline_mini.yaml`, changes only:
  - `model.model_name` and `model.model_kwargs` (the pinned decoding parameters and the seed)
  - `agent.step_limit: 100` and `agent.cost_limit: 1.0`
- The prompt, tools and parser are untouched. The override is committed and diffed against the original in the design doc.
- Dataset: a local SWE-bench-format file built from `configs/tasks.json`. It is needed because astropy-12907 is not in Mini, and mini-swe-agent accepts `--subset <path>`.
- One run per seed. Each run writes `runs/baseline/seed{k}/`: trajectories, `preds.json` and the log. Then the harness scores it into `eval/baseline/seed{k}/`.

---

## 5. Agent design ("gated agent")

**Principle:** the only variable is the agent loop. It reuses mini-swe-agent's `LitellmModel` (same client, retries and cost accounting) and its `DockerEnvironment` (same image, same `/testbed`, same `conda activate testbed`). It gets the same input as the baseline: the issue text only. It never sees the hints, `test_patch` or the F2P/P2P test names.

The agent is a bounded state machine, the same pattern as the LangGraph HR assistant: a fixed number of loops, a verifier, and a capped number of revisions. Deterministic code makes the decisions about phases and submission. The model only proposes.

```
SETUP (no LLM) → LOCALIZE → REPRODUCE → EDIT ⇄ VALIDATE (no LLM) → REVISE (≤3) → SUBMIT best candidate
                         ↑__________ loop/stall detector can force a transition __________↑
```

### 5.1 Tools

The model gets clean, typed tools instead of free bash. A `bash` tool is still available for anything else.

- `search(pattern, glob)`: grep/ripgrep with capped output and `path:line` results.
- `find_files(glob)`
- `view(path, start, end)`: numbered lines, at most 200 lines per call.
- `outline(path)`: classes and functions with line ranges, from Python's `ast`.
- `str_replace(path, old, new)`:
  - `old` must match exactly once.
  - Returns the edited region with line numbers.
  - **Python files are `py_compile`d right after the edit. A syntax error rolls the edit back** and the error goes back to the model. This is the first, per-edit layer of build-break recovery.
- `insert(path, line, text)` and `create(path, text)`
- `run_tests(target)`: runs the repository's own runner. Django uses `tests/runtests.py <label>`, while sphinx and astropy use `pytest -x -q <path>`. It has a timeout, and output is cut to head and tail.
- `run_repro()`: runs the reproduction script.
- Path policy: edits to test files, configs and packaging files are refused, matching the baseline prompt's own boundaries.

### 5.2 Phases

1. **SETUP (no LLM).** Detect the test runner. Run an import smoke test of the package. Take a git checkpoint of the clean tree.
2. **LOCALIZE.** Seed candidate files deterministically from paths, symbols and traceback frames named in the issue, plus grep hits. The model then explores with the tools and must return a ranked list of at most 5 `file:symbol` targets with evidence lines. Edits are disabled in this phase, so the agent cannot edit before it has read code.
3. **REPRODUCE.**
   - The model writes `/tmp/repro_issue.py`, outside the repo so it never ends up in the patch.
   - The gate checks that the script **fails on the unpatched code**, with at most 2 attempts.
   - If the bug cannot be reproduced, the agent goes on with a flag, and validation then relies on the existing tests only.
4. **EDIT.** Edits are allowed only inside the localised files. Opening another file needs an explicit `expand_scope` call with a reason, which is logged.
5. **VALIDATE (no LLM, runs real tests and never trusts the model's claim).** Gates are checked in order:
   - **G0 build:** `py_compile` on the changed files, plus importing the top-level package.
   - **G1 repro:** the repro script now passes. Skipped if REPRODUCE failed.
   - **G2 regression:** select the relevant existing tests. These are the test modules that import or live next to the changed modules, capped at N files and T seconds. The agent ran them on the clean checkpoint in SETUP or LOCALIZE. Any test that passed before and fails now is a regression.
   - **G3 hygiene:** the diff is non-empty and contains only source files. No test, repro or helper files, and no whitespace-only changes.
6. **REVISE.** On a gate failure, the model gets a structured report: which gate failed, the failing test IDs, and the tail of the traceback. It returns to EDIT. At most **3 revision rounds**.
7. **SUBMIT.**
   - The patch submitted is the **best candidate**, the one that passed the most gates, with fewer changed lines breaking ties.
   - Candidates are ranked by the gates in code, not by what the model says.
   - If no candidate passes all gates, the best partial one is submitted and marked `validated: false` in the run log.
   - An empty patch is never submitted while a candidate exists.

### 5.3 Recovery

- **Build break:** each candidate is a git snapshot (`git diff > candidates/n.patch`). If a revision fails G0, the tree is reset to the last candidate that passed G0, and the model is told what was reverted.
- **Loop detection:**
  - Hash each `(tool, normalised args)` pair and each observation.
  - If the same action or observation comes back 3 times, or there are 8 steps without a new file viewed or a new edit, inject a "you are repeating X, change strategy" message.
  - The second trigger forces a phase change: LOCALIZE moves to EDIT, and EDIT moves to VALIDATE using the best candidate.
- **Budget awareness:** the remaining calls and cost are shown to the model. Below 15% remaining, the agent jumps straight to VALIDATE and SUBMIT, so it never times out with an unvalidated patch while a better one exists.
- **Malformed output:** a tool call that fails to parse gets one corrective retry. A second failure counts as one stall step.

### 5.4 Ablations

These are optional and cost-gated, with 1 seed on the eval set after the freeze:

- The gated agent without VALIDATE and REVISE, to see how much of the lift comes from the verifier.
- The gated agent with free bash only, to see how much comes from the tools.

They run only if the budget allows. They are reported as extra evidence, not as the headline number.

### 5.5 Freezing

Before the final run:

1. The agent code is tagged `agent-v1`.
2. The final eval run records the git SHA.
3. No changes after the tag. Any later fix produces a new tag and a full rerun of both agents' reports with an explanation.

---

## 6. Contamination check (both agents, every task and seed)

Every task date is 2017 to 2022, well before the model's training cutoff, so memorisation is plausible for all 8 tasks.

| Signal | How | Flag when |
|---|---|---|
| Gold similarity of the **first** edit and of the final patch | Normalise both diffs (strip whitespace and comments), then compute changed-line overlap with the gold patch plus a `difflib` ratio | Overlap ≥ 0.8, or an exact match of a non-trivial line (over 20 characters) that is not in the issue text |
| Edit before reading | From the trajectory: was the first edit to file F made before any `view`, `cat` or `sed` of F? | Yes. For the baseline it is checked from the bash commands, since its edits are not structured. |
| Steps to first edit | Count of calls before the first edit | Far below the median, together with high gold similarity |
| Zero-context probe | Same model and decoding, no repo access: (a) give only the `instance_id` and ask what the fix was; (b) give the issue text and ask for the patch, or the file and function to change | The probe patch has high gold similarity, or names the exact file and function |

**Report:**

- `results/contamination.md` lists the evidence per task.
- The headline lift is given **on all 8 tasks and on the unflagged subset**, for example: "lift +X on 8; +Y on the N tasks with no memorisation signal".
- The thresholds are fixed now, before any run. Each flag is checked by hand against the trajectory, and the final call (memorised or not) comes with a one-line reason.

---

## 7. Evaluation, numbers and statistics

The harness is `python -m swebench.harness.run_evaluation` with `swebench==5.0.2`, run with `--run_id {agent}-seed{k}` and 2 workers.

- **Per task:** resolved count out of 3 seeds for each agent, plus F2P and P2P pass counts and the cost, calls and wall-clock time of each run.
- **Overall:**
  - % resolved for each seed, then the mean and min/max over the 3 seeds
  - pass@1, the mean over seeds
  - pass@3, solved by at least one seed
  - **lift**, the agent's mean minus the baseline's mean in percentage points
- **Paired comparison:** a per-task, per-seed win/tie/loss table, plus an exact sign or permutation test over the 24 pairs. With n = 8 this is a small sample, so the result is evidence and not proof.
- **Evidence committed:**
  - each agent's diffs (`preds.jsonl` and one `.diff` per task)
  - harness `report.json` and `test_output.txt` for every instance, run and seed
  - full agent trajectories, gzipped JSONL if they get large

---

## 8. One command per run (versions and seeds pinned)

```bash
uv run track3 baseline --seeds 0,1,2   # mini-swe-agent 2.4.6 → runs/baseline/ → harness → eval/baseline/
uv run track3 agent    --seeds 0,1,2   # gated agent @ agent-v1 → runs/agent/ → harness → eval/agent/
uv run track3 report                    # results/per_task.csv, results/summary.md, results/contamination.md
uv run track3 all      --seeds 0,1,2   # all three steps in order
```

- **Configurable endpoint:** `MODEL_NAME`, `API_BASE` and `GEMINI_API_KEY` come from `.env` (gitignored), with `.env.example` committed. Any LiteLLM-compatible endpoint works.
- **Auditing without an API key:**
  - `uv run track3 eval --from-preds` rescores the committed predictions with the harness.
  - `uv run track3 report` rebuilds every number from committed files only.
- **Pinned:** `uv.lock` (mini-swe-agent, swebench, litellm and the rest), image digests, `configs/tasks.json`, `configs/model.yaml`, seeds and budget.

---

## 9. Repo layout

```
README.md              question, exact commands, headline table, time spent and scope cuts
PLAN.md                this file
AI_USAGE.md            index of AI sessions: tool, model, purpose, what was changed or rejected, gaps
docs/design-track3.md  what was built, why, architecture, trade-offs, what did not work, limitations, next steps
configs/               tasks.json, images.lock, model.yaml, budget.yaml, baseline_mini.yaml, litellm_cost_map.json
src/track3/            cli.py, select_tasks.py, dataset.py, run_baseline.py, evaluate.py, contamination.py, report.py
src/track3/agent/      loop.py (state machine), tools.py, validate.py, recovery.py, loopguard.py, prompts/
tests/                 unit tests: tools, path policy, loop detector, gate ranking, report math, contamination metrics
runs/{baseline,agent}/seed{0,1,2}/   trajectories, preds, run logs (model under test)
eval/{baseline,agent}/seed{0,1,2}/   harness reports and test output
results/               per_task.csv, summary.md, contamination.md
.env.example  pyproject.toml  uv.lock  .python-version  .gitattributes  .gitignore
```

---

## 10. AI transcripts

- **This session.** The raw Claude Code transcript is the `.jsonl` file under `~/.claude/projects/<dir>/`. It is exported to a local, git-ignored `ai-logs/` folder and is available on request; it is not committed. Sub-sessions and later sessions each get their own file.
- **Redaction.** `scripts/export_ai_logs.py` scans each log for API keys (`AIza…`, `sk-…`, `gh[opsu]_…`, bearer tokens), credentials and personal data such as email addresses. It replaces each match with `[REDACTED]` and prints a count per pattern. The diff is checked by hand. No other edits are made.
- **AI_USAGE.md** lists, for each session: date, tool (Claude Code desktop), model (Claude Opus 5.5), purpose, and what was accepted, changed or rejected.
- **Gap to state.** Earlier exploratory sessions, which also covered unrelated private projects, are not included; AI_USAGE.md says so.
- **Benchmark logs.** The trajectories of the model under test (section 7) are separate from the AI logs and live in `runs/`.

---

## 11. Timeline (about 1 week)

| Day | Work |
|---|---|
| 1 | Phase 0 (env, images, gold and empty sanity checks, model smoke test); run `select_tasks.py`; start the baseline |
| 2 | Baseline 3 seeds plus harness. Baseline on the dev set for a failure-mode analysis. |
| 3–4 | Build the gated agent with unit tests; iterate on the dev set only |
| 5 | Freeze `agent-v1`; final 3-seed run on the eval set; harness |
| 6 | Contamination analysis; ablations if the budget allows; report |
| 7 | Design doc, README, AI_USAGE.md, review. Push only when the user says so. |

## 12. Risks and fallbacks

| Risk | Mitigation |
|---|---|
| SWE-bench harness or mini-swe-agent misbehaves on Windows | Phase 0 catches it. Fallback: the Linux runner container with the Docker socket mounted (section 3). |
| Gemini ignores `seed` or `temperature` | Write it down. The 3 repeats carry the variance estimate. |
| The model is too weak (baseline 0/8, broken tool calls) | Decide on the dev set before any eval run. If the model must change, it changes for **both** agents and the reason is logged. |
| LiteLLM has no price for the model | Committed cost map, checked in Phase 0 |
| A task cannot run (image or test breakage) | Shown as "not run" with the reason, kept in the totals |
| The design overfits the 8 eval tasks | Separate dev set, frozen tag, one final run |
| Committed logs get too large | gzip trajectories and keep the full harness output |
