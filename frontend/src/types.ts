export type IncidentStatus =
  | "firing"
  | "analyzing"
  | "briefed"
  | "remediating"
  | "resolved"
  | "postmortem_generated"
  | "closed";

export type TimelineEventType =
  | "alert_detected"
  | "analyzing_started"
  | "commit_identified"
  | "runbook_retrieved"
  | "impact_estimated"
  | "slack_brief_posted"
  | "remediation_started"
  | "remediation_applied"
  | "recovery_verified"
  | "remediation_failed"
  | "resolved"
  | "postmortem_generated"
  | "closed"
  | "error";

export interface TimelineEvent {
  id: string;
  ts: string;
  type: TimelineEventType;
  title: string;
  detail: string | null;
}

export interface IncidentSummary {
  id: string;
  status: IncidentStatus;
  ground_truth_scenario_id: string | null;
  diagnosis_correct: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface DegradedEndpoint {
  p95_ms: number;
  baseline_p95_ms: number;
  latency_ratio: number;
  error_rate_pct: number;
  rps: number;
}

export interface Impact {
  severity: string;
  degraded_endpoints: Record<string, DegradedEndpoint>;
  affected_traffic_pct: number;
  requests_affected_per_hr: number;
  est_revenue_at_risk_per_hr_usd: number;
  method: string;
}

export interface SlackBlock {
  type: string;
  text?: { type: string; text: string };
  fields?: { type: string; text: string }[];
}

export interface SlackBrief {
  ok: boolean;
  channel: string;
  ts: string;
  blocks: SlackBlock[];
}

export interface IncidentDetail {
  id: string;
  status: IncidentStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  postmortem_generated_at: string | null;

  detected_alert_text: string;
  baseline_json: string | null;
  detection_stats_json: string | null;

  ground_truth_scenario_id: string | null;
  ground_truth_commit_sha: string | null;
  diagnosis_correct: boolean | null;

  suspected_commit_sha: string | null;
  suspected_commit_message: string | null;
  suspected_commit_author: string | null;
  suspected_commit_diff: string | null;
  commit_analysis_reasoning: string | null;
  commit_analysis_confidence: number | null;

  runbook_id: string | null;
  runbook_title: string | null;
  runbook_excerpt: string | null;

  impact_json: string | null;
  slack_brief_json: string | null;

  remediation_revert_sha: string | null;
  remediation_verified: boolean | null;
  recovery_stats_json: string | null;

  resolution_notes: string | null;
  postmortem_markdown: string | null;
}

export interface FaultScenario {
  id: string;
  title: string;
  description: string;
  deploy_branch: string;
}

export interface GroupStats {
  count: number;
  rps: number;
  p50_ms: number;
  p95_ms: number;
  error_rate_pct: number;
}

export interface SeriesBucket {
  t: number;
  count: number;
  p95_ms: number;
  error_rate_pct: number;
}

export interface Metrics {
  current: Record<string, GroupStats>;
  series: Record<string, SeriesBucket[]>;
  baseline: Record<string, GroupStats> | null;
  baseline_ready: boolean;
  recent_errors: { group: string; body: string }[];
}

export interface Environment {
  app: {
    running: boolean;
    branch: string;
    head_sha: string | null;
    head_message: string | null;
    port: number;
    seconds_since_deploy: number | null;
  };
  detector: {
    baseline_ready: boolean;
    baseline: Record<string, GroupStats> | null;
    baseline_age_s: number | null;
  };
  load_workers: number;
}
