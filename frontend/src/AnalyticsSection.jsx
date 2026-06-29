import { useState, useEffect } from "react";

/* ------------------------------------------------------------------ */
/*  Shared style tokens — matches the existing ReleaseRadar dashboard  */
/* ------------------------------------------------------------------ */
const CARD = {
  background: "#fff",
  border: "1px solid #e6e9ef",
  borderRadius: 14,
  boxShadow: "0 1px 2px rgba(16,24,40,0.05)",
};
const MONO = "ui-monospace, 'SF Mono', Menlo, monospace";
const ACCENT = { indigo: "#4f46e5", green: "#16a34a", orange: "#e8770f" };

const styles = {
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    margin: "40px 2px 18px",
  },
  sectionLabelWrap: { display: "flex", alignItems: "center", gap: 10 },
  liveDot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    background: ACCENT.green,
    boxShadow: "0 0 0 3px rgba(22,163,74,0.15)",
  },
  sectionLabel: {
    fontSize: 13,
    fontWeight: 700,
    letterSpacing: "0.12em",
    color: "#64748b",
  },
  endpointTag: {
    fontSize: 12.5,
    fontWeight: 600,
    color: "#94a3b8",
    fontFamily: MONO,
  },
  badgeRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
  },
  badge: {
    display: "inline-flex",
    alignItems: "center",
    gap: 10,
    background: "#fff",
    border: "1px solid #e6e9ef",
    borderRadius: 999,
    padding: "9px 17px",
    boxShadow: "0 1px 2px rgba(16,24,40,0.05)",
  },
  badgeDot: { width: 8, height: 8, borderRadius: "50%", flexShrink: 0 },
  badgeLabel: { fontSize: 13, fontWeight: 500, color: "#64748b" },
  badgeValue: { fontSize: 16, fontWeight: 800, color: "#1e293b" },
  badgeValueMono: { fontFamily: MONO, fontSize: 14, fontWeight: 700 },
  listCard: {
    background: "#fff",
    border: "1px solid #e6e9ef",
    borderRadius: 16,
    boxShadow: "0 1px 3px rgba(16,24,40,0.06)",
    padding: "24px 28px 10px",
    marginTop: 18,
  },
  listHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    paddingBottom: 6,
  },
  listLabel: {
    fontSize: 12.5,
    fontWeight: 700,
    letterSpacing: "0.1em",
    color: "#64748b",
  },
  listHint: { fontSize: 12, fontWeight: 600, color: "#94a3b8" },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 20,
    padding: "15px 0",
    borderTop: "1px solid #eef1f5",
  },
  rowMain: { display: "flex", flexDirection: "column", gap: 7, minWidth: 0 },
  rowQuery: { fontSize: 15, fontWeight: 500, color: "#1e293b", lineHeight: 1.35 },
  sourcesPill: {
    display: "inline-flex",
    alignItems: "center",
    alignSelf: "flex-start",
    fontSize: 11.5,
    fontWeight: 600,
    color: ACCENT.indigo,
    background: "#eef2ff",
    padding: "3px 9px",
    borderRadius: 999,
  },
  rowTime: {
    fontSize: 13,
    fontWeight: 500,
    color: "#94a3b8",
    whiteSpace: "nowrap",
    fontVariantNumeric: "tabular-nums",
  },
  stateCard: {
    ...CARD,
    padding: "56px 24px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    textAlign: "center",
    marginTop: 0,
  },
  stateTitle: { fontSize: 15, fontWeight: 700, color: "#1e293b" },
  stateSub: { fontSize: 13, color: "#94a3b8", fontWeight: 500 },
  shimmer: {
    background: "linear-gradient(90deg,#eceff4 25%,#f6f8fb 37%,#eceff4 63%)",
    backgroundSize: "400% 100%",
    animation: "rr-shimmer 1.4s ease infinite",
    borderRadius: 8,
  },
};

