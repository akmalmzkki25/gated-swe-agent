"""Pull the task images and pin them by digest in configs/images.lock.

`swebench/...:latest` tags can move. The lock records the repo digest seen at first pull;
later runs use `name@sha256:...` so both agents and the harness see the same bytes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "configs/images.lock"


PULL_ATTEMPTS = 4
PULL_BACKOFF_S = 30


def _docker(*args: str) -> str:
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()[:500]}")
    return r.stdout.strip()


def _pull(ref: str) -> None:
    """docker pull with retries: the link here is slow and the engine has dropped once mid-pull."""
    for attempt in range(1, PULL_ATTEMPTS + 1):
        try:
            _docker("pull", "-q", ref)
            return
        except RuntimeError as e:
            if attempt == PULL_ATTEMPTS:
                raise
            print(f"  attempt {attempt} failed, retrying in {PULL_BACKOFF_S * attempt}s: {e}", flush=True)
            time.sleep(PULL_BACKOFF_S * attempt)


def repo_digest(image: str) -> str:
    digests = json.loads(_docker("image", "inspect", "--format", "{{json .RepoDigests}}", image))
    if not digests:
        raise RuntimeError(f"{image} has no repo digest (built locally?)")
    return digests[0]


def pin_data_files() -> None:
    """Point every row of data/*/test.jsonl at its locked digest.

    The harness reads `image`; mini-swe-agent reads `image_name` (falling back to an
    unpinned `:latest` name it builds itself), so both fields are set.
    """
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for split in ("eval", "dev", "dev_hard"):
        path = ROOT / f"data/{split}/test.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for r in rows:
            r["image"] = r["image_name"] = lock[r["instance_id"]]
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    tasks = json.loads((ROOT / "configs/tasks.json").read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else {}
    for t in tasks["eval"] + tasks["dev"] + tasks.get("dev_hard", []):
        iid, image = t["instance_id"], t["image"]
        pinned = lock.get(iid)
        print(f"pull {iid} <- {pinned or image}", flush=True)
        _pull(pinned or image)
        digest = repo_digest(pinned or image)
        if pinned and digest != pinned:
            sys.exit(f"{iid}: digest drift, lock has {pinned}, docker has {digest}")
        lock[iid] = digest
        LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"locked {len(lock)} images in {LOCK}")
    pin_data_files()
    print("data/eval and data/dev now reference images by digest")


if __name__ == "__main__":
    main()
