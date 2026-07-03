import type { FaultScenario, IncidentSummary } from "../types";

const STATUS_LABELS: Record<string, string> = {
  firing: "Firing",
  analyzing: "Analyzing",
  briefed: "Briefed",
  remediating: "Remediating",
  resolved: "Resolved",
  postmortem_generated: "Postmortem ready",
  closed: "Closed",
};

interface Props {
  incidents: IncidentSummary[];
  scenarios: FaultScenario[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function IncidentList({ incidents, scenarios, selectedId, onSelect }: Props) {
  if (incidents.length === 0) {
    return <p className="muted">No incidents yet.</p>;
  }

  const scenarioTitle = (id: string | null) =>
    scenarios.find((s) => s.id === id)?.title ?? id ?? "organic anomaly";

  return (
    <ul className="incident-list">
      {incidents.map((inc) => (
        <li key={inc.id}>
          <button
            className={`incident-list-item ${inc.id === selectedId ? "selected" : ""}`}
            onClick={() => onSelect(inc.id)}
          >
            <span className={`status-dot status-${inc.status}`} />
            <span className="incident-list-scenario">
              {scenarioTitle(inc.ground_truth_scenario_id)}
              {inc.diagnosis_correct != null && (
                <span
                  className={`diagnosis-chip ${inc.diagnosis_correct ? "ok" : "bad"}`}
                  title={
                    inc.diagnosis_correct
                      ? "AI diagnosis matched the injected commit"
                      : "AI diagnosis did NOT match the injected commit"
                  }
                >
                  {inc.diagnosis_correct ? "✓" : "✗"}
                </span>
              )}
            </span>
            <span className="incident-list-status">
              {STATUS_LABELS[inc.status] ?? inc.status}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
