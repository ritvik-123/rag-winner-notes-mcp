from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".md", ".txt"}


@dataclass
class Document:
    content: str
    source: str


def load_notes(notes_dir: str = "notes") -> list[Document]:
    documents = []
    for path in sorted(Path(notes_dir).rglob("*")):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        content = path.read_text(encoding="utf-8")
        documents.append(Document(content=content, source=str(path)))
    return documents


if __name__ == "__main__":
    docs = load_notes()
    print(f"Loaded {len(docs)} document(s)\n")
    for doc in docs:
        preview = doc.content[:100].replace("\n", " ")
        print(f"- {doc.source} ({len(doc.content)} chars)")
        print(f"  {preview}...")
