import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chunker import chunk_documents
from embedder import embed_chunks, embed_texts
from firebase_auth import get_current_user_id
from loader import Document, extract_text_from_pdf
from rag_chain import RAGAnswer, build_conversational_chain
from retriever import NotesRetriever
from user_store import create_api_key
from vector_store import VectorStore

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Same reasoning as mcp_server.py's warmup call: without this, the first
    # real request pays for loading the embedding model inline.
    embed_texts(["warmup"])
    yield


app = FastAPI(title="RAG Notes API", lifespan=lifespan)

# Wide open for now. In production the frontend (mounted below) is served
# from this same app, so most real traffic is same-origin anyway -- this
# matters for local dev, where the page can be opened via file:// or a
# different port than this API. Either way, the real access control is the
# Firebase token check on every route below, not same-origin policy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str
    session_id: str = "default"


class NotesListResponse(BaseModel):
    sources: list[str]


class NoteChunksResponse(BaseModel):
    source: str
    chunks: list[str]


@app.post("/notes/upload")
async def upload_note(file: UploadFile, user_id: str = Depends(get_current_user_id)) -> dict:
    raw_bytes = await file.read()
    if file.filename.lower().endswith(".pdf"):
        raw_text = extract_text_from_pdf(raw_bytes)
    else:
        raw_text = raw_bytes.decode("utf-8")
    document = Document(content=raw_text, source=file.filename)
    chunks = chunk_documents([document])
    vectors = embed_chunks(chunks)

    # Download -> modify in memory -> re-upload: two uploads for the same
    # user landing at the same moment can race, and one can clobber the
    # other. Accepted for now since only one person uploads to their own
    # notebook at a time; would need real locking (e.g. GCS generation
    # preconditions) before this could trust concurrent writers.
    store = VectorStore()
    store.load_from_gcs(user_id)
    store.upsert_document(chunks, vectors)
    store.save_to_gcs(user_id)

    return {"source": file.filename, "chunks_added": len(chunks)}


@app.post("/ask", response_model=RAGAnswer)
async def ask(request: AskRequest, user_id: str = Depends(get_current_user_id)) -> RAGAnswer:
    store = VectorStore()
    if not store.load_from_gcs(user_id):
        return RAGAnswer(answer="You haven't uploaded any notes yet.", sources=[])

    retriever = NotesRetriever(store=store, top_k=3)
    chain = build_conversational_chain(retriever)
    result = chain.invoke(
        {"question": request.question},
        config={"configurable": {"session_id": f"{user_id}:{request.session_id}"}},
    )
    return RAGAnswer(answer=result["answer"], sources=result["sources"])


@app.get("/notes", response_model=NotesListResponse)
async def list_notes(user_id: str = Depends(get_current_user_id)) -> NotesListResponse:
    store = VectorStore()
    store.load_from_gcs(user_id)
    return NotesListResponse(sources=sorted({chunk.source for chunk in store.chunks}))


@app.get("/notes/{source}", response_model=NoteChunksResponse)
async def get_note(source: str, user_id: str = Depends(get_current_user_id)) -> NoteChunksResponse:
    """Returns a source's chunks in order, not a perfect reconstruction of
    the uploaded file -- chunks overlap by design (see chunker.py), so this
    is deliberately showing the same units retrieval actually searches over.
    """
    store = VectorStore()
    store.load_from_gcs(user_id)
    matching = sorted(
        (chunk for chunk in store.chunks if chunk.source == source),
        key=lambda chunk: chunk.chunk_index,
    )
    return NoteChunksResponse(source=source, chunks=[chunk.content for chunk in matching])


@app.post("/api-keys")
async def mint_api_key(user_id: str = Depends(get_current_user_id)) -> dict:
    """Issue a personal MCP API key for the logged-in user. Shown once in
    the response -- same handling as any other API key, store it somewhere
    safe, there's no "show it again" afterwards.
    """
    return {"api_key": create_api_key(user_id)}


# Serves frontend/index.html (and anything else dropped in frontend/) at
# "/". Mounted last and matched last: every route declared above still
# takes priority for its exact path, so this only catches requests that
# aren't one of the API routes.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    # Same local-run pattern as mcp_server.py: 0.0.0.0 so it's reachable
    # from outside a container, PORT read at runtime for Cloud Run.
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
