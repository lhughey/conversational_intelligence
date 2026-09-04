"""Fake LLM for tests and replay.

Keyed by a hash of the request, so a recorded fixture and the real response
cache share one addressing scheme. Deterministic by construction.
"""

from __future__ import annotations

import hashlib
import json

from ..ports.llm import LLMRequest, LLMResponse


def request_key(request: LLMRequest) -> str:
    payload = json.dumps(
        request.model_dump(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FakeLLM:
    """Serves canned responses.

    `responses` may be keyed by request hash (replay) or supplied as a queue
    (simple unit tests). A miss raises rather than inventing text, so a test can
    never silently pass on a response nobody wrote.
    """

    name = "fake"

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        queue: list[str] | None = None,
        default: str | None = None,
    ):
        self.responses = responses or {}
        self.queue = list(queue or [])
        self.default = default
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        key = request_key(request)
        if key in self.responses:
            text = self.responses[key]
        elif self.queue:
            text = self.queue.pop(0)
        elif self.default is not None:
            text = self.default
        else:
            raise KeyError(
                f"FakeLLM has no response for request {key[:12]}. "
                "Record a fixture or supply queue=/default=."
            )
        return LLMResponse(text=text, model="fake", usage={"input": 0, "output": 0})
