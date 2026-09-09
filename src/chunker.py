import re
from dataclasses import dataclass

from loader import Document

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    content: str
    source: str
    chunk_index: int


def _split_into_sentences(paragraph: str) -> list[str]:
    return [s.strip() for s in SENTENCE_BOUNDARY.split(paragraph) if s.strip()]


def _pack_into_chunks(units: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""

    for unit in units:
        candidate = f"{current} {unit}".strip()
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(unit) <= chunk_size:
            current = unit
        else:
            step = chunk_size - chunk_overlap
            for start in range(0, len(unit), step):
                chunks.append(unit[start:start + chunk_size])
            current = ""

    if current:
        chunks.append(current)

    return _add_overlap(chunks, chunk_overlap)


def _add_overlap(chunks: list[str], chunk_overlap: int) -> list[str]:
    if chunk_overlap <= 0 or len(chunks) < 2:
        return chunks
    overlapped = [chunks[0]]
    for previous, current in zip(chunks, chunks[1:]):
        tail = previous[-chunk_overlap:]
        overlapped.append(f"{tail} {current}".strip())
    return overlapped


def chunk_documents(
    documents: list[Document], chunk_size: int = 300, chunk_overlap: int = 50
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        paragraphs = [p.strip() for p in document.content.split("\n\n") if p.strip()]
        units: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= chunk_size:
                units.append(paragraph)
            else:
                units.extend(_split_into_sentences(paragraph))

        pieces = _pack_into_chunks(units, chunk_size, chunk_overlap)
        for index, piece in enumerate(pieces):
            chunks.append(Chunk(content=piece, source=document.source, chunk_index=index))
    return chunks


if __name__ == "__main__":
    from loader import load_notes

    docs = load_notes()
    chunks = chunk_documents(docs)
    print(f"Loaded {len(docs)} document(s) -> {len(chunks)} chunk(s)\n")
    for chunk in chunks:
        preview = chunk.content[:80].replace("\n", " ")
        print(f"- {chunk.source} #{chunk.chunk_index} ({len(chunk.content)} chars): {preview}...")
