import pytest

from track3.agent.text_tools import EditError, changed_line_count, insert_after, outline, replace_once, view

SRC = "\n".join(f"line {i}" for i in range(1, 11)) + "\n"


class TestView:
    def test_numbers_lines_and_reports_range(self):
        out = view(SRC, "a.py", 3, 5)
        assert out.splitlines()[0] == "a.py: lines 3-5 of 10"
        assert out.splitlines()[1:] == ["     3| line 3", "     4| line 4", "     5| line 5"]

    def test_clamps_out_of_range_requests(self):
        out = view(SRC, "a.py", -4, 99)
        assert out.splitlines()[0] == "a.py: lines 1-10 of 10"

    def test_caps_lines_per_call(self):
        out = view(SRC, "a.py", 1, 10, max_lines=4)
        assert out.splitlines()[0] == "a.py: lines 1-4 of 10 (capped at 4 lines; ask for 5-10 next)"
        assert len(out.splitlines()) == 5


class TestReplaceOnce:
    def test_replaces_a_unique_match_and_returns_numbered_context(self):
        new, snippet = replace_once(SRC, "line 5\n", "line five\n")
        assert "line five\n" in new and "line 5\n" not in new
        assert "     5| line five" in snippet

    def test_missing_text_is_an_error(self):
        with pytest.raises(EditError, match="not found"):
            replace_once(SRC, "line 42", "x")

    def test_missing_text_that_differs_only_in_whitespace_says_so(self):
        with pytest.raises(EditError, match="whitespace"):
            replace_once("def f():\n    return 1\n", "def f():\n  return 1\n", "x")

    def test_ambiguous_match_lists_line_numbers(self):
        with pytest.raises(EditError, match=r"2 times.*lines 1, 2"):
            replace_once("x = 1\nx = 1\n", "x = 1", "x = 2")

    def test_empty_old_text_is_rejected(self):
        with pytest.raises(EditError, match="empty"):
            replace_once(SRC, "", "x")

    def test_identical_old_and_new_is_rejected(self):
        with pytest.raises(EditError, match="identical"):
            replace_once(SRC, "line 3", "line 3")


class TestInsertAfter:
    def test_inserts_after_given_line(self):
        new, _ = insert_after(SRC, 2, "inserted\n")
        assert new.splitlines()[:4] == ["line 1", "line 2", "inserted", "line 3"]

    def test_line_zero_inserts_at_top(self):
        new, _ = insert_after(SRC, 0, "top")
        assert new.splitlines()[0] == "top"

    def test_line_past_end_is_an_error(self):
        with pytest.raises(EditError, match="past the end"):
            insert_after(SRC, 11, "x")


class TestOutline:
    def test_lists_classes_methods_and_functions_with_ranges(self):
        src = "class A:\n    def m(self):\n        pass\n\n\ndef f(x):\n    return x\n"
        assert outline(src) == ["class A  [1-3]", "    def m  [2-3]", "def f  [6-7]"]

    def test_falls_back_to_regex_when_source_does_not_parse(self):
        src = "class A:\n    def m(self):\n        print 'py2'\n"
        assert outline(src) == ["class A  [1]", "    def m  [2]", "(regex outline: file does not parse with this Python)"]


def test_changed_line_count_ignores_headers():
    patch = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n"
        " keep\n-old\n+new\n+added\n"
    )
    assert changed_line_count(patch) == 3
