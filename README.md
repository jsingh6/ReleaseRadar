# 🛰️ ReleaseRadar

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://release-radar-sdk.vercel.app)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI-powered release intelligence for mobile engineering teams. Ask natural language questions across GitHub Issues, crash events, and release notes — get precise, cited answers powered by RAG + Claude.

**Live demo → [release-radar-sdk.vercel.app](https://release-radar-sdk.vercel.app)**

---

## The Problem

When you're serving millions of users, something will break in production. And when it does, your system for understanding what happened is usually five tools that have never met each other — crash logs in one place, bug tickets in another, test cases somewhere else, RCAs in a Google Doc nobody can find two sprints later.

The teams aren't bad at their jobs. They're buried under the coordination tax of tools built for one thing and terrible at talking to each other.

The crash happens. The sprint ends. The doc gets filed. And the next time the same pattern surfaces, everyone starts from scratch.

ReleaseRadar fixes that.

---

[![ReleaseRadar Screenshot](images/screenshot.png)](https://release-radar-sdk.vercel.app/)

---

## How It Works

```
GitHub Issues + Release Notes
        ↓
sentence-transformers (all-MiniLM-L6-v2) → 384-dim embeddings
        ↓
  ┌─────────────────────────────────────┐
  │  Query entity extraction            │
  │  (platform / status / priority)     │
  │         ↓                           │
  │  ChromaDB vector search             │  ← semantic matches
  │  BM25 keyword search                │  ← exact term matches
  │         ↓                           │
  │  Reciprocal Rank Fusion (RRF)       │  ← merged ranking
  └─────────────────────────────────────┘
        ↓
Claude Sonnet — grounded generation + structured insight
        ↓
React frontend (InsightCard + narrative)
```

**Why hybrid?** Pure vector search misses exact identifiers — version numbers like `3.22`, component names like `Impeller` or `Hermes`, issue IDs. BM25 catches those. RRF merges both rankings without needing score normalization.

**Why entity extraction?** A query like "open iOS bugs" should filter `platform=iOS, status=Open` before retrieval, not after — so cosine similarity only runs against the relevant candidate set.

**Why structured output?** Claude emits a typed insight block (severity, affected versions/platforms, pattern, recommendation, confidence) alongside the narrative. The frontend renders it as a severity-coded card — P1 red, P2 orange, P3 yellow — so teams get a scannable signal, not just a wall of text.

## Stack

| Layer | Technology |
|---|---|
| Embeddings | sentence-transformers all-MiniLM-L6-v2 |
| Keyword search | BM25 (rank-bm25) |
| Vector store | ChromaDB |
| Retrieval | Hybrid BM25 + vector, fused with RRF |
| Pre-filtering | Entity extraction → ChromaDB where-clause |
| LLM | Anthropic Claude Sonnet 4.6 |
| Output | Structured insight JSON + streaming narrative |
| Backend | FastAPI + Python |
| Frontend | React + Vite |
| Data | GitHub Issues API (flutter/flutter, facebook/react-native) |

---

## Quickstart

Clone and set up:

    git clone https://github.com/jsingh6/ReleaseRadar
    cd ReleaseRadar/backend
    python3 -m venv venv && source venv/bin/activate
    pip install -r requirements.txt

Configure:

    echo "ANTHROPIC_API_KEY=your_key" > .env
    echo "GITHUB_TOKEN=your_token" >> .env

Fetch real data and run:

    python fetch_data.py
    python main.py

Frontend:

    cd frontend && npm install
    echo "VITE_API_BASE=http://localhost:8000" > .env.local
    npm run dev

---

## Sample Queries

- "Which crash issues affected Android and have been fixed?"
- "Did this auth regression appear in a previous release?"
- "Which open bugs have active crash signals right now?"
- "What changed in the last release that correlates with this error spike?"
- "What are the most critical P1 issues in the dataset?"

---

## Extending with Your Own Data

Point fetch_data.py at your own sources:

**Jira**

    fetch_jira_issues(jira_url, api_token, project_key="YOUR_PROJECT")

**Firebase Crashlytics**

    fetch_crashlytics(firebase_project_id, credentials_path)

**Splunk**

    fetch_splunk_events(splunk_url, token, search_query)

Each connector normalizes to the same dict shape — id, summary, description, platform, component, status — so the RAG pipeline doesn't care where the data came from.

---

## Architecture Decisions

**No LangChain.** The pipeline uses raw sentence-transformers + chromadb directly. Fewer transitive dependencies, full visibility into what each retrieval layer is doing, and no framework magic to debug when scores look wrong.

**Hybrid retrieval over pure vector search.** This domain has a lot of exact identifiers — version strings, component names, issue IDs. Semantic embeddings are weak at exact-match retrieval. Adding BM25 alongside the vector index and fusing with RRF costs one extra dependency and ~5ms, and eliminates an entire class of missed results.

**Structured output via prompt, not tool-use.** Claude is asked to emit `<insight>JSON</insight>` at the end of every response. The backend strips and parses it; the frontend renders it as a typed card. This keeps streaming intact (one LLM call, no round-trips) while giving the UI structured data to work with.

---

## Contributing

Contributions welcome. Open issues for ideas:

- Jira / Firebase Crashlytics / Splunk connectors
- Cross-encoder re-ranking (post-RRF, before Claude)
- Rate limiting on /query endpoint
- Persistent ChromaDB (currently in-memory on Railway)
- Scheduled data refresh (currently fetched manually via fetch_data.py)

---

## Author

**Jaspreet Singh** — Principal Mobile & Quality Engineer
[LinkedIn](https://linkedin.com/in/jaspreetsjsu) · [GitHub](https://github.com/jsingh6)

---

## License

MIT
