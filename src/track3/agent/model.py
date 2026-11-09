"""The model client: mini-swe-agent's LitellmModel with our tool list instead of its one bash tool.

Subclassing (rather than calling LiteLLM directly) keeps everything else identical to the
baseline: the same retry policy, the same cost calculation, the same GLOBAL_MODEL_STATS
budget, the same message preparation, and the same model_kwargs from configs/model.yaml.
"""

from __future__ import annotations

import json
import time

from minisweagent.exceptions import FormatError
from minisweagent.models.litellm_model import LitellmModel


def _format_error(text: str) -> FormatError:
    return FormatError({"role": "user", "content": text, "extra": {"interrupt_type": "FormatError"}})


def parse_tool_calls(tool_calls, known: set[str]) -> list[dict]:
    """[{"tool", "args", "tool_call_id"}]; FormatError if there are none or one is malformed."""
    if not tool_calls:
        raise _format_error(
            "Your response had no tool call. Every response must call at least one of the tools you were given."
        )
    actions = []
    for call in tool_calls:
        name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError as e:
            raise _format_error(f"The arguments of your `{name}` call are not valid JSON ({e}). Call it again.") from e
        if name not in known:
            raise _format_error(f"Unknown tool `{name}`. Available tools: {', '.join(sorted(known))}.")
        if not isinstance(args, dict):
            raise _format_error(f"The arguments of `{name}` must be a JSON object.")
        actions.append({"tool": name, "args": args, "tool_call_id": call.id})
    return actions


class ToolModel(LitellmModel):
    """LitellmModel whose tool list is set per call (the agent's tools depend on its phase)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tools: list[dict] = []

    def _query(self, messages, **kwargs):
        import litellm

        return litellm.completion(
            model=self.config.model_name,
            messages=messages,
            tools=self.tools,
            **(self.config.model_kwargs | kwargs),
        )

    def _parse_actions(self, response) -> list[dict]:
        known = {t["function"]["name"] for t in self.tools}
        return parse_tool_calls(response.choices[0].message.tool_calls or [], known)

    def query(self, messages, **kwargs) -> dict:
        message = super().query(messages, **kwargs)
        # the model id the endpoint reported (Gemini's modelVersion), logged on every call
        message["extra"]["model_version"] = message["extra"]["response"].get("model")
        message["extra"]["timestamp"] = time.time()
        return message
