from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile
from pydantic import BaseModel

from chunker import chunk_documents
from embedder import embed_chunks, embed_texts
from loader import Document
from rag_chain import RAGAnswer, build_conversational_chain
from retriever import NotesRetriever
from vector_store import VectorStore

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Same reasoning as mcp_server.py's warmup call: without this, the first
    # real request pays for loading the embedding model inline.
    embed_texts(["warmup"])
    yield


app = FastAPI(title="RAG Notes API", lifespan=lifespan)


class AskRequest(BaseModel):
    # TODO(phase B): this should come from a verified Firebase ID token's
    # uid instead of being supplied directly by the caller.
    user_id: str
    question: str
    session_id: str = "default"


class NotesListResponse(BaseModel):
    sources: list[str]


@app.post("/notes/upload")
async def upload_note(user_id: str, file: UploadFile) -> dict:
    raw_text = (await file.read()).decode("utf-8")
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
async def ask(request: AskRequest) -> RAGAnswer:
    store = VectorStore()
    if not store.load_from_gcs(request.user_id):
        return RAGAnswer(answer="You haven't uploaded any notes yet.", sources=[])

    retriever = NotesRetriever(store=store, top_k=3)
    chain = build_conversational_chain(retriever)
    result = chain.invoke(
        {"question": request.question},
        config={"configurable": {"session_id": f"{request.user_id}:{request.session_id}"}},
    )
    return RAGAnswer(answer=result["answer"], sources=result["sources"])


@app.get("/notes", response_model=NotesListResponse)
async def list_notes(user_id: str) -> NotesListResponse:
    store = VectorStore()
    store.load_from_gcs(user_id)
    return NotesListResponse(sources=sorted({chunk.source for chunk in store.chunks}))
