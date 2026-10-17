"""Offline tests for the cascade trigger / escalation logic (pure functions)."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from convint.domain.enums import Specificity as S

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "cascade_analysis.py"
_spec = importlib.util.spec_from_file_location("cascade_analysis", _PATH)
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


def test_neighbors_clip_at_the_ends():
    assert ca.neighbors(S.S0) == [S.S1]
    assert ca.neighbors(S.S2) == [S.S1, S.S3]
    assert ca.neighbors(S.S3) == [S.S2]


def test_oracle_and_disagree_triggers():
    assert ca.oracle_trigger(S.S2, S.S3) and not ca.oracle_trigger(S.S3, S.S3)
    assert ca.disagree_trigger(S.S1, S.S2) and not ca.disagree_trigger(S.S1, S.S1)


def test_boundary_trigger_fires_only_next_to_a_decision_flip():
    passes_at_s3 = lambda s: s.rank >= 3  # noqa: E731
    assert ca.boundary_trigger(S.S2, passes_at_s3)      # S2 -> S3 flips
    assert ca.boundary_trigger(S.S3, passes_at_s3)      # S3 -> S2 flips
    assert not ca.boundary_trigger(S.S0, passes_at_s3)  # S1 still fails
    assert not ca.boundary_trigger(S.S1, lambda s: "same")


def test_cascade_takes_strong_only_where_escalated():
    cheap = [S.S1, S.S2, S.S3]
    strong = [S.S0, S.S3, S.S2]
    assert ca.cascade(cheap, strong, [False, True, False]) == [S.S1, S.S3, S.S3]
    with pytest.raises(ValueError):
        ca.cascade(cheap, strong, [True])


def test_triggers_build_every_mask_and_union():
    cheap = [S.S2, S.S1, S.S3]
    gold = [S.S3, S.S1, S.S3]
    rule = [S.S2, S.S2, S.S3]
    decide = lambda s: s.rank >= 3  # noqa: E731
    m = ca.triggers(cheap, gold, rule, [decide] * 3)
    assert m["cheap"] == [False] * 3 and m["strong"] == [True] * 3
    assert m["oracle"] == [True, False, False]
    assert m["disagree"] == [False, True, False]
    assert m["boundary"] == [True, False, True]
    assert m["union"] == [True, True, True]
    assert set(m) == set(ca.POLICY_NAMES)


def test_expected_cost():
    assert ca.expected_cost("cheap", 0.0, 1.0, 10.0) == 1.0
    assert ca.expected_cost("oracle", 0.25, 1.0, 10.0) == 3.5
    assert ca.expected_cost("strong", 1.0, 1.0, 10.0) == 10.0


class _FakeLLM:
    """Records calls; any call here would be a live call in the real script."""
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        raise AssertionError("must not be reached in offline mode")


def test_collect_counts_misses_and_never_calls_inner(tmp_path, monkeypatch):
    import convint.adapters.models as models

    fake = _FakeLLM()
    fake.model_id = "fake-model"
    monkeypatch.setattr(models, "build_llm", lambda key: fake)
    from convint.adapters import cache as cache_mod

    real = cache_mod.CachingLLM
    monkeypatch.setattr(cache_mod, "CachingLLM",
                        lambda inner, mode: real(inner, directory=tmp_path, mode=mode))
    got = ca.collect("haiku-4-5", ["a turn", "another turn"])
    assert got["missing"] == 2 and got["misses"] == 2 and got["hits"] == 0
    assert fake.calls == 0 and got["specs"] == {} and got["cost_per_call"] is None
