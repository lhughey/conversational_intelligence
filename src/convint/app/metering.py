"""Per-turn usage metering for model calls.

One TurnEngine serves concurrent requests (FastAPI runs sync endpoints in a
threadpool), so a turn's usage cannot live on the engine or on an adapter. A
ContextVar holds the current turn's meter; `MeteredLLM` adds each call's usage
to whichever meter is active and is a plain pass-through when none is.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Iterator

from ..adapters.models import REGISTRY, ModelSpec, cost_usd
from ..ports.llm import IncompleteResponse, LLMPort, LLMRequest, LLMResponse


class UsageMeter:
    """Token usage and USD cost summed over one turn's model calls."""

    def __init__(self) -> None:
        self.usage: dict[str, int] = {}
        self.calls = 0
        self._cost = 0.0
        self._cost_known = True

    def record(self, spec: ModelSpec | None, usage: dict[str, int]) -> None:
        self.calls += 1
        for key, value in usage.items():
            self.usage[key] = self.usage.get(key, 0) + int(value)
        if spec is None:
            self._cost_known = False
        else:
            self._cost += cost_usd(spec, usage)

    @property
    def cost_usd(self) -> float | None:
        """0.0 when nothing was called; None when any called model is unpriced."""
        return round(self._cost, 8) if self._cost_known else None


_current: ContextVar[UsageMeter | None] = ContextVar("convint_usage_meter", default=None)


@contextlib.contextmanager
def metering() -> Iterator[UsageMeter]:
    meter = UsageMeter()
    token = _current.set(meter)
    try:
        yield meter
    finally:
        _current.reset(token)


def spec_for(llm: object) -> ModelSpec | None:
    """The registry spec behind an adapter, looking through wrappers."""
    seen = 0
    while llm is not None and seen < 8:
        found = getattr(llm, "spec", None)
        if isinstance(found, ModelSpec):
            return found
        model_id = getattr(llm, "model_id", None)
        if isinstance(model_id, str):
            for candidate in REGISTRY.values():
                if candidate.model_id == model_id:
                    return candidate
        llm = getattr(llm, "inner", None)
        seen += 1
    return None


class MeteredLLM:
    """LLMPort wrapper that reports usage to the active turn meter."""

    def __init__(self, inner: LLMPort, spec: ModelSpec | None = None):
        self.inner = inner
        self.spec = spec or spec_for(inner)

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", type(self.inner).__name__)

    @property
    def model_id(self) -> str:
        if self.spec is not None:
            return self.spec.model_id
        return getattr(self.inner, "model_id", None) or self.name

    def complete(self, request: LLMRequest) -> LLMResponse:
        meter = _current.get()
        try:
            response = self.inner.complete(request)
        except IncompleteResponse as exc:
            # A truncated or refused answer was still billed.
            if meter is not None and exc.usage:
                meter.record(self.spec, exc.usage)
            raise
        if meter is not None:
            meter.record(self.spec, response.usage)
        return response
