"""Provider adapters, exercised with injected fake clients. No network."""

import re
import types

import pytest

from convint.adapters.llm_anthropic import AnthropicLLM
from convint.adapters.llm_openai import OpenAILLM
from convint.adapters.models import REGISTRY, ModelSpec, cost_usd, spec
from convint.ports.llm import LLMMessage, LLMPort, LLMRequest


# --- capability validation -------------------------------------------------

@pytest.mark.parametrize("key", ["opus-5", "opus-4-8", "sonnet-5"])
@pytest.mark.parametrize("temp", [0, 0.3, 0.7, 1.0])
def test_sampling_is_rejected_at_config_load_not_request_time(key, temp):
    """Measured: these models 400 on any non-default temperature. Catching it
    here keeps a model matrix from being silently unfair."""
    with pytest.raises(ValueError, match="does not support"):
        spec(key, temperature=temp)


def test_haiku_still_supports_sampling():
    assert spec("haiku-4-5", temperature=0.7).temperature == 0.7


def test_unknown_model_key_is_rejected():
    with pytest.raises(KeyError):
        spec("gpt-9")


def test_model_ids_are_never_date_suffixed():
    """Date suffixes are a stale-training-data habit and 404 on these models."""
    for m in REGISTRY.values():
        assert not re.search(r"-20\d{6}$", m.model_id), m.model_id


def test_cost_is_computed_from_usage():
    assert cost_usd(spec("opus-5"), {"input": 1_000_000, "output": 0}) == pytest.approx(5.0)
    assert cost_usd(spec("sonnet-5"), {"input": 0, "output": 1_000_000}) == pytest.approx(15.0)


def test_adapters_satisfy_the_port():
    assert isinstance(AnthropicLLM("opus-5", client=object()), LLMPort)
    assert isinstance(OpenAILLM(client=object()), LLMPort)


def test_constructing_an_adapter_does_not_build_a_client():
    """Lazy auth: importing or constructing must not require credentials."""
    adapter = AnthropicLLM("opus-5")
    assert adapter._client is None


def test_non_anthropic_key_rejected_by_anthropic_adapter():
    with pytest.raises(ValueError):
        AnthropicLLM(ModelSpec(key="x", provider="openai", model_id="gpt", supports_sampling=True))


# --- request shaping -------------------------------------------------------

class _FakeAnthropic:
    def __init__(self):
        self.kwargs = None
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return types.SimpleNamespace(
            model=kwargs["model"],
            content=[types.SimpleNamespace(type="text", text="Which shop?")],
            usage=types.SimpleNamespace(input_tokens=11, output_tokens=4),
        )


def _request():
    return LLMRequest(
        system="sys", messages=[LLMMessage(role="user", content="hi")],
        max_tokens=50, effort="low",
    )


def test_anthropic_never_sends_sampling_for_unsupported_models():
    fake = _FakeAnthropic()
    AnthropicLLM("opus-5", client=fake).complete(_request())
    assert "temperature" not in fake.kwargs
    assert "top_p" not in fake.kwargs
    assert "extra_body" not in fake.kwargs


def test_anthropic_sends_effort_as_output_config():
    """Effort is the depth lever, since sampling is unavailable."""
    fake = _FakeAnthropic()
    AnthropicLLM("opus-5", client=fake).complete(_request())
    assert fake.kwargs["output_config"] == {"effort": "low"}


def test_anthropic_sends_sampling_through_extra_body_when_supported():
    """anthropic-sdk 1.x removed temperature/top_p/top_k from messages.create(),
    so a keyword raises TypeError before the request is made. The only route
    left is extra_body - and only for the one model that still allows it."""
    fake = _FakeAnthropic()
    AnthropicLLM(spec("haiku-4-5", temperature=0.4), client=fake).complete(_request())
    assert fake.kwargs["extra_body"] == {"temperature": 0.4}
    assert "temperature" not in fake.kwargs


def test_sdk_no_longer_accepts_sampling_keywords():
    """Guards the reason for the extra_body indirection: if a future SDK
    reinstates these, this test fails and the workaround can be removed."""
    import inspect

    import anthropic

    params = inspect.signature(anthropic.Anthropic().messages.create).parameters
    assert "temperature" not in params
    assert "top_p" not in params


def test_anthropic_parses_text_and_usage():
    resp = AnthropicLLM("opus-5", client=_FakeAnthropic()).complete(_request())
    assert resp.text == "Which shop?"
    assert resp.usage == {"input": 11, "output": 4}
    assert resp.model == "claude-opus-5"


def test_instruction_pseudo_role_is_not_sent_to_the_provider():
    """The generator appends an [instruction] turn; only real roles go on the wire."""
    fake = _FakeAnthropic()
    req = LLMRequest(messages=[
        LLMMessage(role="user", content="hi"),
        LLMMessage(role="system", content="should be dropped"),
    ])
    AnthropicLLM("opus-5", client=fake).complete(req)
    assert [m["role"] for m in fake.kwargs["messages"]] == ["user"]


class _FakeOpenAI:
    def __init__(self):
        self.kwargs = None
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return types.SimpleNamespace(
            model=kwargs["model"],
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok?"))],
            usage=types.SimpleNamespace(prompt_tokens=7, completion_tokens=2),
        )


def test_openai_maps_system_to_developer_role():
    fake = _FakeOpenAI()
    OpenAILLM(client=fake).complete(_request())
    assert fake.kwargs["messages"][0]["role"] == "developer"


def test_openai_parses_text_and_usage():
    resp = OpenAILLM(client=_FakeOpenAI()).complete(_request())
    assert resp.text == "ok?"
    assert resp.usage == {"input": 7, "output": 2}
