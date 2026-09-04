"""Hybrid assessor: take each axis from whichever assessor measures it better.

Measured on the 23-item seed set (see bench-results/):

    assessor          specificity   ownership
    deterministic         74%          91%
    llm/gpt-4.1           83%          83%

The split is consistent and explainable rather than noise. The model reads
narrative structure the regex cannot pattern-match, so it wins on specificity.
Ownership turns on a small closed set of surface cues - confirmations, imported
self-labels - which regex matches exactly and models over-read as insight.

So: specificity from the model, ownership from the rules. This is not a
compromise, it is routing each axis to its better instrument.
"""

from __future__ import annotations

from ..domain.sufficiency import Assessment, SufficiencyComponents
from ..ports.assessor import SufficiencyAssessor
from .assessor_deterministic import DeterministicAssessor


class HybridAssessor:
    name = "hybrid"

    def __init__(self, llm_assessor: SufficiencyAssessor,
                 rule_assessor: SufficiencyAssessor | None = None):
        self.llm_assessor = llm_assessor
        self.rule_assessor = rule_assessor or DeterministicAssessor()

    def assess(self, text: str, prior: SufficiencyComponents) -> Assessment:
        model = self.llm_assessor.assess(text, prior)
        rules = self.rule_assessor.assess(text, prior)
        return Assessment(
            specificity=model.specificity,   # model reads narrative structure
            ownership=rules.ownership,       # rules read the closed cue set
            components=model.components.merge(rules.components),
            confidence=min(model.confidence, rules.confidence) + 0.1,
            assessor=self.name,
        )
