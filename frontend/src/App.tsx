import { useEffect, useRef, useState } from "react";
import {
  fetchEnvironment,
  fetchFaultScenarios,
  fetchIncidents,
  fetchMetrics,
  injectFault,
  remediateIncident,
  resetEnvironment,
  resolveIncident,
  retryIncident,
  useIncidentStream,
  usePolling,
} from "./api";
import type { GroupStats, Impact, SlackBrief } from "./types";
import { EnvironmentBar } from "./components/EnvironmentBar";
import { FaultPicker } from "./components/FaultPicker";
import { IncidentList } from "./components/IncidentList";
import { IncidentTimeline } from "./components/IncidentTimeline";
import { MetricsPanel } from "./components/MetricsPanel";
import { PostmortemView } from "./components/PostmortemView";
import { SlackBriefCard } from "./components/SlackBriefCard";
import "./index.css";

export default function App() {
  const [scenarios, setScenarios] = useState<
    Awaited<ReturnType<typeof fetchFaultScenarios>>
  >([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [injecting, setInjecting] = useState(false);
  const [awaitingSince, setAwaitingSince] = useState<number | null>(null);
  const [busy, setBusy] = useState<"remediate" | "resolve" | "reset" | null>(null);

  const incidents = usePolling(fetchIncidents, 3000) ?? [];
  const metrics = usePolling(fetchMetrics, 2000);
  const environment = usePolling(fetchEnvironment, 5000);
  const { incident, events } = useIncidentStream(selectedId);

  useEffect(() => {
    fetchFaultScenarios().then(setScenarios).catch(console.error);
  }, []);

  // After injecting, auto-open the incident the detector creates.
  const awaitingRef = useRef(awaitingSince);
  awaitingRef.current = awaitingSince;
  useEffect(() => {
    if (awaitingRef.current == null || incidents.length === 0) return;
    const newest = incidents[0];
    if (new Date(newest.created_at).getTime() >= awaitingRef.current) {
      setAwaitingSince(null);
      setSelectedId(newest.id);
    }
  }, [incidents]);

  async function handleInject(scenarioId: string) {
    setInjecting(true);
    try {
      await injectFault(scenarioId);
      setAwaitingSince(Date.now() - 5000); // small clock-skew allowance
      setSelectedId(null);
    } catch (err) {
      console.error(err);
    } finally {
      setInjecting(false);
    }
  }

  async function handleRemediate() {
    if (!selectedId) return;
    setBusy("remediate");
    try {
      await remediateIncident(selectedId);
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(null);
    }
  }

  async function handleResolve() {
    if (!selectedId) return;
    setBusy("resolve");
    try {
      await resolveIncident(selectedId, "Resolved manually from the dashboard.");
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(null);
    }
  }

  async function handleReset() {
    setBusy("reset");
    try {
      await resetEnvironment();
      setSelectedId(null);
      setAwaitingSince(null);
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(null);
    }
  }

  const impact: Impact | null = incident?.impact_json
    ? JSON.parse(incident.impact_json)
    : null;
  const slackBrief: SlackBrief | null = incident?.slack_brief_json
    ? JSON.parse(incident.slack_brief_json)
    : null;
  const detectionStats: Record<string, GroupStats> | null =
    incident?.detection_stats_json ? JSON.parse(incident.detection_stats_json) : null;
  const recoveryStats: Record<string, GroupStats> | null =
    incident?.recovery_stats_json ? JSON.parse(incident.recovery_stats_json) : null;
  const groundTruthScenario = scenarios.find(
    (s) => s.id === incident?.ground_truth_scenario_id,
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="wordmark">
          <span className="wordmark-glyph" aria-hidden="true">
            ⌁
          </span>
          <h1>Incident Response</h1>
        </div>
        <p className="sidebar-tagline">
          Closed-loop SRE agent — detect, diagnose, remediate, verify
        </p>
        <div className="sidebar-section-label">
          <span>Incidents</span>
          <span className="count">{incidents.length}</span>
        </div>
        <IncidentList
          incidents={incidents}
          scenarios={scenarios}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <button className="new-incident-button" onClick={() => setSelectedId(null)}>
          + Inject a Fault
        </button>
      </aside>

      <main className="main">
        <EnvironmentBar
          environment={environment}
          onReset={handleReset}
          resetting={busy === "reset"}
        />
        <MetricsPanel metrics={metrics} />

        {awaitingSince != null && (
          <div className="awaiting-banner">
            <span className="pulse-dot" /> Bad commit deployed. Waiting for the
            anomaly detector to notice the degradation in live metrics…
          </div>
        )}

        {!selectedId && (
          <>
            <div className="pipeline-strip" aria-label="How the closed loop works">
              <div className="pipeline-stage">
                <span className="pipeline-stage-name">deploy</span>
                <span className="pipeline-stage-desc">
                  A fault card ships a real bad commit to the running service.
                </span>
              </div>
              <div className="pipeline-stage">
                <span className="pipeline-stage-name">detect</span>
                <span className="pipeline-stage-desc">
                  Metrics degrade; the detector opens an incident on its own.
                </span>
              </div>
              <div className="pipeline-stage">
                <span className="pipeline-stage-name">diagnose</span>
                <span className="pipeline-stage-desc">
                  The AI names the commit from diffs alone, scored against ground
                  truth.
                </span>
              </div>
              <div className="pipeline-stage">
                <span className="pipeline-stage-name">verify</span>
                <span className="pipeline-stage-desc">
                  One approval reverts, redeploys, and confirms recovery from live
                  metrics.
                </span>
              </div>
            </div>
            <FaultPicker
              scenarios={scenarios}
              onInject={handleInject}
              disabled={injecting || awaitingSince != null || !metrics?.baseline_ready}
            />
          </>
        )}
        {!selectedId && !metrics?.baseline_ready && (
          <p className="muted baseline-note">
            Fault injection unlocks once the detector has learned a healthy
            baseline (~1 minute after startup).
          </p>
        )}

        {selectedId && incident && (
          <div className="incident-detail">
            <header className="incident-header">
              <h2>
                Incident{" "}
                <code className="incident-id">{incident.id.slice(0, 8)}</code>
              </h2>
              <span className={`status-badge status-${incident.status}`}>
                {incident.status.replace(/_/g, " ")}
              </span>
              {incident.status === "briefed" && (
                <>
                  <button
                    className="remediate-button"
                    onClick={handleRemediate}
                    disabled={busy != null}
                  >
                    {busy === "remediate"
                      ? "Approving…"
                      : `Approve Fix: git revert ${incident.suspected_commit_sha?.slice(0, 7)}`}
                  </button>
                  <button
                    className="resolve-button"
                    onClick={handleResolve}
                    disabled={busy != null}
                    title="Skip the automated revert — mark the incident resolved yourself"
                  >
                    Resolve Manually
                  </button>
                </>
              )}
              {incident.status === "remediating" && (
                <span className="muted remediating-note">
                  <span className="pulse-dot" /> reverting, redeploying, and
                  verifying recovery against live metrics…
                </span>
              )}
            </header>

            {incident.error_message && (
              <div className="error-banner">
                <span>Pipeline error: {incident.error_message}</span>
                {(incident.status === "firing" ||
                  incident.status === "analyzing") && (
                  <button
                    className="retry-button"
                    onClick={() => retryIncident(incident.id).catch(console.error)}
                  >
                    Retry Pipeline
                  </button>
                )}
              </div>
            )}

            <div className="incident-columns">
              <section className="panel">
                <h3>Timeline</h3>
                <IncidentTimeline events={events} />

                <div className="alert-card">
                  <h3>Detected alert</h3>
                  <pre className="alert-text">{incident.detected_alert_text}</pre>
                </div>
              </section>

              <section className="panel">
                {incident.suspected_commit_sha && (
                  <div className="commit-card">
                    <h3>Suspected commit (AI diagnosis)</h3>
                    <code className="commit-sha">
                      {incident.suspected_commit_sha.slice(0, 7)}
                    </code>{" "}
                    <span className="commit-message">
                      {incident.suspected_commit_message}
                    </span>
                    <div className="commit-author muted">
                      by {incident.suspected_commit_author}
                      {incident.commit_analysis_confidence != null && (
                        <>
                          {" "}
                          · {Math.round(incident.commit_analysis_confidence * 100)}%
                          confidence
                        </>
                      )}
                    </div>
                    <p className="commit-reasoning">
                      {incident.commit_analysis_reasoning}
                    </p>
                    {incident.suspected_commit_diff && (
                      <pre className="commit-diff">{incident.suspected_commit_diff}</pre>
                    )}
                  </div>
                )}

                {incident.diagnosis_correct != null && (
                  <div
                    className={`ground-truth-card ${incident.diagnosis_correct ? "ok" : "bad"}`}
                  >
                    <h3>
                      Ground truth{" "}
                      <span className="muted">(hidden from the AI)</span>
                    </h3>
                    <p>
                      Injected: <strong>{groundTruthScenario?.title}</strong> — bad
                      commit{" "}
                      <code>{incident.ground_truth_commit_sha?.slice(0, 7)}</code>
                    </p>
                    <p className="ground-truth-verdict">
                      {incident.diagnosis_correct
                        ? "✓ Diagnosis correct — the AI found the injected commit"
                        : "✗ Diagnosis incorrect — the AI picked a different commit"}
                    </p>
                  </div>
                )}

                {impact && (
                  <div className="impact-card">
                    <h3>Impact (measured)</h3>
                    <div className="impact-grid">
                      <div>
                        <span className="impact-value">
                          {impact.severity.toUpperCase()}
                        </span>
                        <span className="impact-label">Severity</span>
                      </div>
                      <div>
                        <span className="impact-value">
                          {impact.affected_traffic_pct}%
                        </span>
                        <span className="impact-label">Traffic degraded</span>
                      </div>
                      <div>
                        <span className="impact-value">
                          ${impact.est_revenue_at_risk_per_hr_usd.toLocaleString()}/hr
                        </span>
                        <span className="impact-label">Est. revenue at risk</span>
                      </div>
                      <div>
                        <span className="impact-value">
                          {impact.requests_affected_per_hr.toLocaleString()}/hr
                        </span>
                        <span className="impact-label">Requests affected</span>
                      </div>
                    </div>
                    <p className="impact-method muted">{impact.method}</p>
                  </div>
                )}

                {incident.remediation_revert_sha && (
                  <div className="remediation-card">
                    <h3>Remediation</h3>
                    <p>
                      Reverted <code>{incident.suspected_commit_sha?.slice(0, 7)}</code>{" "}
                      via revert commit{" "}
                      <code>{incident.remediation_revert_sha.slice(0, 7)}</code>
                    </p>
                    {incident.remediation_verified === true && (
                      <p className="remediation-verified ok">
                        ✓ Recovery verified from live metrics
                      </p>
                    )}
                    {incident.remediation_verified === false && (
                      <p className="remediation-verified bad">
                        ✗ Metrics did not recover — diagnosis may be wrong
                      </p>
                    )}
                    {detectionStats && recoveryStats && (
                      <table className="recovery-table">
                        <thead>
                          <tr>
                            <th>endpoint</th>
                            <th>incident p95</th>
                            <th>after revert</th>
                            <th>err before → after</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(detectionStats).map(([group, det]) => {
                            const rec = recoveryStats[group];
                            if (!rec) return null;
                            return (
                              <tr key={group}>
                                <td>
                                  <code>{group}</code>
                                </td>
                                <td>{det.p95_ms}ms</td>
                                <td>{rec.p95_ms}ms</td>
                                <td>
                                  {det.error_rate_pct}% → {rec.error_rate_pct}%
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}

                {incident.runbook_title && (
                  <div className="runbook-card">
                    <h3>{incident.runbook_title.replace(/^Runbook:\s*/i, "Runbook — ")}</h3>
                    <p className="runbook-excerpt">{incident.runbook_excerpt}</p>
                  </div>
                )}
              </section>

              <section className="panel">
                <h3>Slack brief</h3>
                {slackBrief ? (
                  <SlackBriefCard brief={slackBrief} />
                ) : (
                  <p className="muted">Not posted yet.</p>
                )}

                {incident.postmortem_markdown && (
                  <>
                    <h3>Postmortem</h3>
                    <PostmortemView markdown={incident.postmortem_markdown} />
                  </>
                )}
              </section>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
