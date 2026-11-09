"""Workspace against a real shell in a temp dir (same `execute` contract as mini's environments)."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from track3.agent.workspace import Workspace


def _bash() -> str:
    """A real bash: on Windows `bash` on PATH is often WSL's launcher, so prefer Git Bash."""
    if override := os.environ.get("TRACK3_TEST_BASH"):
        return override
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    return str(git_bash) if sys.platform == "win32" and git_bash.exists() else "bash"


class BashEnv:
    """Runs commands with bash in a directory, returning mini-swe-agent's execute() dict."""

    def __init__(self, cwd):
        self.cwd = str(cwd)
        self.commands = []

    def execute(self, action, cwd="", *, timeout=None):
        self.commands.append(action["command"])
        r = subprocess.run(
            [_bash(), "-c", action["command"]], cwd=cwd or self.cwd, capture_output=True, timeout=timeout or 60
        )
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        return {"output": out, "returncode": r.returncode, "exception_info": ""}


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_bytes(b"def f():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_bytes(b"assert True\n")
    python = shlex.quote(sys.executable.replace("\\", "/"))
    return Workspace(BashEnv(tmp_path), python=python)


def test_read_returns_exact_bytes_including_trailing_newline(ws):
    assert ws.read("pkg/mod.py") == "def f():\n    return 1\n"


def test_read_missing_file_raises(ws):
    with pytest.raises(FileNotFoundError):
        ws.read("pkg/nope.py")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows re-quotes long argv for Git Bash and loses the redirect; the agent runs from the Linux runner, where this test runs",
)
def test_write_round_trips_large_files_in_chunks(ws):
    big = "x = '" + "y" * 300_000 + "'\n"
    ws.write("pkg/big.py", big)
    assert ws.read("pkg/big.py") == big
    assert len(ws.env.commands) > 3  # written in several chunks, not one huge argument


def test_replace_edits_file_and_returns_context(ws):
    result = ws.replace("pkg/mod.py", "return 1", "return 2")
    assert result.ok and "return 2" in result.message
    assert ws.read("pkg/mod.py") == "def f():\n    return 2\n"
    assert "pkg/mod.py" in ws.edited


def test_edit_that_breaks_syntax_is_rolled_back(ws):
    result = ws.replace("pkg/mod.py", "return 1", "return (1")
    assert not result.ok
    assert "rolled back" in result.message and "SyntaxError" in result.message
    assert ws.read("pkg/mod.py") == "def f():\n    return 1\n"
    assert "pkg/mod.py" not in ws.edited


def test_edit_to_test_file_is_refused_without_touching_it(ws):
    result = ws.replace("tests/test_mod.py", "True", "False")
    assert not result.ok and "test files" in result.message
    assert ws.read("tests/test_mod.py") == "assert True\n"


def test_ambiguous_replace_is_reported_not_applied(ws):
    ws.write("pkg/dup.py", "a = 1\na = 1\n")
    result = ws.replace("pkg/dup.py", "a = 1", "a = 2")
    assert not result.ok and "2 times" in result.message


def test_insert_and_create(ws):
    assert ws.insert("pkg/mod.py", 0, "import os").ok
    assert ws.read("pkg/mod.py").startswith("import os\n")
    assert ws.create("pkg/new.py", "X = 1\n").ok
    assert ws.read("pkg/new.py") == "X = 1\n"
    assert not ws.create("pkg/new.py", "X = 2\n").ok  # create never overwrites


def test_view_tracks_files_seen(ws):
    out = ws.view("pkg/mod.py", 1, 2)
    assert "     1| def f():" in out
    assert "pkg/mod.py" in ws.viewed


def test_diff_lists_only_tracked_source_changes(ws):
    env = ws.env
    env.execute({"command": "git init -q && git add -A && git -c user.email=a@b -c user.name=n commit -qm base"})
    ws.replace("pkg/mod.py", "return 1", "return 2")
    env.execute({"command": "echo junk > /tmp/repro_issue_test.txt"})
    diff = ws.diff()
    assert "+    return 2" in diff and "-    return 1" in diff


def test_create_in_a_directory_that_does_not_exist_is_refused(ws):
    result = ws.create("newpkg/__init__.py", "X = 1\n")
    assert not result.ok and "does not exist" in result.message
    assert not ws.exists("newpkg")
