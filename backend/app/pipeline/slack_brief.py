from app.seed.fault_scenarios import FaultScenario


def build_slack_blocks(
    scenario: FaultScenario,
    commit: dict,
    runbook: dict | None,
    impact: dict,
) -> tuple[list[dict], str]:
    text_fallback = f"🚨 Incident: {scenario.title} — suspected commit {commit['sha'][:7]}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚨 {scenario.title}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Alert*\n{scenario.alert_description}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity*\n{impact['severity'].upper()}"},
                {
                    "type": "mrkdwn",
                    "text": f"*Affected users*\n{impact['affected_users_pct']}%",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Revenue at risk*\n${impact['revenue_at_risk_per_hr_usd']:,}/hr",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*p95 latency*\n{impact['p95_latency_ms']}ms",
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
    ]

    if runbook:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Runbook*\n{runbook['title']} — see the full runbook panel for diagnosis and mitigation steps.",
                },
            }
        )

    return blocks, text_fallback
