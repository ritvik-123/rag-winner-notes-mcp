import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from chunker import Chunk


class VectorStore:
    def __init__(self):
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None

    def build(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        self.chunks = chunks
        self.vectors = np.array(vectors, dtype=np.float32)

    def search(self, query_vector: list[float], top_k: int = 3) -> list[tuple[Chunk, float]]:
        if self.vectors is None or len(self.chunks) == 0:
            return []
        query = np.array(query_vector, dtype=np.float32)
        scores = self.vectors @ query
        top_indices = np.argsort(-scores)[:top_k]
        return [(self.chunks[i], float(scores[i])) for i in top_indices]

    def save(self, directory: str = "index") -> None:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        metadata = [asdict(chunk) for chunk in self.chunks]
        (path / "chunks.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def load(self, directory: str = "index") -> None:
        path = Path(directory)
        self.vectors = np.load(path / "vectors.npy")
        metadata = json.loads((path / "chunks.json").read_text(encoding="utf-8"))
        self.chunks = [Chunk(**item) for item in metadata]


if __name__ == "__main__":
    from chunker import chunk_documents
    from embedder import embed_chunks, embed_texts
    from loader import load_notes

    docs = load_notes()
    chunks = chunk_documents(docs)
    vectors = embed_chunks(chunks)

    store = VectorStore()
    store.build(chunks, vectors)
    store.save("index")
    print(f"Saved {len(chunks)} chunk(s) to index/\n")

    query = "What does Ritvik do?"
    query_vector = embed_texts([query])[0]
    results = store.search(query_vector, top_k=3)

    print(f"Query: {query!r}\n")
    for chunk, score in results:
        preview = chunk.content[:100].replace("\n", " ")
        print(f"score={score:.4f} | {chunk.source} #{chunk.chunk_index}: {preview}...")
