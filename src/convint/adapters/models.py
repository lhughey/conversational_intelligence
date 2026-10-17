"""Model registry and capability validation.

Sampling support is a MEASURED capability, not an assumption. Verified live
against the API on 2026-09-03:

    temperature=1.0 (the default)  -> 200 on every model below
    temperature=0.7 / 0.5 / 0.3 / 0 -> 400 on opus-5, opus-4-8, sonnet-5
    top_p=0.9                       -> 400 on opus-5, sonnet-5
    any of the above                -> 200 on haiku-4-5

    error: "`temperature` is deprecated for this model."

`output_config.effort` is a SECOND per-model capability, split the other way:
supported on the Opus/Sonnet 5 family, rejected with 400 on haiku-4-5
("This model does not support the effort parameter"). So haiku-4-5 is the
only model here with a sampling knob and the only one without a depth knob.
(Haiku 5.5, below, drops sampling and gains effort like the rest of the 5.x
family, so "the cheap model" no longer implies "sampling, no effort".)

So on the current Opus/Sonnet models the temperature field is accepted only at its default,
where it is a no-op: there is no sampling control. Setting it uniformly across a
model matrix produces an unfair comparison that looks fair, which is why this is
validated at CONFIG LOAD rather than discovered at request time.

Those models run at temperature 1.0 - the high-variation end. What is lost is
the ability to make output MORE deterministic, not more natural. Variety comes
from move selection and prompt design instead.

Added 2026-10 FROM ANTHROPIC DOCS, NOT YET LIVE-VERIFIED (the table above was
measured; these rows are documented claims until a live probe confirms them):

    opus-5-5    sampling 400, effort low..max, DEFAULT effort `medium`
                (opus-5 defaults to `high`), thinking cannot be disabled
    sonnet-5-5  non-default sampling 400, effort supported, default `high`
    fable-5-1   sampling 400, effort supported
    haiku-5-5   sampling 400 ("omit temperature, top_p, and top_k"), effort
                supported (adaptive thinking), DEFAULT effort `medium`;
                released 2026-10-07; Claude 4.7+ tokenizer (~30% more tokens
                than haiku-4-5 for the same text)

Also from the same docs: sonnet-5 is $2/$10 per MTok (was recorded as $3/$15).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

ANTHROPIC = "anthropic"
OPENAI = "openai"


class ModelSpec(BaseModel):
    key: str
    provider: str
    model_id: str
    supports_sampling: bool
    #: `output_config.effort` - the depth lever. Rejected by 400 on haiku-4-5.
    supports_effort: bool = True
    #: input/output USD per million tokens
    price_in: float = 0.0
    price_out: float = 0.0
    max_tokens: int = 1024
    #: Thinks by default when the request omits `thinking` (adaptive thinking on
    #: the 5.x family). Thinking tokens count against `max_tokens` and are not
    #: returned, so a visible-answer budget alone can be spent entirely on
    #: thinking and come back EMPTY. The Anthropic adapter adds headroom for
    #: these models (see llm_anthropic.thinking_headroom). False for haiku-4-5
    #: (thinking only via an explicit budget), opus-4-8 (omitting `thinking`
    #: runs without it) and every OpenAI model.
    thinks: bool = False
    effort: str | None = None
    temperature: float | None = None

    @model_validator(mode="after")
    def _reject_inexpressible_sampling(self) -> "ModelSpec":
        if self.temperature is not None and not self.supports_sampling:
            raise ValueError(
                f"{self.model_id} does not support `temperature` "
                f"(got {self.temperature}); the API returns 400. Omit it."
            )
        if self.effort is not None and not self.supports_effort:
            raise ValueError(
                f"{self.model_id} does not support `effort` (got {self.effort!r}); "
                "the API returns 400. Omit it."
            )
        return self


#: Model IDs are complete as-is. Never append a date suffix.
REGISTRY: dict[str, ModelSpec] = {
    m.key: m
    for m in [
        ModelSpec(key="opus-5", provider=ANTHROPIC, model_id="claude-opus-5",
                  supports_sampling=False, thinks=True,
                  price_in=5.0, price_out=25.0),
        ModelSpec(key="opus-4-8", provider=ANTHROPIC, model_id="claude-opus-4-8",
                  supports_sampling=False, price_in=5.0, price_out=25.0),
        ModelSpec(key="sonnet-5", provider=ANTHROPIC, model_id="claude-sonnet-5",
                  supports_sampling=False, thinks=True,
                  price_in=2.0, price_out=10.0),
        # Pinned to `high` because opus-5-5's API default is `medium`, while
        # opus-5 (whose spec leaves effort unset) runs at its default `high`.
        # Leaving this unset would benchmark the newer model at lower depth and
        # report the difference as a model difference. It only applies where a
        # caller does not set LLMRequest.effort itself (the generator and the
        # artifact builder); LLMAssessor always sends its own effort ("low").
        ModelSpec(key="opus-5-5", provider=ANTHROPIC, model_id="claude-opus-5-5",
                  supports_sampling=False, thinks=True,
                  price_in=4.0, price_out=20.0,
                  effort="high"),
        ModelSpec(key="sonnet-5-5", provider=ANTHROPIC, model_id="claude-sonnet-5-5",
                  supports_sampling=False, thinks=True,
                  price_in=2.0, price_out=10.0),
        # Registry only: deliberately absent from the default benchmark lists
        # in scripts/ because of cost.
        ModelSpec(key="fable-5-1", provider=ANTHROPIC, model_id="claude-fable-5-1",
                  supports_sampling=False, thinks=True,
                  price_in=10.0, price_out=50.0),
        # Price is the <=100k-token prompt tier ($0.10/$0.50). Above 100k it is
        # $0.50/$2.50; cost_usd does not model that tier (this repo's prompts
        # are far below it). The 4.7+ tokenizer counts the same text as ~30%
        # more tokens than haiku-4-5, so per-MTok prices understate the gap in
        # a cost comparison against it.
        # Effort deliberately NOT pinned: the generator path runs at the API
        # default (`medium`) for now; LLMAssessor always sends its own ("low").
        ModelSpec(key="haiku-5-5", provider=ANTHROPIC, model_id="claude-haiku-5-5",
                  supports_sampling=False, thinks=True,
                  price_in=0.10, price_out=0.50),
        ModelSpec(key="haiku-4-5", provider=ANTHROPIC, model_id="claude-haiku-4-5",
                  supports_sampling=True, supports_effort=False,
                  price_in=1.0, price_out=5.0),
        # OpenAI: sampling is available, `effort` is Anthropic-specific.
        ModelSpec(key="gpt-4.1", provider=OPENAI, model_id="gpt-4.1",
                  supports_sampling=True, supports_effort=False,
                  price_in=2.0, price_out=8.0),
        ModelSpec(key="gpt-4.1-mini", provider=OPENAI, model_id="gpt-4.1-mini",
                  supports_sampling=True, supports_effort=False,
                  price_in=0.4, price_out=1.6),
    ]
}


def build_llm(key: str, **overrides):
    """Construct the right adapter for a registry key."""
    s = spec(key, **overrides)
    if s.provider == ANTHROPIC:
        from .llm_anthropic import AnthropicLLM

        return AnthropicLLM(s)
    from .llm_openai import OpenAILLM

    return OpenAILLM(s.model_id, temperature=s.temperature)


def spec(key: str, **overrides) -> ModelSpec:
    """Build a spec, RE-VALIDATING overrides.

    Note: `model_copy(update=...)` bypasses validators in pydantic v2, which
    would let an unsupported `temperature` through to the API and 400 at request
    time. Reconstructing the model is what makes the capability guard real.
    """
    if key not in REGISTRY:
        raise KeyError(f"unknown model key {key!r}; known: {sorted(REGISTRY)}")
    base = REGISTRY[key]
    if not overrides:
        return base
    return ModelSpec(**{**base.model_dump(), **overrides})


def cost_usd(spec: ModelSpec, usage: dict[str, int]) -> float:
    return (
        usage.get("input", 0) / 1_000_000 * spec.price_in
        + usage.get("output", 0) / 1_000_000 * spec.price_out
    )
