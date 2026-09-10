import re
from html import unescape

TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"[ \t]+")
BLANK_LINES_PATTERN = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    text = unescape(text)
    text = TAG_PATTERN.sub(" ", text)
    text = WHITESPACE_PATTERN.sub(" ", text)
    text = BLANK_LINES_PATTERN.sub("\n\n", text)
    return text.strip()
