# Phase 0 findings (2026-11-06)

Environment checks done before any benchmark run. See PLAN.md section 3.

## Pinned versions

| Item | Pin |
|---|---|
| Python | 3.12 (`.python-version`), deps in `uv.lock` |
| mini-swe-agent | 2.4.6 |
| swebench (harness) | 5.0.2 |
| litellm | 1.108.1 (pulled in by mini-swe-agent; locked) |
| Dataset | `SWE-bench/SWE-bench_Verified` @ `78f471bf655a3137b2e8a75af1501690ec009ec3`; Mini pool `MariusHobbhahn/swe-bench-verified-mini` @ `b316c349947c29963fce3f4a65967c9807a4b673` |
| Images | by digest, `configs/images.lock` |
| Docker | Desktop 28.0.4, Linux x86_64 engine, 18 CPUs, 7.5 GiB |

## Deviations from PLAN.md

1. **Dataset source.** swebench 5 needs the new dataset schema, where each row carries its own `image`, `eval_script`, `log_parser` and `eval_type`. `princeton-nlp/SWE-bench_Verified` does not have these columns, so the source is now `SWE-bench/SWE-bench_Verified`. For all 12 tasks, `patch`, `test_patch`, `problem_statement`, `base_commit`, `FAIL_TO_PASS` and `PASS_TO_PASS` were compared field by field with the princeton copy and are identical.
2. **Dev set.** The draw is `random.Random(7)` over Mini minus eval, one task per cell (easy/medium × django/sphinx). Result: `django__django-12304`, `sphinx-doc__sphinx-8721`, `django__django-12262`, `sphinx-doc__sphinx-10466`.
3. **Wall-clock cap.** mini-swe-agent has no per-task wall-clock limit, only its container's `environment.container_timeout` (default 2 h). Imposing a shorter cap on the baseline would mean changing its config beyond model and budget. So 2 h is a safety net for both agents, and the binding budget is 100 model calls and $1.00 per task, enforced by the same `LitellmModel` accounting.
4. **`drop_params` and `parallel_tool_calls`.** These stay `true`, as in mini's own `swebench.yaml`, so the baseline's model call is unchanged. The gated agent uses the same values. The smoke test runs with `drop_params: false` to prove nothing is being dropped silently.

## Model smoke test (`configs/model_smoke.json`)

- Model `gemini/gemini-3.5-flash-lite` with `temperature=1.0`, `top_p=0.95`, `max_tokens=16384`, `reasoning_effort=low` and `seed`. **All of these are accepted** with `drop_params: false`.
- Gemini reports `modelVersion = gemini-3.5-flash-lite`. That alias is the finest pin the API exposes: there is no dated snapshot. Every call's reported version is logged in the run artifacts, so a silent model change would show up.
- **Seed:** `seed=0` gave identical output (46 reasoning tokens, same text) in two separate smoke runs. `seed=1` and no seed gave different reasoning lengths. So seeding has an effect on this endpoint, but Google does not guarantee determinism, and the 3-seed design still stands.
- **Thinking:** without `reasoning_effort` this model does not think at all (1 output token). With `low` it uses about 40–80 reasoning tokens on a trivial prompt. `low` is the pinned setting.
- **Pricing:** LiteLLM 1.108.1 already lists the official price ($0.30 / $2.50 per 1M tokens, cached input $0.03), so no custom cost map is needed and the $1 cap works.
- Cost of the smoke test: under $0.002.

## Harness on Windows: CRLF breaks grading, so everything now runs in a Linux runner

The first gold-patch probe on the two pulled images (astropy-12907, django-11790) resolved **0/2**. The cause is in the harness, not in the patches:

- swebench 5.0.2 writes the instance's `eval.sh` and `patch.diff` with `Path.write_text` (`run_evaluation.py` lines 291 and 360).
- On Windows, that turns `\n` into `\r\n`.
- Inside the Linux task container, the script then runs `conda activate $'testbed\r'`, which fails. Django is not importable, `git checkout ...test_forms.py\r` fails, and every test is reported failed.
- The astropy gold patch did not apply with `git apply` for the same reason.

**Decision:** this is PLAN.md's fallback. Both agents and the harness run inside one Linux runner container:

- Defined by `docker/runner.Dockerfile` and `compose.yaml`.
- The runner talks to the host engine through `/var/run/docker.sock`.
- No harness or mini-swe-agent code is changed.
- Anyone reproducing the results gets the same environment, whatever their OS.

**Confirmed:** the same gold probe, run inside the runner on the 4 images pulled by then (astropy-12907, django-11790, django-11848, sphinx-10435), resolved **4/4**. Logs are in `logs/run_evaluation/probe-gold-runner/`. The full gold and null check on all 8 tasks runs once every image is pulled.

A native Windows run of the harness would have silently scored real fixes as failures. That is exactly what the gold/null sanity check exists to catch.

## Harness sanity (passed, 2026-11-08)

Run inside the Linux runner, with images referenced by digest. Outputs are in `eval/sanity/`.

| Split | Gold patches resolved | Null patch resolved | Missing reports |
|---|---|---|---|
| eval (8) | **8/8** | **0/8** | 0 |
| dev (4) | **4/4** | **0/4** | 0 |

The null patch only adds an unrelated file, so it applies and the full test run happens. That shows the harness does not pass a task on its own. Every task is runnable in this environment, so no task has to be reported as "not run".

## litellm needs its `mcp` extra for tool calls

