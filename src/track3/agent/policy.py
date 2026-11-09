"""Which files the agent may edit.

Matches the boundaries mini-swe-agent's own swebench prompt states ("DO NOT MODIFY: tests,
configuration files"), but enforced in code instead of left to the model.
"""

from __future__ import annotations

import posixpath
import re

REPO_ROOT = "/testbed"

# Test suites, not library code about testing: django/test/ and sphinx/testing/ are
# importable source packages and stay editable. `tests/` anywhere is a suite (astropy keeps
# one per subpackage); `test/` and `testing/` only count at the repository root.
_TEST_PATTERNS = (
    re.compile(r"(^|/)tests/"),
    re.compile(r"^(test|testing)/"),
    re.compile(r"(^|/)test_[^/]*\.py$"),
    re.compile(r"(^|/)[^/]*_tests?\.py$"),
    re.compile(r"(^|/)conftest\.py$"),
)
_PACKAGING = re.compile(
    r"(^|/)(setup\.py|setup\.cfg|pyproject\.toml|tox\.ini|pytest\.ini|MANIFEST\.in|requirements[^/]*(/.*)?)$"
)


def normalize_repo_path(path: str) -> str | None:
    """Repo-relative POSIX path, or None if it points outside the repository."""
    p = path.replace("\\", "/").strip()
    if p.startswith(REPO_ROOT + "/"):
        p = p[len(REPO_ROOT) + 1 :]
    elif p.startswith("/"):
        return None
    p = posixpath.normpath(p)
    if p == "." or p.startswith("../") or p == "..":
        return None
    return p


def edit_refusal(path: str) -> str | None:
    """None if the agent may edit `path`, otherwise the reason it may not."""
    rel = normalize_repo_path(path)
    if rel is None or rel == ".git" or rel.startswith(".git/"):
        return f"{path}: outside the repository source tree"
    if any(p.search(rel) for p in _TEST_PATTERNS):
        return f"{rel}: test files are not edited; the fix belongs in source code"
    if _PACKAGING.search(rel):
        return f"{rel}: packaging/config files are not edited; the environment is already set up"
    return None
