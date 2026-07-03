import { useState } from "react";
import type { FaultScenario, IncidentSummary } from "../types";

const STATUS_LABELS: Record<string, string> = {
  firing: "Firing",
  analyzing: "Analyzing…",
  briefed: "Awaiting Approval",
  remediating: "Remediating…",
  resolved: "Resolved",
  postmortem_generated: "Postmortem Ready",
  closed: "Closed",
};

const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
});

interface Props {
  incidents: IncidentSummary[];
  scenarios: FaultScenario[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function IncidentList({ incidents, scenarios, selectedId, onSelect }: Props) {
  const [showClosed, setShowClosed] = useState(false);

  const open = incidents.filter((i) => i.status !== "closed");
  const closed = incidents.filter((i) => i.status === "closed");

  const scenarioTitle = (id: string | null) =>
    scenarios.find((s) => s.id === id)?.title ?? id ?? "Organic anomaly";

  const row = (inc: IncidentSummary) => (
    <li key={inc.id}>
      <button
        className={`incident-list-item ${inc.id === selectedId ? "selected" : ""} ${
          inc.status === "closed" ? "closed-item" : ""
        }`}
        onClick={() => onSelect(inc.id)}
      >
        <span className={`status-dot status-${inc.status}`} aria-hidden="true" />
        <span className="incident-list-main">
          <span className="incident-list-scenario">
            {scenarioTitle(inc.ground_truth_scenario_id)}
            {inc.diagnosis_correct != null && (
              <span
                className={`diagnosis-chip ${inc.diagnosis_correct ? "ok" : "bad"}`}
                title={
                  inc.diagnosis_correct
                    ? "AI diagnosis matched the injected commit"
                    : "AI diagnosis did not match the injected commit"
                }
              >
                {inc.diagnosis_correct ? "✓" : "✗"}
              </span>
            )}
          </span>
          <span className="incident-list-meta">
            <span>{timeFormat.format(new Date(inc.created_at))}</span>
            <span>{STATUS_LABELS[inc.status] ?? inc.status}</span>
          </span>
        </span>
      </button>
    </li>
  );

  if (incidents.length === 0) {
    return (
      <p className="muted">
        No incidents yet. Deploy a fault and the detector will open one here.
      </p>
    );
  }

  return (
    <>
      <ul className="incident-list">{open.map(row)}</ul>
      {closed.length > 0 && (
        <>
          <button
            className="closed-toggle"
            onClick={() => setShowClosed((v) => !v)}
            aria-expanded={showClosed}
          >
            {showClosed ? "Hide" : "Show"} {closed.length} closed{" "}
            {closed.length === 1 ? "incident" : "incidents"}
          </button>
          {showClosed && <ul className="incident-list">{closed.map(row)}</ul>}
        </>
      )}
    </>
  );
}
