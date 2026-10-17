"""Provider adapters, exercised with injected fake clients. No network."""

import re
import types

import pytest

from convint.adapters.llm_anthropic import AnthropicLLM
from convint.adapters.llm_openai import OpenAILLM
from convint.adapters.models import REGISTRY, ModelSpec, cost_usd, spec
from convint.ports.llm import LLMMessage, LLMPort, LLMRequest


# --- capability validation -------------------------------------------------

@pytest.mark.parametrize(
    "key", ["opus-5", "opus-4-8", "sonnet-5", "opus-5-5", "sonnet-5-5", "fable-5-1",
            "haiku-5-5"]
)
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
    assert cost_usd(spec("sonnet-5"), {"input": 0, "output": 1_000_000}) == pytest.approx(10.0)
    assert cost_usd(spec("opus-5-5"), {"input": 1_000_000, "output": 1_000_000}) == pytest.approx(
        24.0
    )
    # <=100k-token prompt tier; the >100k tier is not modelled.
    assert cost_usd(spec("haiku-5-5"), {"input": 1_000_000, "output": 1_000_000}) == pytest.approx(
        0.60
    )


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


def test_opus_5_5_defaults_to_high_effort_not_its_api_default():
    """opus-5-5's API default effort is `medium`; opus-5 ran at its default
    `high`. The spec pins `high` so the two are benchmarked at the same depth
    when the caller does not set effort itself (the generator path)."""
    fake = _FakeAnthropic()
    req = LLMRequest(system="sys", messages=[LLMMessage(role="user", content="hi")])
    AnthropicLLM("opus-5-5", client=fake).complete(req)
    assert fake.kwargs["output_config"] == {"effort": "high"}
    assert fake.kwargs["model"] == "claude-opus-5-5"


def test_request_effort_still_overrides_the_opus_5_5_spec_default():
    fake = _FakeAnthropic()
    AnthropicLLM("opus-5-5", client=fake).complete(_request())
    assert fake.kwargs["output_config"] == {"effort": "low"}


def test_haiku_5_5_sends_effort_unlike_haiku_4_5():
    """haiku-4-5 400s on effort, so the adapter drops it; haiku-5-5 supports
    it, so the same request must carry it."""
    fake = _FakeAnthropic()
    AnthropicLLM("haiku-5-5", client=fake).complete(_request())
    assert fake.kwargs["output_config"] == {"effort": "low"}
    assert fake.kwargs["model"] == "claude-haiku-5-5"
    assert "extra_body" not in fake.kwargs

    fake = _FakeAnthropic()
    AnthropicLLM("haiku-4-5", client=fake).complete(_request())
    assert "output_config" not in fake.kwargs


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


# --- unusable responses and thinking headroom -------------------------------

from convint.adapters.llm_anthropic import (  # noqa: E402
    NONSTREAMING_MAX_TOKENS, THINKING_HEADROOM, effective_max_tokens,
)
from convint.ports.llm import (  # noqa: E402
    IncompleteResponse, RefusedResponse, TruncatedResponse,
)


class _ScriptedAnthropic(_FakeAnthropic):
    """Returns a chosen text and stop_reason, as the 5.x models can."""

    def __init__(self, text="ok", stop_reason="end_turn", output_tokens=4):
        super().__init__()
        self.text, self.stop_reason, self.output_tokens = text, stop_reason, output_tokens

    def _create(self, **kwargs):
        self.kwargs = kwargs
        content = [types.SimpleNamespace(type="thinking", thinking="")]
        if self.text is not None:
            content.append(types.SimpleNamespace(type="text", text=self.text))
        return types.SimpleNamespace(
            model=kwargs["model"], content=content, stop_reason=self.stop_reason,
            stop_details=None,
            usage=types.SimpleNamespace(input_tokens=1364, output_tokens=self.output_tokens),
        )


