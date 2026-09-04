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
