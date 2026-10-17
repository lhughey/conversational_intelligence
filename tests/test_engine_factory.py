"""build_engine: server-side configuration decides the models. Offline - the
socket block in conftest proves construction makes no network call."""

import pytest

from convint import config
from convint.adapters.assessor_deterministic import DeterministicAssessor
from convint.adapters.assessor_hybrid import HybridAssessor
from convint.adapters.assessor_llm import LLMAssessor
from convint.adapters.cache import CachingLLM
from convint.adapters.llm_anthropic import AnthropicLLM
from convint.adapters.llm_openai import OpenAILLM
from convint.api.cli import main as cli_main
from convint.api.contract import Options, TurnRequest
from convint.app.engine_factory import (
    DEFAULT_ASSESSOR, DEFAULT_MODEL, build_engine, parse_assessor_spec,
)
from convint.app.metering import MeteredLLM
from convint.bench import gate_eval
from convint.domain import ConversationState, InterviewPlan, StageSpec, TopicRecord, TopicSpec, Turn

CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY")


@pytest.fixture
def env(monkeypatch):
    """A clean slate: no credentials, no CONVINT_* overrides. .env is applied
    first so it cannot re-add what is removed here."""
    config.load()
    for name in CREDENTIAL_VARS + ("CONVINT_ASSESSOR", "CONVINT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _request():
    return TurnRequest(
        plan=InterviewPlan(
            plan_id="p", stages=[StageSpec(stage_id="early_life")],
            topics=[TopicSpec(topic_id="childhood", stage="early_life")],
        ),
        state=ConversationState(
            turns=[Turn(role="user", content="I helped at my parents' shop.")],
            topics=[TopicRecord(topic_id="childhood", stage="early_life")],
            current_topic_id="childhood",
        ),
        options=Options(generate_text=False),
    )


def test_defaults_are_the_recommended_hybrid_and_haiku(env):
    env.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    engine = build_engine()
    assert DEFAULT_ASSESSOR == "hybrid:haiku-4-5" and DEFAULT_MODEL == "haiku-4-5"
    assert isinstance(engine.assessor, HybridAssessor)
    assert engine.assessor.name == "hybrid/haiku-4-5"
    assert engine.assessor_model == "claude-haiku-4-5"
    assert engine.llm.model_id == "claude-haiku-4-5"
    assert engine.startup_warnings == []


def test_serving_path_meters_but_never_caches(env):
    """The response cache is a bench tool, not a serving path."""
    env.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    engine = build_engine()
    inner = engine.assessor.llm_assessor.llm
    assert isinstance(inner, MeteredLLM) and isinstance(inner.inner, AnthropicLLM)
    assert isinstance(engine.llm, MeteredLLM) and isinstance(engine.llm.inner, AnthropicLLM)


def test_bench_make_assessor_still_caches():
    assessor = gate_eval.make_assessor("llm:haiku-4-5")
    assert assessor.name == "llm/haiku-4-5"
    assert isinstance(assessor.llm, CachingLLM)


def test_env_selects_assessor_and_model(env):
    env.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    env.setenv("CONVINT_ASSESSOR", "llm:sonnet-5")
    env.setenv("CONVINT_MODEL", "opus-5")
    engine = build_engine()
    assert isinstance(engine.assessor, LLMAssessor)
    assert engine.assessor.name == "llm/sonnet-5"
    assert engine.llm.model_id == "claude-opus-5"


def test_explicit_arguments_override_env(env):
    env.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    env.setenv("CONVINT_ASSESSOR", "llm:sonnet-5")
    env.setenv("CONVINT_MODEL", "opus-5")
    engine = build_engine(assessor="deterministic", model="none")
    assert isinstance(engine.assessor, DeterministicAssessor)
    assert engine.llm is None and engine.assessor_model is None


def test_model_none_disables_generation(env):
    env.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    env.setenv("CONVINT_MODEL", "none")
    engine = build_engine()
    assert engine.llm is None
    assert engine.model_backed_assessor  # the assessor is configured separately


def test_deterministic_config_is_a_choice_not_a_degradation(env):
    engine = build_engine(assessor="deterministic", model="none")
    assert engine.startup_warnings == []
    resp = engine.run(_request())
    assert resp.diagnostics.degraded is False and resp.diagnostics.warnings == []


def test_missing_credential_degrades_with_a_warning_on_every_response(env):
    engine = build_engine()
    assert isinstance(engine.assessor, DeterministicAssessor)
    assert engine.llm is None
    assert [w.split(":")[0] for w in engine.startup_warnings] == [
        "assessor_degraded", "model_degraded",
    ]
    for _ in range(2):
        diag = engine.run(_request()).diagnostics
        assert diag.degraded is True
        assert diag.warnings == engine.startup_warnings
        assert diag.assessor == "deterministic"


def test_degradation_is_per_provider(env):
    """An Anthropic key does not cover an OpenAI generator, and vice versa."""
    env.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    engine = build_engine(model="gpt-4.1")
    assert engine.assessor.name == "hybrid/haiku-4-5"
    assert engine.llm is None
    assert len(engine.startup_warnings) == 1
    assert engine.startup_warnings[0].startswith("model_degraded: no openai credential")

    env.setenv("OPENAI_API_KEY", "sk-test-not-real")
    engine = build_engine(model="gpt-4.1")
    assert isinstance(engine.llm.inner, OpenAILLM) and engine.startup_warnings == []


def test_auth_token_counts_as_an_anthropic_credential(env):
    env.setenv("ANTHROPIC_AUTH_TOKEN", "tok-test-not-real")
    assert build_engine().startup_warnings == []


@pytest.mark.parametrize("bad", ["", "llm", "llm:", "gpt:haiku-4-5", "hybrid"])
def test_invalid_assessor_spec_is_a_clear_error(env, bad):
    with pytest.raises(ValueError, match="unknown assessor"):
        build_engine(assessor=bad or " ")


def test_unknown_model_key_is_a_clear_error(env):
    with pytest.raises(ValueError, match="CONVINT_ASSESSOR: unknown model key 'nope'"):
        build_engine(assessor="hybrid:nope")
    env.setenv("CONVINT_MODEL", "nope")
    with pytest.raises(ValueError, match="CONVINT_MODEL: unknown model key 'nope'"):
        build_engine(assessor="deterministic")


def test_parse_assessor_spec():
    assert parse_assessor_spec("deterministic") == ("deterministic", None)
    assert parse_assessor_spec("llm:haiku-5-5") == ("llm", "haiku-5-5")
    assert parse_assessor_spec(" hybrid:opus-5 ") == ("hybrid", "opus-5")


def test_cli_rejects_an_invalid_assessor_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["turn", "--assessor", "gpt:x"])
    assert exc.value.code == 2
    assert "unknown assessor" in capsys.readouterr().err