def test_max_tokens_stop_raises_truncated_with_details():
    """The live haiku-5-5 failure: thinking consumed the whole budget."""
    fake = _ScriptedAnthropic(text='{"scene": tr', stop_reason="max_tokens", output_tokens=400)
    with pytest.raises(TruncatedResponse) as exc:
        AnthropicLLM("haiku-5-5", client=fake).complete(_request())
    err = exc.value
    assert err.model == "claude-haiku-5-5"
    assert err.max_tokens == fake.kwargs["max_tokens"]
    assert err.usage == {"input": 1364, "output": 400}
    assert err.stop_reason == "max_tokens"
    assert "max_tokens" in str(err)


def test_context_window_stop_also_raises_truncated():
    fake = _ScriptedAnthropic(stop_reason="model_context_window_exceeded")
    with pytest.raises(TruncatedResponse):
        AnthropicLLM("opus-5", client=fake).complete(_request())


@pytest.mark.parametrize("text", ["", "   \n", None])
def test_empty_text_raises_even_on_end_turn(text):
    fake = _ScriptedAnthropic(text=text, stop_reason="end_turn")
    with pytest.raises(TruncatedResponse, match="no text"):
        AnthropicLLM("haiku-5-5", client=fake).complete(_request())


def test_refusal_raises_its_own_type():
    fake = _ScriptedAnthropic(text="", stop_reason="refusal")
    with pytest.raises(RefusedResponse) as exc:
        AnthropicLLM("opus-5-5", client=fake).complete(_request())
    assert not isinstance(exc.value, TruncatedResponse)
    assert isinstance(exc.value, IncompleteResponse)


def test_complete_response_carries_stop_reason():
    resp = AnthropicLLM("opus-5", client=_ScriptedAnthropic()).complete(_request())
    assert resp.text == "ok"
    assert resp.stop_reason == "end_turn"


def test_thinking_model_gets_headroom_scaled_by_effort():
    """LLMRequest.max_tokens is the visible-answer budget; thinking is extra."""
    fake = _FakeAnthropic()
    AnthropicLLM("haiku-5-5", client=fake).complete(_request())  # effort=low
    assert fake.kwargs["max_tokens"] == 50 + THINKING_HEADROOM["low"]

    fake = _FakeAnthropic()
    req = LLMRequest(messages=[LLMMessage(role="user", content="hi")], max_tokens=900)
    AnthropicLLM("opus-5-5", client=fake).complete(req)  # spec pins effort=high
    assert fake.kwargs["max_tokens"] == 900 + THINKING_HEADROOM["high"]


@pytest.mark.parametrize("key", ["opus-5", "sonnet-5", "opus-5-5", "sonnet-5-5",
                                 "haiku-5-5", "fable-5-1"])
def test_5x_models_are_marked_as_thinking(key):
    assert REGISTRY[key].thinks


@pytest.mark.parametrize("key", ["haiku-4-5", "opus-4-8", "gpt-4.1", "gpt-4.1-mini"])
def test_non_thinking_models_get_no_headroom(key):
    assert not REGISTRY[key].thinks
    assert effective_max_tokens(REGISTRY[key], 400, "low") == 400


def test_haiku_4_5_request_budget_is_sent_unchanged():
    fake = _FakeAnthropic()
    AnthropicLLM("haiku-4-5", client=fake).complete(_request())
    assert fake.kwargs["max_tokens"] == 50


def test_headroom_never_exceeds_the_nonstreaming_ceiling():
    s = REGISTRY["opus-5"]
    assert effective_max_tokens(s, 900, "max") <= NONSTREAMING_MAX_TOKENS
    # ...but never shrinks a budget the caller asked for explicitly.
    assert effective_max_tokens(s, 30_000, "max") == 30_000


def test_openai_maps_finish_reason_and_does_not_raise():
    """OpenAI path unaffected: same text, now with a normalised stop_reason."""
    class _Truncating(_FakeOpenAI):
        def _create(self, **kwargs):
            resp = super()._create(**kwargs)
            resp.choices[0].finish_reason = "length"
            return resp

    fake = _Truncating()
    resp = OpenAILLM(client=fake).complete(_request())
    assert resp.text == "ok?"
    assert resp.stop_reason == "max_tokens"
    assert fake.kwargs["max_completion_tokens"] == 50
    assert OpenAILLM(client=_FakeOpenAI()).complete(_request()).stop_reason is None
