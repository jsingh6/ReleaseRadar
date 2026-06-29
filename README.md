# ReleaseRadar

<img width="1280" height="640" alt="ReleaseRadar-thumbnail" src="https://github.com/user-attachments/assets/95adf192-0c59-4ddb-910b-1c0edb21abc8" />

AI-powered release intelligence for mobile engineering teams. Ask natural language questions across GitHub Issues and release notes — get precise, cited answers with links to the fixes.

**Data sources:** Real GitHub Issues from `flutter/flutter` and `facebook/react-native` (crash, regression, bug labels) + fixture release notes (RM-prefixed). Closed issues include linked PR descriptions so Claude can explain how issues were fixed.

---

## Setup (step by step)

### 1. Clone and navigate

```bash
git clone https://github.com/jsingh6/releaseradar
cd releaseradar
```

### 2. Python environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate      # Mac/Linux
# venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 3. Environment variables

```bash
cp .env.example .env
# Edit .env and add your keys
```

`.env.example`:
```
ANTHROPIC_API_KEY=your_key_here
GITHUB_TOKEN=optional_for_higher_rate_limits
```

> **Note:** `GITHUB_TOKEN` is strongly recommended. Without it you hit GitHub's 60 req/hour unauthenticated limit quickly when fetching issues + linked PRs.

### 4. Fetch real data from GitHub

```bash
python fetch_data.py
```

This pulls crash and regression issues from `flutter/flutter` and `facebook/react-native` via the GitHub Issues API. For each **closed** issue it also fetches the linked PR description so Claude can answer "how was this fixed?" questions with real data.

Saves to `data/github_issues.json` and `data/release_notes.json`.

### 5. Start the backend

```bash
python main.py
# Server running at http://localhost:8000
# API docs at http://localhost:8000/docs
```

**What happens on startup:**
1. Loads `data/github_issues.json` + `data/release_notes.json`
2. Converts each issue/release to a text string (includes fix PR descriptions for closed issues)
3. Embeds with `all-MiniLM-L6-v2` (downloads ~90MB on first run)
4. Stores vectors in ChromaDB at `/tmp/releaseradar_chroma`

### 6. Test it immediately

```bash
# Health check
curl http://localhost:8000/health

# Stats
curl http://localhost:8000/stats

# Analytics
curl http://localhost:8000/analytics

# Ask a question
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Which crash issues affected Android and were fixed in a recent release?"}'
```

### 7. Frontend

```bash
cd ../frontend
npm install
npm run dev
# UI at http://localhost:5173
```

---

## Architecture

```
GitHub Issues API (flutter/flutter, facebook/react-native)
  + Linked PR descriptions (for closed issues)
  + Release Notes (RM-2024.x fixtures)
        ↓ fetch_data.py
  JSON files in backend/data/
        ↓ main.py startup
  all-MiniLM-L6-v2 Embeddings (HuggingFace, 384-dim vectors)
        ↓
  ChromaDB (local vector store, 80 documents)
        ↓ similarity search (top-k=6)
  FastAPI /query endpoint
        ↓
  Claude claude-sonnet-4-6 (Anthropic) — grounded generation
        ↓
  React UI + Analytics Section (/analytics endpoint)
```

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness check |
| `/stats` | GET | Issue counts, release counts, vector store status |
| `/query` | POST | RAG query — returns answer + cited sources |
| `/analytics` | GET | Usage stats — total queries, today's count, most cited issue, top platform, recent queries |

---

## Issue ID conventions

| Prefix | Repo |
|---|---|
| `GH-FL-` | flutter/flutter |
| `GH-RN-` | facebook/react-native |
| `RM-` | Release notes (fixture data) |

---

## Sample queries

**Fix-specific**
- "How was the Flutter Impeller ANR on Samsung Galaxy fixed?"
- "What was the root cause of the iOS 17 gesture recognizer issue in React Native?"
- "Show me all Flutter crash fixes from 2024 with their fix approach"

**Cross-release regression tracking**
- "Were there any regressions introduced in Flutter 3.22 that required a hotfix?"
- "What known issues from RM-2024.3.0 were fixed in RM-2024.3.1?"

**Platform-specific**
- "What Android-only crashes have been reported in Flutter?"
- "Are there any iOS 17 specific bugs across Flutter or React Native?"

**Release quality / upgrade decisions**
- "Is it safe to upgrade to RM-2024.3.0 if my users are on Samsung Galaxy devices?"
- "Which release had the most critical fixes — RM-2024.2.0 or RM-2024.3.0?"

---

## Deployment

**Backend** — Railway. Set these environment variables:
- `ANTHROPIC_API_KEY` — required
- `GITHUB_TOKEN` — recommended (higher GitHub rate limits)

**Frontend** — Vercel. Set:
- `VITE_API_BASE` — Railway backend URL (if not hardcoded)

---

## Author

**Jaspreet Singh** — Principal Mobile & Quality Engineer  
[GitHub](https://github.com/jsingh6) · [LinkedIn](https://linkedin.com/in/jaspreetsjsu)
