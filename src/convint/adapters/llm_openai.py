"""OpenAI adapter. Lazy import, same contract as the Anthropic one."""

from __future__ import annotations

import time

from ..ports.llm import LLMRequest, LLMResponse


class OpenAILLM:
    name = "openai"

    def __init__(self, model_id: str = "gpt-4.1", client=None, temperature: float | None = None):
        self.model_id = model_id
        self.temperature = temperature
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import openai  # lazy

            self._client = openai.OpenAI()
        return self._client

    def complete(self, request: LLMRequest) -> LLMResponse:
        messages = [{"role": "developer", "content": request.system}] if request.system else []
        messages += [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        kwargs = {
            "model": self.model_id,
            "messages": messages,
            "max_completion_tokens": request.max_tokens,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if request.response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "assessment", "strict": True, "schema": request.response_schema
                },
            }

        started = time.monotonic()
        resp = self.client.chat.completions.create(**kwargs)
        elapsed = int((time.monotonic() - started) * 1000)

        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            model=getattr(resp, "model", self.model_id),
            usage={
                "input": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "output": getattr(usage, "completion_tokens", 0) if usage else 0,
            },
            latency_ms=elapsed,
        )
