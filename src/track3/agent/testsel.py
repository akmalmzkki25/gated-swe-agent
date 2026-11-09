"""Pick the repository's own tests that are relevant to a change, run them, compare results.

Used by the regression gate: the same selected tests run on the clean checkout and on each
candidate, and any test that passed before and does not pass after is a regression.

The rule is generic per repository layout, not tuned per task:
- django keeps one suite per app under tests/<app>_tests/ and runs them by dotted label;
- astropy keeps a tests/ package next to each subpackage;
- sphinx keeps a flat tests/test_<area>_<module>.py.
Targets whose files import the changed module come first (direct evidence); within each
group a target scores +1 per module-path word found in its own path, +2 more when that
includes the module's own name (the most specific word: `enums` in django/db/models/enums.py,
not the generic `db` or `models`), and +2 more for an exact `test_<module>.py` name.
Results are parsed with the official SWE-bench log parsers, so "passed" means what the
harness will later count as passed.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

EXACT_NAME_BONUS = 2
LEAF_NAME_BONUS = 2
GENERIC_PARTS = {"__init__", "contrib", "tests", "test"}

_PARSER_BY_REPO = {
    "django/django": "parse_log_django",
    "sphinx-doc/sphinx": "parse_log_sphinx",
    "astropy/astropy": "parse_log_astropy",
}


def module_of(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.suffix != ".py":
        return None
    parts = list(p.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _words(parts) -> set[str]:
    words = set()
    for part in parts:
        for w in re.split(r"[_\W]+", part):
            if w and w not in GENERIC_PARTS:
                words.add(w.lower())
    return words


def _target(repo: str, test_file: str) -> str:
    if repo == "django/django":
        rel = PurePosixPath(test_file).relative_to("tests").with_suffix("")
        return ".".join(rel.parts)
    return test_file


_TEST_MODULE = re.compile(r"^(test.*|.*_tests?|tests)\.py$")


def is_test_module(path: str) -> bool:
    """A file a test runner collects (not a fixture, models.py or migration under tests/)."""
    return bool(_TEST_MODULE.match(PurePosixPath(path).name))


def candidate_tests(
    repo: str, changed_files: list[str], test_files: list[str], import_hits: list[str], max_targets: int = 4
) -> list[str]:
    top = repo.split("/")[1]
    scores: dict[str, int] = {}
    imported: set[str] = set()
    for changed in changed_files:
        mod = module_of(changed)
        if mod is None:
            continue
        mod_parts = [p for p in mod.split(".") if p != top]
        mod_words = _words(mod_parts)
        stem = mod_parts[-1] if mod_parts else ""
        for tf in test_files:
            if not is_test_module(tf):
                continue
            tp = PurePosixPath(tf)
            test_words = _words(p for p in tp.with_suffix("").parts if p != top)
            score = len(mod_words & test_words)
            if _words([stem]) & test_words:
                score += LEAF_NAME_BONUS
            if tp.stem == f"test_{stem}":
                score += EXACT_NAME_BONUS
            if tf in import_hits:
                imported.add(_target(repo, tf))
            if score or tf in import_hits:
                target = _target(repo, tf)
                scores[target] = max(scores.get(target, 0), score)
    ranked = sorted(scores, key=lambda t: (t not in imported, -scores[t], t))
    return ranked[:max_targets]


def import_grep_command(changed_files: list[str], test_roots: list[str]) -> str:
    """Shell command listing test files that import any changed module (one path per line)."""
    mods = [m for m in (module_of(f) for f in changed_files) if m]
    if not mods:
        return "true"
    pattern = "|".join(re.escape(m) for m in mods)
    roots = " ".join(shlex.quote(r) for r in test_roots)
    return f"grep -rlE --include='*.py' '(from|import) ({pattern})( |$|,|\\.)' {roots} 2>/dev/null || true"


def build_test_command(repo: str, targets: list[str]) -> str:
    quoted = " ".join(shlex.quote(t) for t in targets)
    if repo == "django/django":
        return f"./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 {quoted}"
    return f"python -m pytest -rA -p no:cacheprovider {quoted}"


def parse_results(repo: str, log: str) -> dict[str, str]:
    from swebench.harness.log_parsers import PARSER_REGISTRY

    parser = PARSER_REGISTRY[_PARSER_BY_REPO.get(repo, "parse_log_pytest")]
    return dict(parser(log, None))


def regressions(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Tests that passed on the clean checkout and do not pass with the candidate."""
    return sorted(t for t, s in before.items() if s == "PASSED" and after.get(t) != "PASSED")
