from track3.agent.loopguard import FORCE, OK, WARN, LoopGuard, action_key


def test_action_key_ignores_whitespace_differences():
    assert action_key("bash", {"command": "grep  -rn foo ."}) == action_key("bash", {"command": "grep -rn foo .  "})
    assert action_key("view", {"path": "a.py", "start": 1}) != action_key("view", {"path": "a.py", "start": 2})


def test_distinct_productive_steps_never_trigger():
    g = LoopGuard()
    for i in range(30):
        assert g.record(f"view:{i}", f"obs {i}", progressed=True).level == OK


def test_third_identical_action_warns_then_next_trigger_forces():
    g = LoopGuard(repeat_limit=3)
    assert g.record("a", "o1", progressed=True).level == OK
    assert g.record("a", "o2", progressed=False).level == OK
    first = g.record("a", "o3", progressed=False)
    assert first.level == WARN and "repeat" in first.reason
    # the warning clears the counter, so the same action needs three more repeats
    assert g.record("a", "o4", progressed=False).level == OK
    assert g.record("a", "o5", progressed=False).level == OK
    assert g.record("a", "o6", progressed=False).level == FORCE


def test_identical_observations_in_a_row_warn():
    g = LoopGuard(repeat_limit=3)
    g.record("a", "same error", progressed=False)
    g.record("b", "same error", progressed=False)
    sig = g.record("c", "same error", progressed=False)
    assert sig.level == WARN and "same output" in sig.reason


def test_stall_without_progress_warns():
    g = LoopGuard(stall_limit=4)
    levels = [g.record(f"x{i}", f"o{i}", progressed=False).level for i in range(4)]
    assert levels == [OK, OK, OK, WARN]


def test_progress_resets_the_stall_counter():
    g = LoopGuard(stall_limit=3)
    g.record("x1", "o1", progressed=False)
    g.record("x2", "o2", progressed=False)
    g.record("x3", "o3", progressed=True)
    assert g.record("x4", "o4", progressed=False).level == OK


def test_reset_after_phase_change_starts_fresh():
    g = LoopGuard(repeat_limit=2)
    g.record("a", "o", progressed=False)
    assert g.record("a", "o2", progressed=False).level == WARN
    g.reset()
    g.record("a", "o", progressed=False)
    assert g.record("a", "o3", progressed=False).level == WARN
