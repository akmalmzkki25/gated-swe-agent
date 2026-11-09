"""`track3` command line. Run inside the Linux runner: `docker compose run --rm runner track3 ...`.

    track3 baseline --split eval --seeds 0,1,2   mini-swe-agent 2.4.6, then the SWE-bench harness
    track3 agent    --split eval --seeds 0,1,2   the gated agent, then the SWE-bench harness
    track3 eval     --who baseline --split eval --seeds 0,1,2   re-score committed predictions only (no API key)
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from track3.evaluate import ROOT, collect, expected_from_preds, run_harness

app = typer.Typer(add_completion=False, no_args_is_help=True)

WHO = ("baseline", "agent")


def _seeds(text: str) -> list[int]:
    return [int(s) for s in text.split(",") if s.strip()]


def score(who: str, split: str, seed: int, workers: int = 2, rescore_only: bool = False) -> dict[str, bool]:
    """Grade runs/<who>/<split>/seed<k>/preds.jsonl with the harness into eval/<who>/<split>/seed<k>/."""
    preds = ROOT / f"runs/{who}/{split}/seed{seed}/preds.jsonl"
    if not preds.exists():
        raise typer.BadParameter(f"no predictions at {preds}")
    run_id = f"{who}-{split}-seed{seed}"
    if not rescore_only:
        run_harness(ROOT / f"data/{split}/test.jsonl", str(preds), run_id, workers)
    ids, reasons = expected_from_preds(preds)
    resolved = collect(run_id, ROOT / f"eval/{who}/{split}/seed{seed}", ids, reasons)
    print(f"{run_id}: {sum(resolved.values())}/{len(resolved)} resolved", flush=True)
    return resolved


@app.command()
def baseline(split: str = "eval", seeds: str = "0,1,2", workers: int = 2) -> None:
    from track3.run_baseline import run

    for seed in _seeds(seeds):
        run(seed, split, workers)
        score("baseline", split, seed, workers)


@app.command()
def agent(split: str = "eval", seeds: str = "0,1,2", workers: int = 2) -> None:
    from track3.run_agent import run

    for seed in _seeds(seeds):
        run(seed, split, workers)
        score("agent", split, seed, workers)


@app.command("eval")
def eval_only(
    who: str = "baseline", split: str = "eval", seeds: str = "0,1,2", workers: int = 2, collect_only: bool = False
) -> None:
    """Score committed predictions. --collect-only re-reads existing harness logs without re-running tests."""
    if who not in WHO:
        raise typer.BadParameter(f"--who must be one of {WHO}")
    for seed in _seeds(seeds):
        score(who, split, seed, workers, rescore_only=collect_only)


@app.command()
def status(split: str = "eval") -> None:
    """Resolved counts per agent and seed from eval/ (no harness run)."""
    for who in WHO:
        for path in sorted((ROOT / f"eval/{who}/{split}").glob("seed*/resolved.json")):
            r = json.loads(path.read_text(encoding="utf-8"))
            print(f"{who:8s} {split} {path.parent.name}: {sum(r.values())}/{len(r)}")


if __name__ == "__main__":
    app()
