from track3.agent.candidates import GATES, Candidate, best_candidate

PATCH_2 = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
PATCH_6 = PATCH_2 + "-c\n+d\n-e\n+f\n"


def cand(index, patch=PATCH_2, **gates):
    return Candidate(index=index, patch=patch, gates={g: gates.get(g, True) for g in GATES})


def test_gate_order_is_build_repro_regression_hygiene():
    assert GATES == ("build", "repro", "regression", "hygiene")


def test_fully_validated_candidate_beats_partial_ones():
    full = cand(1)
    partial = cand(2, regression=False)
    assert best_candidate([partial, full]) is full
    assert full.validated and not partial.validated


def test_score_counts_gates_passed_before_the_first_failure():
    assert cand(1, build=False).score == 0
    assert cand(1, repro=False).score == 1
    assert cand(1, regression=False).score == 2
    assert cand(1).score == 4


def test_a_skipped_gate_does_not_count_as_a_failure():
    c = cand(1, repro=None)
    assert c.score == 4 and c.validated


def test_build_break_ranks_below_everything_else():
    broken = cand(1, build=False)
    no_repro = cand(2, repro=False)
    assert best_candidate([broken, no_repro]) is no_repro


def test_tie_prefers_the_smaller_patch_then_the_later_candidate():
    small, large = cand(1, PATCH_2), cand(2, PATCH_6)
    assert best_candidate([large, small]) is small
    early, late = cand(3), cand(4)
    assert best_candidate([early, late]) is late


def test_no_candidates_returns_none():
    assert best_candidate([]) is None


def test_new_files_in_patch_finds_created_paths_only():
    from track3.agent.validate import new_files_in_patch

    patch = (
        "diff --git a/pkg/a.py b/pkg/a.py\nindex 1..2 100644\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/pkg/new.py b/pkg/new.py\nnew file mode 100644\nindex 0000000..1\n--- /dev/null\n+++ b/pkg/new.py\n@@ -0,0 +1 @@\n+z\n"
    )
    assert new_files_in_patch(patch) == ["pkg/new.py"]
