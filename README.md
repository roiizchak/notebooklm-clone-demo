# NotebookLM clone — demo

A from-scratch take on the NotebookLM workflow: bring your own sources (PDF / DOCX / URL / YouTube / pasted text), chat with them via RAG with inline citations, then turn the notebook into audio overviews, flashcards, quizzes, study guides, FAQs, notes, and deep-research reports.

> [!WARNING]
> **This is an experiment, not a product.** I built it to explore what NotebookLM-style workflows look like end-to-end on a Next.js + FastAPI + Supabase + Gemini stack. **I do not actually use it for anything**, it is not maintained, and it is not production-grade. Treat the code as a reference implementation — copy ideas, not guarantees. Things will break, costs will surprise you, and APIs will drift out from under it.

---

## What it does

- **Sources** — ingest PDF, DOCX, URLs, YouTube videos (via transcripts), or pasted text. Files upload direct-to-Storage via signed URLs (50MB cap). Each source is chunked, embedded with `gemini-embedding-2` (1536-dim), and stored in Postgres + pgvector with an HNSW index.
- **RAG chat with citations** — multi-turn chat sessions over the notebook. Top-k retrieval through a Postgres RPC (`match_notebook_chunks`), `[1]`-style citations rendered as hoverable popovers in the UI with a "jump to source" affordance.
- **Audio overviews** — multi-speaker dialogue (Alice + Bob) at 5 / 10 / 15 minute targets, produced with `gemini-3.1-flash-tts-preview` and wrapped to WAV server-side. Runs as a FastAPI `BackgroundTask`; one in-flight job per notebook enforced at the DB.
- **Study materials** — flashcards (20), quiz (10), study guide (1), FAQ (8). One row per kind per notebook; regenerate is an atomic upsert.
- **Notes** — written notes, save-from-chat, pin-to-top.
- **Deep research mode** — chat composer "Quick / Deep" toggle. Deep mode runs a 3-stage pipeline (Flash plan → Flash per-section retrieval → Pro stitch) producing a TL;DR + 3-5 sections + open questions with globalized citations. ~60-90s wall-clock, ~$0.05-$0.10 per report.

---

## Stack

- **Frontend** — Next.js 15 (App Router) + React + TanStack Query + Tailwind + shadcn/ui, deployed on Vercel.
- **Backend** — FastAPI (Python 3.11+), deployed on Vercel as serverless functions.
- **Database / storage / auth** — Supabase (Postgres 15 + pgvector + Auth + Storage + Realtime).
- **Models** — Google Gemini: `gemini-embedding-2`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite`, `gemini-3.1-flash-tts-preview`, `gemini-3.1-pro-preview`.

No Redis, no Docker, no Celery, no self-hosted vector DB. All long-lived state in Supabase. Background work runs on FastAPI `BackgroundTasks` (so anything over Vercel's 300s function ceiling is best-effort).

---

## Architecture

```
[Browser]
   │
   ├── PUT signed URL ──→ [Supabase Storage: sources / audio buckets]
   │
   └── HTTPS ──→ [Next.js on Vercel :3000] ──→ [FastAPI on Vercel :8000]
                       │                              │
              Supabase JS SDK (anon)        Supabase Python SDK (service_role)
                       ▼                              ▼
                 [Supabase Auth]    [Postgres + pgvector + Storage + Realtime]
                                                  │
                                                  ▼
                                           [Gemini API]
```

Backend uses the service-role key to bypass RLS for cross-row ops, but every query also filters by `user_id` explicitly (defense-in-depth). Frontend only ever sees the anon key.

---

## Local setup

### Prerequisites

- Python 3.11+
- Node.js 20+ (Bun also works)
- A Supabase project (free tier is fine)
- A Google AI Studio API key with Gemini access
- The Supabase CLI (for migrations)

### 1. Clone and configure

```bash
git clone https://github.com/roiizchak/notebooklm-clone-demo.git
cd notebooklm-clone-demo

