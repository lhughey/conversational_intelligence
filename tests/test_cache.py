import pytest

from convint.adapters.cache import CachingLLM, CacheMiss
from convint.adapters.llm_fake import FakeLLM, request_key
from convint.ports.llm import LLMRequest


class _Model:
    def __init__(self, model_id, text):
        self.model_id = model_id
        self.inner = FakeLLM(default=text)
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return self.inner.complete(request)


def test_cache_hit_avoids_a_second_call(tmp_path):
    inner = _Model("m1", "hello")
    cache = CachingLLM(inner, tmp_path)
    r = LLMRequest(system="s")
    assert cache.complete(r).text == "hello"
    assert cache.complete(r).text == "hello"
    assert inner.calls == 1
    assert cache.stats() == {"hits": 1, "misses": 1}


def test_different_models_do_not_share_entries(tmp_path):
    """The bug this guards: two models sharing a key silently reports one
    model's answers under the other's name, corrupting a comparison."""
    a, b = _Model("model-a", "from-a"), _Model("model-b", "from-b")
    r = LLMRequest(system="same prompt")
    assert CachingLLM(a, tmp_path).complete(r).text == "from-a"
    assert CachingLLM(b, tmp_path).complete(r).text == "from-b"


def test_repetition_index_keeps_separate_entries(tmp_path):
    """No seed parameter exists, so N repetitions must not collapse into one
    entry - that would destroy the variance estimate."""
    r = LLMRequest(system="s")
    CachingLLM(_Model("m", "first"), tmp_path, rep=0).complete(r)
    second = CachingLLM(_Model("m", "second"), tmp_path, rep=1)
    assert second.complete(r).text == "second"
    assert second.stats()["misses"] == 1


def test_offline_mode_raises_instead_of_spending(tmp_path):
    with pytest.raises(CacheMiss, match="offline mode"):
        CachingLLM(_Model("m", "x"), tmp_path, mode="offline").complete(LLMRequest())


def test_off_mode_bypasses_the_cache(tmp_path):
    inner = _Model("m", "x")
    cache = CachingLLM(inner, tmp_path, mode="off")
    r = LLMRequest()
    cache.complete(r); cache.complete(r)
    assert inner.calls == 2


def test_unknown_mode_rejected(tmp_path):
    with pytest.raises(ValueError):
        CachingLLM(_Model("m", "x"), tmp_path, mode="sometimes")


def test_request_key_includes_the_model():
    r = LLMRequest(system="s")
    assert request_key(r, "a") != request_key(r, "b")


# --- never persist, never serve, an unusable response -----------------------

from convint.adapters.llm_anthropic import AnthropicLLM  # noqa: E402
from convint.ports.llm import LLMResponse, TruncatedResponse  # noqa: E402


class _Scripted:
    """An inner adapter that returns whatever it is told, without raising."""

    def __init__(self, *responses, model_id="m"):
        self.model_id = model_id
        self.responses = list(responses)
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return self.responses.pop(0)


def _files(tmp_path):
    return list(tmp_path.rglob("*.json"))


def test_truncation_raised_by_the_adapter_is_not_persisted(tmp_path):
    import types

    def create(**kwargs):
        return types.SimpleNamespace(
            model=kwargs["model"], stop_reason="max_tokens", stop_details=None,
            content=[types.SimpleNamespace(type="text", text="")],
            usage=types.SimpleNamespace(input_tokens=1364, output_tokens=400),
        )

    client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    cache = CachingLLM(AnthropicLLM("haiku-5-5", client=client), tmp_path)
    with pytest.raises(TruncatedResponse):
        cache.complete(LLMRequest(system="s", max_tokens=400))
    assert _files(tmp_path) == []


@pytest.mark.parametrize("bad", [
    LLMResponse(text=""),
    LLMResponse(text="  "),
    LLMResponse(text='{"scene": tr', stop_reason="max_tokens"),
    LLMResponse(text="I can't help", stop_reason="refusal"),
])
def test_write_guard_skips_unusable_responses_from_non_raising_inners(tmp_path, bad):
    inner = _Scripted(bad)
    assert CachingLLM(inner, tmp_path).complete(LLMRequest()) == bad
    assert _files(tmp_path) == []


def test_poisoned_empty_entry_is_a_miss_and_is_overwritten(tmp_path):
    """Self-healing: entries written before the guard existed get replaced."""
    r = LLMRequest(system="s")
    inner = _Scripted(LLMResponse(text="good", stop_reason="end_turn"))
    cache = CachingLLM(inner, tmp_path)
    path = cache._path(r)
    path.parent.mkdir(parents=True)
    path.write_text(LLMResponse(text="", usage={"output": 400}).model_dump_json())

    assert cache.complete(r).text == "good"
    assert inner.calls == 1
    assert cache.stats() == {"hits": 0, "misses": 1}
    assert LLMResponse.model_validate_json(path.read_text()).text == "good"
    assert cache.complete(r).text == "good"  # now a real hit
    assert cache.stats() == {"hits": 1, "misses": 1}


def test_poisoned_entry_in_offline_mode_raises_cache_miss(tmp_path):
    r = LLMRequest(system="s")
    cache = CachingLLM(_Scripted(), tmp_path, mode="offline")
    path = cache._path(r)
    path.parent.mkdir(parents=True)
    path.write_text(LLMResponse(text="").model_dump_json())
    with pytest.raises(CacheMiss):
        cache.complete(r)


def test_cache_key_ignores_thinking_headroom(tmp_path):
    """Headroom is added inside the adapter, after the key is computed from the
    LLMRequest, so entries cached before the headroom change stay valid hits."""
    import types

    sent = []

    def create(**kwargs):
        sent.append(kwargs["max_tokens"])
        return types.SimpleNamespace(
            model=kwargs["model"], stop_reason="end_turn", stop_details=None,
            content=[types.SimpleNamespace(type="text", text="hi")],
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    r = LLMRequest(system="s", max_tokens=300)
    cache = CachingLLM(AnthropicLLM("opus-5", client=client), tmp_path)
    expected = tmp_path / "claude-opus-5" / request_key(r, "claude-opus-5")[:2]
    cache.complete(r)
    assert sent[0] > 300
    assert len(_files(expected)) == 1
