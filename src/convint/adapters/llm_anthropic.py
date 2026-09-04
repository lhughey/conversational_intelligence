"""Anthropic adapter. The SDK import is lazy so core tests never need it."""

from __future__ import annotations

import time

from ..ports.llm import LLMRequest, LLMResponse
from .models import ModelSpec, spec


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
        kwargs = {
            "model": self.spec.model_id,
            "max_tokens": request.max_tokens or self.spec.max_tokens,
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
        return LLMResponse(
            text=text,
            model=getattr(msg, "model", self.spec.model_id),
            usage={
                "input": getattr(msg.usage, "input_tokens", 0),
                "output": getattr(msg.usage, "output_tokens", 0),
            },
            latency_ms=elapsed,
        )
