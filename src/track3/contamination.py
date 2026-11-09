"""Contamination checks (PLAN.md section 6): signs that a patch came from memory, not work.

Per eval task, for both agents and every seed:
- gold overlap: share of the gold patch's added lines (normalised) that the final patch reproduces;
- memorised lines: added lines over 20 characters that match the gold patch exactly and do
  not appear in the issue text;
- first edit: how many model steps passed before the first edit, and whether the edited file
  had been read before it (an edit to an unread file is a memory signal).
Plus zero-context probes with the same model and decoding and no repository access:
(a) only the instance id, (b) only the issue text. A probe that reproduces gold lines means
the model can produce the fix without looking at the code.

Flag rule, fixed before any of this was computed (PLAN.md): overlap >= 0.8, or a memorised
line, or a first edit to an unread file. Each flag is then checked by hand.
"""

from __future__ import annotations

import re

MIN_MEMORISED_CHARS = 20
_EDIT_PATTERNS = (
    re.compile(r"sed\s+-i[^\n]*?\s([\w./-]+\.py)\b"),
    re.compile(r"(?:cat|tee)\s*>{1,2}\s*([\w./-]+\.py)\b"),
    re.compile(r">{1,2}\s*([\w./-]+\.py)\b"),
    re.compile(r"""open\(\s*['"]([\w./-]+\.py)['"]\s*,\s*['"][wa]"""),
    re.compile(r"""Path\(\s*['"]([\w./-]+\.py)['"]\s*\)\.write_text"""),
    re.compile(r"perl\s+-p?i[^\n]*?\s([\w./-]+\.py)\b"),
)


def _norm(line: str) -> str:
    line = re.sub(r"\s+#.*$", "", line)  # trailing comment
    return re.sub(r"\s+", " ", line).strip()


def added_lines(patch: str) -> set[str]:
    out = set()
    for raw in patch.splitlines():
        if raw.startswith("+") and not raw.startswith("+++"):
            line = _norm(raw[1:])
            if line and not line.startswith("#"):
                out.add(line)
    return out


def gold_overlap(candidate: str, gold: str) -> float:
    g = added_lines(gold)
    return round(len(added_lines(candidate) & g) / len(g), 3) if g else 0.0


def memorized_lines(candidate: str, gold: str, issue: str) -> list[str]:
    issue_n = _norm(issue)
    return sorted(
        line
        for line in added_lines(candidate) & added_lines(gold)
        if len(line) > MIN_MEMORISED_CHARS and line not in issue_n
    )


def edit_paths(command: str) -> list[str]:
    """Repository .py files a shell command writes to (absolute /tmp paths are ignored)."""
    paths = []
    for pat in _EDIT_PATTERNS:
        for m in pat.finditer(command):
            p = m.group(1).removeprefix("/testbed/").removeprefix("./")
            if not p.startswith("/") and p not in paths:
                paths.append(p)
    return paths


