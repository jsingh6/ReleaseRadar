import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AnalyticsSection from "./AnalyticsSection";

const API_BASE = "https://releaseradar-production-9651.up.railway.app";

const SUGGESTED_QUERIES = [
  "Which crash issues affected Android?",
  "What regressions were introduced in Flutter 3.19?",
  "Which issues are still open and unresolved?",
  "What rendering bugs appear across multiple releases?",
  "Which release introduced Impeller and what problems followed?",
  "What are the most critical P1 issues in the dataset?",
];

const SOURCE_COLORS = {
  github_issues: { bg: "#EEF2FF", text: "#4338CA", label: "GITHUB" },
  release_notes: { bg: "#F0FDF4", text: "#16A34A", label: "RELEASE" },
};

function SourceBadge({ source }) {
  const cfg = SOURCE_COLORS[source] || { bg: "#F3F4F6", text: "#374151", label: source };
  return (
    <span style={{
      background: cfg.bg, color: cfg.text,
      fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
      padding: "2px 7px", borderRadius: 4, fontFamily: "monospace"
    }}>
      {cfg.label}
    </span>
  );
}

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{
      background: "#fff", borderRadius: 10, padding: "16px 20px",
      border: "1px solid #E5E7EB", flex: 1, minWidth: 120
    }}>
      <div style={{ fontSize: 26, fontWeight: 800, color: color || "#111827", lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#374151", marginTop: 4 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function SourceCard({ s }) {
  const cfg = SOURCE_COLORS[s.source] || { text: "#6B7280" };
  return (
    <div style={{
      background: "#FAFAFA", border: "1px solid #E5E7EB",
      borderLeft: `3px solid ${cfg.text}`,
      borderRadius: 8, padding: "10px 14px", marginBottom: 8
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <SourceBadge source={s.source} />
        <span style={{ fontSize: 12, fontWeight: 700, color: "#111827", fontFamily: "monospace" }}>{s.id}</span>
        <span style={{ fontSize: 11, color: "#9CA3AF" }}>{s.platform}</span>
      </div>
      <div style={{ fontSize: 11, color: "#9CA3AF", fontWeight: 600, marginBottom: 2 }}>{s.component} · {s.repo}</div>
      <div style={{ fontSize: 12, color: "#4B5563", lineHeight: 1.5 }}>{s.snippet}</div>
    </div>
  );
}

export default function ReleaseRadar() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE}/stats`)
      .then(r => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);

  async function runQuery(q) {
    const text = q || query;
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text, top_k: 6 }),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let answer = "";
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop(); // last part may be incomplete
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "token") {
              answer += event.text;
              setLoading(false);
              setResult({ answer, sources: [], query: text });
            } else if (event.type === "done") {
              setResult({ answer, sources: event.sources, query: event.query });
            }
          } catch (_) {}
        }
      }
      setHistory(prev => [{ query: text }, ...prev.slice(0, 4)]);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ fontFamily: "'Inter', system-ui, sans-serif", background: "#F8FAFC", minHeight: "100vh" }}>

      {/* Header */}
      <div style={{
        background: "#0F172A", color: "#fff", padding: "0 32px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        height: 56, borderBottom: "1px solid #1E293B"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 20 }}>🛰️</span>
          <span style={{ fontWeight: 800, fontSize: 17, letterSpacing: "-0.02em" }}>ReleaseRadar</span>
          <span style={{
            background: "#1E3A5F", color: "#60A5FA", fontSize: 10,
            fontWeight: 700, padding: "2px 8px", borderRadius: 4, letterSpacing: "0.05em"
          }}>RAG · MOBILE INTELLIGENCE</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {["GITHUB ISSUES", "RELEASES"].map((s, i) => (
            <span key={s} style={{
              fontSize: 10, fontWeight: 700, padding: "3px 8px",
              borderRadius: 4, fontFamily: "monospace",
              background: ["#312E81", "#14532D"][i],
              color: ["#A5B4FC", "#86EFAC"][i]
            }}>{s}</span>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 24px" }}>

        {/* Stats row */}
        {stats && (
          <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
            <StatCard
              label="GitHub Issues"
              value={stats.issues?.total ?? 0}
              sub={`${stats.issues?.p1 ?? 0} P1 · ${stats.issues?.open ?? 0} open`}
              color="#4338CA"
            />
            <StatCard
              label="Releases Indexed"
              value={stats.releases?.total ?? 0}
              sub={`latest ${stats.releases?.latest ?? "N/A"}`}
              color="#16A34A"
            />
            <StatCard
              label="Vector Store"
              value={stats.vectorstore_ready ? "Ready" : "Building"}
              sub="ChromaDB · 146 chunks"
              color={stats.vectorstore_ready ? "#16A34A" : "#D97706"}
            />
            <StatCard
              label="Sources"
              value="2"
              sub="flutter/flutter · facebook/react-native"
              color="#D97706"
            />
          </div>
        )}

        <AnalyticsSection apiBase={API_BASE} />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 20 }}>

          {/* Main panel */}
          <div>
            <div style={{
              background: "#fff", borderRadius: 12, padding: 20,
              border: "1px solid #E5E7EB", marginBottom: 16,
              boxShadow: "0 1px 3px rgba(0,0,0,0.06)"
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#374151", marginBottom: 10 }}>
                Ask anything about crashes, regressions, or releases
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && runQuery()}
                  placeholder="e.g. Which crash issues affected Android?"
                  style={{
                    flex: 1, padding: "10px 14px", fontSize: 14, border: "1px solid #D1D5DB",
                    borderRadius: 8, outline: "none", fontFamily: "inherit",
                    background: "#F9FAFB"
                  }}
                />
                <button
                  onClick={() => runQuery()}
                  disabled={loading || !query.trim()}
                  style={{
                    background: loading ? "#6B7280" : "#0F172A", color: "#fff",
                    border: "none", borderRadius: 8, padding: "10px 20px",
                    fontSize: 14, fontWeight: 600, cursor: loading ? "not-allowed" : "pointer",
                  }}
                >
                  {loading ? "Searching…" : "Ask →"}
                </button>
              </div>

              <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 6 }}>
                {SUGGESTED_QUERIES.map(q => (
                  <button key={q} onClick={() => { setQuery(q); runQuery(q); }} style={{
                    background: "#F1F5F9", border: "1px solid #E2E8F0",
                    borderRadius: 6, padding: "4px 10px", fontSize: 11,
                    color: "#475569", cursor: "pointer", fontFamily: "inherit"
                  }}>{q}</button>
                ))}
              </div>
            </div>

            {error && (
              <div style={{
                background: "#FEF2F2", border: "1px solid #FECACA",
                borderRadius: 10, padding: 16, color: "#DC2626", fontSize: 13, marginBottom: 16
              }}>
                ⚠️ {error} — Make sure the backend is running on port 8000.
              </div>
            )}

            {loading && (
              <div style={{
                background: "#fff", borderRadius: 12, padding: 32, textAlign: "center",
                border: "1px solid #E5E7EB", color: "#6B7280", fontSize: 14
              }}>
                <div style={{ fontSize: 24, marginBottom: 8 }}>🔍</div>
                Searching GitHub issues and release notes…
              </div>
            )}

            {result && !loading && (
              <div>
                <div style={{
                  background: "#fff", borderRadius: 12, padding: 20, marginBottom: 16,
                  border: "1px solid #E5E7EB", boxShadow: "0 1px 3px rgba(0,0,0,0.06)"
                }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", letterSpacing: "0.06em", marginBottom: 12 }}>
                    AI ANSWER
                  </div>
                  <div style={{ fontSize: 14, color: "#111827", lineHeight: 1.7 }}>
  <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.answer}</ReactMarkdown>
</div>
                </div>

                {result.sources?.length > 0 && (
                  <div style={{
                    background: "#fff", borderRadius: 12, padding: 20,
                    border: "1px solid #E5E7EB", boxShadow: "0 1px 3px rgba(0,0,0,0.06)"
                  }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", letterSpacing: "0.06em", marginBottom: 12 }}>
                      SOURCES RETRIEVED ({result.sources.length})
                    </div>
                    {result.sources.map((s, i) => <SourceCard key={i} s={s} />)}
                  </div>
                )}
              </div>
            )}

            {!result && !loading && !error && (
              <div style={{
                background: "#fff", borderRadius: 12, padding: 40, textAlign: "center",
                border: "1px solid #E5E7EB", color: "#9CA3AF"
              }}>
                <div style={{ fontSize: 36, marginBottom: 12 }}>🛰️</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: "#374151", marginBottom: 6 }}>
                  ReleaseRadar is ready
                </div>
                <div style={{ fontSize: 13 }}>
                  Ask a question or pick a suggested query to search across<br />
                  real GitHub Issues from flutter/flutter and facebook/react-native.
                </div>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div>
            <div style={{
              background: "#0F172A", color: "#E2E8F0", borderRadius: 12,
              padding: 18, marginBottom: 16, fontSize: 12
            }}>
              <div style={{ fontWeight: 700, fontSize: 11, color: "#94A3B8", letterSpacing: "0.08em", marginBottom: 12 }}>
                ARCHITECTURE
              </div>
              {[
                ["Data", "GitHub Issues API"],
                ["Chunking", "LangChain Splitter"],
                ["Embeddings", "all-MiniLM-L6-v2"],
                ["Vector DB", "ChromaDB"],
                ["Retrieval", "top-k=6 similarity"],
                ["LLM", "Claude Sonnet 4.6"],
                ["Backend", "FastAPI + Python"],
                ["Frontend", "React + Vite"],
              ].map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={{ color: "#64748B", fontWeight: 600 }}>{k}</span>
                  <span style={{ color: "#CBD5E1", textAlign: "right" }}>{v}</span>
                </div>
              ))}
            </div>

            {history.length > 0 && (
              <div style={{
                background: "#fff", borderRadius: 12, padding: 16,
                border: "1px solid #E5E7EB"
              }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", letterSpacing: "0.06em", marginBottom: 10 }}>
                  RECENT QUERIES
                </div>
                {history.map((h, i) => (
                  <div
                    key={i}
                    onClick={() => { setQuery(h.query); runQuery(h.query); }}
                    style={{
                      padding: "8px 0",
                      borderBottom: i < history.length - 1 ? "1px solid #F3F4F6" : "none",
                      cursor: "pointer", fontSize: 12, color: "#374151"
                    }}
                  >
                    {h.query.length > 52 ? h.query.slice(0, 52) + "…" : h.query}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}