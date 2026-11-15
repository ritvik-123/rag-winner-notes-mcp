# rag-winner-notes-mcp

A personal knowledge base assistant built from scratch. It lets you upload your own notes, then ask questions about them and get answers grounded in those notes. You can use it two ways: through a website, or through an MCP client (like Claude Code or Claude Desktop). Each person who signs up gets their own private set of notes. It is deployed for real on Google Cloud Run.

## Live Deployment

There are two separate live links, because this app runs as two separate services. Here is what each one is for.

**1. The website:** `https://rag-notes-web-nqni5adpca-uc.a.run.app`

This is the one a normal person should open in a browser. It has a sign-up/sign-in page, a button to upload notes (including PDFs), a box to ask questions, a viewer to see your uploaded notes and how they were split into chunks, and a button to mint an API key (see below). This is the main link to share with someone who just wants to try the app.

**2. The MCP server:** `https://rag-notes-mcp-585012498530.us-central1.run.app/mcp`

This one is not for browsers. It is meant to be typed into the configuration of an MCP client, such as Claude Code or Claude Desktop, so that the client can call a tool named `ask_notes` directly. To use it, you first need an API key, which you get from the website (button 1). Opening this link in a plain browser will just show an error, because browsers do not send the API key header this server requires. That is expected, not a bug.

**Who can use these, and what do they get access to?** Both links are public. Anyone can sign up on the website and get their own account. Each account only has access to its own notes. There is no sign-up restriction right now (any email and password works), so this is an open multi-tenant app rather than a private one. The main real-world risk of that is cost: someone could sign up and use the question-answering feature, which spends Groq API usage on the owner's account. There is no way for one user to see another user's notes.

## Overview

This project was built to learn the full RAG (retrieval augmented generation) stack from the ground up: chunking and embedding text, vector retrieval, LangChain's retrieval and generation pieces, the Model Context Protocol (MCP), and real cloud deployment. Partway through, the project was expanded a second time: it started as a single-user script and was turned into a real multi-tenant service, with accounts, per-user storage, and API key issuance. Every layer was built and understood on its own before moving to the next one.

## Architecture

### Core RAG pipeline

1. **Loading and chunking** (`src/loader.py`, `src/cleaner.py`, `src/chunker.py`)
   Reads `.md`/`.txt` files, strips HTML and whitespace noise, and splits each document into roughly 300 character chunks with 50 character overlap. It splits on paragraphs first, and falls back to sentence-level splitting for long paragraphs.

2. **Embedding and indexing** (`src/embedder.py`, `src/vector_store.py`)
   Embeds chunks with `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dimensions, normalized) into a flat numpy cosine similarity index. The index is not a single local file anymore; see "Multi-tenant storage" below for where it actually lives.

3. **Retrieval and generation** (`src/retriever.py`, `src/rag_chain.py`)
   A LangChain pipeline does the following in order: it rewrites vague follow-up questions using conversation history, retrieves the most relevant chunks, builds a prompt, generates an answer using Groq (`openai/gpt-oss-120b`), and returns a structured `{answer, sources}` result through Pydantic. It also remembers conversation history per user and session, using `RunnableWithMessageHistory`.

### Multi-tenant layer

The original version above served one shared notebook to anyone who had a single hardcoded API key. It has since been reworked so each user has their own notes, their own vector index, and their own credentials.

4. **Per-user vector storage** (`src/vector_store.py`)
   `VectorStore.save_to_gcs(user_id)` and `load_from_gcs(user_id)` save and load each user's index to `gs://<bucket>/users/<user_id>/index/`, instead of a shared local `index/` folder. This matters because Cloud Run instances are stateless and temporary. Nothing written to local disk survives between requests or between instances, so the index needs to live somewhere every instance can reach. When a user re-uploads a source file, `upsert_document` replaces that source's old chunks instead of duplicating them.

5. **Web API** (`src/web_api.py`, FastAPI)
   A REST API, so notes and questions do not have to go through the MCP protocol at all. It has four routes:
   - `POST /notes/upload`: upload a note, chunk and embed it, and merge it into the caller's GCS-backed index.
   - `POST /ask`: ask a question against the caller's own notes.
   - `GET /notes`: list the caller's uploaded source filenames.
   - `POST /api-keys`: mint a personal MCP API key for the logged-in user, shown once.

   Every one of these routes requires the caller to be signed in (`Depends(get_current_user_id)`).

