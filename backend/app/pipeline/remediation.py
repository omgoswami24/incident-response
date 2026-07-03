"""Auto-remediation: revert the suspected commit, redeploy the target app,
and verify recovery from live metrics before resolving.

The verification is the honest part: recovery is judged against the same
baseline the detector learned, from fresh traffic hitting the redeployed
service. If the diagnosis was wrong, reverting the wrong commit won't move
the metrics, verification times out, and the incident is marked as a failed
remediation — the system doesn't get to grade its own homework.
"""

import json
import logging
import time

from sqlmodel import Session

from app.db import engine
from app.live.app_manager import RevertFailedError, manager
from app.live.metrics import store
from app.models import Incident, IncidentStatus, TimelineEventType
from app.pipeline.orchestrator import run_postmortem
from app.state_machine import record_error, transition

logger = logging.getLogger(__name__)

VERIFY_GRACE_S = 10  # let fresh traffic reach the redeployed app
VERIFY_TIMEOUT_S = 90
VERIFY_POLL_S = 3
VERIFY_WINDOW_S = 12
CONSECUTIVE_OK_POLLS = 2
MIN_SAMPLES = 10


def _recovered(baseline: dict, current: dict) -> bool:
    """Every baselined endpoint group must be back within tolerance."""
    for group, base in baseline.items():
        cur = current.get(group)
        if cur is None or cur["count"] < MIN_SAMPLES:
            return False
        if cur["p95_ms"] > max(1.6 * base["p95_ms"], base["p95_ms"] + 25):
            return False
        if cur["error_rate_pct"] > max(2.0, base["error_rate_pct"] + 2):
            return False
    return True


def _recovery_summary(detection: dict, baseline: dict, current: dict) -> str:
    """Human-readable before/after for the groups that were degraded."""
    parts = []
    for group, detected in detection.items():
        base = baseline.get(group)
        cur = current.get(group)
        if base is None or cur is None:
            continue
        was_latency = detected["p95_ms"] > 2 * base["p95_ms"]
        was_errors = detected["error_rate_pct"] > base["error_rate_pct"] + 5
        if was_latency:
            parts.append(f"{group} p95 {detected['p95_ms']}ms → {cur['p95_ms']}ms")
        if was_errors:
            parts.append(
                f"{group} error rate {detected['error_rate_pct']}% → "
                f"{cur['error_rate_pct']}%"
            )
    return "; ".join(parts) if parts else "all endpoint groups back within baseline tolerance"


def run_remediation(incident_id: str) -> None:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            logger.error("run_remediation: incident %s not found", incident_id)
            return
        if incident.status != IncidentStatus.briefed:
            logger.warning(
                "run_remediation: incident %s in status %s, skipping",
                incident_id,
                incident.status,
            )
            return
        if not incident.suspected_commit_sha:
            record_error(session, incident, "No suspected commit to revert")
            return

        try:
            transition(
                session,
                incident,
                IncidentStatus.remediating,
                TimelineEventType.remediation_started,
                f"Auto-remediation approved: reverting {incident.suspected_commit_sha[:7]} "
                f"({incident.suspected_commit_message})",
            )

            try:
                revert_sha = manager.revert_commit(incident.suspected_commit_sha)
            except RevertFailedError as exc:
                incident.remediation_verified = False
                session.add(incident)
                session.commit()
                session.refresh(incident)
                transition(
                    session,
                    incident,
                    incident.status,
                    TimelineEventType.remediation_failed,
                    f"Remediation failed: {exc} The service is back up on the "
                    "unreverted code; manual intervention required.",
                )
                return
            incident.remediation_revert_sha = revert_sha
            session.add(incident)
            session.commit()
            session.refresh(incident)

            transition(
                session,
                incident,
                incident.status,
                TimelineEventType.remediation_applied,
                f"Revert commit {revert_sha[:7]} deployed to {manager.deployed_branch}; "
                "verifying recovery against live metrics",
            )

            baseline = json.loads(incident.baseline_json or "{}")
            detection = json.loads(incident.detection_stats_json or "{}")

            time.sleep(VERIFY_GRACE_S)
            recovered = False
            current: dict = {}
            ok_polls = 0
            deadline = time.monotonic() + VERIFY_TIMEOUT_S
            while time.monotonic() < deadline:
                current = store.group_stats(VERIFY_WINDOW_S)
                if baseline and _recovered(baseline, current):
                    ok_polls += 1
                    if ok_polls >= CONSECUTIVE_OK_POLLS:
                        recovered = True
                        break
                else:
                    ok_polls = 0
                time.sleep(VERIFY_POLL_S)

            if recovered:
                summary = _recovery_summary(detection, baseline, current)
                incident.remediation_verified = True
                incident.recovery_stats_json = json.dumps(current)
                incident.resolution_notes = (
                    f"Automated: reverted {incident.suspected_commit_sha[:7]} "
                    f"(revert commit {revert_sha[:7]}); recovery verified from live "
                    f"metrics — {summary}."
                )
                session.add(incident)
                session.commit()
                session.refresh(incident)
                transition(
                    session,
                    incident,
                    IncidentStatus.resolved,
                    TimelineEventType.recovery_verified,
                    f"Recovery verified from live metrics: {summary}",
                    {"recovery_stats": current},
                )
            else:
                incident.remediation_verified = False
                session.add(incident)
                session.commit()
                session.refresh(incident)
                transition(
                    session,
                    incident,
                    incident.status,
                    TimelineEventType.remediation_failed,
                    "Metrics did not recover after the revert — the diagnosis may be "
                    "wrong. Manual intervention required (you can still resolve manually).",
                )
                return

        except Exception as exc:  # noqa: BLE001
            logger.exception("Remediation failed for incident %s", incident_id)
            record_error(session, incident, str(exc))
            return

    # separate session inside; only reached on verified recovery
    run_postmortem(incident_id)
