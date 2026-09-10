from sentence_transformers import SentenceTransformer

from chunker import Chunk

MODEL_NAME = "all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_chunks(chunks: list[Chunk]) -> list[list[float]]:
    return embed_texts([chunk.content for chunk in chunks])


if __name__ == "__main__":
    import numpy as np

    from chunker import chunk_documents
    from loader import load_notes

    docs = load_notes()
    chunks = chunk_documents(docs)
    vectors = embed_chunks(chunks)

    print(f"Embedded {len(chunks)} chunk(s) into vectors of dimension {len(vectors[0])}\n")

    a, b = np.array(vectors[0]), np.array(vectors[1])
    cosine_sim = float(np.dot(a, b))
    print(f"Cosine similarity between chunk 0 and chunk 1: {cosine_sim:.4f}")
    print(f"Chunk 0: {chunks[0].content[:80]!r}")
    print(f"Chunk 1: {chunks[1].content[:80]!r}")
