import json
import logging
import re
import time

import litellm

from app.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES_PER_MODEL = 3
RETRY_BASE_DELAY_SECONDS = 3

# transient upstream conditions worth retrying / falling back over
_RETRYABLE = (
    litellm.ServiceUnavailableError,
    litellm.RateLimitError,
    litellm.InternalServerError,
    litellm.APIConnectionError,
    litellm.Timeout,
)


def _model_chain() -> list[str]:
    """Primary model plus free-tier fallbacks, deduplicated in order."""
    chain = [settings.llm_model, *settings.llm_fallback_models]
    seen: set[str] = set()
    return [m for m in chain if not (m in seen or seen.add(m))]


def complete(system: str, user: str, max_tokens: int = 2000) -> str:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Set it in .env to enable commit "
            "analysis and postmortem generation."
        )

    last_error: Exception | None = None
    for model in _model_chain():
        for attempt in range(MAX_RETRIES_PER_MODEL):
            try:
                response = litellm.completion(
                    model=model,
                    api_key=settings.gemini_api_key,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return response.choices[0].message.content
            except _RETRYABLE as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed (%s, attempt %d/%d): %s",
                    model,
                    attempt + 1,
                    MAX_RETRIES_PER_MODEL,
                    type(exc).__name__,
                )
                if attempt < MAX_RETRIES_PER_MODEL - 1:
                    time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
        logger.warning("model %s exhausted, falling back to next in chain", model)

    if isinstance(last_error, litellm.RateLimitError):
        raise RuntimeError(
            "LLM rate-limited: the free Gemini tier is temporarily out of quota. "
            "Wait ~60s and retry the pipeline (or set a paid GEMINI_API_KEY)."
        ) from last_error
    raise last_error


def complete_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    text = complete(system, user, max_tokens=max_tokens)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {text!r}")
    return json.loads(match.group(0))
