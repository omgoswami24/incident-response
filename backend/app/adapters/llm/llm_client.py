import json
import re
import time

import litellm

from app.config import settings

MAX_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 3


def complete(system: str, user: str, max_tokens: int = 2000) -> str:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Set it in .env to enable commit "
            "analysis and postmortem generation."
        )

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = litellm.completion(
                model=settings.llm_model,
                api_key=settings.gemini_api_key,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return response.choices[0].message.content
        except litellm.ServiceUnavailableError as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))

    raise last_error


def complete_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    text = complete(system, user, max_tokens=max_tokens)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {text!r}")
    return json.loads(match.group(0))
