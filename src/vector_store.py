import json
import os
from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import numpy as np
from google.cloud import storage

from chunker import Chunk

_storage_client: storage.Client | None = None


def _get_bucket(bucket_name: str | None = None) -> storage.Bucket:
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client.bucket(bucket_name or os.environ["GCS_BUCKET_NAME"])


class VectorStore:
    def __init__(self):
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None

    def build(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        self.chunks = chunks
        self.vectors = np.array(vectors, dtype=np.float32)

    def upsert_document(self, new_chunks: list[Chunk], new_vectors: list[list[float]]) -> None:
        """Add a document's chunks, first dropping any existing chunks from
        the same source -- so re-uploading an edited note replaces its old
        chunks instead of leaving stale duplicates behind.
        """
        new_array = np.array(new_vectors, dtype=np.float32)
        sources_to_replace = {chunk.source for chunk in new_chunks}

        if self.vectors is None or len(self.chunks) == 0:
            self.chunks = list(new_chunks)
            self.vectors = new_array
            return

        keep_indices = [i for i, chunk in enumerate(self.chunks) if chunk.source not in sources_to_replace]
        kept_vectors = (
            self.vectors[keep_indices] if keep_indices else np.empty((0, new_array.shape[1]), dtype=np.float32)
        )
        self.chunks = [self.chunks[i] for i in keep_indices] + new_chunks
        self.vectors = np.vstack([kept_vectors, new_array])

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

    def save_to_gcs(self, user_id: str, bucket_name: str | None = None) -> None:
        """Serialize this store and upload it to gs://<bucket>/users/<user_id>/index/,
        overwriting whatever that user already had. Needed because every
        Cloud Run instance is stateless -- the next request, possibly on a
        different instance, can't rely on anything written to local disk.
        """
        bucket = _get_bucket(bucket_name)

        vectors_buffer = BytesIO()
        np.save(vectors_buffer, self.vectors)
        bucket.blob(f"users/{user_id}/index/vectors.npy").upload_from_string(
            vectors_buffer.getvalue(), content_type="application/octet-stream"
        )

        metadata = [asdict(chunk) for chunk in self.chunks]
        bucket.blob(f"users/{user_id}/index/chunks.json").upload_from_string(
            json.dumps(metadata), content_type="application/json"
        )

    def load_from_gcs(self, user_id: str, bucket_name: str | None = None) -> bool:
        """Download and load a user's index from GCS. Returns False, leaving
        this store empty, if the user has never uploaded a note yet -- a
        brand new user is a normal case to handle, not an error.
        """
        bucket = _get_bucket(bucket_name)
        vectors_blob = bucket.blob(f"users/{user_id}/index/vectors.npy")
        if not vectors_blob.exists():
            return False

        self.vectors = np.load(BytesIO(vectors_blob.download_as_bytes()))
        metadata = json.loads(bucket.blob(f"users/{user_id}/index/chunks.json").download_as_text())
        self.chunks = [Chunk(**item) for item in metadata]
        return True


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
