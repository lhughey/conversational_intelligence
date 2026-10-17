"""Anthropic adapter. The SDK import is lazy so core tests never need it."""

from __future__ import annotations

import time

from ..ports.llm import LLMRequest, LLMResponse, RefusedResponse, TruncatedResponse
from .models import ModelSpec, spec

#: Extra `max_tokens` granted to models that think by default, by effort.
#: `LLMRequest.max_tokens` means the VISIBLE-answer budget; on a thinking model
#: the thinking tokens are billed against the same `max_tokens` and are not
#: returned, so sending the answer budget alone let haiku-5-5 at effort=low
#: spend all 400 tokens thinking and return an empty text block. Deeper effort
#: thinks longer, hence the scaling. `max_tokens` is a ceiling, not a spend:
#: unused headroom costs nothing.
THINKING_HEADROOM: dict[str, int] = {
    "low": 2000,
    "medium": 4000,
    "high": 8000,
    "xhigh": 12000,
    "max": 16000,
}
#: Used when no effort is sent, i.e. the model runs at its API default, which is
#: `high` on most of the family - so assume the deep end.
DEFAULT_THINKING_HEADROOM = THINKING_HEADROOM["high"]
#: The SDK refuses a NON-streaming request whose max_tokens implies more than
#: ~10 minutes of generation (~21.3k tokens). Headroom never pushes past this.
NONSTREAMING_MAX_TOKENS = 21_000

#: Stop reasons that mean the answer was cut off rather than finished.
_TRUNCATING = {"max_tokens", "model_context_window_exceeded"}


def thinking_headroom(model: ModelSpec, effort: str | None) -> int:
    """Tokens added on top of the visible-answer budget. 0 for non-thinkers."""
    if not model.thinks:
        return 0
    if effort is None:
        return DEFAULT_THINKING_HEADROOM
    return THINKING_HEADROOM.get(effort, DEFAULT_THINKING_HEADROOM)


def effective_max_tokens(model: ModelSpec, requested: int, effort: str | None) -> int:
    headroom = thinking_headroom(model, effort)
    if not headroom:
        return requested
    return max(requested, min(requested + headroom, NONSTREAMING_MAX_TOKENS))


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, model: str | ModelSpec = "opus-5", client=None):
        self.spec = model if isinstance(model, ModelSpec) else spec(model)
        if self.spec.provider != "anthropic":
            raise ValueError(f"{self.spec.key} is not an Anthropic model")
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic  # lazy: keeps the core dependency-free

            from ..config import load

            load()  # this repo's .env, never a sibling project's

            # An unset ANTHROPIC_API_KEY does not mean no credentials; the SDK
            # resolves auth tokens and `ant auth login` profiles too.
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, request: LLMRequest) -> LLMResponse:
        budget = request.max_tokens or self.spec.max_tokens
        kwargs = {
            "model": self.spec.model_id,
            "max_tokens": budget,
            "system": request.system,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
                if m.role in ("user", "assistant")
            ],
        }
        output_config: dict = {}
        # Effort is a hint: dropped rather than fatal when the model lacks it,
        # since it changes depth but not meaning. Sampling is different - it is
        # validated at config load because it silently skews a comparison.
        effort = request.effort or self.spec.effort
        if effort and self.spec.supports_effort:
            output_config["effort"] = effort
        sent_effort = output_config.get("effort")
        kwargs["max_tokens"] = effective_max_tokens(self.spec, budget, sent_effort)
        if request.response_schema is not None:
            # Verified shape: output_config.format.type must be "json_schema".
            output_config["format"] = {
                "type": "json_schema", "schema": request.response_schema
            }
        if output_config:
            kwargs["output_config"] = output_config
        # Sampling, when the model supports it at all, must go through
        # `extra_body`: anthropic-sdk 1.x removed `temperature`/`top_p`/`top_k`
        # from messages.create() entirely, so passing them as keywords raises
        # TypeError before the request is ever made. Never sent for models that
        # reject the value server-side either (see models.py).
        if self.spec.supports_sampling and self.spec.temperature is not None:
            kwargs["extra_body"] = {"temperature": self.spec.temperature}

        started = time.monotonic()
        msg = self.client.messages.create(**kwargs)
        elapsed = int((time.monotonic() - started) * 1000)

        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        usage = {
            "input": getattr(msg.usage, "input_tokens", 0),
            "output": getattr(msg.usage, "output_tokens", 0),
        }
        model = getattr(msg, "model", self.spec.model_id)
        stop_reason = getattr(msg, "stop_reason", None)
        detail = dict(model=model, max_tokens=kwargs["max_tokens"], usage=usage,
                      stop_reason=stop_reason)

        # Never return an unusable answer: a caller would parse it and fail
        # obscurely, and a cache would persist it so every rerun fails the same.
        if stop_reason == "refusal":
            raise RefusedResponse(
                f"{model} refused the request (stop_reason=refusal, "
                f"stop_details={getattr(msg, 'stop_details', None)!r}, usage={usage})",
                **detail,
            )
        if stop_reason in _TRUNCATING:
            raise TruncatedResponse(
                f"{model} stopped at stop_reason={stop_reason} with max_tokens="
                f"{kwargs['max_tokens']} (answer budget {budget}, usage={usage}); "
                "on a thinking model the thinking counts against max_tokens. "
                "Raise the request's max_tokens or the thinking headroom.",
                **detail,
            )
        if not text.strip():
            raise TruncatedResponse(
                f"{model} returned no text (stop_reason={stop_reason}, max_tokens="
                f"{kwargs['max_tokens']}, usage={usage})",
                **detail,
            )
        return LLMResponse(
            text=text,
            model=model,
            usage=usage,
            latency_ms=elapsed,
            stop_reason=stop_reason,
        )
