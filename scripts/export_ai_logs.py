"""Copy raw Claude Code transcripts into ai-logs/, redacting secrets and personal data only.

    python scripts/export_ai_logs.py

Each source file is copied line for line. The only change is that matches of the patterns
below are replaced by [REDACTED]; the script prints how many matches each pattern had per file.
Re-run it after the last session ends, so the final turns are included.
"""

from __future__ import annotations

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
                fout.write(redact(line, counts))
        print(f"{name}: {src.stat().st_size / 1e6:.1f} MB, redactions {counts or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
