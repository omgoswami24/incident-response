import type { Environment } from "../types";

export function EnvironmentBar({
  environment,
  onReset,
  resetting,
}: {
  environment: Environment | null;
  onReset: () => void;
  resetting: boolean;
}) {
  const app = environment?.app;
  return (
    <div className="environment-bar">
      <span className={`env-dot ${app?.running ? "up" : "down"}`} />
      <span className="env-label">
        target app{" "}
        {app?.running ? (
          <>
            running on <code>:{app.port}</code>
          </>
        ) : (
          "down"
        )}
      </span>
      {app?.branch && (
        <span className="env-label">
          deployed <code>{app.branch}</code>
          {app.head_sha && <code className="env-sha">@{app.head_sha.slice(0, 7)}</code>}
        </span>
      )}
      {app?.head_message && (
        <span className="env-label muted env-head-msg">“{app.head_message}”</span>
      )}
      <span className="env-spacer" />
      <button className="env-reset-button" onClick={onReset} disabled={resetting}>
        {resetting ? "Resetting…" : "Reset environment"}
      </button>
    </div>
  );
}
