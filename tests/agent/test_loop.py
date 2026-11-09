"""End-to-end tests of the gated loop with a scripted model on a tiny git repo.

Needs bash, git and pytest on PATH: run inside the Linux runner
(`docker compose run --rm runner python -m pytest`).
"""

import itertools
import subprocess
import sys

import pytest
from minisweagent.exceptions import FormatError

from track3.agent.loop import AgentConfig, GatedAgent

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="runs in the Linux runner")

BUGGY = "def add(a, b):\n    return a - b\n"
TESTS = "from pkg.calc import add\n\n\ndef test_add_zero():\n    assert add(1, 0) == 1\n\n\ndef test_add_type():\n    assert isinstance(add(1, 0), int)\n"
REPRO = "import sys\nsys.path.insert(0, '/work-repo')\nfrom pkg.calc import add\nassert add(2, 3) == 5, add(2, 3)\n"


class BashEnv:
    def __init__(self, cwd):
        self.cwd = str(cwd)

    def execute(self, action, cwd="", *, timeout=None):
        r = subprocess.run(["bash", "-c", action["command"]], cwd=cwd or self.cwd, capture_output=True, timeout=timeout or 120)
        return {"output": (r.stdout + r.stderr).decode("utf-8", "replace"), "returncode": r.returncode, "exception_info": ""}


class ScriptedModel:
    """Returns one scripted response per query; each response is a list of (tool, args)."""

    def __init__(self, script, cost=0.01):
        self.script = iter(script)
        self.cost = cost
        self.tools = []
        self.calls = 0
        self._ids = itertools.count()

    def query(self, messages):
        self.calls += 1
        step = next(self.script)
        if step == "FORMAT_ERROR":
            raise FormatError({"role": "user", "content": "no tool call", "extra": {"cost": self.cost}})
        actions = [{"tool": t, "args": a, "tool_call_id": f"c{next(self._ids)}"} for t, a in step]
        return {"role": "assistant", "content": "", "extra": {"actions": actions, "cost": self.cost, "model_version": "scripted"}}


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "calc.py").write_text(BUGGY)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(TESTS)
    subprocess.run(
        "git init -q && git add -A && git -c user.email=a@b -c user.name=n commit -qm base",
        shell=True, cwd=tmp_path, check=True,
    )
    return tmp_path


def repro_for(repo):
    return REPRO.replace("/work-repo", str(repo))


def make_agent(repo, script, **cfg):
    model = ScriptedModel(script)
    agent = GatedAgent(model, BashEnv(repo), "acme/pkg", AgentConfig(**{"step_limit": 20, **cfg}))
    return agent, model


def happy_script(repo, fix="    return a + b\n"):
    return [
        [("view", {"path": "pkg/calc.py"})],
        [("report_location", {"targets": ["pkg/calc.py:add"], "evidence": "add subtracts"})],
        [("run_repro", {"script": repro_for(repo)})],
        [("replace", {"path": "pkg/calc.py", "old": "    return a - b\n", "new": fix})],
        [("submit", {})],
    ]


def test_happy_path_validates_and_submits_the_fix(repo):
    agent, model = make_agent(repo, happy_script(repo))
    result = agent.run("add() subtracts instead of adding")
    assert result.exit_status == "submitted"
    assert "+    return a + b" in result.submission
    assert result.n_calls == 5 and model.calls == 5
    assert result.candidates[-1]["gates"] == {"build": True, "repro": True, "regression": True, "hygiene": True}
    assert result.candidates[-1]["targets"] == ["tests/test_calc.py"]


def test_edit_tools_are_refused_before_the_edit_phase(repo):
    script = [
        [("replace", {"path": "pkg/calc.py", "old": "a - b", "new": "a + b"})],
        [("bash", {"command": "sed -i 's/a - b/a + b/' pkg/calc.py"})],
    ] + happy_script(repo)
    agent, _ = make_agent(repo, script)
    agent.run("bug")
    tool_msgs = [m["content"] for m in agent.messages if m["role"] == "tool"]
    assert "not available in the LOCALIZE phase" in tool_msgs[0]
    assert "were reverted" in tool_msgs[1]


def test_a_regression_triggers_one_revision_then_the_fix_is_submitted(repo):
    script = happy_script(repo, fix="    return a * b\n") + [
        [("replace", {"path": "pkg/calc.py", "old": "    return a * b\n", "new": "    return a + b\n"})],
        [("submit", {})],
    ]
    agent, _ = make_agent(repo, script)
    result = agent.run("bug")
    first, second = result.candidates
    assert first["gates"]["repro"] is False and first["gates"]["regression"] is False
    assert second["gates"]["regression"] is True
    assert agent.revisions == 1 and "+    return a + b" in result.submission
    revise = [m["content"] for m in agent.messages if m["role"] == "user" and "Validation of your submission" in m["content"]]
    assert revise and "test_add_zero" in revise[0]


def test_unvalidated_best_candidate_is_still_submitted_when_revisions_run_out(repo):
    script = happy_script(repo, fix="    return a * b\n") + [[("submit", {})]] * 3
    agent, _ = make_agent(repo, script, max_revisions=2)
    result = agent.run("bug")
    assert len(result.candidates) == 3 and "+    return a * b" in result.submission


