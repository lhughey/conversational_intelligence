"""Content-addressed response cache.

Two jobs. It makes re-scoring free - change a metric, re-run the evaluation, pay
nothing - and it makes a benchmark reproducible without re-spending. Both matter
more than usual here, because credit exhaustion mid-run is a real failure mode
we have already hit.

Keyed on the canonical request plus a repetition index. The index exists because
there is NO seed parameter on Anthropic: N identical requests must produce N
distinct entries, or repeated sampling collapses into one and destroys the
variance estimate.
"""

from __future__ import annotations

import json
import pathlib

from ..ports.llm import LLMRequest, LLMResponse
from .llm_fake import request_key

DEFAULT_DIR = pathlib.Path("cache")

#: Stop reasons whose response is not an answer and must never be served or
#: stored. Adapters raise on these before returning; this is the second line.
_UNUSABLE_STOPS = {"max_tokens", "model_context_window_exceeded", "refusal"}


def usable(response: LLMResponse) -> bool:
    """False for a response that must not be cached: empty, cut off, declined.

    A persisted bad response is worse than a failed call - every rerun replays
    it for free, so the failure looks deterministic and never self-corrects.
    """
    return bool(response.text.strip()) and response.stop_reason not in _UNUSABLE_STOPS


class CacheMiss(RuntimeError):
    pass


class CachingLLM:
    """Wraps any LLMPort.

    mode="rw"      read, and write through on a miss (default)
    mode="off"     bypass entirely; always call the inner adapter
    mode="offline" read only; a miss raises instead of spending money
    """

    def __init__(self, inner, directory: pathlib.Path | str = DEFAULT_DIR,
                 mode: str = "rw", rep: int = 0):
        if mode not in {"rw", "off", "offline"}:
            raise ValueError(f"unknown cache mode {mode!r}")
        self.inner = inner
        self.dir = pathlib.Path(directory)
        self.mode = mode
        self.rep = rep
        self.hits = 0
        self.misses = 0

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", "inner")

    def _model_id(self) -> str:
        """Model identity MUST be part of the key.

        Without it two models share entries and a comparison silently reports
        one model's answers under the other's name - which corrupts precisely
        the measurement this cache exists to make cheap.
        """
        spec = getattr(self.inner, "spec", None)
        if spec is not None:
            return spec.model_id
        return getattr(self.inner, "model_id", getattr(self.inner, "name", "unknown"))

    def _path(self, request: LLMRequest) -> pathlib.Path:
        key = request_key(request, self._model_id())
        return self.dir / self._model_id() / key[:2] / f"{key}-r{self.rep}.json"

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self.mode == "off":
            return self.inner.complete(request)

        path = self._path(request)
        if path.exists():
            cached = LLMResponse.model_validate_json(path.read_text(encoding="utf-8"))
            # A poisoned entry (written before the write guard existed) is a
            # miss, and the fresh answer below overwrites it: self-healing.
            if usable(cached):
                self.hits += 1
                return cached

        self.misses += 1
        if self.mode == "offline":
            raise CacheMiss(
                f"cache miss for {path.name} in offline mode. "
                "Run once with --cache=rw to populate it."
            )

        response = self.inner.complete(request)
        if not usable(response):
            # Adapters raise before reaching here; an inner that does not
            # (fake, OpenAI) still never gets its bad answer persisted.
            return response
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(), encoding="utf-8")
        return response

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
