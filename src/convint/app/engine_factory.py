"""Build the serving TurnEngine from this repository's configuration.

Every transport (HTTP, MCP, CLI) calls `build_engine()`, so the operator - not
the caller - decides which models run and therefore what a turn costs:

    CONVINT_ASSESSOR   deterministic | llm:<key> | hybrid:<key>
                       (default hybrid:haiku-4-5, the recommended assessor)
    CONVINT_MODEL      registry key for generation and the Read
                       (default haiku-4-5); `none` disables model generation

Values come from an exported env var or this repo's `.env` via
`convint.config` - never a sibling project's. Explicit `assessor=` / `model=`
arguments (CLI flags) override both.

A component whose provider has no credential is built DEGRADED rather than
failing: that component falls back (deterministic assessor / no generation)
and a startup warning rides on every response's diagnostics. Construction
never makes a network call; adapters create their clients lazily.
"""

from __future__ import annotations

import logging
from typing import Callable

from .. import config
from ..adapters.models import ANTHROPIC, OPENAI, REGISTRY, build_llm
from ..ports.llm import LLMPort
from .metering import MeteredLLM
from .turn_engine import TurnEngine

ASSESSOR_ENV = "CONVINT_ASSESSOR"
MODEL_ENV = "CONVINT_MODEL"
DEFAULT_ASSESSOR = "hybrid:haiku-4-5"
DEFAULT_MODEL = "haiku-4-5"
NO_MODEL = "none"

#: Env vars that count as a resolved credential, per provider.
CREDENTIAL_VARS: dict[str, tuple[str, ...]] = {
    ANTHROPIC: ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    OPENAI: ("OPENAI_API_KEY",),
}

log = logging.getLogger("convint")


def parse_assessor_spec(spec: str) -> tuple[str, str | None]:
    """`deterministic` -> ("deterministic", None); `llm:<key>` / `hybrid:<key>`
    -> (kind, key). Does not check the key against the registry."""
    spec = (spec or "").strip()
    if spec == "deterministic":
        return "deterministic", None
    kind, _, key = spec.partition(":")
    if kind not in {"llm", "hybrid"} or not key:
        raise ValueError(
            f"unknown assessor {spec!r}; use deterministic, llm:<key> or hybrid:<key>"
        )
    return kind, key


def assessor_from_spec(spec: str, wrap: Callable[[LLMPort], LLMPort] = lambda llm: llm):
    """Construct an assessor from a spec. `wrap` decorates the model adapter
    (the bench passes a response cache; serving passes a usage meter).
    Constructing makes no call; assessing does."""
    from ..adapters.assessor_deterministic import DeterministicAssessor

    kind, key = parse_assessor_spec(spec)
    if kind == "deterministic":
        return DeterministicAssessor()
    from ..adapters.assessor_hybrid import HybridAssessor
    from ..adapters.assessor_llm import LLMAssessor

    llm = LLMAssessor(wrap(build_llm(key)))
    if kind == "llm":
        llm.name = f"llm/{key}"
        return llm
    hybrid = HybridAssessor(llm)
    hybrid.name = f"hybrid/{key}"
    return hybrid


def has_credentials(provider: str) -> bool:
    return any(config.has(name) for name in CREDENTIAL_VARS.get(provider, ()))


def _known(key: str, what: str) -> None:
    if key not in REGISTRY:
        raise ValueError(f"{what}: unknown model key {key!r}; known: {sorted(REGISTRY)}")


def _missing(provider: str) -> str:
    return f"no {provider} credential ({' or '.join(CREDENTIAL_VARS[provider])})"


def build_engine(assessor: str | None = None, model: str | None = None) -> TurnEngine:
    """The engine every transport serves. Raises ValueError on an invalid
    spec, so a misconfigured server fails at startup rather than per turn."""
    assessor_spec = (assessor or config.get(ASSESSOR_ENV) or DEFAULT_ASSESSOR).strip()
    model_key = (model or config.get(MODEL_ENV) or DEFAULT_MODEL).strip()

    kind, assessor_key = parse_assessor_spec(assessor_spec)
    if assessor_key is not None:
        _known(assessor_key, ASSESSOR_ENV)
    if model_key.lower() == NO_MODEL:
        model_key = None
    else:
        _known(model_key, MODEL_ENV)

    warnings: list[str] = []
    if assessor_key is not None:
        provider = REGISTRY[assessor_key].provider
        if not has_credentials(provider):
            warnings.append(
                f"assessor_degraded: {_missing(provider)}; using deterministic "
                f"instead of {assessor_spec}"
            )
            assessor_spec, assessor_key = "deterministic", None
    if model_key is not None:
        provider = REGISTRY[model_key].provider
        if not has_credentials(provider):
            warnings.append(
                f"model_degraded: {_missing(provider)}; message and artifact are "
                f"disabled instead of using {model_key}"
            )
            model_key = None

    for warning in warnings:
        log.warning("convint started degraded: %s", warning)

    return TurnEngine(
        assessor=assessor_from_spec(assessor_spec, wrap=MeteredLLM),
        llm=MeteredLLM(build_llm(model_key)) if model_key is not None else None,
        assessor_model=REGISTRY[assessor_key].model_id if assessor_key else None,
        startup_warnings=warnings,
    )
