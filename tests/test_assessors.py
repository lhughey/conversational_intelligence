"""LLM and hybrid assessors, driven by fakes."""

import json

import pytest

from convint.adapters.assessor_deterministic import DeterministicAssessor
from convint.adapters.assessor_hybrid import HybridAssessor
from convint.adapters.assessor_llm import SCHEMA, LLMAssessor
from convint.adapters.llm_fake import FakeLLM
from convint.domain import Ownership, Specificity
from convint.domain.sufficiency import SufficiencyComponents
from convint.ports.assessor import SufficiencyAssessor


def _payload(**over):
    base = dict(specificity="S3", ownership="O0", scene=True, stakes=True,
                action=True, outcome=True, reflection=False, evidence="quote")
    base.update(over)
    return json.dumps(base)


def test_llm_assessor_parses_structured_output():
    a = LLMAssessor(FakeLLM(default=_payload()))
    r = a.assess("some episode", SufficiencyComponents())
    assert r.specificity is Specificity.S3 and r.ownership is Ownership.O0
    assert r.assessor == "llm"


def test_llm_assessor_sends_a_response_schema():
    """Structured output by construction, not by asking the model nicely."""
    fake = FakeLLM(default=_payload())
    LLMAssessor(fake).assess("x", SufficiencyComponents())
    assert fake.calls[0].response_schema == SCHEMA


def test_llm_assessor_accumulates_prior_components():
    a = LLMAssessor(FakeLLM(default=_payload(specificity="S1", scene=False, stakes=False,
                                             action=False, outcome=False)))
    prior = SufficiencyComponents(scene=True, stakes=True, action=True, outcome=True)
    r = a.assess("thin turn", prior)
    # a thin turn must not erase an episode already established on the topic
    assert r.specificity is Specificity.S3


def test_llm_assessor_rejects_unparseable_output():
    a = LLMAssessor(FakeLLM(default="not json"))
    with pytest.raises(ValueError, match="unparseable"):
        a.assess("x", SufficiencyComponents())


def test_assessors_satisfy_the_port():
    assert isinstance(DeterministicAssessor(), SufficiencyAssessor)
    assert isinstance(LLMAssessor(FakeLLM(default=_payload())), SufficiencyAssessor)
    assert isinstance(HybridAssessor(LLMAssessor(FakeLLM(default=_payload()))), SufficiencyAssessor)


def test_hybrid_routes_each_axis_to_its_better_instrument():
    """Measured: the model wins specificity, the rules win ownership."""
    llm = LLMAssessor(FakeLLM(default=_payload(specificity="S3", ownership="O2")))
    hybrid = HybridAssessor(llm)
    # "Yes. That lands." is a confirmation: rules call it O1, the model O2.
    r = hybrid.assess("Yes. That lands. That's me.", SufficiencyComponents())
    assert r.specificity is Specificity.S3    # from the model
    assert r.ownership is Ownership.O1        # from the rules
    assert r.assessor == "hybrid"
