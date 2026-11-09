from track3.agent.testsel import (
    candidate_tests,
    module_of,
    parse_results,
    regressions,
    build_test_command,
)

DJANGO_TESTS = [
    "tests/auth_tests/test_forms.py",
    "tests/auth_tests/test_views.py",
    "tests/forms_tests/tests/test_forms.py",
    "tests/admin_views/tests.py",
    "tests/auth_tests/models.py",
    "tests/auth_tests/migrations/0001_initial.py",
]
SPHINX_TESTS = ["tests/test_util_inspect.py", "tests/test_build_html.py", "tests/test_util.py"]
ASTROPY_TESTS = [
    "astropy/modeling/tests/test_separable.py",
    "astropy/modeling/tests/test_core.py",
    "astropy/io/fits/tests/test_core.py",
]


def test_module_of_turns_paths_into_dotted_modules():
    assert module_of("django/contrib/auth/forms.py") == "django.contrib.auth.forms"
    assert module_of("sphinx/ext/autodoc/__init__.py") == "sphinx.ext.autodoc"
    assert module_of("README.rst") is None


class TestCandidateTests:
    def test_django_maps_to_app_test_labels(self):
        got = candidate_tests("django/django", ["django/contrib/auth/forms.py"], DJANGO_TESTS, import_hits=[])
        assert got[0] == "auth_tests.test_forms"
        assert "admin_views.tests" not in got

    def test_files_that_import_the_module_rank_first(self):
        got = candidate_tests(
            "django/django", ["django/contrib/auth/forms.py"], DJANGO_TESTS, import_hits=["tests/admin_views/tests.py"]
        )
        assert got[0] == "admin_views.tests"

    def test_sibling_tests_dir_for_pytest_repos(self):
        got = candidate_tests("astropy/astropy", ["astropy/modeling/separable.py"], ASTROPY_TESTS, import_hits=[])
        assert got[0] == "astropy/modeling/tests/test_separable.py"
        assert "astropy/io/fits/tests/test_core.py" not in got

    def test_sphinx_matches_flat_test_names_by_module_tokens(self):
        got = candidate_tests("sphinx-doc/sphinx", ["sphinx/util/inspect.py"], SPHINX_TESTS, import_hits=[])
        assert got[0] == "tests/test_util_inspect.py"

    def test_result_is_capped(self):
        many = [f"tests/test_util_{i}.py" for i in range(20)]
        got = candidate_tests("sphinx-doc/sphinx", ["sphinx/util/x.py"], many, import_hits=[], max_targets=3)
        assert len(got) == 3

    def test_unrelated_change_selects_nothing(self):
        assert candidate_tests("sphinx-doc/sphinx", ["sphinx/locale/xx.py"], SPHINX_TESTS, import_hits=[]) == []


class TestCommand:
    def test_django_uses_runtests_with_labels(self):
        cmd = build_test_command("django/django", ["auth_tests.test_forms"])
        assert cmd.startswith("./tests/runtests.py ") and cmd.endswith(" auth_tests.test_forms")
        assert "--parallel 1" in cmd

    def test_pytest_repos_use_pytest_with_rA(self):
        cmd = build_test_command("sphinx-doc/sphinx", ["tests/test_util_inspect.py"])
        assert "pytest" in cmd and "-rA" in cmd and cmd.endswith("tests/test_util_inspect.py")

    def test_targets_are_shell_quoted(self):
        assert "'tests/a b.py'" in build_test_command("astropy/astropy", ["tests/a b.py"])


class TestResults:
    def test_parses_pytest_summary_lines(self):
        log = "PASSED tests/test_a.py::test_x\nFAILED tests/test_a.py::test_y - AssertionError\n"
        assert parse_results("sphinx-doc/sphinx", log) == {
            "tests/test_a.py::test_x": "PASSED",
            "tests/test_a.py::test_y": "FAILED",
        }

    def test_parses_django_verbose_lines(self):
        log = "test_a (auth_tests.test_forms.T) ... ok\ntest_b (auth_tests.test_forms.T) ... FAIL\n"
        res = parse_results("django/django", log)
        assert res["test_a (auth_tests.test_forms.T)"] == "PASSED"
        assert res["test_b (auth_tests.test_forms.T)"] == "FAILED"

    def test_regression_is_a_pass_that_no_longer_passes(self):
        before = {"a": "PASSED", "b": "PASSED", "c": "FAILED"}
        after = {"a": "PASSED", "b": "FAILED", "c": "PASSED"}
        assert regressions(before, after) == ["b"]

    def test_a_passing_test_that_disappears_counts_as_regression(self):
        # e.g. the patch breaks the import of the test module, so nothing is collected
        assert regressions({"a": "PASSED"}, {}) == ["a"]


def test_non_test_modules_under_tests_are_never_selected():
    got = candidate_tests(
        "django/django",
        ["django/contrib/auth/forms.py"],
        DJANGO_TESTS,
        import_hits=["tests/auth_tests/models.py", "tests/auth_tests/migrations/0001_initial.py"],
    )
    assert "auth_tests.models" not in got and not any("migrations" in g for g in got)


def test_leaf_module_name_outweighs_generic_package_words():
    tests = [
        "tests/auth_tests/test_models.py",
        "tests/check_framework/test_multi_db.py",
        "tests/db_functions/comparison/test_cast.py",
        "tests/model_enums/tests.py",
    ]
    got = candidate_tests("django/django", ["django/db/models/enums.py"], tests, import_hits=[])
    assert got[0] == "model_enums.tests"
