import type { TimelineEvent, TimelineEventType } from "../types";

// marker color category per event type — dots, not emoji
const CATEGORIES: Record<TimelineEventType, string> = {
  alert_detected: "alert",
  analyzing_started: "analysis",
  commit_identified: "analysis",
  runbook_retrieved: "doc",
  impact_estimated: "analysis",
  slack_brief_posted: "doc",
  remediation_started: "remediation",
  remediation_applied: "remediation",
  recovery_verified: "success",
  remediation_failed: "error",
  resolved: "success",
  postmortem_generated: "doc",
  closed: "doc",
  error: "error",
};

const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function IncidentTimeline({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return <p className="muted">Waiting for the first event…</p>;
  }

  return (
    <ol className="timeline">
      {events.map((e) => (
        <li
          key={e.id}
          className={`timeline-item ${e.type === "error" ? "timeline-item-error" : ""}`}
        >
          <span
            className={`timeline-marker cat-${CATEGORIES[e.type] ?? "doc"}`}
            aria-hidden="true"
          />
          <div className="timeline-body">
            <div className="timeline-title">{e.title}</div>
            <div className="timeline-time">{timeFormat.format(new Date(e.ts))}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}
