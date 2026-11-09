"""The gated agent: a bounded state machine around the model.

LOCALIZE -> REPRODUCE -> EDIT <-> VALIDATE (no model call) -> at most N revisions -> SUBMIT.
The model proposes actions; code decides phases, enforces the budget, runs the gates and picks
the submitted patch. Budget accounting mirrors mini-swe-agent's DefaultAgent: one call is
counted per model query, and its cost is added from the same LiteLLM cost calculation.
"""

from __future__ import annotations

import hashlib
import re
import shlex
import time
from dataclasses import dataclass, field

from minisweagent.exceptions import FormatError

from track3.agent import prompts, testsel
from track3.agent.candidates import Candidate, best_candidate
from track3.agent.loopguard import FORCE, OK, WARN, LoopGuard, action_key
from track3.agent.policy import edit_refusal, normalize_repo_path
from track3.agent.text_tools import outline
from track3.agent.tools import ALL_TOOLS, EDIT, LOCALIZE, PHASE_TOOLS, REPRODUCE
from track3.agent.validate import REPRO_PATH, REPRO_TIMEOUT, Validator, restore_patch
from track3.agent.workspace import Workspace

DONE = "done"
# The last line of a Python traceback names the exception; only an assertion counts as the bug.
_ASSERTION = re.compile(r"^AssertionError\b", re.M)


@dataclass
class AgentConfig:
    step_limit: int = 100
    cost_limit: float = 1.0
    max_revisions: int = 3
    max_repro_attempts: int = 2
    low_budget_fraction: float = 0.15
    repeat_limit: int = 3
    stall_limit: int = 8
    test_timeout: int = 900
    bash_timeout: int = 60
    observation_chars: int = 10_000  # same truncation threshold as mini-swe-agent's swebench config


@dataclass
class Step:
    observation: str
    progressed: bool = False
    transition: str | None = None


@dataclass
class AgentResult:
    submission: str
    exit_status: str
    n_calls: int
    cost: float
    candidates: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n... [{len(text) - limit} characters elided; narrow your command] ...\n{text[-half:]}"


