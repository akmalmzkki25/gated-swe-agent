"""Run the reference agent: mini-swe-agent 2.4.6, unmodified, on the pinned model and budget.

The config is mini's own built-in `swebench.yaml`, merged with one override that sets only
the model (name + decoding kwargs from configs/model.yaml), the seed, and the budget from
configs/budget.yaml. The override actually used is written next to each run for audit.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv

from track3.smoke_model import load_model_config

ROOT = Path(__file__).resolve().parents[2]


def baseline_override(seed: int) -> dict:
    model = load_model_config()
    budget = yaml.safe_load((ROOT / "configs/budget.yaml").read_text(encoding="utf-8"))
    return {
        "model": {"model_name": model["model_name"], "model_kwargs": {**model["model_kwargs"], "seed": seed}},
        "agent": {"step_limit": budget["per_task"]["model_calls"], "cost_limit": budget["per_task"]["cost_usd"]},
    }


def run(seed: int, split: str = "eval", workers: int | None = None) -> Path:
    load_dotenv(ROOT / ".env")
    budget = yaml.safe_load((ROOT / "configs/budget.yaml").read_text(encoding="utf-8"))
    out = ROOT / f"runs/baseline/{split}/seed{seed}"
    out.mkdir(parents=True, exist_ok=True)
    override = out / "override.yaml"
    override.write_text(yaml.safe_dump(baseline_override(seed), sort_keys=False), encoding="utf-8", newline="\n")
    env = {
        **os.environ,
        "MSWEA_GLOBAL_COST_LIMIT": str(budget["global"]["cost_usd"]),
        "MSWEA_CONFIGURED": "true",
        "PYTHONUTF8": "1",
    }
    cmd = [
        "mini-extra", "swebench",
        "--subset", str(ROOT / f"data/{split}"), "--split", "test",
        "-c", "swebench.yaml", "-c", str(override),
        "-o", str(out),
        "-w", str(workers or budget["workers"]),
    ]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)
    preds = json.loads((out / "preds.json").read_text(encoding="utf-8"))
    with (out / "preds.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for p in preds.values():
            f.write(json.dumps(p) + "\n")
    return out
