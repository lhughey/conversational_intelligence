"""Deterministic assessor: regex features, no network.

Conservative by construction - it under-calls S3 rather than over-calling it,
because a false S3 causes a premature advance, the failure this component
exists to prevent. Measured recall on the reference corpus is reported by the
benchmark, not asserted here.
"""

from __future__ import annotations

from ..domain.sufficiency import (
    Assessment, SufficiencyComponents, derive, extract_components,
)


class DeterministicAssessor:
    name = "deterministic"

    def assess(self, text: str, prior: SufficiencyComponents) -> Assessment:
        merged = prior.merge(extract_components(text))
        spec, own = derive(text, merged)
        return Assessment(
            specificity=spec, ownership=own, components=merged,
            confidence=0.5, assessor=self.name,
        )
