import pytest

from track3.agent.policy import edit_refusal, normalize_repo_path


@pytest.mark.parametrize(
    "path",
    [
        "django/contrib/auth/forms.py",
        "astropy/modeling/separable.py",
        "sphinx/ext/autodoc/__init__.py",
        "sphinx/writers/latex.py",
        # library code that happens to be about testing, not a test suite
        "django/test/testcases.py",
        "sphinx/testing/fixtures.py",
    ],
)
def test_source_files_are_editable(path):
    assert edit_refusal(path) is None


@pytest.mark.parametrize(
    "path,reason",
    [
        ("tests/auth_tests/test_forms.py", "test"),
        ("astropy/modeling/tests/test_separable.py", "test"),
        ("testing/foo.py", "test"),
        ("test/regrtest.py", "test"),
        ("conftest.py", "test"),
        ("foo/bar_test.py", "test"),
        ("setup.py", "packaging"),
        ("setup.cfg", "packaging"),
        ("pyproject.toml", "packaging"),
        ("tox.ini", "packaging"),
        ("requirements/py3.txt", "packaging"),
        (".git/config", "outside"),
        ("../etc/passwd", "outside"),
        ("/etc/passwd", "outside"),
    ],
)
def test_tests_packaging_and_outside_paths_are_refused(path, reason):
    assert reason in edit_refusal(path)


def test_absolute_testbed_paths_are_normalized():
    assert normalize_repo_path("/testbed/django/forms.py") == "django/forms.py"
    assert normalize_repo_path("./django/forms.py") == "django/forms.py"
    assert normalize_repo_path("/etc/passwd") is None
    assert normalize_repo_path("django/../../etc") is None
