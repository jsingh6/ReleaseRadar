"""
ReleaseRadar — FastAPI Backend (v3.0)
Hybrid BM25 + vector retrieval, metadata pre-filtering, structured insight output.
"""
from __future__ import annotations

import json
import os
import re as _re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import anthropic
from posthog import Posthog
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import chromadb

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
print(f"🔑 ANTHROPIC_API_KEY present: {'yes' if ANTHROPIC_API_KEY else 'NO — MISSING'} (len={len(ANTHROPIC_API_KEY)}, prefix={ANTHROPIC_API_KEY[:10]!r})")

POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
if POSTHOG_API_KEY:
    ph = Posthog(project_api_key=POSTHOG_API_KEY, host="https://us.i.posthog.com")
    print("📊 PostHog analytics enabled")
else:
    ph = Posthog(project_api_key="disabled", disabled=True)
    print("📊 PostHog disabled (no POSTHOG_API_KEY)")

POSTHOG_PERSONAL_KEY = os.getenv("POSTHOG_PERSONAL_API_KEY", "")
_posthog_project_id: str | None = os.getenv("POSTHOG_PROJECT_ID", None)
DATA_DIR = Path(__file__).parent / "data"

app = FastAPI(title="ReleaseRadar API", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_model: SentenceTransformer = None
_collection = None
_bm25: BM25Okapi = None
_all_texts: list[str] = []
_all_metas: list[dict] = []


# ── Text conversion ──────────────────────────────────────────────────────────

def issue_to_text(issue: dict) -> str:
    labels = ", ".join(issue.get("labels", []))
    resolved = f"Resolved: {issue['resolved']}" if issue.get("resolved") else "Status: Open"
    fix = issue.get("fix_description", "")
    return (
        f"[ISSUE {issue['id']}] {issue['summary']}\n"
        f"Repo: {issue['repo']} | Component: {issue['component']} | "
        f"Platform: {issue['platform']} | Priority: {issue['priority']} | {resolved}\n"
        f"Labels: {labels}\n"
        f"Description: {issue['description']}"
        + (f"\nFix: {fix}" if fix else "")
    )


def release_to_text(release: dict) -> str:
    highlights = "\n".join(f"  - {h}" for h in release["highlights"])
    known = "\n".join(f"  - {k}" for k in release.get("known_issues", []))
    return (
        f"[RELEASE {release['version']}] {release['release_date']} | {release['platform']}\n"
        f"Repo: {release.get('repo', 'N/A')}\n"
        f"Highlights:\n{highlights}\n"
        f"Changes: {release['changes']}"
        + (f"\nKnown Issues:\n{known}" if known else "")
    )


# ── Vector store + BM25 index ────────────────────────────────────────────────

def build_vectorstore():
    global _model, _collection, _bm25, _all_texts, _all_metas

    issues_path = DATA_DIR / "github_issues.json"
    releases_path = DATA_DIR / "release_notes.json"

    issues = json.loads(issues_path.read_text()) if issues_path.exists() else []
    releases = json.loads(releases_path.read_text()) if releases_path.exists() else []

    texts = []
    metadatas = []

    for issue in issues:
        texts.append(issue_to_text(issue))
        metadatas.append({
            "source": "github_issues", "id": issue["id"],
            "component": issue["component"], "platform": issue["platform"],
            "priority": issue["priority"], "status": issue["status"],
            "repo": issue["repo"], "version": "",
        })

    for release in releases:
        texts.append(release_to_text(release))
        metadatas.append({
            "source": "release_notes", "id": release["version"],
            "component": "Release", "platform": release["platform"],
            "priority": "info", "status": "Released",
            "repo": release.get("repo", ""), "version": release["version"],
        })

    if not texts:
        print("⚠️  No data to index.")
        return

    _all_texts = texts
    _all_metas = metadatas

    print("🧠 Loading embedding model...")
    _model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"💾 Embedding {len(texts)} documents...")
    vectors = _model.encode(texts, show_progress_bar=False)

    client = chromadb.Client()
    _collection = client.get_or_create_collection("releaseradar")
    # IDs are positional strings ("0", "1", ...) — used to look back into _all_texts
    _collection.add(
        ids=[str(i) for i in range(len(texts))],
        documents=texts,
        embeddings=vectors.tolist(),
        metadatas=metadatas,
    )

    print("🔤 Building BM25 index...")
    _bm25 = BM25Okapi([t.lower().split() for t in texts])

    print(f"✅ Ready: {len(texts)} documents (vector + BM25)")


