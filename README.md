# rag-winner-notes-mcp

A personal knowledge base assistant built from scratch: retrieval augmented generation over personal notes, exposed both as a remote MCP tool (for MCP clients like Claude Code/Desktop) and as a REST API, with per-user accounts and a real deployment on Google Cloud Run.

## Live Deployment

**Web app / dashboard:** `https://rag-notes-web-nqni5adpca-uc.a.run.app`

**MCP server:** `https://rag-notes-mcp-585012498530.us-central1.run.app/mcp` — **Note:** this one still predates the multi-tenant rework (phases A-D); only `rag-notes-web` has been redeployed so far. Redeploying `rag-notes-mcp` per [Deployment](#deployment) below is the next step; this line will be updated once that's done.

## Overview

This project was built to learn the full RAG stack end to end: chunking and embedding strategy, vector retrieval, LangChain's retrieval and generation abstractions, the Model Context Protocol, real cloud deployment, and — in a second pass — turning a single-user script into a multi-tenant service (auth, per-user storage, API key issuance). Every layer was built and understood individually before moving on to the next.

## Architecture

### Core RAG pipeline

1. **Loading and chunking** (`src/loader.py`, `src/cleaner.py`, `src/chunker.py`)
   Reads `.md`/`.txt` files, strips HTML and whitespace noise, and splits each document into roughly 300 character chunks with 50 character overlap, splitting on paragraphs first and falling back to sentence level splitting for long paragraphs.

2. **Embedding and indexing** (`src/embedder.py`, `src/vector_store.py`)
   Embeds chunks with `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dimensions, normalized) into a flat numpy cosine similarity index. The index is no longer a single local file on disk — see "Multi-tenant storage" below.

3. **Retrieval and generation** (`src/retriever.py`, `src/rag_chain.py`)
   A LangChain pipeline: history aware query rewriting (resolving vague follow-up questions using conversation history), vector retrieval, prompt construction, generation via Groq (`openai/gpt-oss-120b`), structured `{answer, sources}` output through Pydantic, and multi-turn memory via `RunnableWithMessageHistory` (keyed per user + session, see below).

### Multi-tenant layer

The original version above served one shared notebook to anyone with the single hardcoded API key. It's since been reworked so each user has their own notes, their own vector index, and their own credentials:

4. **Per-user vector storage** (`src/vector_store.py`)
   `VectorStore.save_to_gcs(user_id)` / `load_from_gcs(user_id)` persist each user's index to `gs://<bucket>/users/<user_id>/index/` instead of the local `index/` directory. This matters because Cloud Run instances are stateless and ephemeral — nothing written to local disk survives between requests or across instances, so the index has to live somewhere every instance can reach. `upsert_document` replaces a source's old chunks on re-upload rather than duplicating them.

5. **Web API** (`src/web_api.py`, FastAPI)
   REST surface so notes/questions don't have to go through the MCP protocol at all:
   - `POST /notes/upload` — upload a note, chunk + embed it, merge into the caller's GCS-backed index
   - `POST /ask` — ask a question against the caller's own notes
   - `GET /notes` — list the caller's uploaded source filenames
   - `POST /api-keys` — mint a personal MCP API key for the logged-in user (shown once)

   Every route is gated by `Depends(get_current_user_id)`.

6. **Firebase Authentication** (`src/firebase_auth.py`)
   The web API expects `Authorization: Bearer <firebase-id-token>`. The token is a self-certifying JWT verified locally against Google's public keys (no network round trip per request) via `firebase_admin.auth.verify_id_token`, returning the caller's Firebase `uid`.

7. **Per-user MCP accounts** (`src/user_store.py`, `src/mcp_server.py`)
   MCP API keys are no longer one shared secret. `create_api_key(user_id)` mints a random key and stores the `key -> user_id` mapping in Firestore (`api_keys` collection); `resolve_api_key(api_key)` looks it up. `mcp_server.py`'s `ask_notes` tool resolves the caller's `x-api-key` header to a `user_id` this way, then loads *that* user's GCS-backed index — so each MCP caller only ever sees their own notes.

### MCP server

8. **MCP server** (`src/mcp_server.py`, `src/auth.py`)
   Exposes `ask_notes(question, session_id)` over MCP's Streamable HTTP transport, gated by `ApiKeyMiddleware` (checks the key is present/well-formed) and then `resolve_api_key` (checks whose notes to load).

### Frontend (phase E)

9. **Dashboard page** (`frontend/index.html`)
   A single static page (no build step — the Firebase JS SDK is loaded via `<script>` tags) covering the full flow: real email/password sign-up and sign-in through Firebase Auth, uploading a note, listing and viewing a note's stored chunks, asking a question and seeing the grounded answer plus sources, and minting an MCP API key. `web_api.py` serves this page itself (`StaticFiles` mounted at `/`), so in production it's reachable at the same URL as the API, with no separate static server. `CORSMiddleware` (wide open for now) is still needed for local dev, where the page can be pointed at a different host/port than the one serving it — access control itself comes from the per-route Firebase token check, not from CORS.

## Tech Stack

Python, FastAPI, LangChain, sentence-transformers, Groq, MCP (Streamable HTTP transport), Firebase Auth, Firestore, Google Cloud Storage, Docker, Google Cloud Run, Google Cloud Build.

## Running Locally

Requires Python 3.14 and a virtual environment (`.rag_venv/` in this repo).

```cmd
.rag_venv\Scripts\activate.bat
pip install -r requirements.txt
```

Create a `.env` file in the project root:
```
GROQ_API_KEY=your_groq_api_key
GOOGLE_CLOUD_PROJECT=your_gcp_project_id
GCS_BUCKET_NAME=your_gcs_bucket_name
FIREBASE_WEB_API_KEY=your_firebase_web_api_key
```
`GOOGLE_CLOUD_PROJECT` is only needed locally — **user** ADC credentials (`gcloud auth application-default login`) don't carry a project ID the way a service account does, so `firebase_admin`'s default initialization can't resolve one on its own without it. Not needed on Cloud Run, where the attached service account resolves it automatically.
(`MCP_API_KEY`, used in the original single-tenant version, is dead as of phase D — nothing in `src/` reads it anymore. MCP access is now controlled by minting a per-user key from `POST /api-keys`, not a static env var. `test_mcp_client.py` still references the old variable and needs updating to match `test_web_api_client.py`'s mint-then-call pattern — see Next Steps.)

Google credentials (GCS, Firestore, Firebase Admin) resolve via Application Default Credentials — run `gcloud auth application-default login` once locally; on Cloud Run this comes from the attached service account instead.

**Run the MCP server:**
```cmd
python src\mcp_server.py
```
Listens on `http://0.0.0.0:8080/mcp` (or `$PORT`). Every request must include a matching `x-api-key` header, resolved to a user account via Firestore.

**Run the web API:**
```cmd
python src\web_api.py
```
Listens on `http://0.0.0.0:8080` (or `$PORT`). Every request must include `Authorization: Bearer <firebase-id-token>`.

**Try it end to end without a frontend:**
```cmd
python test_web_api_client.py
```
Signs in against Firebase's own REST API (standing in for a browser login form, which doesn't exist yet — see Next Steps) and exercises `/api-keys`, `/notes/upload`, `/notes`, and `/ask` in sequence.

`test_mcp_client.py` does the equivalent smoke test against the MCP server directly, minting its own key the same way. Since both this and the web API default to port 8080, run the MCP server with a different port when trying both locally at once: `set PORT=8081 && python src\mcp_server.py`, then `set MCP_SERVER_URL=http://localhost:8081/mcp` before running the test client (or just edit the default in the script).

**Try the real login page:** `web_api.py` serves `frontend/index.html` itself (see "Frontend" below), so with it running, just open `http://localhost:8080/` — no separate static server needed. Sign up or sign in, upload a note, and ask a question about it.

## Deployment

Containerized with the included `Dockerfile` and deployed to Google Cloud Run as **two separate services built from the same image** — one process per container is the normal Cloud Run shape, and `web_api.py`/`mcp_server.py` are already two separate entrypoints, so this is the natural split rather than merging them into one process:

- **`rag-notes-web`** — runs `web_api.py` (the Dockerfile's default `CMD`): the REST API plus `frontend/index.html`, served at the same origin so the page's own "Backend URL" field can stay blank.
- **`rag-notes-mcp`** — runs `mcp_server.py` instead, by overriding the image's default command at deploy time (`--command`/`--args`) rather than building a second image. Reuses the live service name/URL from before the multi-tenant rework.

The build happens remotely through Cloud Build (`gcloud run deploy --source .`) rather than a local Docker push. Secrets are passed in as environment variables at deploy time (`--env-vars-file env.yaml`, itself gitignored, kept in sync with `.env`) and are never baked into the image. Cloud Run's own authentication is left open (`--allow-unauthenticated`) since the app-level auth (`ApiKeyMiddleware`/Firestore resolution for MCP, Firebase tokens for the web API) is the intended access control layer, not GCP's.

**To deploy** (from the project root, once `env.yaml` has `GROQ_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET_NAME`, and `FIREBASE_WEB_API_KEY` — same values as `.env`):

```cmd
gcloud run deploy rag-notes-web --source . --region us-central1 --allow-unauthenticated --env-vars-file env.yaml --memory 2Gi

gcloud run deploy rag-notes-mcp --source . --region us-central1 --allow-unauthenticated --env-vars-file env.yaml --command python --args src/mcp_server.py --memory 2Gi
```

Each prints its own `*.run.app` URL. `rag-notes-web`'s URL is the real website now — open it directly. `rag-notes-mcp`'s URL (with `/mcp` appended) is what goes into an MCP client config, replacing the one in [Live Deployment](#live-deployment) above once redeployed.

Three deploy-time gotchas worth remembering: `.gcloudignore` controls what gets uploaded to Cloud Build and is separate from `.gitignore`, so anything excluded from git (like `notes/`, `index/`, and now the test clients) has to be excluded from `.gcloudignore` too if it shouldn't ship. The MCP SDK's own DNS rebinding protection also defaults to only allowing a `Host` header of `127.0.0.1`, so it silently blocked every request once deployed under a real hostname, until it was explicitly disabled in favor of the API-key/Firestore layer already doing that job. And `--memory` needs to be bumped above Cloud Run's 512 MiB default — loading the `sentence-transformers` embedding model (plus torch, firebase_admin, etc.) at startup used over 1114 MiB in practice, which silently manifests as a generic "container failed to start and listen on the port" error with no memory-related wording at all; `gcloud logging read` on the revision is what actually surfaces the real `Memory limit ... exceeded` reason. Separately, the model is downloaded from the Hugging Face Hub fresh on every cold start (it already hit an HF rate limit once) rather than being baked into the image — not fixed yet, see Next Steps.

## Next Steps (as of this update)

- **Everything through Phase E is done and verified locally:** multi-tenant storage/auth (phases A-D), the login + upload + ask dashboard (phase E), PDF uploads, and the note/chunk viewer.
- **`rag-notes-web` is redeployed and live** (see [Live Deployment](#live-deployment)) on the two-service, GCS-backed, frontend-serving setup — required bumping `--memory` to `2Gi` to avoid an OOM on startup (see [Deployment](#deployment) gotchas).
- **`rag-notes-mcp` still needs the same redeploy** — it's still running the pre-phase-A-D single-tenant image. Run the second `gcloud run deploy` command in [Deployment](#deployment) above, then update [Live Deployment](#live-deployment) with its real URL.
- **Cold-start model download isn't fixed yet** — the embedding model is pulled from the Hugging Face Hub on every cold start instead of being baked into the image, and already hit an HF rate limit once in practice. Worth caching it into the Docker image at build time or setting an `HF_TOKEN`, to avoid slow/flaky cold starts.
- **After that:** pick back up **Project 2 — codebase Q&A / doc-grounded coding assistant**, the next project in the series.

## Part of a Series

This was originally planned as the first of three projects to learn RAG, LangChain, local/hosted model serving, and MCP from scratch (next: a codebase Q&A assistant with file/line citations, then a shared-memory MCP server). Work has stayed on this project longer than planned in order to take it from a single-user script to a real multi-tenant service — picking up Project 2 is still on the table once the gaps above are closed.
