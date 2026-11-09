"""Pure text operations behind the agent's file tools.

No I/O here: the workspace reads a file out of the task container, calls one of these, and
writes the result back. Keeping them pure makes every edit rule unit-testable.
"""

from __future__ import annotations

import ast
import re

CONTEXT_LINES = 4


class EditError(ValueError):
    """An edit the agent asked for that cannot be applied as stated."""


def _numbered(lines: list[str], first: int) -> list[str]:
    return [f"{n:6d}| {text}" for n, text in enumerate(lines, start=first)]


def view(content: str, path: str, start: int, end: int, max_lines: int = 200) -> str:
    lines = content.splitlines()
    total = len(lines)
    start = max(1, start)
    end = min(total, end) if end >= start else start
    header = f"{path}: lines {start}-{end} of {total}"
    if end - start + 1 > max_lines:
        capped_end = start + max_lines - 1
        header = f"{path}: lines {start}-{capped_end} of {total} (capped at {max_lines} lines; ask for {capped_end + 1}-{end} next)"
        end = capped_end
    return "\n".join([header, *_numbered(lines[start - 1 : end], start)])


def _context(content: str, first_line: int, last_line: int) -> str:
    lines = content.splitlines()
    lo = max(1, first_line - CONTEXT_LINES)
    hi = min(len(lines), last_line + CONTEXT_LINES)
    return "\n".join(_numbered(lines[lo - 1 : hi], lo))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def replace_once(content: str, old: str, new: str) -> tuple[str, str]:
    """Replace the single exact occurrence of `old`. Returns (new_content, numbered snippet)."""
    if not old:
        raise EditError("old text is empty; use insert to add new lines")
    if old == new:
        raise EditError("old and new text are identical; nothing would change")
    count = content.count(old)
    if count == 0:
        if _squash(old) and _squash(old) in _squash(content):
            raise EditError("old text not found exactly, but it matches if whitespace is ignored: copy the indentation from `view` output")
        raise EditError("old text not found in the file; `view` the region first and copy it exactly")
    if count > 1:
        starts, pos = [], content.find(old)
        while pos != -1:
            starts.append(content.count("\n", 0, pos) + 1)
            pos = content.find(old, pos + 1)
        raise EditError(f"old text occurs {count} times (lines {', '.join(map(str, starts))}); include more surrounding lines to make it unique")
    pos = content.find(old)
    first = content.count("\n", 0, pos) + 1
    updated = content[:pos] + new + content[pos + len(old) :]
    last = first + max(new.count("\n"), 1) - 1
    return updated, _context(updated, first, last)


def insert_after(content: str, line: int, text: str) -> tuple[str, str]:
    lines = content.splitlines(keepends=True)
    if line < 0 or line > len(lines):
        raise EditError(f"line {line} is past the end of the file ({len(lines)} lines)")
    block = text if text.endswith("\n") else text + "\n"
    if line > 0 and not lines[line - 1].endswith("\n"):
        lines[line - 1] += "\n"
    updated = "".join(lines[:line]) + block + "".join(lines[line:])
    return updated, _context(updated, line + 1, line + block.count("\n"))


def outline(source: str) -> list[str]:
    """Classes and functions with line ranges, nested by indentation."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _regex_outline(source)
    out: list[str] = []

    def walk(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                out.append(f"{'    ' * depth}{kind} {child.name}  [{child.lineno}-{child.end_lineno}]")
                walk(child, depth + 1)

    walk(tree, 0)
    return out


def _regex_outline(source: str) -> list[str]:
    out = []
    for n, line in enumerate(source.splitlines(), start=1):
        m = re.match(r"^(\s*)(class|def|async def)\s+(\w+)", line)
        if m:
            depth = len(m.group(1).expandtabs()) // 4
            kind = "def" if "def" in m.group(2) else "class"
            out.append(f"{'    ' * depth}{kind} {m.group(3)}  [{n}]")
    return out + ["(regex outline: file does not parse with this Python)"]


def changed_line_count(patch: str) -> int:
    return sum(
        1
        for line in patch.splitlines()
        if (line.startswith("+") and not line.startswith("+++")) or (line.startswith("-") and not line.startswith("---"))
    )
