import json
import logging

from sqlmodel import Session, select

from app.adapters.factory import get_github_adapter, get_slack_adapter
from app.db import engine
from app.models import Incident, IncidentStatus, TimelineEvent, TimelineEventType
from app.pipeline.commit_analysis import analyze_commits
from app.pipeline.impact_estimator import estimate_impact
from app.pipeline.postmortem import build_postmortem
from app.pipeline.runbook_rag import query_runbook
from app.pipeline.slack_brief import build_slack_blocks
from app.seed.fault_scenarios import FAULT_SCENARIOS
from app.state_machine import record_error, transition

logger = logging.getLogger(__name__)


def run_pipeline(incident_id: str) -> None:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            logger.error("run_pipeline: incident %s not found", incident_id)
            return

        scenario = FAULT_SCENARIOS[incident.fault_scenario_id]

        try:
            transition(
                session,
                incident,
                IncidentStatus.analyzing,
                TimelineEventType.analyzing_started,
                "Analyzing recent commits and estimating impact",
            )

            adapter = get_github_adapter()
            commit = analyze_commits(adapter, scenario)
            incident.suspected_commit_sha = commit["sha"]
            incident.suspected_commit_message = commit["message"]
            incident.suspected_commit_author = commit["author"]
            incident.suspected_commit_diff = commit["diff"]
            incident.commit_analysis_reasoning = commit["reasoning"]
            incident.commit_analysis_confidence = commit["confidence"]
            session.add(incident)
            session.commit()
            session.refresh(incident)

            transition(
                session,
                incident,
                incident.status,
                TimelineEventType.commit_identified,
                f"Suspected commit: {commit['sha'][:7]} — {commit['message']}",
                {"confidence": commit["confidence"]},
            )

            runbook = query_runbook(scenario.alert_description)
            if runbook:
                incident.runbook_id = runbook["runbook_id"]
                incident.runbook_title = runbook["title"]
                incident.runbook_excerpt = runbook["excerpt"]
                session.add(incident)
                session.commit()
                session.refresh(incident)

            transition(
                session,
                incident,
                incident.status,
                TimelineEventType.runbook_retrieved,
                f"Runbook retrieved: {runbook['title']}" if runbook else "No matching runbook found",
            )

            impact = estimate_impact(scenario)
            incident.impact_json = json.dumps(impact)
            session.add(incident)
            session.commit()
            session.refresh(incident)

            transition(
                session,
                incident,
                incident.status,
                TimelineEventType.impact_estimated,
                f"Impact estimated: {impact['severity']} severity, "
                f"{impact['affected_users_pct']}% of users affected",
                impact,
            )

            blocks, text_fallback = build_slack_blocks(scenario, commit, runbook, impact)
            slack_adapter = get_slack_adapter()
            from app.config import settings

            result = slack_adapter.post_message(settings.slack_channel, blocks, text_fallback)
            incident.slack_brief_json = json.dumps(result.model_dump())
            session.add(incident)
            session.commit()
            session.refresh(incident)

            transition(
                session,
                incident,
                IncidentStatus.briefed,
                TimelineEventType.slack_brief_posted,
                f"Slack brief posted to {settings.slack_channel}",
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline failed for incident %s", incident_id)
            record_error(session, incident, str(exc))


def run_postmortem(incident_id: str) -> None:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            logger.error("run_postmortem: incident %s not found", incident_id)
            return

        try:
            timeline = session.exec(
                select(TimelineEvent)
                .where(TimelineEvent.incident_id == incident_id)
                .order_by(TimelineEvent.ts)
            ).all()

            markdown = build_postmortem(incident, timeline)
            incident.postmortem_markdown = markdown
            session.add(incident)
            session.commit()
            session.refresh(incident)

            transition(
                session,
                incident,
                IncidentStatus.postmortem_generated,
                TimelineEventType.postmortem_generated,
                "Postmortem generated",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Postmortem generation failed for incident %s", incident_id)
            record_error(session, incident, str(exc))
