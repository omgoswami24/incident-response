import type { TimelineEvent, TimelineEventType } from "../types";

const ICONS: Record<TimelineEventType, string> = {
  alert_detected: "🚨",
  analyzing_started: "🔍",
  commit_identified: "🔗",
  runbook_retrieved: "📖",
  impact_estimated: "📊",
  slack_brief_posted: "💬",
  remediation_started: "🛠️",
  remediation_applied: "⏪",
  recovery_verified: "📈",
  remediation_failed: "🚧",
  resolved: "✅",
  postmortem_generated: "📝",
  closed: "🔒",
  error: "⚠️",
};

function formatTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function IncidentTimeline({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return <p className="muted">Waiting for the first event…</p>;
  }

  return (
    <ol className="timeline">
      {events.map((e) => (
        <li key={e.id} className={`timeline-item ${e.type === "error" ? "timeline-item-error" : ""}`}>
          <span className="timeline-icon">{ICONS[e.type] ?? "•"}</span>
          <div className="timeline-body">
            <div className="timeline-title">{e.title}</div>
            <div className="timeline-time">{formatTime(e.ts)}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}
