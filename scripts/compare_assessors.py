"""Compare assessor strategies across models against the seed labels.

Cached by (model, request, rep), so only the first run costs anything.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from convint.adapters.assessor_deterministic import DeterministicAssessor  # noqa: E402
from convint.adapters.assessor_hybrid import HybridAssessor  # noqa: E402
from convint.adapters.assessor_llm import LLMAssessor  # noqa: E402
from convint.adapters.cache import CachingLLM  # noqa: E402
from convint.adapters.models import build_llm  # noqa: E402
from convint.bench.evaluate import evaluate  # noqa: E402

MODELS = ["haiku-4-5", "sonnet-5", "opus-5", "gpt-4.1-mini", "gpt-4.1"]


def main() -> int:
    print(f"{'assessor':<26} {'S':>5} {'O':>5} {'both':>6}")
    det = evaluate(DeterministicAssessor())
    print(f"{'deterministic':<26} {det['specificity_exact']:>5.0%} "
          f"{det['ownership_exact']:>5.0%} {det['both_exact']:>6.0%}")

    for key in MODELS:
        try:
            llm = LLMAssessor(CachingLLM(build_llm(key), mode="rw"))
            for label, assessor in ((f"llm/{key}", llm), (f"hybrid/{key}", HybridAssessor(llm))):
                r = evaluate(assessor)
                print(f"{label:<26} {r['specificity_exact']:>5.0%} "
                      f"{r['ownership_exact']:>5.0%} {r['both_exact']:>6.0%}")
        except Exception as exc:
            print(f"{'llm/'+key:<26} FAILED: {str(exc)[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
