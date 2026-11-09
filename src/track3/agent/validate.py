"""VALIDATE: run real checks on the current edits. No model call happens here.

G0 build       every changed .py file compiles with the repository's own Python
G1 repro       the accepted reproduction script exits 0 (skipped when none was accepted);
               it is rewritten from the agent's stored copy first, so edits to /tmp do not count
G2 regression  related existing tests that passed on the clean checkout still pass
G3 hygiene     the diff is non-empty, not whitespace-only, and touches no test/config file
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from track3.agent import testsel
from track3.agent.candidates import GATES
from track3.agent.policy import edit_refusal
from track3.agent.workspace import Workspace

REPRO_PATH = "/tmp/repro_issue.py"
REPRO_TIMEOUT = 120
SAVED_PATCH = "/tmp/track3_edits.patch"


@dataclass
class GateResult:
    patch: str
    gates: dict[str, bool | None]
    details: dict[str, str] = field(default_factory=dict)
    targets: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = []
        for g in GATES:
            status = {True: "passed", False: "FAILED", None: "skipped"}[self.gates.get(g)]
            lines.append(f"- {g}: {status}" + (f"\n{self.details[g]}" if self.details.get(g) else ""))
        return "\n".join(lines)


def new_files_in_patch(patch: str) -> list[str]:
    """Paths the patch creates (a `new file mode` header follows their `diff --git` line)."""
    files, current = [], None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[1] if " b/" in line else None
        elif line.startswith("new file mode") and current:
            files.append(current)
    return files


def restore_patch(ws: Workspace, patch_path: str) -> None:
    """Re-apply a saved diff onto HEAD and mark its new files intent-to-add, so they stay in the diff.

    `git apply --intent-to-add` is not used: in the git versions shipped in these images it
    empties the index.
    """
    if ws.run(f"test -s {shlex.quote(patch_path)}")[0] != 0:
        return
    ws._ok(f"git apply {shlex.quote(patch_path)}")
    _, names = ws.run("git diff --name-only HEAD")
    ws.drop_bytecode(names.split())
    created = new_files_in_patch(ws.read(patch_path))
    if created:
        ws._ok("git add -N -- " + " ".join(shlex.quote(f) for f in created))


def _tail(text: str, n: int = 3000) -> str:
    return text if len(text) <= n else "...\n" + text[-n:]


class Validator:
    def __init__(self, ws: Workspace, repo: str, test_files: list[str], test_timeout: int = 900):
        self.ws = ws
        self.repo = repo
        self.test_files = test_files
        self.test_timeout = test_timeout
        self._clean_results: dict[str, dict[str, str]] = {}

    def changed_files(self) -> list[str]:
        _, out = self.ws.run("git diff --name-only HEAD")
        return [line.strip() for line in out.splitlines() if line.strip()]

    def validate(self, repro_script: str | None) -> GateResult:
        patch = self.ws.diff()
        changed = self.changed_files()
        gates: dict[str, bool | None] = {g: None for g in GATES}
        details: dict[str, str] = {}

        broken = [f"{f}:\n{err}" for f in changed if (err := self.ws.compile_error(f))]
        gates["build"] = not broken and bool(changed)
        if broken:
            details["build"] = _tail("\n".join(broken))
        if not changed:
            details["build"] = "no file is changed"

        if gates["build"]:
            if repro_script is not None:
                self.ws.write(REPRO_PATH, repro_script)
                self.ws.drop_bytecode(changed)
                rc, out = self.ws.run(f"{self.ws.python} {REPRO_PATH}", timeout=REPRO_TIMEOUT)
                gates["repro"] = rc == 0
                if rc != 0:
                    details["repro"] = f"/tmp/repro_issue.py still exits {rc}:\n{_tail(out, 2000)}"
            targets = self._targets(changed)
            if targets:
                gates["regression"], details["regression"] = self._regression(targets)
            result_targets = targets
        else:
            result_targets = []

        refused = [r for f in changed if (r := edit_refusal(f))]
        whitespace_only = bool(changed) and self.ws.run("git diff -w --quiet HEAD")[0] == 0
        gates["hygiene"] = bool(patch.strip()) and not refused and not whitespace_only
        if refused:
            details["hygiene"] = "patch touches files that must not change:\n" + "\n".join(refused)
        elif whitespace_only:
            details["hygiene"] = "the diff only changes whitespace"
        return GateResult(patch=patch, gates=gates, details=details, targets=result_targets)

    # ---- regression gate ----------------------------------------------------------------
    def _targets(self, changed: list[str]) -> list[str]:
        _, hits = self.ws.run(testsel.import_grep_command(changed, ["."]), timeout=120)
        tests = set(self.test_files)
        import_hits = [h.strip().removeprefix("./") for h in hits.splitlines() if h.strip().removeprefix("./") in tests]
        return testsel.candidate_tests(self.repo, changed, self.test_files, import_hits)

    def _run_tests(self, targets: list[str]) -> tuple[dict[str, str], str]:
        self.ws.drop_bytecode(self.changed_files())
        _, out = self.ws.run(testsel.build_test_command(self.repo, targets), timeout=self.test_timeout)
        return testsel.parse_results(self.repo, out), out

    def _clean_baseline(self, targets: list[str]) -> None:
        """Run targets not seen yet on the clean checkout.

        The edits are saved as a patch, the tree is reset to HEAD, the tests run, and the patch
        is re-applied. (`git stash -u` is not used: it also stashes untracked __pycache__ files,
        which the test run recreates, and then the stash cannot be popped.)
        """
        missing = [t for t in targets if t not in self._clean_results]
        if not missing:
            return
        patch = self.ws.diff()
        changed = self.changed_files()
        self.ws.write(SAVED_PATCH, patch)
        self.ws._ok("git reset -q --hard HEAD")
        self.ws.drop_bytecode(changed)
        try:
            for t in missing:
                self._clean_results[t] = self._run_tests([t])[0]
        finally:
            restore_patch(self.ws, SAVED_PATCH)

    def _regression(self, targets: list[str]) -> tuple[bool | None, str]:
        self._clean_baseline(targets)
        before = {k: v for t in targets for k, v in self._clean_results[t].items()}
        if not before:
            return None, f"selected tests {targets} produced no parseable results on the clean checkout; gate skipped"
        after, out = self._run_tests(targets)
        broken = testsel.regressions(before, after)
        if broken:
            shown = "\n".join(f"  {t}" for t in broken[:15])
            more = f"\n  ... and {len(broken) - 15} more" if len(broken) > 15 else ""
            return False, f"tests that passed before your edits and fail now ({targets}):\n{shown}{more}\n\nTest output (tail):\n{_tail(out)}"
        passed = sum(1 for s in after.values() if s == "PASSED")
        return True, f"{passed} tests passed in {targets}; none of the previously passing ones broke"
