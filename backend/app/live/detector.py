"""Anomaly detection over live metrics — the replacement for canned alerts.

Nothing tells the detector which fault (if any) was deployed. It learns a
baseline per endpoint group while the service is demonstrably healthy,
compares a short trailing window against that baseline every tick, and when
a breach persists for two consecutive ticks it opens an incident whose alert
text is composed entirely from measured numbers. The diagnosis pipeline runs
from that alert alone; the injected scenario is stored only as hidden ground
truth for scoring the diagnosis afterwards.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db import engine
from app.live.app_manager import manager
from app.live.metrics import store
from app.models import Incident, IncidentStatus, TimelineEventType
from app.pipeline.orchestrator import run_pipeline
from app.state_machine import transition

logger = logging.getLogger(__name__)

TICK_S = 2.0
DETECTION_WINDOW_S = 15
BASELINE_WINDOW_S = 45
BASELINE_REFRESH_S = 20
DEPLOY_GRACE_S = 12
MIN_SAMPLES = 20
CONSECUTIVE_TICKS = 2
ACTIVE_INCIDENT_TIMEOUT_S = 15 * 60

TERMINAL_STATUSES = {IncidentStatus.postmortem_generated, IncidentStatus.closed}


def _age_seconds(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


class AnomalyDetector:
    def __init__(self) -> None:
        self.baseline: dict[str, dict] | None = None
        self.baseline_updated_at: float = 0.0
        self._breach_ticks = 0
        # keep strong refs so in-flight pipeline tasks aren't GC'd
        self._pipeline_tasks: set[asyncio.Task] = set()

    # -- state --------------------------------------------------------------

    def has_active_incident(self) -> bool:
        with Session(engine) as session:
            open_incidents = session.exec(
                select(Incident).where(Incident.status.not_in(TERMINAL_STATUSES))
            ).all()
        return any(
            _age_seconds(i.updated_at) < ACTIVE_INCIDENT_TIMEOUT_S for i in open_incidents
        )

    def public_state(self) -> dict:
        """Exposed via /api/environment for the dashboard."""
        return {
            "baseline_ready": self.baseline is not None,
            "baseline": self.baseline,
            "baseline_age_s": (
                round(time.time() - self.baseline_updated_at)
                if self.baseline is not None
                else None
            ),
        }

    # -- detection logic ----------------------------------------------------

    def _find_breaches(self, current: dict[str, dict]) -> dict[str, list[str]]:
        assert self.baseline is not None
        breaches: dict[str, list[str]] = {}
        for group, cur in current.items():
            base = self.baseline.get(group)
            if base is None or cur["count"] < MIN_SAMPLES:
                continue
            reasons = []
            if (
                cur["p95_ms"] > 2 * base["p95_ms"]
                and cur["p95_ms"] > base["p95_ms"] + 30
            ):
                ratio = cur["p95_ms"] / max(base["p95_ms"], 0.1)
                reasons.append(
                    f"p95 latency {cur['p95_ms']}ms vs baseline {base['p95_ms']}ms "
                    f"({ratio:.1f}x)"
                )
            if cur["error_rate_pct"] > max(5.0, base["error_rate_pct"] + 5):
                reasons.append(
                    f"error rate {cur['error_rate_pct']}% vs baseline "
                    f"{base['error_rate_pct']}%"
                )
            if reasons:
                breaches[group] = reasons
        return breaches

    def _compose_alert(
        self,
        current: dict[str, dict],
        breaches: dict[str, list[str]],
        error_samples: list[dict],
    ) -> str:
        assert self.baseline is not None
        lines = [
            "AUTO-DETECTED ANOMALY — live service metrics, trailing "
            f"{DETECTION_WINDOW_S}s window vs a baseline learned from healthy traffic.",
            "",
            "Degraded endpoints:",
        ]
        for group, reasons in sorted(breaches.items()):
            lines.append(
                f"- {group}: {'; '.join(reasons)}; throughput {current[group]['rps']} req/s"
            )
        lines.append("")
        lines.append("Nominal endpoints:")
        nominal = [g for g in sorted(current) if g not in breaches and g in self.baseline]
        if nominal:
            for group in nominal:
                cur, base = current[group], self.baseline[group]
                lines.append(
                    f"- {group}: p95 {cur['p95_ms']}ms (baseline {base['p95_ms']}ms), "
                    f"error rate {cur['error_rate_pct']}%"
                )
        else:
            lines.append("- none")
        if error_samples:
            lines.append("")
            lines.append("Recent 5xx response body samples:")
            for sample in error_samples[:5]:
                lines.append(f"- [{sample['group']}] {sample['body']}")
        return "\n".join(lines)

    def _fire(self, current: dict[str, dict], breaches: dict[str, list[str]]) -> str:
        error_samples = store.recent_error_samples(seconds=30)
        alert_text = self._compose_alert(current, breaches, error_samples)
        with Session(engine) as session:
            incident = Incident(
                detected_alert_text=alert_text,
                ground_truth_scenario_id=manager.deployed_scenario_id,
                ground_truth_commit_sha=manager.ground_truth_commit_sha(),
                baseline_json=json.dumps(self.baseline),
                detection_stats_json=json.dumps(current),
            )
            session.add(incident)
            session.commit()
            session.refresh(incident)
            transition(
                session,
                incident,
                IncidentStatus.firing,
                TimelineEventType.alert_detected,
                f"Anomaly detected on {len(breaches)} endpoint group(s): "
                + ", ".join(sorted(breaches)),
                {"alert_text": alert_text},
            )
            logger.info("detector fired incident %s: %s", incident.id, sorted(breaches))
            return incident.id

    def tick(self) -> str | None:
        """One detection pass. Returns a new incident id if it fired."""
        if not manager.is_running():
            self._breach_ticks = 0
            return None

        now = time.time()
        since_deploy = now - manager.last_deploy_ts if manager.last_deploy_ts else 1e9
        active = self.has_active_incident()

        # (Re)learn the baseline only while demonstrably healthy: no open
        # incident and the whole baseline window postdates the last deploy.
        if (
            not active
            and since_deploy > BASELINE_WINDOW_S + DEPLOY_GRACE_S
            and now - self.baseline_updated_at > BASELINE_REFRESH_S
        ):
            stats = store.group_stats(BASELINE_WINDOW_S)
            if stats and all(s["count"] >= MIN_SAMPLES for s in stats.values()):
                self.baseline = stats
                self.baseline_updated_at = now

        if self.baseline is None or active or since_deploy < DEPLOY_GRACE_S:
            self._breach_ticks = 0
            return None

        current = store.group_stats(DETECTION_WINDOW_S)
        breaches = self._find_breaches(current)
        if not breaches:
            self._breach_ticks = 0
            return None

        self._breach_ticks += 1
        if self._breach_ticks < CONSECUTIVE_TICKS:
            return None
        self._breach_ticks = 0
        return self._fire(current, breaches)

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                incident_id = self.tick()
                if incident_id is not None:
                    # diagnosis pipeline is sync (LLM calls); run off-loop
                    task = asyncio.get_running_loop().create_task(
                        asyncio.to_thread(run_pipeline, incident_id)
                    )
                    self._pipeline_tasks.add(task)
                    task.add_done_callback(self._pipeline_tasks.discard)
            except Exception:  # noqa: BLE001 — the watchdog must never die
                logger.exception("detector tick failed")
            await asyncio.sleep(TICK_S)


detector = AnomalyDetector()
