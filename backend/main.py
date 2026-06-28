"""
ReleaseRadar — FastAPI Backend
Reads GitHub Issues + release notes, builds a ChromaDB vector store, serves a RAG query endpoint.

KEY LEARNING: This file shows BOTH approaches side by side:
  - WITH LangChain (what we actually use)
  - WITHOUT LangChain (raw chromadb + sentence_transformers)
Search for "# ── WITHOUT LANGCHAIN" to see the equivalent raw code.
"""

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import anthropic

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
print(f"🔑 ANTHROPIC_API_KEY present: {'yes' if ANTHROPIC_API_KEY else 'NO — MISSING'} (len={len(ANTHROPIC_API_KEY)}, prefix={ANTHROPIC_API_KEY[:10]!r})")
DATA_DIR = Path(__file__).parent / "data"
CHROMA_DIR = "/tmp/releaseradar_chroma"

# ──────────────────────────────────────────────────────────────────────────────
# APPROACH A — WITH LANGCHAIN (what we use)
# LangChain wraps sentence-transformers + chromadb behind a unified interface.
# You call from_texts() and similarity_search_with_score() — it handles the rest.
# ──────────────────────────────────────────────────────────────────────────────
from sentence_transformers import SentenceTransformer
import chromadb
# ──────────────────────────────────────────────────────────────────────────────
# APPROACH B — WITHOUT LANGCHAIN (equivalent raw code, not used but shown)
# Uncomment this block and replace the LangChain calls below to switch modes.
# ──────────────────────────────────────────────────────────────────────────────
#
# from sentence_transformers import SentenceTransformer
# import chromadb
# import numpy as np
#
# _raw_model = None      # SentenceTransformer instance
# _raw_collection = None # chromadb Collection instance
#
# def build_vectorstore_raw(texts: list[str], metadatas: list[dict]):
#     global _raw_model, _raw_collection
#
#     # Step 1: Load embedding model
#     _raw_model = SentenceTransformer("all-MiniLM-L6-v2")
#
#     # Step 2: Embed all chunks — returns numpy array shape (N, 384)
#     vectors = _raw_model.encode(texts, show_progress_bar=True)
#
#     # Step 3: Create ChromaDB collection
#     client = chromadb.PersistentClient(path=CHROMA_DIR)
#     client.delete_collection("releaseradar")  # fresh rebuild
#     _raw_collection = client.create_collection(
#         "releaseradar",
#         metadata={"hnsw:space": "cosine"}  # use cosine similarity
#     )
#
#     # Step 4: Add — ids must be unique strings
#     _raw_collection.add(
#         ids=[str(i) for i in range(len(texts))],
#         documents=texts,
#         embeddings=vectors.tolist(),  # chromadb wants list, not numpy
#         metadatas=metadatas
#     )
#     print(f"✅ Raw: indexed {len(texts)} chunks")
#
# def search_raw(query: str, k: int = 6):
#     query_vector = _raw_model.encode([query]).tolist()
#     results = _raw_collection.query(
#         query_embeddings=query_vector,
#         n_results=k,
#         include=["documents", "metadatas", "distances"]
#     )
#     # results["documents"] is a list-of-lists (one per query)
#     docs = results["documents"][0]
#     metas = results["metadatas"][0]
#     distances = results["distances"][0]
#     return list(zip(docs, metas, distances))
#
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="ReleaseRadar API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_model = None
_collection = None

# ── Text conversion ──────────────────────────────────────────────────────────
# This is the most important tuning surface in a RAG system.
# What you include here determines what the embedding model can "see".
# More context per document = better retrieval, but larger chunks.

def issue_to_text(issue: dict) -> str:
    """
    Convert a GitHub issue dict to a single text string for embedding.
    
    WHY: The embedding model only sees text. Everything you want to be searchable
    must be in this string. IDs, platform, component, status — all of it.
    Fields that stay in metadata (for filtering) don't need to be here.
    """
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


# ── Vector store build ───────────────────────────────────────────────────────

_model: SentenceTransformer = None
_collection = None

def build_vectorstore():
    global _model, _collection

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

    print("🧠 Loading embedding model...")
    _model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"💾 Embedding {len(texts)} documents...")
    vectors = _model.encode(texts, show_progress_bar=False)

    client = chromadb.Client()
    _collection = client.get_or_create_collection("releaseradar")
    _collection.add(
        ids=[str(i) for i in range(len(texts))],
        documents=texts,
        embeddings=vectors.tolist(),
        metadatas=metadatas,
    )
    print(f"✅ Vector store ready: {len(texts)} documents indexed")


@app.on_event("startup")
async def startup():
    """
    FastAPI startup event — runs once when the server starts.
    We build the vector store here so it's ready before any request arrives.
    The _vectorstore global persists in memory for the server's lifetime.
    """
    build_vectorstore()


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


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceDoc]
    query: str


# ── RAG query endpoint ───────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    The core RAG endpoint. Three steps:
    1. Retrieve: similarity search in ChromaDB
    2. Assemble: build context string from top-k chunks
    3. Generate: call Claude with context + question
    """
    if not _collection:
        raise HTTPException(status_code=503, detail="Vector store not ready. Run fetch_data.py first.")

    # ── Step 1: Retrieve ────────────────────────────────────────────────────
    # similarity_search_with_score embeds the query and finds nearest neighbors.
    # Returns list of (Document, score) tuples. Lower score = more similar.
# ── Step 1: Retrieve ────────────────────────────────────────────────────
    query_vector = _model.encode([req.query]).tolist()
    results = _collection.query(
        query_embeddings=query_vector,
        n_results=req.top_k,
        include=["documents", "metadatas", "distances"]
    )
    docs = results["documents"][0]
    metas = results["metadatas"][0]

    # ── Step 2: Assemble context ────────────────────────────────────────────
    context_parts = []
    sources = []
    seen_ids = set()

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

    # DEBUG TIP: Print context here if Claude's answers seem wrong
    # print("=== CONTEXT SENT TO CLAUDE ===")
    # print(context[:1000])

    # ── Step 3: Generate ────────────────────────────────────────────────────
    system_prompt = """You are ReleaseRadar, an AI assistant for mobile engineering teams.
You analyze GitHub Issues and release notes from open source mobile projects (Flutter, React Native) 
to help teams understand crash patterns, regressions, and release quality.

Rules:
- Only use information from the context provided. Never invent issue IDs.
- Always cite issue IDs (e.g. GH-FL-1234) and release versions (e.g. RM-2024.3.0) when referencing specific items.
- Distinguish between iOS and Android when the platform is relevant.
- If the context doesn't contain enough information, say so clearly rather than guessing."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"Context:\n\n{context}\n\n---\n\nQuestion: {req.query}"
        }],
    )
    answer = message.content[0].text

    return QueryResponse(answer=answer, sources=sources, query=req.query)


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
        "vectorstore_ready": _collection is not None
    }


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Always check this first when debugging. If this fails, nothing else will work."""
    return {"status": "ok", "vectorstore_ready": _collection is not None}

if __name__ == "__main__":
    import uvicorn
    # reload=True means the server restarts when you save main.py
    # Use this during development. Remove in production.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