def test_budget_exhaustion_without_edits_submits_nothing(repo):
    agent, _ = make_agent(repo, itertools.repeat([("search", {"pattern": "def add"})]), step_limit=4, repeat_limit=99, stall_limit=99)
    result = agent.run("bug")
    assert result.exit_status == "budget_exhausted" and result.submission == "" and result.n_calls == 4


def test_low_budget_validates_and_submits_existing_edits(repo):
    script = happy_script(repo)[:4] + [[("view", {"path": "pkg/calc.py", "start": i})] for i in range(1, 50)]
    agent, _ = make_agent(repo, script, step_limit=8, stall_limit=99)
    result = agent.run("bug")
    assert result.exit_status == "low_budget_submit"
    assert "+    return a + b" in result.submission and result.n_calls < 8


def test_repeated_actions_warn_then_force_the_phase_forward(repo):
    agent, _ = make_agent(repo, itertools.repeat([("view", {"path": "pkg/calc.py"})]), step_limit=12, repeat_limit=3)
    agent.run("bug")
    kinds = [e["event"] for e in agent.events]
    signals = [e for e in agent.events if e["event"] == "loop_signal"]
    assert signals[0]["level"] == "warn" and signals[1]["level"] == "force"
    assert "forced_transition" in kinds
    assert agent.phase == "edit" and "pkg/calc.py" in agent.scope


def test_format_errors_count_against_the_budget(repo):
    agent, _ = make_agent(repo, ["FORMAT_ERROR"] + happy_script(repo))
    result = agent.run("bug")
    assert result.n_calls == 6 and result.exit_status == "submitted"


def test_repro_that_passes_on_buggy_code_is_rejected(repo):
    script = happy_script(repo)[:2] + [
        [("run_repro", {"script": "print('ok')\n"})],
        [("run_repro", {"script": repro_for(repo)})],
    ] + happy_script(repo)[3:]
    agent, _ = make_agent(repo, script)
    result = agent.run("bug")
    msgs = [m["content"] for m in agent.messages if m["role"] == "tool"]
    assert any("does not show the bug" in m for m in msgs)
    assert agent.repro_state == "accepted" and result.candidates[-1]["gates"]["repro"] is True


def test_edits_outside_reported_location_need_expand_scope(repo):
    (repo / "pkg" / "other.py").write_text("X = 1\n")
    subprocess.run("git add -A && git -c user.email=a@b -c user.name=n commit -qm other", shell=True, cwd=repo, check=True)
    script = happy_script(repo)[:3] + [
        [("replace", {"path": "pkg/other.py", "old": "X = 1", "new": "X = 2"})],
        [("expand_scope", {"path": "pkg/other.py", "reason": "needed"})],
        [("replace", {"path": "pkg/other.py", "old": "X = 1", "new": "X = 2"})],
    ] + happy_script(repo)[3:]
    agent, _ = make_agent(repo, script)
    agent.run("bug")
    msgs = [m["content"] for m in agent.messages if m["role"] == "tool"]
    assert any("call expand_scope first" in m for m in msgs)
    assert "pkg/other.py" in agent.scope


def test_repro_that_fails_with_a_setup_error_is_rejected(repo):
    broken = "raise RuntimeError('settings are not configured')\n"
    script = happy_script(repo)[:2] + [[("run_repro", {"script": broken})]] + happy_script(repo)[2:]
    agent, _ = make_agent(repo, script)
    agent.run("bug")
    msgs = [m["content"] for m in agent.messages if m["role"] == "tool"]
    assert any("not an AssertionError" in m for m in msgs)
    assert agent.repro_state == "accepted" and agent.repro_script == repro_for(repo)


def test_overwriting_the_repro_with_bash_does_not_change_validation(repo):
    # wrong fix, then the model replaces the accepted script with one that always passes
    script = happy_script(repo, fix="    return a * b\n")[:4] + [
        [("bash", {"command": "echo 'print(1)' > /tmp/repro_issue.py"})],
        [("submit", {})],
    ]
    agent, _ = make_agent(repo, script, max_revisions=0)
    result = agent.run("bug")
    assert result.candidates[-1]["gates"]["repro"] is False


def test_a_tool_that_raises_becomes_an_observation_not_a_crash(repo, monkeypatch):
    agent, _ = make_agent(repo, [[("outline", {"path": "pkg/calc.py"})]] + happy_script(repo))

    def boom(**kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(agent, "_tool_outline", boom)
    result = agent.run("bug")
    first_tool = next(m["content"] for m in agent.messages if m["role"] == "tool")
    assert "`outline` failed" in first_tool and "disk on fire" in first_tool
    assert result.exit_status == "submitted" and "+    return a + b" in result.submission


def test_an_unexpected_error_still_submits_the_best_candidate(repo, monkeypatch):
    agent, model = make_agent(repo, happy_script(repo)[:4] + [[("view", {"path": "pkg/calc.py"})]] * 3)
    real_query = model.query

    def flaky(messages):
        if model.calls == 5:
            raise RuntimeError("API exploded")
        return real_query(messages)

    monkeypatch.setattr(model, "query", flaky)
    result = agent.run("bug")
    assert result.exit_status.startswith("error")
    assert "+    return a + b" in result.submission