# Backend env
cp backend/.env.example backend/.env
# then edit backend/.env and fill in:
#   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_ISSUER, SUPABASE_DB_PASSWORD
#   GOOGLE_API_KEY

# Frontend env
cp frontend/.env.local.example frontend/.env.local
# then edit frontend/.env.local and fill in:
#   NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_URL
```

### 2. Apply database migrations

```bash
# Link to your Supabase project (one-time)
supabase link --project-ref <your-project-ref>

# Push migrations
supabase db push --linked --password "$SUPABASE_DB_PASSWORD"
```

Migrations live under `backend/supabase/migrations/` (timestamp-prefixed) with hand-numbered duplicates in `backend/migrations/` for readability.

### 3. Run the backend

```bash
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt pytest pytest-asyncio    # Windows
# source .venv/bin/activate && pip install ...                            # macOS / Linux

./.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Tests:

```bash
./.venv/Scripts/python -m pytest
```

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev    # starts on http://localhost:3000
```

If you prefer one command:

```bash
cd frontend && npm run dev    # `concurrently` runs both backend (:8001) and frontend (:3000)
```

Sign up at `/register`, create a notebook, add a source, and chat.

---

## Cost (verified May 2026 pricing)

| Operation | Approx cost |
|---|---|
| Embedding a 100-chunk source | ~$0.0001 |
| One RAG chat turn (8 retrieved chunks + answer) | ~$0.001-0.003 |
| One study-material kind (e.g. flashcards) | ~$0.002-0.005 |
| One 10-minute audio overview | ~$0.30 (TTS is 25 tokens/sec @ $20/1M output) |
| One deep-research report | ~$0.05-0.10 |

Per-model rates ($/1M tokens):

| Model | Input | Output |
|---|---|---|
| `gemini-embedding-2` | 0.20 | — |
| `gemini-3-flash-preview` | 0.50 | 3.00 |
| `gemini-3.1-flash-lite` | 0.25 | 1.50 |
| `gemini-3.1-flash-tts-preview` | 1.00 | 20.00 |
| `gemini-3.1-pro-preview` | 2.00 | 12.00 |

These are pulled from Google's posted prices and may have shifted; verify before running anything serious.

---

## Known limits

- **No streaming chat.** The UI inserts an optimistic "Thinking…" message and replaces it with the full response when the request returns.
- **Polling, not WebSockets.** Source ingest, audio generation, and deep research status all poll every 2.5-3s while in flight (visibility-gated — polling pauses when the tab is hidden).
- **15-minute audio is best-effort.** Vercel's 300s function ceiling caps it; longer jobs surface as `status='failed'`. A real queue (Trigger.dev / similar) would fix it.
- **Embeddings issued one at a time.** ~0.4s per chunk, so a 100-chunk source takes ~40s to ingest. Fine on free Vercel; would batch under load.
- **WAV files are big.** ~28MB for a 10-min overview. No MP3/Opus compression yet (would need an ffmpeg layer).
- **Notes are plain text.** No Markdown rendering, no tag filter UI, no full-text search.
- **Study materials are stateless.** No quiz scoring persistence, no spaced-repetition, no per-item editing.

---

## Repo layout

```
backend/
  app/
    main.py                  FastAPI app + CORS + router registration
    config.py                Pydantic settings (env-driven)
    services/                auth, gemini, ingestion, rag, storage, audio, research, usage
    routers/                 notebooks, sources, chat, profile, studies, notes, audio, research, config
    schemas/                 Pydantic request/response models
    middleware/              request-id propagation
  migrations/                Hand-numbered SQL (documentation)
  supabase/migrations/       Timestamp-prefixed SQL (what supabase CLI pushes)
  tests/                     pytest + e2e_*.py smoke scripts
frontend/
  src/
    app/                     Next.js App Router pages
    components/              chat, sources, studio (audio/studies/notes/reports), brand, ui (shadcn)
    lib/                     api client, hooks, utils
```

---

## License

[MIT](LICENSE) — copyright (c) 2026 roiizchak.

Code is provided as-is. If something breaks, you keep both pieces.
