export type IncidentStatus =
  | "firing"
  | "analyzing"
  | "briefed"
  | "resolved"
  | "postmortem_generated";

export type TimelineEventType =
  | "fault_injected"
  | "analyzing_started"
  | "commit_identified"
  | "runbook_retrieved"
  | "impact_estimated"
  | "slack_brief_posted"
  | "resolved"
  | "postmortem_generated"
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
  fault_scenario_id: string;
  status: IncidentStatus;
  created_at: string;
  updated_at: string;
}

export interface Impact {
  affected_users_pct: number;
  revenue_at_risk_per_hr_usd: number;
  p95_latency_ms: number;
  error_rate_pct: number;
  severity: string;
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
  fault_scenario_id: string;
  status: IncidentStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  postmortem_generated_at: string | null;

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
  resolution_notes: string | null;
  postmortem_markdown: string | null;
}

export interface FaultScenario {
  id: string;
  title: string;
  alert_description: string;
}
