"""Patch candidates and how the submitted one is chosen.

Every time the agent's edits reach VALIDATE, the current diff is saved as a candidate with
the result of each gate. The patch submitted is picked here, in code, from gate results the
loop measured by running things, never from what the model says about its own patch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from track3.agent.text_tools import changed_line_count

# Order matters: a later gate only means something if the earlier ones passed.
GATES = ("build", "repro", "regression", "hygiene")


@dataclass(frozen=True)
class Candidate:
    index: int
    patch: str
    # gate -> True (passed), False (failed), None (skipped, e.g. the bug could not be reproduced)
    gates: dict[str, bool | None] = field(default_factory=dict)

    @property
    def score(self) -> int:
        """Gates passed, in order, before the first failure. Skipped gates do not stop the count."""
        n = 0
        for g in GATES:
            if self.gates.get(g) is False:
                break
            n += 1
        return n

    @property
    def validated(self) -> bool:
        return all(self.gates.get(g) is not False for g in GATES)

    @property
    def size(self) -> int:
        return changed_line_count(self.patch)


def best_candidate(candidates: list[Candidate]) -> Candidate | None:
    """Most gates passed; then the smaller patch; then the later (more revised) candidate."""
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c.score, -c.size, c.index))
