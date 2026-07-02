import type { FaultScenario } from "../types";

interface Props {
  scenarios: FaultScenario[];
  onInject: (scenarioId: string) => void;
  disabled: boolean;
}

export function FaultPicker({ scenarios, onInject, disabled }: Props) {
  return (
    <div className="fault-picker">
      <h2>Inject a fault</h2>
      <p className="muted">
        Simulate a production incident in the toy storefront below. The
        system will identify the bad commit, retrieve a runbook, estimate
        impact, and post a Slack brief — live.
      </p>
      <div className="fault-grid">
        {scenarios.map((s) => (
          <button
            key={s.id}
            className="fault-card"
            disabled={disabled}
            onClick={() => onInject(s.id)}
          >
            <span className="fault-card-title">{s.title}</span>
            <span className="fault-card-alert">{s.alert_description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