@app.on_event("startup")
async def startup():
    build_vectorstore()


# ── Query entity extraction ──────────────────────────────────────────────────

def extract_query_filters(query: str) -> dict:
    """
    Pull platform / status / priority / source signals from natural language.
    These become ChromaDB where-clause filters, applied before vector search
    so we're not burning retrieval budget on irrelevant documents.
    """
    q = query.lower()
    filters: dict = {}

    if "android" in q and not any(x in q for x in ["ios", "iphone", "ipad"]):
        filters["platform"] = "Android"
    elif any(x in q for x in ["ios", "iphone", "ipad"]) and "android" not in q:
        filters["platform"] = "iOS"

    if any(x in q for x in ["still open", "unresolved", "not fixed", "still broken", "open issue", "open bug"]):
        filters["status"] = "Open"
    elif any(x in q for x in [" fixed", "resolved", "closed", "patched"]):
        filters["status"] = "Done"

    if any(x in q for x in ["p1", "critical", "blocker"]):
        filters["priority"] = "P1"
    elif any(x in q for x in ["p2", "high priority"]):
        filters["priority"] = "P2"

    if any(x in q for x in ["release", "changelog", "what changed", "what's new", "upgrade to", "version notes"]):
        filters["source"] = "release_notes"
    elif any(x in q for x in ["crash report", "open issue", "open bug", "filed issue"]):
        filters["source"] = "github_issues"

    return filters


