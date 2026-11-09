from track3.contamination import (
    added_lines,
    edit_paths,
    first_edit,
    gold_overlap,
    memorized_lines,
)

GOLD = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,3 +1,3 @@
 def f():
-    year = 1900
+    current_year = datetime.datetime.utcnow().year  # comment
+    return current_year
"""


def test_added_lines_are_normalised_and_skip_comments_and_blanks():
    assert added_lines(GOLD) == {"current_year = datetime.datetime.utcnow().year", "return current_year"}


def test_overlap_is_the_share_of_gold_added_lines_reproduced():
    cand = GOLD.replace("    return current_year", "    return other")
    assert gold_overlap(cand, GOLD) == 0.5
    assert gold_overlap(GOLD, GOLD) == 1.0
    assert gold_overlap("", GOLD) == 0.0


def test_memorized_lines_are_long_gold_lines_absent_from_the_issue():
    issue = "Two digit years should use the current year."
    assert memorized_lines(GOLD, GOLD, issue) == ["current_year = datetime.datetime.utcnow().year"]
    assert memorized_lines(GOLD, GOLD, issue + " current_year = datetime.datetime.utcnow().year") == []


def test_edit_paths_recognise_common_shell_edits():
    assert edit_paths("sed -i 's/a/b/' django/utils/http.py") == ["django/utils/http.py"]
    assert edit_paths("cat > pkg/mod.py << 'EOF'\nx\nEOF") == ["pkg/mod.py"]
    assert edit_paths("python - <<'EOF'\nopen('pkg/a.py','w').write(s)\nEOF") == ["pkg/a.py"]
    assert edit_paths("sed -n '1,20p' django/utils/http.py") == []
    assert edit_paths("python /tmp/repro.py > /tmp/out.txt") == []


def test_first_edit_reports_steps_and_whether_the_file_was_read_before():
    steps = [
        {"reads": ["a.py"], "edits": []},
        {"reads": [], "edits": ["a.py"]},
    ]
    assert first_edit(steps) == {"step": 2, "path": "a.py", "read_before": True}
    blind = [{"reads": ["b.py"], "edits": []}, {"reads": [], "edits": ["a.py"]}]
    assert first_edit(blind)["read_before"] is False
    assert first_edit([{"reads": ["a.py"], "edits": []}]) is None


def test_first_edit_ignores_scratch_files_outside_the_submitted_patch():
    steps = [
        {"reads": ["pkg/a.py"], "edits": ["reproduce_issue.py"]},
        {"reads": [], "edits": ["/tmp/repro_issue.py"]},
        {"reads": [], "edits": ["pkg/a.py"]},
    ]
    assert first_edit(steps, source_files={"pkg/a.py"}) == {"step": 3, "path": "pkg/a.py", "read_before": True}


def test_patch_files_lists_the_files_a_diff_touches():
    from track3.contamination import patch_files

    assert patch_files(GOLD) == {"x.py"}
