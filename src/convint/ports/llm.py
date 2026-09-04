"""The LLM port. Everything that touches a network lives behind this.

The domain never imports it; only adapters implement it and only the app layer
calls it. That is what makes the whole gate testable with no API key.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMRequest(BaseModel):
    system: str = ""
    messages: list[LLMMessage] = Field(default_factory=list)
    max_tokens: int = 512
    #: "low" | "medium" | "high" | "xhigh" | "max" - depth, since sampling is not tunable
    effort: str | None = None
    #: JSON Schema for structured output, when the caller needs a parseable answer
    response_schema: dict | None = None


class LLMResponse(BaseModel):
    text: str
    model: str = ""
    usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: int = 0


@runtime_checkable
class LLMPort(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...
