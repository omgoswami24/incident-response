import json

from app.adapters.llm.llm_client import complete
from app.models import Incident, TimelineEvent

SYSTEM_PROMPT = """You are an SRE assistant writing a postmortem report after an \
incident has been resolved. Write a clear, concise markdown postmortem with these \
sections: ## Summary, ## Timeline, ## Root Cause, ## Impact, ## Detection, \
## Resolution, ## Action Items. Base every claim strictly on the incident data \
provided — do not invent facts. The incident was detected automatically from live \
metrics and (if the data shows a revert) remediated by reverting the offending \
commit, with recovery verified against the same metrics — reflect that story \
accurately. Action items should be concrete and specific to the root cause."""


def build_postmortem(incident: Incident, timeline: list[TimelineEvent]) -> str:
    timeline_text = "\n".join(
        f"- [{e.ts.isoformat()}] {e.type}: {e.title}"
        for e in timeline
    )
    impact = json.loads(incident.impact_json) if incident.impact_json else {}
    recovery = (
        json.loads(incident.recovery_stats_json) if incident.recovery_stats_json else None
    )

    user_prompt = f"""Auto-detected alert (composed from live metrics at detection time):
{incident.detected_alert_text}

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

Impact estimate (measured from live traffic): {json.dumps(impact)}

Remediation: {
        f"reverted suspected commit via revert commit {incident.remediation_revert_sha}"
        if incident.remediation_revert_sha
        else "no automated revert was applied"
    }
Recovery verified from live metrics: {incident.remediation_verified}
Post-recovery metrics window: {json.dumps(recovery) if recovery else "(not captured)"}

Resolution notes: {incident.resolution_notes or "(none provided)"}
"""

    return complete(SYSTEM_PROMPT, user_prompt, max_tokens=8000)
