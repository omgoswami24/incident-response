from app.adapters.github.base import GitHubAdapter
from app.adapters.llm.llm_client import complete_json

SYSTEM_PROMPT = """You are an SRE incident-response assistant. Given a production \
alert (composed from live service metrics) and a numbered list of recent commits \
(each with its diff) from the service's repository, identify which single commit \
most likely caused the alert.

Apply standard root-cause priors:
- The anomaly appeared recently, so strongly prefer the most recent commits: \
older commits have been running in production without triggering this alert.
- Distinguish a change that INTRODUCED a subsystem long ago (running fine since) \
from a recent change that altered that subsystem's behavior or configuration.
- Config-only changes (timeouts, TTLs, pool sizes, flags) are common regression \
sources and fully capable of explaining large latency or error shifts.
- Only pick an older commit if no recent commit can plausibly explain the alert.

Respond with ONLY a JSON object, no other text:
{"suspected_candidate_number": <integer index of the most likely commit from the list>, \
"reasoning": "<2-3 sentence explanation citing specific lines from the diff>", \
"confidence": <float between 0 and 1>}"""


def analyze_commits(adapter: GitHubAdapter, alert_text: str, limit: int = 15) -> dict:
    commits = adapter.list_recent_commits(limit=limit)

    candidates = []
    for i, c in enumerate(commits):
        diff = adapter.get_diff(c.sha)
        candidates.append(
            f"### Candidate {i}\nMessage: {c.message}\nAuthor: {c.author}\nDate: {c.date}\n"
            f"Files changed: {', '.join(c.files_changed)}\nDiff:\n```diff\n{diff}\n```"
        )

    user_prompt = (
        f"Alert:\n{alert_text}\n\n"
        f"Recent commits (most recent first):\n\n" + "\n\n".join(candidates)
    )

    result = complete_json(SYSTEM_PROMPT, user_prompt, max_tokens=8000)

    index = int(result["suspected_candidate_number"])
    if not 0 <= index < len(commits):
        raise ValueError(f"LLM returned out-of-range candidate number: {index}")
    suspected = commits[index]
    diff = adapter.get_diff(suspected.sha)

    return {
        "sha": suspected.sha,
        "message": suspected.message,
        "author": suspected.author,
        "diff": diff,
        "reasoning": result["reasoning"],
        "confidence": float(result["confidence"]),
    }
