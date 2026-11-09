"""Loop and stall detection.

Three signals: the same action repeated, the same output seen several steps in a row, and
too many steps without progress (no new file viewed, no new edit). The first signal in a
phase is a WARN: the loop tells the model it is repeating itself. Any further signal in the
same phase is a FORCE: the loop moves to the next phase itself instead of asking again.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass

OK, WARN, FORCE = "ok", "warn", "force"


@dataclass(frozen=True)
class Signal:
    level: str
    reason: str = ""


def action_key(tool: str, args: dict) -> str:
    """Stable key for a tool call; whitespace differences do not make a new action."""
    norm = {k: re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v for k, v in args.items()}
    return f"{tool}:{json.dumps(norm, sort_keys=True)}"


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


class LoopGuard:
    def __init__(self, repeat_limit: int = 3, stall_limit: int = 8):
        self.repeat_limit = repeat_limit
        self.stall_limit = stall_limit
        self.reset()

    def reset(self) -> None:
        """Start fresh, e.g. after a phase change."""
        self._actions: Counter[str] = Counter()
        self._last_obs: str | None = None
        self._obs_streak = 0
        self._since_progress = 0
        self._triggers = 0

    def record(self, key: str, observation: str, progressed: bool) -> Signal:
        self._actions[key] += 1
        obs = _digest(observation)
        self._obs_streak = self._obs_streak + 1 if obs == self._last_obs else 1
        self._last_obs = obs
        self._since_progress = 0 if progressed else self._since_progress + 1

        reason = ""
        if self._actions[key] >= self.repeat_limit:
            reason = f"you have run the same action {self._actions[key]} times (repeat)"
            self._actions[key] = 0
        elif self._obs_streak >= self.repeat_limit:
            reason = f"the last {self._obs_streak} steps returned the same output"
            self._obs_streak = 0
        elif self._since_progress >= self.stall_limit:
            reason = f"{self._since_progress} steps without viewing a new file or making a new edit"
            self._since_progress = 0
        if not reason:
            return Signal(OK)
        self._triggers += 1
        return Signal(WARN if self._triggers == 1 else FORCE, reason)
