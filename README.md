# rag-winner-notes-mcp

A personal knowledge base assistant built from scratch: retrieval augmented generation over personal notes, exposed both as a remote MCP tool (for MCP clients like Claude Code/Desktop) and as a REST API, with per-user accounts and a real deployment on Google Cloud Run.

## Live Deployment

`https://rag-notes-mcp-585012498530.us-central1.run.app/mcp`

The service is public but gated by an API key check (`x-api-key` header). **Note:** this URL was deployed before the multi-tenant rework below (phases A-D) — redeploying with the current `Dockerfile` is still pending, see [Next Steps](#next-steps-as-of-this-update).

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
GCS_BUCKET_NAME=your_gcs_bucket_name
FIREBASE_WEB_API_KEY=your_firebase_web_api_key
```
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

## Deployment

Containerized with the included `Dockerfile` and deployed to Google Cloud Run. The build happens remotely through Cloud Build (`gcloud run deploy --source .`) rather than a local Docker push. Secrets are passed in as environment variables at deploy time (`--env-vars-file env.yaml`, itself gitignored) and are never baked into the image.

Cloud Run's own authentication is left open (`--allow-unauthenticated`) since the app-level auth (`ApiKeyMiddleware`/Firestore resolution for MCP, Firebase tokens for the web API) is the intended access control layer, not GCP's.

**Known gap:** the committed `Dockerfile` still bakes a local `notes/`/`index/` into the image and only runs `mcp_server.py` — that reflects the pre-multi-tenant deploy and hasn't been updated for GCS-backed storage or the new `web_api.py` entrypoint. The live URL above is the old deploy; redeploying is an open next step.

Two deploy-time gotchas worth remembering: `.gcloudignore` controls what gets uploaded to Cloud Build and is separate from `.gitignore`, so anything excluded from git (like `notes/`, `index/`, and now the test clients) has to be excluded from `.gcloudignore` too if it shouldn't ship. The MCP SDK's own DNS rebinding protection also defaults to only allowing a `Host` header of `127.0.0.1`, so it silently blocked every request once deployed under a real hostname, until it was explicitly disabled in favor of the API-key/Firestore layer already doing that job.

## Next Steps (as of this update)

- **Phases A-D are now verified end to end, both the web API and the MCP server.** `test_web_api_client.py` and `test_mcp_client.py` both run successfully against a local `web_api.py`/`mcp_server.py` (GCS-backed per-user storage, Firestore key resolution, Firebase token verification all confirmed working, not just consistent-looking code). Two local-dev-only setup gaps were fixed along the way (neither recurs on Cloud Run, since the attached service account resolves both automatically):
  - `firebase_auth.py` needs `GOOGLE_CLOUD_PROJECT` set in `.env` — **user** ADC credentials (`gcloud auth application-default login`) don't carry a project ID the way a service account does, so `firebase_admin.initialize_app()` can't resolve one on its own locally.
  - `gcloud config set project` and Application Default Credentials are separate credential stores; the Python Google SDKs only read the latter, so `gcloud auth application-default login` (not plain `gcloud auth login`) has to be run once locally too.
  - Also found and fixed a real bug while verifying: `mcp_server.py`'s `ask_notes` read `ctx.request_headers`, which doesn't exist on this SDK version's `Context` — the correct attribute is `ctx.headers`.
- **`test_mcp_client.py` is fixed.** It now mints its own per-user API key via the web API (same pattern as `test_web_api_client.py`) instead of reading the dead `MCP_API_KEY`, and defaults to localhost instead of the live Cloud Run URL.
- **Phase E — real login.** `test_web_api_client.py` signs in via Firebase's raw REST API as a stand-in; there's still no actual login form/frontend. Needed before this is usable by anyone but the person running test scripts.
- **Redeploy.** `Dockerfile`/Cloud Run config predate phases A-D — still single-tenant, still only runs `mcp_server.py`, still bakes in a local index. Needs a second entrypoint (or a way to run both `web_api.py` and `mcp_server.py`), `GCS_BUCKET_NAME`/`FIREBASE_WEB_API_KEY` added to `env.yaml`, and the baked-in `notes/`/`index/` dropped from the image now that storage is per-user and GCS-backed.
- **README/deploy docs vs. reality.** Keep this file in sync as the multi-tenant rework continues — it drifted noticeably between the original single-user deploy and phases A-D.

## Part of a Series

This was originally planned as the first of three projects to learn RAG, LangChain, local/hosted model serving, and MCP from scratch (next: a codebase Q&A assistant with file/line citations, then a shared-memory MCP server). Work has stayed on this project longer than planned in order to take it from a single-user script to a real multi-tenant service — picking up Project 2 is still on the table once the gaps above are closed.
