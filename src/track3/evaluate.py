"""Score predictions with the official SWE-bench harness and keep the evidence.

Wraps `python -m swebench.harness.run_evaluation` (swebench==5.0.2) and copies, per
instance, the harness `report.json`, `test_output.txt`, `patch.diff` and `run_instance.log`
into eval/<name>/, plus the run-level report. Nothing is graded here: the harness grades.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS_LOGS = ROOT / "logs/run_evaluation"
KEEP = ("report.json", "test_output.txt", "patch.diff", "run_instance.log")


def run_harness(dataset: Path, predictions: str, run_id: str, workers: int = 2, timeout: int = 1800) -> None:
    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", str(dataset),
        "--predictions_path", predictions,
        "--run_id", run_id,
        "--max_workers", str(workers),
        "--timeout", str(timeout),
        "--report_dir", str(ROOT / "logs"),
    ]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def expected_from_preds(preds_path: Path) -> tuple[list[str], dict[str, str]]:
    """Every instance in a predictions file, and why some will get no harness report."""
    ids, reasons = [], {}
    for line in preds_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        ids.append(p["instance_id"])
        if not (p.get("model_patch") or "").strip():
            reasons[p["instance_id"]] = "empty patch (the harness does not run it)"
    return ids, reasons


def collect(run_id: str, out_dir: Path, expected: list[str], reasons: dict[str, str] | None = None) -> dict:
    """Copy the harness evidence for run_id into out_dir; return {instance_id: resolved}.

    Every expected instance is in the result. One with no harness report (an empty patch,
    which the harness skips, or a run that errored) counts as unresolved, and the reason
    goes to unscored.json, so the denominator is always the full task set.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, bool] = {}
    for inst_dir in sorted(HARNESS_LOGS.glob(f"{run_id}/*/*")):
        if not inst_dir.is_dir():
            continue
        dest = out_dir / inst_dir.name
        dest.mkdir(exist_ok=True)
        for name in KEEP:
            if (inst_dir / name).exists():
                shutil.copy2(inst_dir / name, dest / name)
        report = inst_dir / "report.json"
        if report.exists():
            data = json.loads(report.read_text(encoding="utf-8"))
            resolved[inst_dir.name] = bool(data[inst_dir.name]["resolved"])
    for run_report in (ROOT / "logs").glob(f"*.{run_id}.json"):
        shutil.copy2(run_report, out_dir / "run_report.json")
    unscored = {
        iid: (reasons or {}).get(iid, "no harness report (the run or the harness errored)")
        for iid in expected
        if iid not in resolved
    }
    resolved = {iid: resolved.get(iid, False) for iid in expected}
    (out_dir / "resolved.json").write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "unscored.json").write_text(json.dumps(unscored, indent=2) + "\n", encoding="utf-8", newline="\n")
    return resolved
