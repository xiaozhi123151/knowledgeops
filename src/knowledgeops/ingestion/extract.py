import hashlib
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass

from bs4 import BeautifulSoup
from pypdf import PdfReader

from knowledgeops.schemas import Chunk


@dataclass
class Segment:
    text: str
    page: int | None = None
    section: str = ""


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(re.sub(r"[ \t]+", " ", x).strip() for x in text.split("\n"))).strip()


def extract(data: bytes, suffix: str, max_pages=300):
    if suffix == '.pdf':
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("ENCRYPTED_PDF: decrypt the document before importing")
        if len(reader.pages) > max_pages:
            raise ValueError("PDF_PAGE_LIMIT")
        segments = [Segment(normalize(p.extract_text() or ''), i + 1) for i, p in enumerate(reader.pages)]
        if any(not s.text for s in segments):
            raise ValueError("OCR_REQUIRED: at least one PDF page has no extractable text")
    elif suffix in ('.md', '.txt'):
        text = normalize(data.decode('utf-8-sig'))
        segments, section, buf = [], '', []
        for line in text.splitlines():
            if suffix == '.md' and re.match(r"^#{1,6}\s", line):
                if buf:
                    segments.append(Segment(normalize('\n'.join(buf)), section=section))
                section, buf = line.lstrip('#').strip(), [line]
            else:
                buf.append(line)
        if buf:
            segments.append(Segment(normalize('\n'.join(buf)), section=section))
    elif suffix == '.html':
        soup = BeautifulSoup(data, 'html.parser')
        for node in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript']):
            node.decompose()
        root = soup.find('main') or soup.find('article') or soup.body or soup
        segments = [Segment(normalize(root.get_text('\n', strip=True)))]
    else:
        raise ValueError("UNSUPPORTED_FORMAT: PDF, Markdown, TXT or URL only")
    segments = [s for s in segments if s.text]
    if not segments:
        raise ValueError("EMPTY_DOCUMENT")
    return segments


def make_chunks(segments, source, title, size=800, overlap=120):
    full_text = '\n\n'.join(s.text for s in segments)
    doc_id = hashlib.sha256(full_text.encode()).hexdigest()
    chunks, offset = [], 0
    for segment in segments:
        start = 0
        while start < len(segment.text):
            end = min(start + size, len(segment.text))
            if end < len(segment.text):
                split = segment.text.rfind('\n\n', start + size // 2, end)
                if split >= 0:
                    end = split + 2
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ko:v1:{doc_id}:{offset+start}:{offset+end}"))
            chunks.append(Chunk(chunk_id=chunk_id, doc_id=doc_id, text=segment.text[start:end],
                                page=segment.page, section=segment.section, start=offset+start,
                                end=offset+end, source=source, title=title))
            if end == len(segment.text):
                break
            start = max(start + 1, end - overlap)
        offset += len(segment.text) + 2
    return doc_id, chunks