class GatedAgent:
    def __init__(self, model, env, repo: str, config: AgentConfig | None = None):
        self.model = model
        self.model.tools = ALL_TOOLS
        self.ws = Workspace(env)
        self.repo = repo
        self.cfg = config or AgentConfig()
        self.guard = LoopGuard(self.cfg.repeat_limit, self.cfg.stall_limit)
        self.phase = LOCALIZE
        self.messages: list[dict] = []
        self.events: list[dict] = []
        self.candidates: list[Candidate] = []
        self.candidate_details: list[dict] = []
        self.scope: set[str] = set()
        self.repro_state = "none"  # none | accepted | skipped
        self.repro_script: str | None = None  # the accepted script, kept here so later edits to /tmp do not count
        self.repro_attempts = 0
        self.revisions = 0
        self.n_calls = 0
        self.cost = 0.0
        self.validator: Validator | None = None
        self._diff_hash = ""

    # ---- bookkeeping --------------------------------------------------------------------
    def log(self, kind: str, **data) -> None:
        self.events.append({"t": time.time(), "event": kind, "phase": self.phase, "n_calls": self.n_calls, **data})

    def _budget_left(self) -> tuple[int, float]:
        return self.cfg.step_limit - self.n_calls, self.cfg.cost_limit - self.cost

    def _exhausted(self) -> bool:
        calls, cost = self._budget_left()
        return calls <= 0 or cost <= 0

    def _low_budget(self) -> bool:
        calls, cost = self._budget_left()
        f = self.cfg.low_budget_fraction
        return calls < f * self.cfg.step_limit or cost < f * self.cfg.cost_limit

    def _user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    # ---- main loop ----------------------------------------------------------------------
    def run(self, problem_statement: str) -> AgentResult:
        self._setup()
        self.messages = [
            {"role": "system", "content": prompts.SYSTEM},
            {"role": "user", "content": prompts.INSTANCE.format(problem_statement=problem_statement)},
        ]
        status = "budget_exhausted"
        try:
            while not self._exhausted():
                if self._low_budget() and self._has_diff():
                    self._user(prompts.LOW_BUDGET)
                    self.log("low_budget_submit")
                    self._validate()
                    status = "low_budget_submit"
                    break
                if self._turn() == DONE:
                    status = "submitted"
                    break
        except Exception as e:  # never lose the work done so far: fall through to submit the best candidate
            status = f"error: {type(e).__name__}: {str(e)[:300]}"
            self.log("error", error=status)
        return self._finish(status)

    def _setup(self) -> None:
        _, files = self.ws.run("git ls-files '*.py'", timeout=120)
        tests = [f for f in files.splitlines() if (r := edit_refusal(f)) and "test files" in r]
        self.validator = Validator(self.ws, self.repo, tests, self.cfg.test_timeout)
        self.log("setup", n_test_files=len(tests))

    def _turn(self) -> str | None:
        try:
            message = self.model.query(self.messages)
        except FormatError as e:
            self.n_calls += 1
            self.cost += e.messages[0].get("extra", {}).get("cost", 0.0)
            self.messages.extend(e.messages)
            self.log("format_error")
            return self._react(self.guard.record("format_error", e.messages[0]["content"], False))
        self.n_calls += 1
        self.cost += message["extra"].get("cost", 0.0)
        self.messages.append(message)
        self.log("model_call", model_version=message["extra"].get("model_version"), cost=message["extra"].get("cost"))
        transition, signal = None, None
        for action in message["extra"]["actions"]:
            if transition:
                obs = "Not executed: the phase changed before this call."
            else:
                step = self._dispatch(action)
                obs, transition = step.observation, step.transition
                sig = self.guard.record(action_key(action["tool"], action["args"]), obs, step.progressed)
                signal = sig if sig.level != OK and (signal is None or sig.level == FORCE) else signal
            calls, cost = self._budget_left()
            self.messages.append({
                "role": "tool",
                "tool_call_id": action["tool_call_id"],
                "content": f"{truncate(obs, self.cfg.observation_chars)}\n[budget left: {calls} calls, ${max(cost, 0):.2f}]",
            })
        if transition:
            return self._enter(transition)
        return self._react(signal)

    def _react(self, signal) -> str | None:
        if signal is None or signal.level == OK:
            return None
        self.log("loop_signal", level=signal.level, reason=signal.reason)
        if signal.level == WARN:
            self._user(prompts.LOOP_WARNING.format(reason=signal.reason))
            return None
        forced = {LOCALIZE: EDIT, REPRODUCE: EDIT, EDIT: "validate" if self._has_diff() else None}[self.phase]
        if forced is None:
            self._user(prompts.LOOP_WARNING.format(reason=signal.reason))
            return None
        if self.phase == LOCALIZE:
            self.scope |= {f for f in self.ws.viewed if edit_refusal(f) is None}
        if self.phase in (LOCALIZE, REPRODUCE) and self.repro_state == "none":
            self.repro_state = "skipped"
        self.log("forced_transition", to=forced)
        return self._enter(forced)

    # ---- phases -------------------------------------------------------------------------
    def _enter(self, target: str) -> str | None:
        self.guard.reset()
        if target == "validate":
            return self._validate_and_maybe_revise()
        self.log("phase", to=target)
        self.phase = target
        if target == REPRODUCE:
            self._user(prompts.REPRODUCE.format(targets=", ".join(sorted(self.scope)) or "(none)"))
        elif target == EDIT:
            repro = prompts.REPRO_ACCEPTED if self.repro_state == "accepted" else prompts.REPRO_SKIPPED
            self._user(prompts.EDIT.format(scope=", ".join(sorted(self.scope)) or "(none yet)", repro=repro))
        return None

    def _validate(self):
        result = self.validator.validate(self.repro_script if self.repro_state == "accepted" else None)
        cand = Candidate(index=len(self.candidates), patch=result.patch, gates=result.gates)
        self.candidates.append(cand)
        self.candidate_details.append({"index": cand.index, "gates": result.gates, "details": result.details,
                                       "targets": result.targets, "patch": result.patch, "score": cand.score})
        self.log("validate", gates=result.gates, score=cand.score, validated=cand.validated)
        return cand, result

    def _validate_and_maybe_revise(self) -> str | None:
        cand, result = self._validate()
        if cand.validated or self.revisions >= self.cfg.max_revisions:
            return DONE
        self.revisions += 1
        reverted = ""
        if result.gates.get("build") is False and (good := self._last_buildable()):
            self._restore(good.patch)
            reverted = f"; the tree was reset to candidate {good.index}, the last one that compiled"
        self.phase = EDIT
        self._user(prompts.REVISE.format(attempt=self.revisions, max_attempts=self.cfg.max_revisions,
                                         report=result.report(), reverted=reverted))
        self.log("revise", attempt=self.revisions, reverted=bool(reverted))
        return None

    def _last_buildable(self) -> Candidate | None:
        good = [c for c in self.candidates if c.gates.get("build")]
        return good[-1] if good else None

    def _restore(self, patch: str) -> None:
        self.ws.run("git reset -q --hard HEAD")
        self.ws.write("/tmp/track3_restore.patch", patch)
        try:
            restore_patch(self.ws, "/tmp/track3_restore.patch")
            self.log("restore", ok=True)
        except OSError as e:
            self.log("restore", ok=False, output=str(e)[-300:])

    def _has_diff(self) -> bool:
        return self.ws.run("git diff --quiet HEAD")[0] != 0

    def _finish(self, status: str) -> AgentResult:
        # edits made after the last validation (e.g. the budget ran out mid-revision) still get gated
        try:
            if self._has_diff() and (not self.candidates or self.ws.diff() != self.candidates[-1].patch):
                self._validate()
        except Exception as e:  # fall back to the candidates already validated
            self.log("error", error=f"final validation failed: {type(e).__name__}: {str(e)[:300]}")
        best = best_candidate(self.candidates)
        submission = best.patch if best else ""
        self.log("finish", status=status, chosen=best.index if best else None, validated=bool(best and best.validated))
        return AgentResult(submission=submission, exit_status=status, n_calls=self.n_calls, cost=self.cost,
                           candidates=self.candidate_details, events=self.events, messages=self.messages)

    # ---- tools --------------------------------------------------------------------------
    def _dispatch(self, action: dict) -> Step:
        tool, args = action["tool"], action["args"]
        if tool not in PHASE_TOOLS[self.phase]:
            return Step(f"`{tool}` is not available in the {self.phase.upper()} phase. "
                        f"Available: {', '.join(PHASE_TOOLS[self.phase])}.")
        try:
            return getattr(self, f"_tool_{tool}")(**args)
        except TypeError as e:
            return Step(f"Bad arguments for `{tool}`: {e}")
        except Exception as e:  # a failing tool is reported to the model, never fatal to the run
            self.log("tool_error", tool=tool, error=f"{type(e).__name__}: {str(e)[:300]}")
            return Step(f"`{tool}` failed: {type(e).__name__}: {str(e)[:1000]}")

    def _tool_view(self, path: str, start: int = 1, end: int = 200) -> Step:
        before = len(self.ws.viewed)
        return Step(self.ws.view(path, start, end), progressed=len(self.ws.viewed) > before)

    def _tool_search(self, pattern: str, path: str = ".", glob: str = "*.py") -> Step:
        cmd = f"grep -rnE --include={shlex.quote(glob)} -e {shlex.quote(pattern)} {shlex.quote(path)} 2>/dev/null"
        _, out = self.ws.run(f"{cmd} | head -100; echo \"[total matches: $({cmd} | wc -l)]\"", timeout=self.cfg.bash_timeout)
        return Step(out or "no matches")

    def _tool_find_files(self, name: str) -> Step:
        _, out = self.ws.run(f"find . -path ./.git -prune -o -name {shlex.quote(name)} -print | head -100")
        return Step(out or "no files found")

    def _tool_outline(self, path: str) -> Step:
        rel = normalize_repo_path(path) or path
        try:
            source = self.ws.read(rel)
        except FileNotFoundError:
            return Step(f"{rel}: no such file")
        before = len(self.ws.viewed)
        self.ws.viewed.add(rel)
        return Step("\n".join([f"{rel}:"] + outline(source)) or "(no classes or functions)", progressed=len(self.ws.viewed) > before)

    def _tool_bash(self, command: str) -> Step:
        self.ws.drop_bytecode(self.validator.changed_files())
        rc, out = self.ws.run(command, timeout=self.cfg.bash_timeout)
        obs = f"[exit {rc}]\n{out}"
        if self.phase != EDIT and self._has_diff():
            self.ws.run("git checkout -q -- .")
            return Step(obs + "\nYour command changed tracked files; edits are not allowed in this phase, so they were reverted.")
        return Step(obs, progressed=self.phase == EDIT and self._diff_changed())

    def _tool_report_location(self, targets: list[str], evidence: str = "") -> Step:
        files = {normalize_repo_path(t.split(":")[0]) for t in targets}
        missing = sorted(f or "?" for f in files if not f or not self.ws.exists(f))
        if missing or not files:
            return Step(f"These targets do not exist: {', '.join(missing) or '(empty list)'}. Report existing source files.")
        refused = [r for f in files if (r := edit_refusal(f))]
        if refused:
            return Step("These cannot be edited:\n" + "\n".join(refused))
        self.scope |= files
        self.log("localized", targets=targets, evidence=evidence[:2000])
        return Step(f"Location recorded: {', '.join(sorted(files))}", progressed=True, transition=REPRODUCE)

    def _tool_run_repro(self, script: str | None = None) -> Step:
        if script is not None and self.phase == EDIT:
            return Step("The reproduction script is fixed once the EDIT phase starts; call run_repro without `script`.")
        if script is None and self.repro_script is None and self.phase == EDIT:
            return Step("No reproduction script was accepted; validation relies on the existing tests.")
        candidate = script if script is not None else self.repro_script
        if candidate is None:
            return Step("There is no reproduction script yet; pass `script`.")
        self.ws.write(REPRO_PATH, candidate)
        self.ws.drop_bytecode(self.validator.changed_files())
        rc, out = self.ws.run(f"{self.ws.python} {REPRO_PATH}", timeout=REPRO_TIMEOUT)
        obs = f"[exit {rc}]\n{out}"
        if self.phase != REPRODUCE:
            return Step(obs)
        if rc != 0 and _ASSERTION.search(out):
            self.repro_state, self.repro_script = "accepted", candidate
            self.log("repro_accepted")
            return Step(obs + "\nAccepted: the script fails with an AssertionError on the unpatched code.", progressed=True, transition=EDIT)
        self.repro_attempts += 1
        why = (
            "it exits 0 on the unpatched code, so it does not show the bug"
            if rc == 0
            else "it fails with an error that is not an AssertionError, so the script itself is broken or the failure is not the bug"
        )
        if self.repro_attempts >= self.cfg.max_repro_attempts:
            self.repro_state = "skipped"
            self.log("repro_given_up", reason=why)
            return Step(f"{obs}\nNot accepted ({why}). Attempts used up; moving on without a reproduction.", transition=EDIT)
        return Step(f"{obs}\nNot accepted: {why}. Adjust the script.")

    def _tool_skip_repro(self, reason: str) -> Step:
        self.repro_state = "skipped"
        self.log("repro_skipped", reason=reason[:500])
        return Step("Skipped. Validation will rely on the existing tests.", transition=EDIT)

    def _editable(self, path: str) -> str | None:
        rel = normalize_repo_path(path)
        if rel and self.scope and rel not in self.scope and self.ws.exists(rel):
            return f"{rel} is outside the reported location ({', '.join(sorted(self.scope))}); call expand_scope first."
        return None

    def _tool_replace(self, path: str, old: str, new: str) -> Step:
        if msg := self._editable(path):
            return Step(msg)
        r = self.ws.replace(path, old, new)
        return Step(r.message, progressed=r.ok and self._diff_changed())

    def _tool_insert(self, path: str, line: int, text: str) -> Step:
        if msg := self._editable(path):
            return Step(msg)
        r = self.ws.insert(path, line, text)
        return Step(r.message, progressed=r.ok and self._diff_changed())

    def _tool_create(self, path: str, content: str) -> Step:
        r = self.ws.create(path, content)
        if r.ok:
            self.scope.add(normalize_repo_path(path))
        return Step(r.message, progressed=r.ok and self._diff_changed())

    def _tool_expand_scope(self, path: str, reason: str) -> Step:
        rel = normalize_repo_path(path)
        if refusal := edit_refusal(path):
            return Step(refusal)
        if not self.ws.exists(rel):
            return Step(f"{rel}: no such file")
        self.scope.add(rel)
        self.log("expand_scope", path=rel, reason=reason[:500])
        return Step(f"You may now edit {rel}.", progressed=True)

    def _tool_run_tests(self, targets: list[str]) -> Step:
        if not targets:
            return Step("Pass at least one test target.")
        self.ws.drop_bytecode(self.validator.changed_files())
        _, out = self.ws.run(testsel.build_test_command(self.repo, targets), timeout=self.cfg.test_timeout)
        res = testsel.parse_results(self.repo, out)
        failed = sorted(t for t, s in res.items() if s in ("FAILED", "ERROR"))
        summary = f"[{sum(s == 'PASSED' for s in res.values())} passed, {len(failed)} failed/error]"
        return Step(f"{summary}\n" + ("Failing:\n" + "\n".join(failed[:20]) + "\n\n" if failed else "") + out[-4000:])

    def _tool_submit(self) -> Step:
        return Step("Submitted for validation.", transition="validate")

    def _diff_changed(self) -> bool:
        _, diff = self.ws.run("git diff HEAD")
        h = hashlib.sha1(diff.encode("utf-8", "replace")).hexdigest()
        changed, self._diff_hash = h != self._diff_hash, h
        return changed
