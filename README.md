# rag-winner-notes-mcp

A personal knowledge base assistant built from scratch: retrieval augmented generation over personal notes, exposed as a remote MCP tool so any MCP compatible client (Claude Code, Claude Desktop, etc.) can query the notes directly, with a real public deployment on Google Cloud Run.

## Live Deployment

`https://rag-notes-mcp-585012498530.us-central1.run.app/mcp`

The service is public but gated by an API key check (`x-api-key` header). This repo is meant to demonstrate a complete, working architecture rather than serve as an open public endpoint, so a valid key is required to actually query it.

## Overview

This project was built to learn the full RAG stack end to end: chunking and embedding strategy, vector retrieval, LangChain's retrieval and generation abstractions, the Model Context Protocol, and real cloud deployment, rather than just wiring together a demo. Every layer below was built and understood individually before moving on to the next.

## Architecture

1. **Loading and chunking** (`src/loader.py`, `src/cleaner.py`, `src/chunker.py`)
   Reads `.md`/`.txt` files from `notes/`, strips HTML and whitespace noise, and splits each document into roughly 300 character chunks with 50 character overlap, splitting on paragraphs first and falling back to sentence level splitting for long paragraphs.

2. **Embedding and indexing** (`src/embedder.py`, `src/vector_store.py`)
   Embeds chunks with `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dimensions, normalized) and stores them in a flat numpy cosine similarity index (`index/`).

3. **Retrieval and generation** (`src/retriever.py`, `src/rag_chain.py`)
   A LangChain pipeline: history aware query rewriting (resolving vague follow up questions using conversation history), vector retrieval, prompt construction, generation via Groq (`openai/gpt-oss-120b`), structured `{answer, sources}` output through Pydantic, and multi turn memory via `RunnableWithMessageHistory`.

4. **MCP server** (`src/mcp_server.py`, `src/auth.py`)
   Exposes the chain as a single tool, `ask_notes(question, session_id)`, over MCP's Streamable HTTP transport, gated by a custom `ApiKeyMiddleware`.

## Tech Stack

Python, LangChain, sentence transformers, Groq, MCP (Streamable HTTP transport), Docker, Google Cloud Run, Google Cloud Build.

## Running Locally

Requires Python 3.14 and a virtual environment (`.rag_venv/` in this repo).

```cmd
.rag_venv\Scripts\activate.bat
pip install -r requirements.txt
```

Create a `.env` file in the project root:
```
GROQ_API_KEY=your_groq_api_key
MCP_API_KEY=any_random_string_you_choose
```

Build the index (one time, or whenever `notes/` changes):
```cmd
python src\vector_store.py
```

Run the server:
```cmd
python src\mcp_server.py
```

The server listens on `http://0.0.0.0:8080/mcp` (or `$PORT` if set). Every request must include a matching `x-api-key` header.

## Deployment

Containerized with the included `Dockerfile` and deployed to Google Cloud Run. The build happens remotely through Cloud Build (`gcloud run deploy --source .`) rather than a local Docker push. Secrets are passed in as environment variables at deploy time (`--env-vars-file env.yaml`, itself gitignored) and are never baked into the image. `notes/` and the prebuilt `index/` are baked into the image, since the container needs to be self contained to answer questions.

Cloud Run's own authentication is left open (`--allow-unauthenticated`) since `ApiKeyMiddleware` is the intended access control layer, not GCP's.

Two deploy time gotchas worth remembering: `.gcloudignore` controls what gets uploaded to Cloud Build and is separate from `.gitignore`, so `notes/` and `index/` had to be explicitly kept out of it even though both are excluded from git. The MCP SDK's own DNS rebinding protection also defaults to only allowing a `Host` header of `127.0.0.1`, so it silently blocked every request once deployed under a real hostname, until it was explicitly disabled in favor of the API key layer already doing that job.

## Part of a Series

This is the first of three planned projects to learn RAG, LangChain, local and hosted model serving, and MCP from scratch. Next up: a codebase question and answer assistant with citations back to file and line, and a shared memory MCP server backed by a vector database.
