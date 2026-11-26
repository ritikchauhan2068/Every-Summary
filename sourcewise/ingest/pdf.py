import os

import pymupdf

from sourcewise.config import MAX_TEXT
from sourcewise.domain import Material, Passage, SourceError, split_words

MAX_PAGES = 200


def load(path, filename, progress):
    progress("Reading PDF pages")
    passages = []
    ocr_pages = 0
    missing = []
    extracted = 0
    try:
        with pymupdf.open(path, filetype="pdf") as doc:
            if doc.needs_pass:
                raise SourceError("This PDF is password protected.")
            if len(doc) > MAX_PAGES:
                raise SourceError(f"Upload a PDF with {MAX_PAGES} pages or fewer.")
            title = (doc.metadata or {}).get("title") or filename.removesuffix(".pdf")
            for index, page in enumerate(doc, 1):
                text = page.get_text(sort=True).strip()
                if len(text) < 20:
                    progress(f"Reading scanned page {index} of {len(doc)}")
                    try:
                        layer = page.get_textpage_ocr(
                            language=os.getenv("OCR_LANGUAGE", "eng"),
                            dpi=min(140, max(36, int(144_000 / max(page.rect.width, page.rect.height, 1)))),
                            full=True
                        )
                        ocr = page.get_text(textpage=layer).strip()
                        if len(ocr) > len(text):
                            text = ocr
                            ocr_pages += 1
                    except (RuntimeError, ValueError):
                        pass
                if len(text) < 20:
                    missing.append(index)
                extracted += len(text)
                if extracted > MAX_TEXT:
                    raise SourceError("The PDF exceeds 200,000 extracted characters. Upload a smaller section.")
                for part in split_words(text):
                    passages.append(Passage(part, f"Page {index}", start=index, end=index))
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError) as exc:
        raise SourceError("The file could not be opened as a PDF.") from exc
    if not passages or not any(len(p.text) >= 20 for p in passages):
        raise SourceError("No readable text was extracted. Use a clearer scan or a text-based PDF.")
    notes = []
    if missing:
        pages = ", ".join(map(str, missing[:12])) + (" …" if len(missing) > 12 else "")
        notes.append(f"Little or no text was recovered from pages {pages}.")
    return Material(str(title)[:180], "PDF text + OCR" if ocr_pages else "PDF text", passages, notes=notes)