def _build_chroma_where(filters: dict) -> dict | None:
    clauses = []

    if "platform" in filters:
        # "iOS, Android" is the combined platform value — include it for both platform queries
        clauses.append({"platform": {"$in": [filters["platform"], "iOS, Android"]}})

    if "status" in filters:
        clauses.append({"status": {"$eq": filters["status"]}})

    if "priority" in filters:
        clauses.append({"priority": {"$eq": filters["priority"]}})

    if "source" in filters:
        clauses.append({"source": {"$eq": filters["source"]}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _matches_filters(meta: dict, filters: dict) -> bool:
    for key, val in filters.items():
        if key == "platform":
            if val not in meta.get("platform", ""):
                return False
        elif key == "status":
            if meta.get("status", "").lower() != val.lower():
                return False
        elif key == "priority":
            if meta.get("priority", "") != val:
                return False
        elif key == "source":
            if meta.get("source", "") != val:
                return False
    return True


# ── Hybrid retrieval (BM25 + vector, RRF fusion) ─────────────────────────────

def _rrf_fuse(bm25_ranking: list[int], vector_ranking: list[int], k: int = 60) -> list[int]:
    """
    Reciprocal Rank Fusion: each doc scores 1/(k + rank) from each ranker.
    k=60 is the standard constant — dampens high-rank bonuses without losing signal.
    """
    scores: dict[int, float] = {}
    for rank, idx in enumerate(bm25_ranking):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    for rank, idx in enumerate(vector_ranking):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return [idx for idx, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def hybrid_search(query: str, top_k: int, filters: dict) -> tuple[list[str], list[dict]]:
    """
    BM25 catches exact term matches (version numbers, component names like Impeller/Hermes).
    Vector search catches semantic matches (paraphrases, related concepts).
    RRF merges both rankings without needing to tune score thresholds.
    """
    fetch_k = min(top_k * 3, len(_all_texts))
    chroma_where = _build_chroma_where(filters)

    # Vector search
    query_vector = _model.encode([query]).tolist()
    kwargs: dict = {
        "query_embeddings": query_vector,
        "n_results": fetch_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if chroma_where:
        kwargs["where"] = chroma_where

    try:
        vector_results = _collection.query(**kwargs)
    except Exception:
        # Filter may be too restrictive (e.g. zero matching docs) — retry without
        kwargs.pop("where", None)
        kwargs["n_results"] = min(fetch_k, _collection.count())
        vector_results = _collection.query(**kwargs)

    # ChromaDB IDs are positional strings ("0", "1", ...) matching _all_texts indices
    vector_ranking = [int(id_) for id_ in vector_results["ids"][0]]

    # BM25 search — full corpus, then apply metadata filter
    tokens = query.lower().split()
    bm25_scores = _bm25.get_scores(tokens)
    bm25_ranking = sorted(range(len(_all_texts)), key=lambda i: bm25_scores[i], reverse=True)
    if filters:
        bm25_ranking = [i for i in bm25_ranking if _matches_filters(_all_metas[i], filters)]
    bm25_ranking = bm25_ranking[:fetch_k]

    fused = _rrf_fuse(bm25_ranking, vector_ranking)[:top_k]
    return [_all_texts[i] for i in fused], [_all_metas[i] for i in fused]


# ── Structured insight extraction ────────────────────────────────────────────

def _extract_insight(text: str) -> tuple[str, dict | None]:
    """Strip <insight>JSON</insight> from the answer and parse it separately."""
    m = _re.search(r'<insight>(.*?)</insight>', text, _re.DOTALL)
    if not m:
        return text, None
    clean = (text[:m.start()].rstrip() + text[m.end():]).strip()
    try:
        return clean, json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return text, None


# ── Request / Response models ────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    top_k: int = 6


class SourceDoc(BaseModel):
    source: str
    id: str
    component: str
    platform: str
    repo: str
    snippet: str


# ── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are ReleaseRadar, an AI assistant for mobile engineering teams.
You analyze GitHub Issues and release notes from Flutter and React Native to help teams understand crash patterns, regressions, and release quality.

Rules:
- Only use information from the context provided. Never invent issue IDs or versions.
- Always cite issue IDs (e.g. GH-FL-1234) and release versions (e.g. FL-3.22.0) when referencing specific items.
- Distinguish between iOS and Android when platform is relevant.
- If context is insufficient, say so clearly rather than guessing.

After your analysis, append this block on its own with no surrounding text:
<insight>{"severity":"P1|P2|P3|Info","affected_versions":["FL-x.x","RN-x.x"],"affected_platforms":["iOS","Android"],"pattern":"one concise sentence describing the core pattern or finding","recommendation":"concrete action the engineering team should take","confidence":"High|Medium|Low"}</insight>

Severity: P1=crashes or data loss, P2=regressions impacting UX, P3=minor bugs, Info=general question.
Confidence: High=3+ sources corroborate, Medium=1-2 direct sources, Low=inferred from indirect evidence.
Only include versions and platforms actually mentioned in the context."""


# ── RAG query endpoint ───────────────────────────────────────────────────────

@app.post("/query")
async def query(req: QueryRequest):
    if not _collection or not _bm25:
        raise HTTPException(status_code=503, detail="Vector store not ready.")

    filters = extract_query_filters(req.query)
    docs, metas = hybrid_search(req.query, req.top_k, filters)

    context_parts = []
    sources = []
    seen_ids: set[str] = set()

    for doc, meta in zip(docs, metas):
        context_parts.append(
            f"[{meta['source'].upper()} | {meta['id']} | {meta.get('repo', '')} | {meta['platform']}]\n{doc}"
        )
        uid = f"{meta['source']}:{meta['id']}"
        if uid not in seen_ids:
            seen_ids.add(uid)
            sources.append(SourceDoc(
                source=meta["source"],
                id=meta["id"],
                component=meta["component"],
                platform=meta["platform"],
                repo=meta.get("repo", ""),
                snippet=doc[:200] + "..." if len(doc) > 200 else doc,
            ))

    context = "\n\n---\n\n".join(context_parts)
    async_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    sources_payload = [s.model_dump() for s in sources]

    async def generate():
        from datetime import datetime, timezone
        full_answer = ""

        yield ": ping\n\n"

        async with async_client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Context:\n\n{context}\n\n---\n\nQuestion: {req.query}"
            }],
        ) as stream:
            async for text in stream.text_stream:
                full_answer += text
                # Stop streaming display at <insight> — the tag is parsed separately
                display_cutoff = full_answer.find("<insight>")
                display = full_answer if display_cutoff < 0 else full_answer[:display_cutoff]
                yield f"data: {json.dumps({'type': 'token', 'text': text, 'display': display})}\n\n"

        clean_answer, insight = _extract_insight(full_answer)

        ph.capture(
            distinct_id="releaseradar-user",
            event="query_answered",
            properties={
                "query": req.query,
                "sources_count": len(sources),
                "source_ids": [s.id for s in sources],
                "repos": list({s.repo for s in sources}),
                "platforms": list({s.platform for s in sources}),
                "filters_applied": filters or None,
                "retrieval": "hybrid_bm25_vector_rrf",
                "insight_severity": insight.get("severity") if insight else None,
                "insight_confidence": insight.get("confidence") if insight else None,
            }
        )

        log_path = DATA_DIR / "query_log.json"
        log = json.loads(log_path.read_text()) if log_path.exists() else []
        log.append({
            "query": req.query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources_count": len(sources),
            "source_ids": [s.id for s in sources],
            "platforms": list({s.platform for s in sources}),
            "repos": list({s.repo for s in sources}),
            "filters": filters or None,
        })
        log_path.write_text(json.dumps(log))

        yield f"data: {json.dumps({'type': 'done', 'sources': sources_payload, 'query': req.query, 'answer': clean_answer, 'insight': insight, 'filters': filters or None})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── Stats endpoint ───────────────────────────────────────────────────────────

@app.get("/stats")
async def stats():
    issues_path = DATA_DIR / "github_issues.json"
    releases_path = DATA_DIR / "release_notes.json"

    issues = json.loads(issues_path.read_text()) if issues_path.exists() else []
    releases = json.loads(releases_path.read_text()) if releases_path.exists() else []

    p1 = sum(1 for i in issues if i.get("priority") == "P1")
    open_count = sum(1 for i in issues if i.get("status") == "Open")

    return {
        "issues": {"total": len(issues), "p1": p1, "open": open_count},
        "releases": {"total": len(releases), "latest": releases[-1]["version"] if releases else "N/A"},
        "vectorstore_ready": _collection is not None,
        "retrieval": "hybrid_bm25_vector",
    }


# ── Analytics endpoint ───────────────────────────────────────────────────────

def _fetch_posthog_events_sync() -> list[dict]:
    global _posthog_project_id
    import requests as req
    headers = {"Authorization": f"Bearer {POSTHOG_PERSONAL_KEY}"}

    if not _posthog_project_id:
        r = req.get("https://us.posthog.com/api/projects/", headers=headers, timeout=30)
        r.raise_for_status()
        _posthog_project_id = str(r.json()["results"][0]["id"])
        print(f"📊 PostHog project ID discovered: {_posthog_project_id}")

    all_events = []
    url = f"https://us.posthog.com/api/projects/{_posthog_project_id}/events/"
    params: dict = {"event": "query_answered", "limit": 500}
    while url:
        r = req.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        all_events.extend(data.get("results", []))
        url = data.get("next")
        params = {}
    return all_events


@app.get("/analytics")
async def analytics():
    from datetime import date
    from collections import Counter

    if POSTHOG_PERSONAL_KEY:
        try:
            from asyncio import get_event_loop
            events = await get_event_loop().run_in_executor(None, _fetch_posthog_events_sync)
            today = date.today().isoformat()
            queries_today = sum(1 for e in events if e.get("timestamp", "").startswith(today))

            props = [e.get("properties", {}) for e in events]
            all_ids = [sid for p in props for sid in p.get("source_ids", [])]
            most_cited = Counter(all_ids).most_common(1)[0][0] if all_ids else None

            all_platforms = [p2 for p in props for p2 in p.get("platforms", [])]
            top_platform = Counter(all_platforms).most_common(1)[0][0] if all_platforms else None

            recent = sorted(events, key=lambda e: e.get("timestamp", ""), reverse=True)[:5]
            return {
                "total_queries": len(events),
                "queries_today": queries_today,
                "most_cited_issue": most_cited,
                "top_platform": top_platform,
                "recent_queries": [
                    {
                        "query": e["properties"].get("query", ""),
                        "timestamp": e["timestamp"],
                        "sources_count": e["properties"].get("sources_count", 0),
                    }
                    for e in recent
                ],
            }
        except Exception as exc:
            print(f"⚠️  PostHog analytics fetch failed: {type(exc).__name__}: {exc!r} — falling back to local log")

    from collections import Counter
    log_path = DATA_DIR / "query_log.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    today = date.today().isoformat()
    queries_today = sum(1 for e in log if e.get("timestamp", "").startswith(today))
    all_ids = [sid for e in log for sid in e.get("source_ids", [])]
    most_cited = Counter(all_ids).most_common(1)[0][0] if all_ids else None
    all_platforms = [p for e in log for p in e.get("platforms", [])]
    top_platform = Counter(all_platforms).most_common(1)[0][0] if all_platforms else None
    recent = sorted(log, key=lambda e: e.get("timestamp", ""), reverse=True)[:5]
    return {
        "total_queries": len(log),
        "queries_today": queries_today,
        "most_cited_issue": most_cited,
        "top_platform": top_platform,
        "recent_queries": [
            {"query": e["query"], "timestamp": e["timestamp"], "sources_count": e["sources_count"]}
            for e in recent
        ],
    }


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "vectorstore_ready": _collection is not None,
        "bm25_ready": _bm25 is not None,
        "doc_count": len(_all_texts),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
