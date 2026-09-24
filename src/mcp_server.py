import os

import uvicorn
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from auth import ApiKeyMiddleware
from embedder import embed_texts
from rag_chain import RAGAnswer, build_conversational_chain
from retriever import NotesRetriever
from vector_store import VectorStore

load_dotenv()

# Loaded once, at process startup -- this is the long-running server process
# that finally makes the "loading weights every time" issue from rag_chain.py
# go away. The embedding model, the index, and the conversation chain are all
# built once here and reused for every tool call for the life of the process.
store = VectorStore()
store.load("index")
retriever = NotesRetriever(store=store, top_k=3)
conversational_chain = build_conversational_chain(retriever)

# embedder.get_model() is a *lazy* singleton -- it only actually loads the
# model the first time something calls embed_texts(). Without this line,
# that first load (which includes several HTTP round-trips to Hugging Face
# Hub to check cached file metadata) would happen inline during whichever
# client's request happens to be first, risking a client-side timeout. Doing
# it here, once, at startup, means every real request -- including the
# first one -- hits an already-warm model.
embed_texts(["warmup"])

server = MCPServer(name="rag-notes-assistant")


@server.tool()
def ask_notes(question: str, session_id: str = "default") -> RAGAnswer:
    """Answer a question using Ritvik's personal notes, citing the source files used."""
    result = conversational_chain.invoke(
        {"question": question},
        config={"configurable": {"session_id": session_id}},
    )
    return RAGAnswer(answer=result["answer"], sources=result["sources"])


if __name__ == "__main__":
    # Fail fast: refuse to start rather than silently serve unauthenticated.
    api_key = os.environ["MCP_API_KEY"]

    app = server.streamable_http_app()
    app = ApiKeyMiddleware(app, api_key=api_key)

    # 0.0.0.0, not 127.0.0.1: inside a container, 127.0.0.1 only accepts
    # connections from *within that same container* -- traffic coming in
    # through Docker's port mapping (or Cloud Run's own routing) looks like
    # it's from a different host, so binding to loopback would make the
    # server unreachable from outside despite "running" fine internally.
    # PORT: Cloud Run injects this env var and expects the app to listen on
    # whatever value it sets, defaulting to 8080 -- not our old hardcoded
    # 8000 -- so we read it at runtime instead of hardcoding either.
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
