"""Freeze the eval and dev task sets.

Rule (written down before any model run, see PLAN.md section 2):
- eval = three anchor instances fixed up front + 5 drawn from SWE-bench Verified Mini
  with random.Random(42), stratified by Verified's difficulty label and repo.
- dev = 4 more drawn from the rest of Verified Mini with random.Random(7). Agent iteration
  happens on dev only; eval is touched once for the baseline and once for the frozen agent.
- dev_hard = 8 more, added 2026-11-08 after the baseline solved all 12 dev runs and so gave
  no failures to learn from: drawn with random.Random(11) from Verified Mini minus eval and
  dev, 4 medium + 4 of the "1-4 hours" label, half django and half sphinx. eval is unchanged.

Running this module writes configs/tasks.json and SWE-bench-format files under data/.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

# The swebench>=5 schema: same instances and gold data as princeton-nlp/SWE-bench_Verified (checked
# field by field for all 12 tasks), plus the image, eval_script and log_parser the harness needs.
VERIFIED = "SWE-bench/SWE-bench_Verified"
VERIFIED_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
MINI = "MariusHobbhahn/swe-bench-verified-mini"
MINI_REVISION = "b316c349947c29963fce3f4a65967c9807a4b673"

ANCHORS = ("astropy__astropy-12907", "django__django-11790", "django__django-11848")

EASY, MEDIUM, HARD = "<15 min fix", "15 min - 1 hour", "1-4 hours"
DJANGO, SPHINX = "django/django", "sphinx-doc/sphinx"


@dataclass(frozen=True)
class Cell:
    difficulty: str
    repo: str
    k: int


EVAL_SEED = 42
EVAL_CELLS = (Cell(EASY, SPHINX, 2), Cell(EASY, DJANGO, 1), Cell(MEDIUM, SPHINX, 1), Cell(HARD, DJANGO, 1))
DEV_SEED = 7
DEV_CELLS = (Cell(EASY, DJANGO, 1), Cell(EASY, SPHINX, 1), Cell(MEDIUM, DJANGO, 1), Cell(MEDIUM, SPHINX, 1))

DEV_HARD_SEED = 11
DEV_HARD_CELLS = (Cell(HARD, DJANGO, 2), Cell(HARD, SPHINX, 2), Cell(MEDIUM, DJANGO, 2), Cell(MEDIUM, SPHINX, 2))

ROOT = Path(__file__).resolve().parents[2]


def stratified_draw(rows: list[dict], cells, seed: int, exclude: set[str] = frozenset()) -> list[str]:
    """Draw cell.k instance IDs per (difficulty, repo) cell, in cell order.

    Candidates are sorted by ID first, so the result depends only on the seed and the pool.
    """
    rng = random.Random(seed)
    ordered = sorted(rows, key=lambda r: r["instance_id"])
    picked: list[str] = []
    for cell in cells:
        stratum = [
            r["instance_id"]
            for r in ordered
            if r["difficulty"] == cell.difficulty
            and r["repo"] == cell.repo
            and r["instance_id"] not in exclude
            and r["instance_id"] not in picked
        ]
        if len(stratum) < cell.k:
            raise ValueError(f"cell {cell} needs {cell.k} candidates but only {len(stratum)} exist")
        picked += rng.sample(stratum, cell.k)
    return picked


def _load_rows() -> tuple[dict[str, dict], list[str]]:
    from datasets import load_dataset

    verified = load_dataset(VERIFIED, split="test", revision=VERIFIED_REVISION)
    mini = load_dataset(MINI, split="test", revision=MINI_REVISION)
    by_id = {r["instance_id"]: dict(r) for r in verified}
    return by_id, [r["instance_id"] for r in mini]


def _as_list(v) -> list:
    return json.loads(v) if isinstance(v, str) else list(v)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    by_id, mini_ids = _load_rows()
    missing = [i for i in mini_ids if i not in by_id]
    if missing:
        raise RuntimeError(f"Mini IDs missing from Verified: {missing}")
    mini_rows = [by_id[i] for i in mini_ids]

    eval_ids = list(ANCHORS) + stratified_draw(mini_rows, EVAL_CELLS, EVAL_SEED, exclude=set(ANCHORS))
    dev_ids = stratified_draw(mini_rows, DEV_CELLS, DEV_SEED, exclude=set(eval_ids))
    dev_hard_ids = stratified_draw(mini_rows, DEV_HARD_CELLS, DEV_HARD_SEED, exclude=set(eval_ids) | set(dev_ids))

    # Rows come from Verified (not Mini) so every instance, astropy-12907 included, has the same schema.
    _write_jsonl(ROOT / "data/eval/test.jsonl", [by_id[i] for i in eval_ids])
    _write_jsonl(ROOT / "data/dev/test.jsonl", [by_id[i] for i in dev_ids])
    _write_jsonl(ROOT / "data/dev_hard/test.jsonl", [by_id[i] for i in dev_hard_ids])

    def describe(i: str) -> dict:
        r = by_id[i]
        return {
            "instance_id": i,
            "repo": r["repo"],
            "difficulty": r["difficulty"],
            "in_mini": i in mini_ids,
            "image": r["image"],
            "n_fail_to_pass": len(_as_list(r["FAIL_TO_PASS"])),
            "n_pass_to_pass": len(_as_list(r["PASS_TO_PASS"])),
        }

    out = {
        "source": {"verified": [VERIFIED, VERIFIED_REVISION], "mini": [MINI, MINI_REVISION]},
        "rule": {
            "eval": {"anchors": list(ANCHORS), "seed": EVAL_SEED, "cells": [c.__dict__ for c in EVAL_CELLS]},
            "dev": {"seed": DEV_SEED, "cells": [c.__dict__ for c in DEV_CELLS], "excludes": "eval"},
            "dev_hard": {"seed": DEV_HARD_SEED, "cells": [c.__dict__ for c in DEV_HARD_CELLS], "excludes": "eval, dev"},
        },
        "eval": [describe(i) for i in eval_ids],
        "dev": [describe(i) for i in dev_ids],
        "dev_hard": [describe(i) for i in dev_hard_ids],
    }
    path = ROOT / "configs/tasks.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"eval": eval_ids, "dev": dev_ids, "dev_hard": dev_hard_ids}, indent=2))


if __name__ == "__main__":
    main()
