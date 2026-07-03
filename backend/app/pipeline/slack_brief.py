from app.models import Incident


def _alert_excerpt(incident: Incident) -> str:
    """The degraded-endpoints section of the detected alert, for the brief."""
    text = incident.detected_alert_text or ""
    if "Nominal endpoints:" in text:
        text = text.split("Nominal endpoints:")[0].rstrip()
    return text[:900]


def build_slack_blocks(
    incident: Incident,
    commit: dict,
    runbook: dict | None,
    impact: dict,
) -> tuple[list[dict], str]:
    degraded_groups = list(impact.get("degraded_endpoints", {}))
    headline = ", ".join(degraded_groups) if degraded_groups else "service degradation"
    title = f"[{impact['severity'].upper()}] {headline}"
    text_fallback = f"🚨 Incident: {title} — suspected commit {commit['sha'][:7]}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚨 {title}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Auto-detected alert*\n{_alert_excerpt(incident)}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity*\n{impact['severity'].upper()}"},
                {
                    "type": "mrkdwn",
                    "text": f"*Affected traffic*\n{impact['affected_traffic_pct']}%",
                },
                {
                    "type": "mrkdwn",
                    "text": (
                        "*Est. revenue at risk*\n"
                        f"${impact['est_revenue_at_risk_per_hr_usd']:,}/hr"
                    ),
                },
                {
                    "type": "mrkdwn",
                    "text": (
                        "*Requests affected*\n"
                        f"{impact['requests_affected_per_hr']:,}/hr"
                    ),
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Suspected commit* `{commit['sha'][:7]}`\n"
                    f"> {commit['message']}\n"
                    f"_by {commit['author']}_\n\n"
                    f"*Reasoning* ({commit['confidence']:.0%} confidence)\n{commit['reasoning']}"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Proposed remediation*\n`git revert {commit['sha'][:7]}` and redeploy "
                    "— awaiting approval. Recovery will be verified against live metrics."
                ),
            },
        },
    ]

    if runbook:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Runbook*\n{runbook['title']} — see the full runbook panel "
                        "for diagnosis and mitigation steps."
                    ),
                },
            }
        )

    return blocks, text_fallback
