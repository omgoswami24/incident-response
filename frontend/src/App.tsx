import { useEffect, useState } from "react";
import {
  fetchFaultScenarios,
  fetchIncidents,
  injectFault,
  resolveIncident,
  useIncidentStream,
} from "./api";
import type { FaultScenario, IncidentSummary, Impact, SlackBrief } from "./types";
import { EcommerceStorefront } from "./components/EcommerceStorefront";
import { FaultPicker } from "./components/FaultPicker";
import { IncidentList } from "./components/IncidentList";
import { IncidentTimeline } from "./components/IncidentTimeline";
import { SlackBriefCard } from "./components/SlackBriefCard";
import { PostmortemView } from "./components/PostmortemView";
import "./index.css";

export default function App() {
  const [scenarios, setScenarios] = useState<FaultScenario[]>([]);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [injecting, setInjecting] = useState(false);
  const [resolving, setResolving] = useState(false);

  const { incident, events } = useIncidentStream(selectedId);

  useEffect(() => {
    fetchFaultScenarios().then(setScenarios).catch(console.error);
    refreshIncidents();
  }, []);

  // Refresh the sidebar whenever the selected incident's status changes.
  useEffect(() => {
    if (incident) refreshIncidents();
  }, [incident?.status]);

  function refreshIncidents() {
    fetchIncidents().then(setIncidents).catch(console.error);
  }

  async function handleInject(scenarioId: string) {
    setInjecting(true);
    try {
      const { incident_id } = await injectFault(scenarioId);
      setSelectedId(incident_id);
    } catch (err) {
      console.error(err);
      alert(`Failed to inject fault: ${err}`);
    } finally {
      setInjecting(false);
    }
  }

  async function handleResolve() {
    if (!selectedId) return;
    setResolving(true);
    try {
      await resolveIncident(
        selectedId,
        "Reverted the offending commit and redeployed.",
      );
    } catch (err) {
      console.error(err);
      alert(`Failed to resolve incident: ${err}`);
    } finally {
      setResolving(false);
    }
  }

  const impact: Impact | null = incident?.impact_json
    ? JSON.parse(incident.impact_json)
    : null;
  const slackBrief: SlackBrief | null = incident?.slack_brief_json
    ? JSON.parse(incident.slack_brief_json)
    : null;
  const scenarioTitle =
    scenarios.find((s) => s.id === incident?.fault_scenario_id)?.title ??
    incident?.fault_scenario_id;

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Incident Response</h1>
        <p className="muted">Autonomous AI SRE assistant — live demo</p>
        <IncidentList
          incidents={incidents}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <button
          className="new-incident-button"
          onClick={() => setSelectedId(null)}
        >
          + New fault
        </button>
      </aside>

      <main className="main">
        {!selectedId && (
          <>
            <EcommerceStorefront />
            <FaultPicker
              scenarios={scenarios}
              onInject={handleInject}
              disabled={injecting}
            />
          </>
        )}

        {selectedId && incident && (
          <div className="incident-detail">
            <header className="incident-header">
              <h2>{scenarioTitle}</h2>
              <span className={`status-badge status-${incident.status}`}>
                {incident.status.replace(/_/g, " ")}
              </span>
              {incident.status === "briefed" && (
                <button
                  className="resolve-button resolve-button-header"
                  onClick={handleResolve}
                  disabled={resolving}
                >
                  {resolving ? "Resolving…" : "Resolve incident"}
                </button>
              )}
            </header>

            {incident.error_message && (
              <div className="error-banner">
                Pipeline error: {incident.error_message}
              </div>
            )}

            <div className="incident-columns">
              <section className="panel">
                <h3>Timeline</h3>
                <IncidentTimeline events={events} />
              </section>

              <section className="panel">
                {incident.suspected_commit_sha && (
                  <div className="commit-card">
                    <h3>Suspected commit</h3>
                    <code className="commit-sha">
                      {incident.suspected_commit_sha.slice(0, 7)}
                    </code>{" "}
                    <span className="commit-message">
                      {incident.suspected_commit_message}
                    </span>
                    <div className="commit-author muted">
                      by {incident.suspected_commit_author}
                      {incident.commit_analysis_confidence != null && (
                        <> · {Math.round(incident.commit_analysis_confidence * 100)}% confidence</>
                      )}
                    </div>
                    <p className="commit-reasoning">
                      {incident.commit_analysis_reasoning}
                    </p>
                    {incident.suspected_commit_diff && (
                      <pre className="commit-diff">
                        {incident.suspected_commit_diff}
                      </pre>
                    )}
                  </div>
                )}

                {impact && (
                  <div className="impact-card">
                    <h3>Impact</h3>
                    <div className="impact-grid">
                      <div>
                        <span className="impact-value">
                          {impact.severity.toUpperCase()}
                        </span>
                        <span className="impact-label">Severity</span>
                      </div>
                      <div>
                        <span className="impact-value">
                          {impact.affected_users_pct}%
                        </span>
                        <span className="impact-label">Users affected</span>
                      </div>
                      <div>
                        <span className="impact-value">
                          ${impact.revenue_at_risk_per_hr_usd.toLocaleString()}
                          /hr
                        </span>
                        <span className="impact-label">Revenue at risk</span>
                      </div>
                      <div>
                        <span className="impact-value">
                          {impact.p95_latency_ms}ms
                        </span>
                        <span className="impact-label">p95 latency</span>
                      </div>
                    </div>
                  </div>
                )}

                {incident.runbook_title && (
                  <div className="runbook-card">
                    <h3>Runbook: {incident.runbook_title}</h3>
                    <p className="runbook-excerpt">
                      {incident.runbook_excerpt}
                    </p>
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
