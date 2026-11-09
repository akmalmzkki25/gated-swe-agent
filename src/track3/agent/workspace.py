"""File and git operations on the task repository, through any mini-swe-agent environment.

`env` is anything with mini-swe-agent's `execute({"command": ...}, cwd, timeout=)` contract:
the DockerEnvironment the baseline uses in real runs, a plain bash runner in tests.

File contents travel as base64 in both directions, so trailing newlines, tabs and non-UTF-8
bytes survive intact. Writes are chunked to stay under per-argument size limits, because
some sphinx and django modules are larger than those limits once encoded.
"""

from __future__ import annotations

import base64
import shlex
from dataclasses import dataclass, field

from track3.agent.policy import edit_refusal, normalize_repo_path
from track3.agent.text_tools import EditError, insert_after, replace_once, view

# base64 characters per shell command: under Linux's 128 KiB per-argument limit and under
# Windows' 32,767-character command line, so the agent also works if launched from a Windows host
CHUNK = 30_000
TMP_SUFFIX = ".track3-write"


@dataclass(frozen=True)
class EditResult:
    ok: bool
    message: str


@dataclass
class Workspace:
    env: object
    python: str = "python"
    viewed: set[str] = field(default_factory=set)
    edited: set[str] = field(default_factory=set)

    def run(self, command: str, timeout: int | None = None) -> tuple[int, str]:
        out = self.env.execute({"command": command}, timeout=timeout)
        text = out.get("output", "")
        if out.get("exception_info"):
            text = f"{text}\n{out['exception_info']}".strip()
        return out.get("returncode", -1), text

    # ---- raw file I/O -------------------------------------------------------------------
    def read(self, path: str) -> str:
        q = shlex.quote(path)
        rc, out = self.run(f"test -f {q} && base64 < {q} | tr -d '\\n'")
        if rc != 0:
            raise FileNotFoundError(path)
        return base64.b64decode(out.strip()).decode("utf-8", "surrogateescape")

    def write(self, path: str, content: str) -> None:
        data = base64.b64encode(content.encode("utf-8", "surrogateescape")).decode("ascii")
        q, tmp = shlex.quote(path), shlex.quote(path + TMP_SUFFIX)
        self._ok(f": > {tmp}")
        for i in range(0, len(data), CHUNK):
            self._ok(f"printf %s {shlex.quote(data[i : i + CHUNK])} >> {tmp}")
        # keep the original file's mode by writing into it rather than replacing it
        self._ok(f"base64 -d {tmp} > {q} && rm -f {tmp}")
        self.drop_bytecode([path])

    def drop_bytecode(self, paths: list[str]) -> None:
        """Delete cached bytecode of these source files.

        Python decides a .pyc is stale from the source's mtime (1 s resolution) and size, so a
        same-size edit made within a second of the last import would run the old code.
        """
        globs = []
        for p in paths:
            if p.endswith(".py"):
                d, _, name = p.rpartition("/")
                globs.append(shlex.quote(f"{d + '/' if d else ''}__pycache__/{name[:-3]}.") + "*.pyc")
        if globs:
            self.run("rm -f " + " ".join(globs))

    def exists(self, path: str) -> bool:
        return self.run(f"test -e {shlex.quote(path)}")[0] == 0

    def _ok(self, command: str) -> str:
        rc, out = self.run(command)
        if rc != 0:
            raise OSError(f"command failed ({rc}): {out[-500:]}")
        return out

    # ---- agent-facing operations --------------------------------------------------------
    def view(self, path: str, start: int = 1, end: int = 200) -> str:
        rel = normalize_repo_path(path) or path
        try:
            content = self.read(rel)
        except FileNotFoundError:
            return f"{rel}: no such file"
        self.viewed.add(rel)
        return view(content, rel, start, end)

    def replace(self, path: str, old: str, new: str) -> EditResult:
        return self._edit(path, lambda content: replace_once(content, old, new))

    def insert(self, path: str, after_line: int, text: str) -> EditResult:
        return self._edit(path, lambda content: insert_after(content, after_line, text))

    def create(self, path: str, content: str) -> EditResult:
        rel = normalize_repo_path(path)
        if refusal := edit_refusal(path):
            return EditResult(False, refusal)
        if self.exists(rel):
            return EditResult(False, f"{rel} already exists; use replace or insert to change it")
        parent = rel.rpartition("/")[0] or "."
        if self.run(f"test -d {shlex.quote(parent)}")[0] != 0:
            # also keeps scratch packages (e.g. repro/) out of the submitted patch
            return EditResult(False, f"directory {parent}/ does not exist; new files go into an existing package")
        self.write(rel, content)
        if problem := self.compile_error(rel):
            self.run(f"rm -f {shlex.quote(rel)}")
            return EditResult(False, f"{rel} was not created (rolled back): it does not compile\n{problem}")
        # intent-to-add, so the new file shows up in `git diff HEAD` (the submitted patch)
        self.run(f"git add -N {shlex.quote(rel)}")
        self.edited.add(rel)
        return EditResult(True, f"created {rel} ({content.count(chr(10))} lines)")

    def _edit(self, path: str, transform) -> EditResult:
        if refusal := edit_refusal(path):
            return EditResult(False, refusal)
        rel = normalize_repo_path(path)
        try:
            original = self.read(rel)
        except FileNotFoundError:
            return EditResult(False, f"{rel}: no such file (use create for new files)")
        try:
            updated, snippet = transform(original)
        except EditError as e:
            return EditResult(False, f"{rel}: {e}")
        self.write(rel, updated)
        if problem := self.compile_error(rel):
            self.write(rel, original)
            return EditResult(False, f"{rel}: edit rolled back, the file no longer compiles\n{problem}")
        self.edited.add(rel)
        return EditResult(True, f"{rel} edited:\n{snippet}")

    def compile_error(self, rel: str) -> str | None:
        """Compile with the repository's own interpreter (its Python version decides valid syntax)."""
        if not rel.endswith(".py"):
            return None
        rc, out = self.run(f"{self.python} -m py_compile {shlex.quote(rel)}")
        return None if rc == 0 else out.strip()[-1500:]

    def diff(self) -> str:
        """Diff of tracked files against HEAD: the patch as the harness will apply it."""
        return self._ok("git -c core.fileMode=false diff --no-color HEAD")
