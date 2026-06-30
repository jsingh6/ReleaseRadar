---
name: launch_release_radar
description: Start the ReleaseRadar backend (FastAPI on :8000) and frontend (Vite on :5173) for local development and preview
---

# Launch ReleaseRadar locally

Starts both the FastAPI backend and the Vite dev server so changes can be previewed at http://localhost:5173.

## Prerequisites

- `backend/venv` must exist (run `python3 -m venv venv && pip install -r requirements.txt` once if not)
- `.env` in `backend/` must have `ANTHROPIC_API_KEY` set
- `frontend/.env.local` exists with `VITE_API_BASE=http://localhost:8000` (already committed)

## Steps

### 1 — Kill any existing processes on the ports

```bash
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
lsof -ti :5173 | xargs kill -9 2>/dev/null || true
```

### 2 — Start the backend

```bash
cd /Users/jsingh6/Desktop/ReleaseRadar/backend
source venv/bin/activate
python main.py &> /tmp/rr_backend.log &
echo "Backend PID: $!"
```

Wait ~8 seconds for the embedding model to load and BM25 index to build.

### 3 — Verify backend is healthy

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected:
```json
{
    "status": "ok",
    "vectorstore_ready": true,
    "bm25_ready": true,
    "doc_count": 83
}
```

If `bm25_ready` is false, check `/tmp/rr_backend.log` for errors.

### 4 — Start the frontend

```bash
cd /Users/jsingh6/Desktop/ReleaseRadar/frontend
npm run dev &> /tmp/rr_frontend.log &
echo "Frontend PID: $!"
```

### 5 — Verify frontend is up

```bash
sleep 3 && cat /tmp/rr_frontend.log
```

Should show `VITE vX.X.X  ready` and `Local: http://localhost:5173/`.

### 6 — Open in browser

Navigate to **http://localhost:5173** — the app should load with the stats bar and query interface.

### 7 — Smoke test the new pipeline

```bash
curl -s -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query":"Which crash issues affected Android?","top_k":4}' \
  | grep '"type": "done"' \
  | python3 -c "
import sys, json
data = json.loads(sys.stdin.read().strip().replace('data: ', '', 1))
print('insight:', data.get('insight'))
print('filters:', data.get('filters'))
"
```

Expect `insight` to be a non-null dict with `severity`, `pattern`, `recommendation`, `confidence`.
Expect `filters` to be `{'platform': 'Android'}` for this query.

## Logs

- Backend: `/tmp/rr_backend.log`
- Frontend: `/tmp/rr_frontend.log`

## Stop everything

```bash
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
lsof -ti :5173 | xargs kill -9 2>/dev/null || true
```

## Architecture (v3.0)

- Retrieval: Hybrid BM25 + ChromaDB vector search, fused with Reciprocal Rank Fusion
- Pre-filtering: Entity extraction from query → ChromaDB `where` clause
- Output: Claude emits structured `<insight>` JSON + narrative; frontend renders `InsightCard`
- Model: Claude Sonnet 4.6 via AsyncAnthropic SSE streaming
