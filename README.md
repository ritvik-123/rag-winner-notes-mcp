# rag-winner-notes-mcp

A personal knowledge-base assistant: retrieval-augmented generation (RAG) over your own Markdown/text notes, exposed as a remote MCP tool so any MCP-compatible client (Claude Code, Claude Desktop, etc.) can query your notes directly.

## How it works

1. **Loading & chunking** (`src/loader.py`, `src/cleaner.py`, `src/chunker.py`) — reads `.md`/`.txt` files from `notes/`, strips HTML/whitespace noise, and splits each document into ~300-character chunks with 50-character overlap (paragraph-first, falling back to sentence-level splitting for long paragraphs).
2. **Embedding & indexing** (`src/embedder.py`, `src/vector_store.py`) — embeds chunks with `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, normalized), stores them in a flat numpy cosine-similarity index (`index/`).
3. **Retrieval + generation** (`src/retriever.py`, `src/rag_chain.py`) — a LangChain pipeline: history-aware query rewriting (resolves vague follow-ups like "what tools does he use for *that*?" using conversation history) → vector retrieval → prompt construction → generation via Groq (`openai/gpt-oss-120b`) → structured `{answer, sources}` output (Pydantic) → multi-turn memory (`RunnableWithMessageHistory`).
4. **MCP server** (`src/mcp_server.py`, `src/auth.py`) — exposes the chain as a single tool, `ask_notes(question, session_id)`, over MCP's Streamable HTTP transport, gated by a simple API-key check (`ApiKeyMiddleware`).

## Running locally

Requires Python 3.14 and a virtualenv (`.rag_venv/` in this repo).

```cmd
.rag_venv\Scripts\activate.bat
pip install -r requirements.txt
```

Create a `.env` file in the project root:
```
GROQ_API_KEY=your_groq_api_key
MCP_API_KEY=any_random_string_you_choose
```

Build the index (one-time, or whenever `notes/` changes):
```cmd
python src\vector_store.py
```

Run the server:
```cmd
python src\mcp_server.py
```

The server listens on `http://0.0.0.0:8080/mcp` (or `$PORT` if set). Every request must include a matching `x-api-key` header.

## Deployment

Containerized via the included `Dockerfile`, deployed to **Google Cloud Run** with the build happening remotely via Cloud Build (`gcloud run deploy --source .`) rather than a local Docker push. Secrets are passed in as environment variables at deploy time (`--env-vars-file env.yaml`, itself gitignored), never baked into the image — `notes/` and the prebuilt `index/` *are* baked in, since the container needs to be self-contained to answer questions.

Cloud Run's own auth is left open (`--allow-unauthenticated`) since `ApiKeyMiddleware` is the intended access-control layer, not GCP's.

## Stack

Python · LangChain · sentence-transformers · Groq · MCP (Streamable HTTP) · Docker · Google Cloud Run