The first mini-swe-agent smoke run (dev task django-12304, 5-step cap) stopped on its first model call with `ModuleNotFoundError: No module named 'mcp'`.

- **Cause:** `litellm.completion()` 1.108.1 imports its MCP handler whenever `tools=` is passed (`litellm/main.py` around line 5297), and that handler needs the optional `mcp` package.
- **Why the model smoke test missed it:** it sent no tools.
- **Scope:** this breaks both agents, because both send tools.
- **Fix:** depend on `litellm[mcp]==1.108.1`. The version stays the same; only the extra is added.
- **Rejected alternative:** passing `_skip_mcp_handler=True` in the model kwargs. It was not used because it would change the baseline's model call.
- **Verified:** a tool-calling request now returns a `bash` tool call.

## Smoke runs on dev task django-12304 (seed 0)

- **mini-swe-agent**, built-in config, step limit 5: ran 5 calls for $0.0053 and stopped with `LimitsExceeded`. Its commands were sensible (`git grep`, reading `enums.py`, `./tests/runtests.py model_enums`) and ran inside the task container. Early calls cost far less than the PLAN.md estimate.
- **Gated agent**, budget cut to 30 calls / $0.30 for the smoke run only. The first run worked end to end (25 calls, $0.044) but showed three problems, all fixed and covered by tests before the next run:
  1. **Broken reproduction accepted.** The script failed with `ImproperlyConfigured` (no template backend). That is a setup error, not the bug. Repros are now accepted only if they fail with an `AssertionError`.
  2. **The model gamed the repro gate.** After its accepted script kept failing, it overwrote `/tmp/repro_issue.py` through `bash`, and validation ran the new script. The accepted script is now kept by the agent and rewritten before every run and every validation.
  3. **The regression gate picked non-test files** under `tests/` (`models.py`, migrations), so it was skipped. Only real test modules are runnable targets now, and the module's own name (`enums`) outweighs generic path words (`db`, `models`), so `model_enums.tests` ranks first.
- **Final dev smoke:** 20 calls, $0.036, all four gates passed. The repro was accepted on an AssertionError, and the regression gate ran `model_enums.tests` plus 3 others: 82 tests passed, none broke. The submitted patch sets `cls.do_not_call_in_templates = True` in `ChoicesMeta.__new__`.
- **Bugs caught by the loop tests before any API spend:**
  - `git stash -u` cannot be popped after a test run recreates `__pycache__`.
  - `git apply --intent-to-add` empties the index in these git versions.
  - Same-size edits within one second ran stale `.pyc` files.

## Dev set extended: `dev_hard` (2026-11-08, after the baseline)

The baseline resolved all 12 dev runs (4 tasks × 3 seeds), so the dev set showed no failures to design against. The user approved adding harder dev tasks. **The eval set is unchanged** (same 8 IDs, same order).

- **Rule** (in `select_tasks.py`, recorded in `configs/tasks.json` under `rule.dev_hard`): `random.Random(11)` draws from Verified Mini minus eval and dev.
  - 2 django and 2 sphinx with the "1-4 hours" label
  - 2 django and 2 sphinx with the "15 min - 1 hour" label
- **Draw:** django-12708, django-12325, sphinx-9461, sphinx-9229 (1–4 h); django-12774, django-12050, sphinx-7985, sphinx-8551 (15 min–1 h).
- **Next:** the same harness sanity (gold/null) runs on these tasks, then the baseline with 3 seeds. Their failures are what the agent is tuned against.

## Eval-set exposure log

Things I (the designer, not the agent) saw about the 8 eval tasks before the agent was frozen. The agent itself never receives `eval_script`, `test_patch`, hints or FAIL_TO_PASS/PASS_TO_PASS.

| Date | What was seen | Why | Effect on design |
|---|---|---|---|
| 2026-11-06 | F2P and P2P counts, difficulty labels | task selection (section 2 of PLAN.md) | none; selection is a seeded draw |
| 2026-11-08 | Baseline resolved/unresolved per eval task and seed, with call counts and costs (`results/baseline.md`) | reporting the baseline | none yet; eval trajectories have not been read |
| 2026-11-08 | Each eval task's test command line from `eval_script`, which names the relevant test module (e.g. `auth_tests.test_forms`, `tests/test_build_latex.py`) | checking how the harness invokes django/pytest/tox, to reuse its log parsers | Test selection for the regression gate is written as a generic per-repo rule (module path to test module), not tuned per task, and it is evaluated on the dev set only |

## Images

- Download bandwidth is about 0.7 MB/s.
- The astropy image is 4.16 GB unpacked and took about 30 minutes. Later images share base layers.
- **Remaining download (2026-11-08)**, from registry manifests:
  - About **3.3 GB** of compressed layers that are not on disk yet.
  - Breakdown: django-11848 1.12 GB (a different env layer), each sphinx image about 0.44 GB, each other django image about 0.09 GB.
  - Measured bandwidth has varied from 0.09 to 0.7 MB/s, with DNS and TLS dropouts.
- **Incident, 2026-11-07.** The Docker Desktop engine went down mid-pull, during the django-11790 pull.
  - On restart it showed an error dialog: it could not remove a stale `Docker/run/userAnalyticsOtlpHttp.sock`.
  - Fix: quit Docker Desktop, delete the stale socket file, start it again. "Reset to factory defaults" was avoided because it would wipe the pulled images.
  - The astropy image and its lock entry survived.
  - `images.py` now retries each pull 4 times with backoff and reports Docker's stderr.

_Pending: digests, harness sanity (gold, null), mini-swe-agent smoke run._
