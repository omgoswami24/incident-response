import type { FaultScenario } from "../types";

interface Props {
  scenarios: FaultScenario[];
  onInject: (scenarioId: string) => void;
  disabled: boolean;
}

export function FaultPicker({ scenarios, onInject, disabled }: Props) {
  return (
    <div className="fault-picker">
      <h2>Deploy a bad commit</h2>
      <p className="muted">
        Each card deploys a branch with a real regression buried in its git
        history to the live target app. Nothing is announced: the anomaly
        detector has to notice the degradation in the metrics above, and the
        AI pipeline has to find the offending commit on its own.
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
            <span className="fault-card-alert">{s.description}</span>
            <span className="fault-card-branch">
              <code>{s.deploy_branch}</code>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
