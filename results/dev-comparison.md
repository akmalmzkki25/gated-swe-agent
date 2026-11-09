# Gated agent vs baseline on the dev splits (development only, not the reported result)

- Model, decoding, budget (100 calls / $1) and seeds 0–2 are the same for both agents.
- Both are scored by the same harness in the same runner.
- The agent code was still changing during these runs (`agent_version: no-commit+dirty`). These are development numbers; the reported comparison is the eval run of the frozen agent.

## dev (4 tasks)

Baseline 12/12, agent 12/12. No difference: these tasks are too easy for this model to show any.

## dev_hard (8 tasks)

| Task | Baseline | Gated agent |
|---|---|---|
| django__django-12050 | ✔✔✔ | ✔✔✔ |
| django__django-12325 | ✘✘✘ | ✘✘✘ |
| django__django-12708 | ✔✔✔ | ✔✔✔ * |
| django__django-12774 | ✔✔✔ | ✔✔✔ |
| sphinx-doc__sphinx-7985 | ✘✘✘ | ✔✔✘ |
| sphinx-doc__sphinx-8551 | ✘✘✘ | ✔✔✔ |
| sphinx-doc__sphinx-9229 | ✘✘✘ | ✘✘✘ |
| sphinx-doc__sphinx-9461 | ✘✘✘ | ✘✘✘ |
| **Resolved (pass@1)** | **9/24 = 37.5%** | **14/24 = 58.3%** |
| Cost | $2.67 | $2.44 |

\* **Seed 2 of django-12708** first crashed: `create` into a directory that did not exist raised an `OSError`, the error was not caught, and the run ended with an empty patch. The bug was fixed and tested:
- `create` only adds files to existing packages.
- A tool error goes back to the model as an observation.
- An unexpected error still submits the best candidate.

The run was then repeated with the fixed code and resolved. The crashed trajectory is kept in `runs/agent/dev_hard/_crashed/`. With the crash counted as a failure, the agent's score is 13/24.

## Where the lift comes from

- **sphinx-8551 and sphinx-7985:** the baseline failed every seed. The dev failure analysis (`docs/dev-failure-analysis.md`) classified them as a misunderstood lookup and an incomplete or ordering fix, and the baseline never ran the issue's example end to end. The agent must first get a reproduction script to fail with an AssertionError, then make it pass. That forces the end-to-end check.
- **Still unsolved** (12325, 9229, 9461): the hidden tests expect more than the issue states, or the issue's example does not reproduce on this Python version. This matches the analysis.