6. **Firebase Authentication** (`src/firebase_auth.py`)
   The web API expects an `Authorization: Bearer <firebase-id-token>` header. That token is a self-certifying JWT, so it can be verified locally against Google's public keys, with no extra network round trip per request, using `firebase_admin.auth.verify_id_token`. Verifying it returns the caller's Firebase `uid`.

7. **Per-user MCP accounts** (`src/user_store.py`, `src/mcp_server.py`)
   MCP API keys are no longer one shared secret. `create_api_key(user_id)` mints a random key and stores the mapping from that key to the user in Firestore, in the `api_keys` collection. `resolve_api_key(api_key)` looks that mapping up. `mcp_server.py`'s `ask_notes` tool reads the caller's `x-api-key` header, resolves it to a `user_id` this way, and then loads that user's own GCS-backed index. So each MCP caller only ever sees their own notes.

### MCP server

8. **MCP server** (`src/mcp_server.py`, `src/auth.py`)
   Exposes a tool called `ask_notes(question, session_id)` over MCP's Streamable HTTP transport. Two checks happen before a request reaches the tool: `ApiKeyMiddleware` checks that an API key is present at all, and then `resolve_api_key` checks whose account that key belongs to, so the right notes get loaded.

### Frontend (phase E)

9. **Dashboard page** (`frontend/index.html`)
   A single static page with no build step. It loads the Firebase JS SDK directly via `<script>` tags, and covers the full flow: signing up and signing in with email and password through Firebase Auth, uploading a note, listing and viewing a note's stored chunks, asking a question and seeing the grounded answer plus its sources, and minting an MCP API key. `web_api.py` serves this page itself, so in production it is reachable at the same URL as the API, with no separate static server needed. `CORSMiddleware` is wide open for now; this is only needed for local development, where the page might be opened from a different host or port than the one serving the API. Access control itself comes from the Firebase token check on each route, not from CORS.

## Tech Stack

Python, FastAPI, LangChain, sentence-transformers, Groq, MCP (Streamable HTTP transport), Firebase Auth, Firestore, Google Cloud Storage, Docker, Google Cloud Run, Google Cloud Build.

## Running Locally

You need Python 3.14 and a virtual environment (`.rag_venv/` in this repo).

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
`GOOGLE_CLOUD_PROJECT` is only needed locally. User-level Application Default Credentials (set up with `gcloud auth application-default login`) do not carry a project ID the way a service account does, so `firebase_admin`'s default setup cannot figure one out on its own without this variable. It is not needed on Cloud Run, because the attached service account resolves it automatically there.

(`MCP_API_KEY` was used in the original single-tenant version and is dead now, since phase D. Nothing in `src/` reads it anymore. MCP access is controlled by minting a per-user key from `POST /api-keys` instead of using a static environment variable.)

Google credentials for GCS, Firestore, and Firebase Admin resolve through Application Default Credentials. Run `gcloud auth application-default login` once locally to set that up. On Cloud Run, this comes from the attached service account instead.

**Run the MCP server:**
```cmd
python src\mcp_server.py
```
It listens on `http://0.0.0.0:8080/mcp` (or whatever `$PORT` is set to). Every request must include a matching `x-api-key` header, which gets resolved to a user account through Firestore.

**Run the web API:**
```cmd
python src\web_api.py
```
It listens on `http://0.0.0.0:8080` (or whatever `$PORT` is set to). Every request must include an `Authorization: Bearer <firebase-id-token>` header.

**Try it end to end without a frontend:**
```cmd
python test_web_api_client.py
```
This signs in against Firebase's own REST API, standing in for a browser login form, and then exercises `/api-keys`, `/notes/upload`, `/notes`, and `/ask` in sequence.

`test_mcp_client.py` does the same kind of smoke test, but against the MCP server directly, minting its own key the same way. Both the MCP server and the web API default to port 8080, so if you want to run both locally at the same time, start the MCP server on a different port: `set PORT=8081 && python src\mcp_server.py`, then `set MCP_SERVER_URL=http://localhost:8081/mcp` before running the test client. (Or just edit the default URL in the script.)

**Try the real login page:** `web_api.py` serves `frontend/index.html` itself (see "Frontend" above), so once it is running, just open `http://localhost:8080/`. No separate static server is needed. Sign up or sign in, upload a note, and ask a question about it.

## Deployment

