"""Run the gated agent on a split, one seed at a time, in the same containers as the baseline.

The container comes from mini-swe-agent's own `get_sb_environment` with the environment
section of its built-in swebench.yaml (cwd /testbed, conda testbed via BASH_ENV, same image
by digest), and the model client is mini's LitellmModel with our tools, so the only thing
that differs from the baseline run is the agent loop.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import threading
import traceback
from dataclasses import asdict
from pathlib import Path

import yaml
from dotenv import load_dotenv

from track3.agent.loop import AgentConfig, GatedAgent
from track3.agent.model import ToolModel
from track3.smoke_model import load_model_config

ROOT = Path(__file__).resolve().parents[2]
_PREDS_LOCK = threading.Lock()


def agent_version() -> str:
    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""

    sha = git("rev-parse", "HEAD") or "no-commit"
    dirty = bool(git("status", "--porcelain", "--", "src"))
    return f"{sha}{'+dirty' if dirty else ''}"


def _update_preds(out: Path, instance_id: str, patch: str) -> None:
    with _PREDS_LOCK:
        path = out / "preds.json"
        preds = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        preds[instance_id] = {"model_name_or_path": "gated-agent", "instance_id": instance_id, "model_patch": patch}
        path.write_text(json.dumps(preds, indent=2), encoding="utf-8", newline="\n")


def run_instance(instance: dict, out: Path, seed: int, version: str, budget_override: dict | None = None) -> None:
    from minisweagent.config import get_config_from_spec
    from minisweagent.run.benchmarks.swebench import get_sb_environment

    model_cfg = load_model_config()
    budget = yaml.safe_load((ROOT / "configs/budget.yaml").read_text(encoding="utf-8"))
    mini_cfg = get_config_from_spec("swebench.yaml")
    model = ToolModel(model_name=model_cfg["model_name"], model_kwargs={**model_cfg["model_kwargs"], "seed": seed})
    per_task = {**budget["per_task"], **(budget_override or {})}  # override only for smoke runs, never for reported numbers
    cfg = AgentConfig(step_limit=per_task["model_calls"], cost_limit=per_task["cost_usd"])
    iid = instance["instance_id"]
    env, result, error = None, None, None
    try:
        env = get_sb_environment(mini_cfg, instance)
        result = GatedAgent(model, env, instance["repo"], cfg).run(instance["problem_statement"])
    except Exception as e:  # recorded per instance; the run continues with the next one
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    finally:
        if env is not None and hasattr(env, "cleanup"):
            env.cleanup()
    traj = {
        "instance_id": iid,
        "info": {
            "agent_version": version,
            "seed": seed,
            "model": model_cfg["model_name"],
            "model_kwargs": model.config.model_kwargs,
            "config": asdict(cfg),
            "exit_status": result.exit_status if result else "error",
            "error": error,
            "n_calls": result.n_calls if result else None,
            "cost": result.cost if result else None,
        },
        "candidates": result.candidates if result else [],
        "events": result.events if result else [],
        "messages": result.messages if result else [],
    }
    inst_dir = out / iid
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / f"{iid}.traj.json").write_text(json.dumps(traj, indent=2, default=str), encoding="utf-8", newline="\n")
    _update_preds(out, iid, result.submission if result else "")


def run(
    seed: int,
    split: str = "eval",
    workers: int | None = None,
    only: list[str] | None = None,
    out: Path | None = None,
    budget_override: dict | None = None,
) -> Path:
    load_dotenv(ROOT / ".env")
    budget = yaml.safe_load((ROOT / "configs/budget.yaml").read_text(encoding="utf-8"))
    os.environ.setdefault("MSWEA_GLOBAL_COST_LIMIT", str(budget["global"]["cost_usd"]))
    out = out or ROOT / f"runs/agent/{split}/seed{seed}"
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (ROOT / f"data/{split}/test.jsonl").read_text(encoding="utf-8").splitlines()]
    done = set(json.loads((out / "preds.json").read_text(encoding="utf-8"))) if (out / "preds.json").exists() else set()
    todo = [r for r in rows if r["instance_id"] not in done and (not only or r["instance_id"] in only)]
    version = agent_version()
    print(f"agent {version}: {len(todo)} instances, seed {seed} -> {out}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers or budget["workers"]) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(run_instance, r, out, seed, version, budget_override) for r in todo]):
            fut.result()
    preds = json.loads((out / "preds.json").read_text(encoding="utf-8"))
    with (out / "preds.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for p in preds.values():
            f.write(json.dumps(p) + "\n")
    return out
