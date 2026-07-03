import { useEffect, useRef, useState } from "react";
import type {
  Environment,
  FaultScenario,
  IncidentDetail,
  IncidentSummary,
  Metrics,
  TimelineEvent,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`);
  }
  return resp.json() as Promise<T>;
}

export async function fetchFaultScenarios(): Promise<FaultScenario[]> {
  return json(await fetch(`${API_BASE}/api/fault-scenarios`));
}

export async function fetchIncidents(): Promise<IncidentSummary[]> {
  return json(await fetch(`${API_BASE}/api/incidents`));
}

export async function fetchIncident(id: string): Promise<IncidentDetail> {
  return json(await fetch(`${API_BASE}/api/incidents/${id}`));
}

export async function fetchTimeline(id: string): Promise<TimelineEvent[]> {
  return json(await fetch(`${API_BASE}/api/incidents/${id}/timeline`));
}

export async function injectFault(
  faultScenarioId: string,
): Promise<{ deployed_branch: string; head_sha: string | null; note: string }> {
  return json(
    await fetch(`${API_BASE}/api/faults/inject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fault_scenario_id: faultScenarioId }),
    }),
  );
}

export async function retryIncident(id: string): Promise<IncidentDetail> {
  return json(
    await fetch(`${API_BASE}/api/incidents/${id}/retry`, { method: "POST" }),
  );
}

export async function remediateIncident(id: string): Promise<IncidentDetail> {
  return json(
    await fetch(`${API_BASE}/api/incidents/${id}/remediate`, { method: "POST" }),
  );
}

export async function fetchMetrics(): Promise<Metrics> {
  return json(await fetch(`${API_BASE}/api/metrics`));
}

export async function fetchEnvironment(): Promise<Environment> {
  return json(await fetch(`${API_BASE}/api/environment`));
}

export async function resetEnvironment(): Promise<unknown> {
  return json(await fetch(`${API_BASE}/api/environment/reset`, { method: "POST" }));
}

/** Poll helper: refetches on an interval while the tab is visible. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number): T | null {
  const [data, setData] = useState<T | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      fetcherRef.current()
        .then((d) => {
          if (!cancelled) setData(d);
        })
        .catch(() => {});
    };
    tick();
    const handle = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [intervalMs]);

  return data;
}

export async function resolveIncident(
  id: string,
  resolutionNotes?: string,
): Promise<IncidentDetail> {
  return json(
    await fetch(`${API_BASE}/api/incidents/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution_notes: resolutionNotes ?? null }),
    }),
  );
}

/** Live-updates a timeline via SSE, re-fetching the full incident on every
 * event so the UI stays in sync with derived fields (status, commit, etc.),
 * not just the raw event log. */
export function useIncidentStream(incidentId: string | null): {
  incident: IncidentDetail | null;
  events: TimelineEvent[];
} {
  const [incident, setIncident] = useState<IncidentDetail | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setIncident(null);
    setEvents([]);
    if (!incidentId) return;

    let cancelled = false;
    const seenIds = new Set<string>();
    const addEvents = (newEvents: TimelineEvent[]) => {
      const fresh = newEvents.filter((e) => !seenIds.has(e.id));
      fresh.forEach((e) => seenIds.add(e.id));
      if (fresh.length) {
        setEvents((prev) =>
          [...prev, ...fresh].sort((a, b) => a.ts.localeCompare(b.ts)),
        );
      }
    };

    // Subscribe before backfilling so events can't land in the gap.
    const source = new EventSource(
      `${API_BASE}/api/incidents/${incidentId}/stream`,
    );
    sourceRef.current = source;

    source.addEventListener("timeline_event", (e) => {
      const event: TimelineEvent = JSON.parse((e as MessageEvent).data);
      addEvents([event]);
      fetchIncident(incidentId).then((inc) => {
        if (!cancelled) setIncident(inc);
      });
    });

    fetchIncident(incidentId).then((inc) => {
      if (!cancelled) setIncident(inc);
    });
    fetchTimeline(incidentId).then((initial) => {
      if (!cancelled) addEvents(initial);
    });

    return () => {
      cancelled = true;
      source.close();
    };
  }, [incidentId]);

  return { incident, events };
}
