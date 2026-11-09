"""Harness sanity check, run before any model run (PLAN.md Phase 0).

- gold patches must resolve every task: the environment and grading work;
- a null patch (adds one unrelated file, so it applies and the full test run happens)
  must resolve none: the harness is not passing tasks on its own.
A task that fails either check is reported as broken in this environment, not dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

from track3.evaluate import ROOT, collect, expected_from_preds, run_harness

NULL_PATCH = """diff --git a/SANITY_NULL_PATCH.txt b/SANITY_NULL_PATCH.txt
new file mode 100644
index 0000000..d00491f
--- /dev/null
+++ b/SANITY_NULL_PATCH.txt
@@ -0,0 +1 @@
+1
"""


def _write_null_preds(dataset: Path, path: Path) -> None:
    ids = [json.loads(line)["instance_id"] for line in dataset.read_text(encoding="utf-8").splitlines()]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for iid in ids:
            f.write(json.dumps({"instance_id": iid, "model_name_or_path": "null-patch", "model_patch": NULL_PATCH}) + "\n")


def _unscored(name: str) -> int:
    """Instances with no harness report (now counted as unresolved by collect)."""
    return len(json.loads((ROOT / f"eval/sanity/{name}/unscored.json").read_text(encoding="utf-8")))


def main(split: str = "eval", workers: int = 2) -> None:
    dataset = ROOT / f"data/{split}/test.jsonl"
    n = len(dataset.read_text(encoding="utf-8").splitlines())

    run_harness(dataset, "gold", f"sanity-gold-{split}", workers)
    ids = [json.loads(line)["instance_id"] for line in dataset.read_text(encoding="utf-8").splitlines()]
    gold = collect(f"sanity-gold-{split}", ROOT / f"eval/sanity/gold-{split}", ids)

    null_preds = ROOT / f"eval/sanity/null-{split}/preds.jsonl"
    _write_null_preds(dataset, null_preds)
    run_harness(dataset, str(null_preds), f"sanity-null-{split}", workers)
    null = collect(f"sanity-null-{split}", ROOT / f"eval/sanity/null-{split}", *expected_from_preds(null_preds))

    summary = {
        "split": split,
        "n_tasks": n,
        "gold_resolved": sum(gold.values()),
        "null_resolved": sum(null.values()),
        "gold_not_resolved": sorted(i for i, ok in gold.items() if not ok),
        "gold_missing_report": _unscored(f"gold-{split}"),
        "null_resolved_ids": sorted(i for i, ok in null.items() if ok),
        "null_missing_report": _unscored(f"null-{split}"),
    }
    (ROOT / f"eval/sanity/summary-{split}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import sys

    main(*(sys.argv[1:2] or ["eval"]))
