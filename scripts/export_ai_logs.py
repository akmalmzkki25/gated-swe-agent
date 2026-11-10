"""Copy raw Claude Code transcripts into ai-logs/, redacting secrets and personal data only.

    python scripts/export_ai_logs.py

Each source file is copied line for line. The only change is that matches of the patterns
below are replaced by [REDACTED]; the script prints how many matches each pattern had per file.
Re-run it after the last session ends, so the final turns are included.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HOME = Path.home() / ".claude/projects/C--"
ROOT = Path(__file__).resolve().parents[1]  # writes to ai-logs/, which is git-ignored
SESSION = "a88d1261-9f83-49bc-b117-67b70434782a"

# source transcript -> file name in ai-logs/ (date the session started, tool, track)
SOURCES = {
    HOME / f"{SESSION}.jsonl": "2026-11-06_claude-code_track3.jsonl",
    HOME / SESSION / "subagents/agent-aa2343c9e5734a67b.jsonl": "2026-11-08_claude-code_track3_subagent-dev-failure-analysis.jsonl",
}

PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "github_token": re.compile(r"gh[opsur]_[0-9A-Za-z]{30,}"),
    "openai_style_key": re.compile(r"sk-[0-9A-Za-z_\-]{20,}"),
    "bearer_token": re.compile(r"(?i)bearer\s+[0-9A-Za-z._\-]{20,}"),
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
}
# Extra private terms (e.g. the local part of a personal e-mail address, which can also appear on its
# own, say as a grep pattern) are read from a git-ignored file, one per line, so they never enter the repo.
_LOCAL_TERMS = Path(__file__).with_name(".redact_terms")
if _LOCAL_TERMS.exists():
    _terms = [t.strip() for t in _LOCAL_TERMS.read_text(encoding="utf-8").splitlines() if t.strip()]
    if _terms:
        PATTERNS["personal_term"] = re.compile("|".join(re.escape(t) for t in _terms))
# addresses that are not personal data (tool attributions, placeholders)
ALLOWED_EMAILS = {"noreply@anthropic.com", "a@b"}


def redact(text: str, counts: dict[str, int]) -> str:
    for name, pat in PATTERNS.items():
        def sub(m: re.Match) -> str:
            if name == "email" and m.group(0).lower() in ALLOWED_EMAILS:
                return m.group(0)
            counts[name] = counts.get(name, 0) + 1
            return "[REDACTED]"

        text = pat.sub(sub, text)
    return text


def redact_value(value, counts: dict[str, int]):
    """Redact inside decoded JSON strings, so escapes like \\n can never be cut in half."""
    if isinstance(value, str):
        return redact(value, counts)
    if isinstance(value, list):
        return [redact_value(v, counts) for v in value]
    if isinstance(value, dict):
        return {k: redact_value(v, counts) for k, v in value.items()}
    return value


def redact_line(line: str, counts: dict[str, int]) -> str:
    """Lines without a match are kept byte for byte; changed lines are re-serialised compactly."""
    obj = json.loads(line)
    before = sum(counts.values())
    new = redact_value(obj, counts)
    if sum(counts.values()) == before:
        return line
    return json.dumps(new, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    out_dir = ROOT / "ai-logs"
    out_dir.mkdir(exist_ok=True)
    for src, name in SOURCES.items():
        if not src.exists():
            print(f"missing: {src}", file=sys.stderr)
            return 1
        counts: dict[str, int] = {}
        with src.open(encoding="utf-8") as fin, (out_dir / name).open("w", encoding="utf-8", newline="\n") as fout:
            for line in fin:
                if line.strip():
                    fout.write(redact_line(line, counts))
        print(f"{name}: {src.stat().st_size / 1e6:.1f} MB, redactions {counts or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
