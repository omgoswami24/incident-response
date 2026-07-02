import type { IncidentSummary } from "../types";

const STATUS_LABELS: Record<string, string> = {
  firing: "Firing",
  analyzing: "Analyzing",
  briefed: "Briefed",
  resolved: "Resolved",
  postmortem_generated: "Postmortem ready",
};

interface Props {
  incidents: IncidentSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function IncidentList({ incidents, selectedId, onSelect }: Props) {
  if (incidents.length === 0) {
    return <p className="muted">No incidents yet.</p>;
  }

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
              {inc.fault_scenario_id}
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
