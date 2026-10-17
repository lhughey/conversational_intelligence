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
    #: Provider stop reason, normalised to Anthropic's vocabulary ("end_turn",
    #: "max_tokens", "refusal", ...). None when the adapter does not report one
    #: (the fake) - absence is not evidence of truncation.
    stop_reason: str | None = None


class IncompleteResponse(RuntimeError):
    """The provider returned something that is not a usable answer.

    Raised by adapters instead of returning it, so that no caller - and above
    all no cache - ever mistakes a cut-off or declined response for a real one.
    """

    def __init__(self, message: str, *, model: str = "", max_tokens: int | None = None,
                 usage: dict[str, int] | None = None, stop_reason: str | None = None):
        super().__init__(message)
        self.model = model
        self.max_tokens = max_tokens
        self.usage = dict(usage or {})
        self.stop_reason = stop_reason


class TruncatedResponse(IncompleteResponse):
    """Hit max_tokens (or the context window), or came back with no text.

    On thinking models the thinking tokens count against max_tokens and are not
    returned, so this can surface as an EMPTY text block, not just a cut one.
    """


class RefusedResponse(IncompleteResponse):
    """stop_reason == "refusal": the model's safety classifiers declined."""


@runtime_checkable
class LLMPort(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...
