"""Configuration, loaded from THIS repository only.

The component is standalone: it reads its own `.env` and never inherits
credentials from a sibling project. That is deliberate - a benchmark whose
credentials come from somewhere outside the repo is not reproducible, and
picking up another app's key silently bills the wrong account.

Resolution order for a credential:
  1. an already-exported environment variable (CI, or an explicit override)
  2. this repository's .env
  3. nothing - and then a clear error naming what to set

Note an unset ANTHROPIC_API_KEY does not by itself mean "no credentials": the
Anthropic SDK also resolves auth tokens and `ant auth login` profiles. So
`require` is used only where we genuinely cannot proceed.
"""

from __future__ import annotations

import os
import pathlib

from dotenv import dotenv_values

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"

_loaded = False


def load(force: bool = False) -> dict[str, str]:
    """Load this repo's .env into the process, without overriding real env vars."""
    global _loaded
    if _loaded and not force:
        return dict(os.environ)

    if ENV_PATH.exists():
        for key, value in dotenv_values(ENV_PATH).items():
            if value is not None and key not in os.environ:
                os.environ[key] = value
    _loaded = True
    return dict(os.environ)


def get(name: str, default: str | None = None) -> str | None:
    load()
    return os.environ.get(name, default)


def require(name: str) -> str:
    value = get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Add it to {ENV_PATH} (see .env.example). "
            "This component reads only its own .env - it will not inherit "
            "credentials from another project."
        )
    return value


def has(name: str) -> bool:
    return bool(get(name))


def status() -> dict[str, object]:
    load()
    return {
        "env_file": str(ENV_PATH),
        "env_file_present": ENV_PATH.exists(),
        "anthropic": has("ANTHROPIC_API_KEY"),
        "openai": has("OPENAI_API_KEY"),
    }
