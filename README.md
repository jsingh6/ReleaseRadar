# ReleaseRadar

<img width="1280" height="640" alt="ReleaseRadar-thumbnail" src="https://github.com/user-attachments/assets/95adf192-0c59-4ddb-910b-1c0edb21abc8" />


AI-powered release intelligence for mobile engineering teams. Ask natural language questions across GitHub Issues and release notes — get precise, cited answers.

**Data sources:** Real GitHub Issues from `flutter/flutter` and `facebook/react-native` + fixture release notes (RM-prefixed).

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
# Edit .env and add your Anthropic API key
```

`.env.example`:
```
ANTHROPIC_API_KEY=your_key_here
GITHUB_TOKEN=optional_for_higher_rate_limits
```

### 4. Fetch real data from GitHub

```bash
python fetch_data.py
```

This pulls crash and regression issues from `flutter/flutter` and `facebook/react-native` via the GitHub Issues API (no auth needed for public repos). Saves to `data/github_issues.json`.

If rate limited: add `GITHUB_TOKEN` to `.env` and rerun.

### 5. Start the backend

```bash
python main.py
# Server running at http://localhost:8000
# API docs at http://localhost:8000/docs
```

**What happens on startup:**
1. Loads `data/github_issues.json` + `data/release_notes.json`
2. Converts each issue/release to a text string
3. Chunks with LangChain `RecursiveCharacterTextSplitter` (600 chars, 80 overlap)
4. Embeds with `all-MiniLM-L6-v2` (downloads ~90MB on first run)
5. Stores vectors in ChromaDB at `/tmp/releaseradar_chroma`

### 6. Test it immediately

```bash
# Health check
curl http://localhost:8000/health

# Stats
curl http://localhost:8000/stats

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
  + Release Notes (RM-2024.x fixtures)
        ↓ fetch_data.py
  JSON files in backend/data/
        ↓ main.py startup
  RecursiveCharacterTextSplitter (LangChain)
        ↓
  all-MiniLM-L6-v2 Embeddings (HuggingFace, 384-dim vectors)
        ↓
  ChromaDB (local vector store)
        ↓ similarity_search(query, k=6)
  FastAPI /query endpoint
        ↓
  Claude claude-sonnet-4-6 (Anthropic) — grounded generation
        ↓
  React UI
```

### With vs Without LangChain

`main.py` includes commented-out code showing the equivalent implementation without LangChain (raw `sentence_transformers` + `chromadb`). LangChain saves ~50 lines of glue code for chunking, embedding, and vector store management.

---

## Sample queries

- "Which crash issues affected Android and have been fixed?"
- "What regressions were introduced in Flutter 3.19?"
- "Did any issues appear in both flutter and react-native releases?"
- "What are the open P1 issues in the Navigation component?"
- "Which release introduced Impeller and what problems followed?"

---

## Extending with real Crashlytics data

```python
# Add to fetch_data.py
from google.oauth2 import service_account
import googleapiclient.discovery

# Requires Firebase project credentials
creds = service_account.Credentials.from_service_account_file("firebase-sa.json")
service = googleapiclient.discovery.build("firebaseappdistribution", "v1", credentials=creds)
# Fetch crash issues and add to all_issues list
```

---

## Author

**Jaspreet Singh** — Principal Mobile & Quality Engineer  
[GitHub](https://github.com/jsingh6) · [LinkedIn](https://linkedin.com/in/jaspreetsjsu)