def patch_files(patch: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^diff --git a/(\S+) b/", patch, flags=re.M)}


def first_edit(steps: list[dict], source_files: set[str] | None = None) -> dict | None:
    """steps: [{"reads": [paths], "edits": [paths]}] per model step, in order.

    With `source_files` (the files of the submitted patch), edits to anything else, such as
    repro scripts in /tmp or helper scripts at the repo root, are not counted as the first edit.
    """
    seen: set[str] = set()
    for n, step in enumerate(steps, start=1):
        for path in step["edits"]:
            if source_files is not None and path not in source_files:
                continue
            return {"step": n, "path": path, "read_before": path in seen}
        seen.update(step["reads"])
    return None


# ---- trajectories -------------------------------------------------------------------------
_PY_PATH = re.compile(r"[\w./-]+\.py\b")


def _shell_step(command: str) -> dict:
    edits = edit_paths(command)
    reads = [p.removeprefix("/testbed/").removeprefix("./") for p in _PY_PATH.findall(command)]
    return {"reads": [p for p in reads if p not in edits and not p.startswith("/")], "edits": edits}


def steps_from_baseline(traj: dict) -> list[dict]:
    steps = []
    for m in traj["messages"]:
        if m.get("role") != "assistant":
            continue
        step = {"reads": [], "edits": []}
        for a in m.get("extra", {}).get("actions", []):
            s = _shell_step(a.get("command", ""))
            step["reads"] += s["reads"]
            step["edits"] += s["edits"]
        steps.append(step)
    return steps


def steps_from_agent(traj: dict) -> list[dict]:
    steps = []
    for m in traj["messages"]:
        if m.get("role") != "assistant":
            continue
        step = {"reads": [], "edits": []}
        for a in m.get("extra", {}).get("actions", []):
            tool, args = a["tool"], a["args"]
            path = str(args.get("path", "")).removeprefix("/testbed/").removeprefix("./")
            if tool in ("view", "outline") or (tool == "search" and path.endswith(".py")):
                step["reads"].append(path)
            elif tool in ("replace", "insert", "create"):
                step["edits"].append(path)
            elif tool == "bash":
                s = _shell_step(args.get("command", ""))
                step["reads"] += s["reads"]
                step["edits"] += s["edits"]
        steps.append(step)
    return steps


# ---- zero-context probes ------------------------------------------------------------------
PROBE_ID = (
    "SWE-bench instance {instance_id} is a bug fix merged into the {repo} repository. "
    "Without looking at any code, write the unified diff of that fix. Output only the diff."
)
PROBE_ISSUE = (
    "Here is an issue from the {repo} repository at commit {base_commit}:\n<issue>\n{problem_statement}\n</issue>\n"
    "You have no access to the repository. Write the unified diff that fixes the issue. Output only the diff."
)


def extract_diff(text: str) -> str:
    blocks = re.findall(r"```(?:diff|patch)?\n(.*?)```", text, flags=re.S)
    return "\n".join(blocks) if blocks else text


def run_probe(row: dict, template: str, seed: int = 0) -> dict:
    import litellm

    from track3.smoke_model import load_model_config

    cfg = load_model_config()
    prompt = template.format(**row)
    r = litellm.completion(
        model=cfg["model_name"],
        messages=[{"role": "user", "content": prompt}],
        **{**cfg["model_kwargs"], "seed": seed},
    )
    text = r.choices[0].message.content or ""
    return {"text": text, "diff": extract_diff(text), "cost": litellm.completion_cost(completion_response=r)}


# ---- report -------------------------------------------------------------------------------
OVERLAP_FLAG = 0.8


def _run_signals(patch: str, gold: str, issue: str, steps: list[dict]) -> dict:
    fe = first_edit(steps, source_files=patch_files(patch))
    return {
        "overlap": gold_overlap(patch, gold),
        "memorized": memorized_lines(patch, gold, issue),
        "first_edit_step": fe["step"] if fe else None,
        "first_edit_read_before": fe["read_before"] if fe else None,
    }


def _flags(sig: dict) -> list[str]:
    flags = []
    if sig["overlap"] >= OVERLAP_FLAG:
        flags.append(f"overlap {sig['overlap']}")
    if sig["memorized"]:
        flags.append(f"{len(sig['memorized'])} gold line(s) not in the issue")
    if sig.get("first_edit_read_before") is False:
        flags.append("first edit to an unread file")
    return flags


def analyze(split: str = "eval", seeds=(0, 1, 2), probe: bool = True) -> dict:
    import glob
    import json
    from pathlib import Path

    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    rows = [json.loads(line) for line in (root / f"data/{split}/test.jsonl").read_text(encoding="utf-8").splitlines()]
    out: dict = {}
    for row in rows:
        iid, gold, issue = row["instance_id"], row["patch"], row["problem_statement"]
        entry = {"runs": {}, "probes": {}}
        for who, steps_of in (("baseline", steps_from_baseline), ("agent", steps_from_agent)):
            for s in seeds:
                traj = json.loads(Path(glob.glob(str(root / f"runs/{who}/{split}/seed{s}/{iid}/*.traj.json"))[0]).read_text(encoding="utf-8"))
                preds = json.loads((root / f"runs/{who}/{split}/seed{s}/preds.json").read_text(encoding="utf-8"))
                resolved = json.loads((root / f"eval/{who}/{split}/seed{s}/resolved.json").read_text(encoding="utf-8"))
                sig = _run_signals(preds[iid]["model_patch"] or "", gold, issue, steps_of(traj))
                sig["resolved"] = resolved.get(iid, False)
                sig["flags"] = _flags(sig)
                entry["runs"][f"{who}/seed{s}"] = sig
        if probe:
            probe_dir = root / f"runs/probes/{split}"
            probe_dir.mkdir(parents=True, exist_ok=True)
            for name, template in (("id_only", PROBE_ID), ("issue_only", PROBE_ISSUE)):
                cache = probe_dir / f"{iid}.{name}.json"
                p = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else run_probe(row, template)
                cache.write_text(json.dumps(p, indent=2), encoding="utf-8", newline="\n")
                sig = {"overlap": gold_overlap(p["diff"], gold), "memorized": memorized_lines(p["diff"], gold, issue)}
                sig["flags"] = _flags(sig)
                entry["probes"][name] = sig
        out[iid] = entry
    (root / f"results/contamination-{split}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    return out


if __name__ == "__main__":
    import json
    import sys

    res = analyze(*(sys.argv[1:2] or ["eval"]))
    for iid, e in res.items():
        print(iid)
        for k, v in {**e["runs"], **{f"probe/{n}": p for n, p in e["probes"].items()}}.items():
            print(f"  {k:16s} res={v.get('resolved', '-')!s:5s} ov={v['overlap']:<5} mem={len(v['memorized'])} "
                  f"fe={v.get('first_edit_step', '-')}/{v.get('first_edit_read_before', '-')} {v['flags']}")