/* Relative timestamp, e.g. "7m ago" */
function relTime(ts) {
  const d = new Date(ts);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  const days = Math.floor(diff / 86400);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function SectionHeader() {
  return (
    <div style={styles.sectionHeader}>
      <div style={styles.sectionLabelWrap}>
        <span style={styles.liveDot} />
        <span style={styles.sectionLabel}>ANALYTICS</span>
      </div>
      <span style={styles.endpointTag}>GET /analytics</span>
    </div>
  );
}

/* Inject the shimmer keyframes once (kept here so the component is drop-in). */
const KEYFRAMES = `@keyframes rr-shimmer{0%{background-position:100% 0}100%{background-position:0 0}}`;

export default function AnalyticsSection({ data: dataProp, apiBase = "" }) {
  const [data, setData] = useState(dataProp || null);
  const [loading, setLoading] = useState(!dataProp);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (dataProp) return; // data supplied directly — skip fetch
    let alive = true;
    fetch(`${apiBase}/analytics`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((json) => {
        if (alive) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (alive) {
          setError(err.message || "Failed to load analytics");
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [dataProp]);

  const recent = (data?.recent_queries || []).slice(0, 5);
  const isEmpty = data && data.total_queries === 0 && recent.length === 0;

  return (
    <>
      <style>{KEYFRAMES}</style>
      <SectionHeader />

      {loading && <LoadingState />}

      {!loading && error && (
        <div style={styles.stateCard}>
          <div style={styles.stateTitle}>Couldn’t load analytics</div>
          <div style={{ ...styles.stateSub, maxWidth: 360, lineHeight: 1.5 }}>
            {error}. Check that the <code style={{ fontFamily: MONO }}>/analytics</code> endpoint is reachable.
          </div>
        </div>
      )}

      {!loading && !error && isEmpty && (
        <div style={styles.stateCard}>
          <div style={styles.stateTitle}>No analytics yet</div>
          <div style={{ ...styles.stateSub, maxWidth: 340, lineHeight: 1.5 }}>
            Usage data will appear here once people start asking ReleaseRadar questions.
          </div>
        </div>
      )}

      {!loading && !error && !isEmpty && data && (
        <>
          <div style={styles.badgeRow}>
            <Badge dot={ACCENT.indigo} label="Total queries">
              <span style={styles.badgeValue}>{data.total_queries}</span>
            </Badge>
            <Badge dot={ACCENT.green} label="Today">
              <span style={styles.badgeValue}>{data.queries_today}</span>
            </Badge>
            <Badge dot={ACCENT.orange} label="Most cited">
              <span style={{ ...styles.badgeValueMono, color: ACCENT.orange }}>{data.most_cited_issue}</span>
            </Badge>
            <Badge dot={ACCENT.indigo} label="Top platform">
              <span style={{ ...styles.badgeValue, fontSize: 15, color: ACCENT.indigo }}>{data.top_platform}</span>
            </Badge>
          </div>

          <div style={styles.listCard}>
            <div style={styles.listHeader}>
              <span style={styles.listLabel}>RECENT QUERIES</span>
              <span style={styles.listHint}>last 5 questions</span>
            </div>
            {recent.map((q, i) => (
              <div key={i} style={styles.row}>
                <div style={styles.rowMain}>
                  <span style={styles.rowQuery}>{q.query}</span>
                  <span style={styles.sourcesPill}>
                    {q.sources_count} {q.sources_count === 1 ? "source" : "sources"}
                  </span>
                </div>
                <span style={styles.rowTime} title={new Date(q.timestamp).toLocaleString()}>
                  {relTime(q.timestamp)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}

function Badge({ dot, label, children }) {
  return (
    <div style={styles.badge}>
      <span style={{ ...styles.badgeDot, background: dot }} />
      <span style={styles.badgeLabel}>{label}</span>
      {children}
    </div>
  );
}

function LoadingState() {
  return (
    <>
      <div style={styles.badgeRow}>
        {[110, 70, 150, 120].map((w, i) => (
          <div key={i} style={styles.badge}>
            <span style={{ ...styles.badgeDot, ...styles.shimmer, borderRadius: "50%" }} />
            <div style={{ ...styles.shimmer, width: w, height: 12, borderRadius: 6 }} />
          </div>
        ))}
      </div>
      <div style={{ ...styles.listCard, padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20 }}>
            <div style={{ ...styles.shimmer, width: "58%", height: 14, borderRadius: 6 }} />
            <div style={{ ...styles.shimmer, width: 64, height: 12, borderRadius: 6 }} />
          </div>
        ))}
      </div>
    </>
  );
}
