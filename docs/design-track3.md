# Design: a verifier-gated SWE agent vs mini-swe-agent

## Result first

| | mini-swe-agent 2.4.6 (reference) | gated agent (`agent-v1`) |
|---|---|---|
| Eval pass@1 (8 tasks × 3 seeds) | **79.2%** | **66.7%** |
| Eval pass@3 | 100% | 75% |
| **Lift** | | **−12.5 pts** (1 win, 4 losses, 19 ties; sign test p = 0.375) |
| dev_hard pass@1 (development, not frozen) | 37.5% | 58.3% (+20.8 pts; 5 wins, 0 losses) |

**The agent did not beat the reference on the eval set.** It did beat it clearly on harder development tasks, where the reference fails for reasons this design targets. Both results are reported. The eval number is the headline, because it comes from the frozen agent run once.

## What was built

- **One runner for both agents.** A Linux runner container (`docker/runner.Dockerfile`, `compose.yaml`) runs both agents and the SWE-bench harness 5.0.2. It talks to the host Docker engine through the socket. Running the harness natively on Windows scored gold patches 0/2, because it writes `eval.sh` with CRLF; this is why everything goes through the runner.
- **Baseline.** mini-swe-agent 2.4.6 with its own `swebench.yaml`. The override sets only the model, the seed and the budget.
- **Gated agent** (`src/track3/agent/`):
  - **State machine:** `LOCALIZE → REPRODUCE → EDIT ⇄ VALIDATE → SUBMIT`. The model proposes actions; code decides phase changes, budget and what gets submitted.
  - **Same model client and container as the baseline.** The client is a subclass of mini-swe-agent's `LitellmModel`, so retries, cost accounting and decoding parameters are identical; only the tool list differs. The container comes from mini-swe-agent's `get_sb_environment`. Budget counting copies `DefaultAgent`: 100 model calls, $1.
  - **Typed tools:** `view`, `search`, `find_files`, `outline`, `replace` (exactly one match), `insert`, `create`, `run_repro`, `run_tests`, `submit`, plus `bash`.
    - Every edit to a `.py` file is compiled with the repository's own Python and rolled back if it does not compile.
    - Edits to test and packaging files are refused.
    - Edits outside the reported location need `expand_scope`.
  - **Gates** (run in code, never taken from the model's word):
    - **build:** the changed files compile.
    - **repro:** the agent's own reproduction script must fail with an `AssertionError` before the edit and pass after it. The accepted script is stored by the agent and rewritten before each run, so `/tmp` cannot be edited to cheat.
    - **regression:** related existing tests that passed on the clean checkout must still pass. Tests are selected per repository by module name and imports, and parsed with SWE-bench's own log parsers.
    - **hygiene:** the diff is non-empty, not whitespace-only, and touches no test or config files.
  - **Recovery:**
    - Up to 3 revision rounds, each with the failing gate's report.
    - Reset to the last candidate that compiled if a revision breaks the build.
    - A loop and stall guard: a warning first, then a forced phase change.
    - At less than 15% budget left, the agent validates and submits.
    - The best candidate by gates passed is always submitted, even after an error. mini-swe-agent submits an empty patch when it runs out of budget.
- **Evaluation:**
  - **Pinned:** tasks (seeded, stratified, `select_tasks.py`), images by digest, dependencies in `uv.lock`, decoding parameters checked live (`configs/model_smoke.json`).
  - **Harness sanity before any model run:** gold patches 8/8 and a null patch 0/8 on every split.
  - **Scoring:** every predicted instance counts in the denominator. Empty patches are unresolved, with the reason in `unscored.json`.
  - **Contamination check:** overlap with the gold patch, edit-before-read, and zero-context probes (`results/contamination.md`).

## Why this design

The reference agent is a single loop that trusts the model to decide when it is done. The bet: a loop that **requires measured evidence** (a failing-then-passing reproduction, plus related tests that still pass) would turn more of the reference's plausible-but-wrong patches into correct ones, at the same budget. This applies harness/loop work I had done earlier: a bounded loop, a verifier and a capped number of revisions.

The dev failure analysis (`docs/dev-failure-analysis.md`) supported part of this bet. On dev_hard, the reference never ran the issue's example end to end in most of its failures. Requiring a reproduction fixed two of those tasks (sphinx-8551 0/3 → 3/3, sphinx-7985 0/3 → 2/3).

## Why it lost on eval

1. **The regression gate cannot tell a regression from an intended change** (sphinx-10435). The correct fix changes LaTeX output, and an existing test asserts the old output. The gate rejected the right fix 3 times, and the agent moved its edit to a `.sty` file that no test checks. The dev analysis had flagged the same pattern in django-12325, but no dev task exercised it hard enough to show the damage.
2. **Gates check only what the agent's own reproduction checks** (django-11848). The agent's `datetime.now()` fix passes its own script. The hidden tests mock `utcnow()`, which the reference chose in all 3 runs.
3. **Ceiling effect.** The reference already resolves 79% of eval runs and solves every eval task at least once. The headroom is 5 runs out of 24. Any cost of the extra structure (more steps spent on reproduction and validation, an occasional wrong gate decision) shows up directly as a loss.

With 8 tasks, neither direction is statistically clear (p = 0.375 on eval, p = 0.062 on dev_hard).

## Trade-offs and choices

- **Same budget, different stopping rule.** Both agents get 100 calls and $1. When the budget runs out, the gated agent submits its best gated candidate, while the reference submits nothing. No eval run hit the limit, so this did not affect the result.
- **All tools are declared on every call; phases are enforced in the dispatcher.** This avoids the API rejecting earlier tool calls to undeclared tools and keeps the prompt prefix cacheable.
- **Development data.** The dev set (4 tasks) was too easy: the reference scored 12/12. A harder dev set (8 tasks, seeded draw, eval untouched) was added with the user's approval. Every agent change was driven by dev and dev_hard runs only. What I saw of the eval set before the freeze is logged in `docs/phase0.md`: task metadata, test command lines and baseline pass/fail. The eval trajectories were read only after the frozen run.
- **Model choice.** `gemini-3.5-flash-lite` was chosen for cost, and in the expectation that it would leave headroom. It turned out stronger on Verified Mini than expected (79% on eval), which shrank the room for any lift.

## What did not work, or broke along the way

All of these were found and fixed before the freeze, each with a test:

- Running the harness on Windows (CRLF).
- litellm needing its `mcp` extra for any call with tools.
- `git stash -u` failing to pop after test runs, and `git apply --intent-to-add` wiping the index on the git versions in these images.
- Stale `.pyc` files after same-size edits.
- The reproduction gate first accepting setup errors, and the model rewriting `/tmp/repro_issue.py` to pass it.
- The regression gate picking non-test modules.
- A `create` into a missing directory crashing a whole run.
- The scoring script dropping empty patches from the denominator.

## Known limitations

- 8 eval tasks and 3 seeds are too few to separate a ±12-point difference from noise.
- The regression gate penalises intended behaviour changes (the main known flaw).
- The reproduction gate can only check what the model thinks the issue asks for. It cannot catch fixes that are correct for the issue text but not for the hidden tests (`now` vs `utcnow`; output formats).
- Gemini does not guarantee determinism even with `seed`. A seed reproduced exactly in the smoke test, but long runs may still differ.
- The only model id that can be pinned is `gemini-3.5-flash-lite`; it has no dated snapshot. Every call logs the reported model version.

## Next steps (not done; any of them would be post hoc for this eval set)

1. **Make the regression gate advisory when a reproduction exists.** Show the "regressions" to the model as evidence and let it argue that a failing test encodes the old behaviour, instead of rejecting the candidate. Measure this on dev_hard first.
2. **Ask the reproduction for edge cases the issue implies** (time zones, output format), and run several reproduction variants.
3. **Use more tasks**: the full 50-task Verified Mini minus the dev tasks, with 5 seeds. That gives enough pairs to see a ±10-point effect.
4. **Ablations** with 1 seed each: no regression gate, and no reproduction gate. They show which gate carries the dev_hard lift and which one causes the eval loss.
