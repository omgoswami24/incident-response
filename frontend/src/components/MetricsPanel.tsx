import type { Metrics, SeriesBucket } from "../types";

/** Inline SVG sparkline of p95 latency with the learned baseline as a dashed
 * reference line. Buckets with 5xx errors are marked red. */
function Sparkline({
  buckets,
  baselineP95,
}: {
  buckets: SeriesBucket[];
  baselineP95: number | null;
}) {
  const W = 260;
  const H = 56;
  const active = buckets.filter((b) => b.count > 0);
  const maxY = Math.max(
    baselineP95 ?? 0,
    ...active.map((b) => b.p95_ms),
    10,
  );
  const x = (i: number) => (i / Math.max(buckets.length - 1, 1)) * W;
  const y = (v: number) => H - 4 - (v / maxY) * (H - 10);

  const points = buckets
    .map((b, i) => (b.count > 0 ? `${x(i).toFixed(1)},${y(b.p95_ms).toFixed(1)}` : null))
    .filter(Boolean)
    .join(" ");

  // area wash under the line, anchored to the bottom edge
  const activeIndices = buckets
    .map((b, i) => (b.count > 0 ? i : null))
    .filter((i): i is number => i !== null);
  const areaPoints =
    activeIndices.length > 1
      ? `${x(activeIndices[0]).toFixed(1)},${H} ${points} ${x(
          activeIndices[activeIndices.length - 1],
        ).toFixed(1)},${H}`
      : "";

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="p95 latency over the last 5 minutes vs learned baseline"
    >
      {areaPoints && <polygon points={areaPoints} className="sparkline-area" />}
      {baselineP95 != null && (
        <line
          x1={0}
          x2={W}
          y1={y(baselineP95)}
          y2={y(baselineP95)}
          className="sparkline-baseline"
        />
      )}
      {points && <polyline points={points} className="sparkline-line" />}
      {buckets.map((b, i) =>
        b.count > 0 && b.error_rate_pct > 0 ? (
          <circle
            key={i}
            cx={x(i)}
            cy={y(b.p95_ms)}
            r={2.2}
            className="sparkline-error-dot"
          />
        ) : null,
      )}
    </svg>
  );
}

export function MetricsPanel({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) {
    return (
      <div className="metrics-panel">
        <p className="muted">Connecting to live metrics…</p>
      </div>
    );
  }

  const groups = Object.keys(metrics.series).sort();
  return (
    <div className="metrics-panel">
      <div className="metrics-panel-header">
        <h3>Live traffic — target app</h3>
        <span className={`baseline-chip ${metrics.baseline_ready ? "ready" : ""}`}>
          {metrics.baseline_ready ? "baseline learned" : "learning baseline…"}
        </span>
      </div>
      <div className="metrics-grid">
        {groups.map((group) => {
          const cur = metrics.current[group];
          const base = metrics.baseline?.[group] ?? null;
          // Mirror the backend detector's breach rule (live/detector.py) so
          // the chip lights up only when the detector would actually consider
          // it a breach: 2x baseline AND a +30ms absolute floor (which stops
          // fast, low-baseline endpoints from flickering on normal jitter).
          const degraded =
            cur &&
            base &&
            ((cur.p95_ms > 2 * base.p95_ms && cur.p95_ms > base.p95_ms + 30) ||
              cur.error_rate_pct > Math.max(5, base.error_rate_pct + 5));
          return (
            <div key={group} className={`metric-card ${degraded ? "degraded" : ""}`}>
              <div className="metric-card-title">
                <code>{group}</code>
                {degraded && <span className="degraded-chip">degraded</span>}
              </div>
              <Sparkline
                buckets={metrics.series[group]}
                baselineP95={base?.p95_ms ?? null}
              />
              <div className="metric-card-stats">
                <div className="stat-primary">
                  <span>
                    p95 <strong>{cur ? `${cur.p95_ms}ms` : "—"}</strong>
                  </span>
                  <span className={cur && cur.error_rate_pct > 0 ? "err-text" : "muted"}>
                    <strong>{cur ? `${cur.error_rate_pct}%` : "—"}</strong> err
                  </span>
                </div>
                <div className="stat-secondary">
                  <span>{base ? `base ${base.p95_ms}ms` : "learning…"}</span>
                  <span>{cur ? `${cur.rps} rps` : ""}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {metrics.recent_errors.length > 0 && (
        <div className="recent-errors">
          <span className="err-text">recent 5xx:</span>{" "}
          <code>{metrics.recent_errors[metrics.recent_errors.length - 1].body}</code>
        </div>
      )}
    </div>
  );
}
