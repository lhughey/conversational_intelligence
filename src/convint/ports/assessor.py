"""The sufficiency-assessment port.

Two implementations ship: a deterministic one (no network, conservative) and a
model-backed one. They are interchangeable, which is what lets the benchmark
measure how much the model actually buys over regex.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.sufficiency import Assessment, SufficiencyComponents


@runtime_checkable
class SufficiencyAssessor(Protocol):
    def assess(self, text: str, prior: SufficiencyComponents) -> Assessment:
        """Assess one user turn, accumulating onto a topic's prior components."""
        ...
