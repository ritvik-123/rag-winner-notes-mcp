import os

import uvicorn
from dotenv import load_dotenv
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from auth import ApiKeyMiddleware
from embedder import embed_texts
from rag_chain import RAGAnswer, build_conversational_chain
from retriever import NotesRetriever
from user_store import resolve_api_key
from vector_store import VectorStore

load_dotenv()

# embedder.get_model() is a *lazy* singleton -- it only actually loads the
# model the first time something calls embed_texts(). Without this line,
# that first load (which includes several HTTP round-trips to Hugging Face
# Hub to check cached file metadata) would happen inline during whichever
# client's request happens to be first, risking a client-side timeout. Doing
# it here, once, at startup, means every real request -- including the
# first one -- hits an already-warm model. Unlike the old single-notebook
# version, the *index* can no longer be preloaded here too: each call now
# belongs to a different user's own notes, fetched from GCS per request.
embed_texts(["warmup"])

server = MCPServer(name="rag-notes-assistant")


@server.tool()
def ask_notes(question: str, ctx: Context, session_id: str = "default") -> RAGAnswer:
    """Answer a question using the calling user's own uploaded notes, citing the source files used."""
    api_key = (ctx.headers or {}).get("x-api-key")
    user_id = resolve_api_key(api_key) if api_key else None
    if user_id is None:
        return RAGAnswer(answer="Unrecognized API key.", sources=[])

    store = VectorStore()
    if not store.load_from_gcs(user_id):
        return RAGAnswer(answer="You haven't uploaded any notes yet.", sources=[])

    retriever = NotesRetriever(store=store, top_k=3)
    conversational_chain = build_conversational_chain(retriever)
    result = conversational_chain.invoke(
        {"question": question},
        config={"configurable": {"session_id": f"{user_id}:{session_id}"}},
    )
    return RAGAnswer(answer=result["answer"], sources=result["sources"])


if __name__ == "__main__":
    # The SDK's own DNS-rebinding protection defaults to only allowing a
    # Host header of "127.0.0.1", which is why this worked locally but not
    # once deployed under a real hostname. ApiKeyMiddleware is already the
    # real access-control layer here, so this specific protection (aimed at
    # naive unauthenticated local servers) is redundant for this app --
    # disabling it rather than hardcoding the deployed hostname into source.
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = server.streamable_http_app(transport_security=transport_security)
    app = ApiKeyMiddleware(app)

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