This app is containerized with the included `Dockerfile` and deployed to Google Cloud Run as two separate services, both built from the same image. One process per container is the normal shape for Cloud Run, and `web_api.py`/`mcp_server.py` are already two separate entry points, so this split is the natural one rather than merging them into a single process.

The two services are:

- **`rag-notes-web`**: runs `web_api.py`, which is the Dockerfile's default command. This serves both the REST API and `frontend/index.html`, from the same origin, so the page's own "Backend URL" field can stay blank.
- **`rag-notes-mcp`**: runs `mcp_server.py` instead, by overriding the image's default command at deploy time. It reuses the same service name and URL that it had before the multi-tenant rework.

The build happens remotely through Cloud Build (`gcloud run deploy --source .`), not through a local Docker push. Secrets are passed in as environment variables at deploy time, using `--env-vars-file env.yaml`. That file is gitignored and kept in sync with `.env`, so secrets are never baked into the image. Cloud Run's own authentication is left open, using `--allow-unauthenticated`, because the real access control is the app-level auth: `ApiKeyMiddleware` plus Firestore resolution for the MCP server, and Firebase tokens for the web API. GCP's own auth is not meant to be the gate.

**To deploy** (from the project root, once `env.yaml` has `GROQ_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET_NAME`, and `FIREBASE_WEB_API_KEY`, matching the same values as `.env`):

```cmd
gcloud run deploy rag-notes-web --source . --region us-central1 --allow-unauthenticated --env-vars-file env.yaml --memory 2Gi

gcloud run deploy rag-notes-mcp --source . --region us-central1 --allow-unauthenticated --env-vars-file env.yaml --command python --args src/mcp_server.py --memory 2Gi
```

Each command prints its own `*.run.app` URL. `rag-notes-web`'s URL is the real website; open it directly. `rag-notes-mcp`'s URL, with `/mcp` appended, is what goes into an MCP client config.

A few deploy-time issues are worth remembering if you hit them again:

`.gcloudignore` controls what gets uploaded to Cloud Build, and it is separate from `.gitignore`. So anything excluded from git, like `notes/`, `index/`, and the test clients, also needs to be excluded from `.gcloudignore` if it should not ship in the image.

The MCP SDK has its own DNS rebinding protection, which by default only allows a `Host` header of `127.0.0.1`. This silently blocked every request once the server was deployed under a real hostname. It was explicitly disabled in favor of the API-key/Firestore layer, which already does that job.

`--memory` needs to be set above Cloud Run's default of 512 MiB. Loading the `sentence-transformers` embedding model, plus torch, firebase_admin, and everything else, used over 1114 MiB in practice at startup. When that happens, Cloud Run shows a generic "container failed to start and listen on the port" error, with no mention of memory at all. The real reason only shows up by running `gcloud logging read` on the revision, which will say something like "Memory limit ... exceeded."

Separately, the embedding model is downloaded fresh from the Hugging Face Hub on every cold start, instead of being baked into the image. This has already hit a Hugging Face rate limit once. It is not fixed yet; see Next Steps.

## Next Steps (as of this update)

Everything through phase E is done and verified locally: multi-tenant storage and auth (phases A through D), the login, upload, and ask dashboard (phase E), PDF uploads, and the note/chunk viewer.

Both services are redeployed and live. `rag-notes-web` is redeployed on the two-service, GCS-backed, frontend-serving setup, which needed `--memory 2Gi` to avoid an out-of-memory error on startup (see the Deployment section above). `rag-notes-mcp` is redeployed the same way, and was verified end to end against its live URL using `test_mcp_client.py`: it minted a key, resolved it through Firestore, loaded a test user's GCS index, and returned a correct, grounded answer with a source citation.

Cold-start model download is not fixed yet. The embedding model is pulled from the Hugging Face Hub on every cold start, instead of being baked into the image, and this has already hit a Hugging Face rate limit once. It is probably worth caching the model into the Docker image at build time, or setting an `HF_TOKEN`, to avoid slow or flaky cold starts.

After that, the plan is to pick back up **Project 2: a codebase Q&A / doc-grounded coding assistant**, the next project in the series.

## Part of a Series

This was originally planned as the first of three projects to learn RAG, LangChain, local/hosted model serving, and MCP from scratch. The next one is a codebase Q&A assistant with file and line citations, and after that, a shared-memory MCP server. Work has stayed on this project longer than planned, in order to take it from a single-user script to a real multi-tenant service. Picking up Project 2 is still on the table once the gaps above are closed.
