"""Tool schemas (OpenAI function format, as LiteLLM expects) and which phase offers which."""

from __future__ import annotations

LOCALIZE, REPRODUCE, EDIT = "localize", "reproduce", "edit"


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_S = {"type": "string"}
_I = {"type": "integer"}

TOOLS = {
    "view": _tool(
        "view",
        "Show lines of a file with line numbers (at most 200 lines per call).",
        {"path": _S, "start": _I, "end": _I},
        ["path"],
    ),
    "search": _tool(
        "search",
        "grep -rnE for a regex in the repository. Returns path:line:text, at most 100 matches.",
        {"pattern": _S, "path": {**_S, "description": "directory or file, default ."}, "glob": {**_S, "description": "file glob, default *.py"}},
        ["pattern"],
    ),
    "find_files": _tool("find_files", "Find files whose name matches a glob, e.g. '*forms*.py'.", {"name": _S}, ["name"]),
    "outline": _tool("outline", "List the classes and functions in a Python file with their line ranges.", {"path": _S}, ["path"]),
    "bash": _tool(
        "bash",
        "Run a bash command in /testbed (60 s timeout). Use the dedicated tools for viewing and editing files.",
        {"command": _S},
        ["command"],
    ),
    "report_location": _tool(
        "report_location",
        "Finish localization: the files (and functions) the fix will touch, most likely first, with the evidence.",
        {"targets": {"type": "array", "items": _S, "description": "e.g. ['django/contrib/auth/forms.py:AuthenticationForm']"}, "evidence": _S},
        ["targets", "evidence"],
    ),
    "run_repro": _tool(
        "run_repro",
        "Write /tmp/repro_issue.py with `script` and run it. It must exit non-zero (e.g. a failing assert) while the bug is present and exit 0 once it is fixed. Without `script`, re-run the existing one.",
        {"script": _S},
        [],
    ),
    "skip_repro": _tool("skip_repro", "Give up on a reproduction script, with the reason.", {"reason": _S}, ["reason"]),
    "replace": _tool(
        "replace",
        "Replace one exact occurrence of `old` with `new` in a file. `old` must match exactly once, including indentation.",
        {"path": _S, "old": _S, "new": _S},
        ["path", "old", "new"],
    ),
    "insert": _tool("insert", "Insert text after a line number (0 = top of file).", {"path": _S, "line": _I, "text": _S}, ["path", "line", "text"]),
    "create": _tool("create", "Create a new source file (never overwrites).", {"path": _S, "content": _S}, ["path", "content"]),
    "expand_scope": _tool(
        "expand_scope",
        "Allow edits to a file you did not report during localization, with the reason.",
        {"path": _S, "reason": _S},
        ["path", "reason"],
    ),
    "run_tests": _tool(
        "run_tests",
        "Run the repository's own tests. Django: test labels like 'auth_tests.test_forms'. Others: pytest paths like 'tests/test_util.py' or 'pkg/tests/test_x.py::test_y'.",
        {"targets": {"type": "array", "items": _S}},
        ["targets"],
    ),
    "submit": _tool(
        "submit",
        "Submit your edits. The harness then compiles them, runs your reproduction script and the related tests; if something fails you get the report and can revise.",
        {},
        [],
    ),
}

_READ = ["view", "search", "find_files", "outline", "bash"]
PHASE_TOOLS = {
    LOCALIZE: _READ + ["report_location"],
    REPRODUCE: _READ + ["run_repro", "skip_repro"],
    EDIT: _READ + ["replace", "insert", "create", "expand_scope", "run_repro", "run_tests", "submit"],
}


ALL_TOOLS = list(TOOLS.values())


def tools_for(phase: str) -> list[dict]:
    return [TOOLS[name] for name in PHASE_TOOLS[phase]]


# The model is always sent ALL_TOOLS; phases are enforced by the dispatcher instead. Changing
# the declared tool list mid-conversation risks the API rejecting earlier calls to tools that
# are no longer declared, and a fixed tool list keeps the prompt prefix cacheable.
