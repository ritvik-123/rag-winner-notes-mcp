from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from embedder import embed_texts
from vector_store import VectorStore


class NotesRetriever(BaseRetriever):
    """Adapts our hand-rolled VectorStore to LangChain's Retriever interface."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: VectorStore
    top_k: int = 3

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        query_vector = embed_texts([query])[0]
        results = self.store.search(query_vector, top_k=self.top_k)
        return [
            Document(
                page_content=chunk.content,
                metadata={
                    "source": chunk.source,
                    "chunk_index": chunk.chunk_index,
                    "score": score,
                },
            )
            for chunk, score in results
        ]


if __name__ == "__main__":
    store = VectorStore()
    store.load("index")
    retriever = NotesRetriever(store=store, top_k=3)

    query = "What does Ritvik do?"
    docs = retriever.invoke(query)

    print(f"Query: {query!r}\n")
    for doc in docs:
        preview = doc.page_content[:100].replace("\n", " ")
        print(
            f"score={doc.metadata['score']:.4f} | "
            f"{doc.metadata['source']} #{doc.metadata['chunk_index']}: {preview}..."
        )
