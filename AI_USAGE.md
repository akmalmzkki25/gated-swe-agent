# AI usage

This study was built with **Claude Code** (desktop app, Code tab), model **Claude Opus 5.5** (`claude-opus-5-5`).

- **Where the transcripts are:** the raw transcripts (JSONL, including every tool call and its output) are **not stored in this repository**. They are available on request.
- **How they were exported:** `scripts/export_ai_logs.py` writes them to a local `ai-logs/` folder, which is git-ignored. It replaces e-mail addresses and any API keys or tokens with `[REDACTED]`, and changes nothing else.
- **Not the same as the benchmark logs:** the logs of the model *under test* (Gemini) are benchmark evidence and are committed in `runs/` and `eval/`.

## Sessions

| Transcript | Date | Tool / model | Used for |
|---|---|---|---|
| `2026-11-06_claude-code_track3.jsonl` | 2026-11-06 → 2026-11-09 | Claude Code, `claude-opus-5-5` | Everything in this repo: framing the question, planning, environment checks, task selection, building the harness wrappers and the gated agent (test-first), running the baseline and agent, the failure and contamination analysis, the docs |
| `2026-11-08_claude-code_track3_subagent-dev-failure-analysis.jsonl` | 2026-11-08 | Claude Code subagent (general-purpose), `claude-opus-5-5` | Read the reference agent's failed dev_hard trajectories and classified why they failed (`docs/dev-failure-analysis.md`). It was told not to read any eval data. |

**Gap:** the question was scoped in an earlier exploratory Claude Code session that also covered unrelated private projects, and that session is not included. The brief it produced is the first message of the main transcript.

## What I steered, changed or rejected

**Decisions I made:**
- Plan approved before any code was written.
- Model, reference agent, task selection rule, seeds and budget: confirmed one by one.
- Stopping the baseline mid-run and resuming it later.
- Adding a harder dev split after the reference scored 12/12 on dev. The eval set was left unchanged.
- Freezing the agent and running eval once.
- **Reporting `agent-v1` as final after it lost on eval**, instead of tuning a v2 against the eval result.
- Committing only when I asked.

**Where I overruled the AI:** when Docker Desktop crashed, the AI killed its processes and began relaunching it. I interrupted and restarted Docker myself.

**AI mistakes caught during the work, mostly by the tests and sanity checks the AI wrote first.** All are described in `docs/phase0.md` and `docs/design-track3.md`:
- running the SWE-bench harness natively on Windows (CRLF made gold patches fail);
- a scoring script that dropped empty patches from the denominator;
- a reproduction gate that accepted setup errors, and that the model under test could bypass by rewriting the script;
- test selection that picked non-test files;
- several git and bytecode edge cases in the agent's workspace;
- a contamination heuristic that flagged edits to scratch files.

**Judgement calls the AI made that I accepted:**
- treating every eval look-up before the freeze as exposure, and logging it (`docs/phase0.md`);
- keeping the reference agent unmodified apart from model, seed and budget;
- reporting the negative eval lift as the headline.
