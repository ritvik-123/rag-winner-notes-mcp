from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}


@dataclass
class Document:
    content: str
    source: str


def extract_text_from_pdf(data: bytes) -> str:
    """PDF pages don't give you one string, they give you a reader object
    you page through -- join each page's extracted text (None on an
    image-only/scanned page, no OCR here) with a blank line.
    """
    reader = PdfReader(BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def load_notes(notes_dir: str = "notes") -> list[Document]:
    documents = []
    for path in sorted(Path(notes_dir).rglob("*")):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if path.suffix.lower() == ".pdf":
            content = extract_text_from_pdf(path.read_bytes())
        else:
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
