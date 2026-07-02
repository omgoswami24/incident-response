import json

from app.adapters.llm.llm_client import complete
from app.models import Incident, TimelineEvent

SYSTEM_PROMPT = """You are an SRE assistant writing a postmortem report after an \
incident has been resolved. Write a clear, concise markdown postmortem with these \
sections: ## Summary, ## Timeline, ## Root Cause, ## Impact, ## Resolution, \
## Action Items. Base every claim strictly on the incident data provided — do \
not invent facts. Action items should be concrete and specific to the root cause."""


def build_postmortem(incident: Incident, timeline: list[TimelineEvent]) -> str:
    timeline_text = "\n".join(
        f"- [{e.ts.isoformat()}] {e.type}: {e.title}"
        + (f" ({e.detail})" if e.detail else "")
        for e in timeline
    )
    impact = json.loads(incident.impact_json) if incident.impact_json else {}

    user_prompt = f"""Incident: {incident.fault_scenario_id}

Timeline:
{timeline_text}

Suspected root-cause commit: {incident.suspected_commit_sha}
Commit message: {incident.suspected_commit_message}
Commit author: {incident.suspected_commit_author}
Diff:
```diff
{incident.suspected_commit_diff}
```
Commit analysis reasoning: {incident.commit_analysis_reasoning}

Runbook used: {incident.runbook_title}
Runbook excerpt: {incident.runbook_excerpt}

Impact estimate: {json.dumps(impact)}

Resolution notes: {incident.resolution_notes or "(none provided)"}
"""

    return complete(SYSTEM_PROMPT, user_prompt, max_tokens=8000)
