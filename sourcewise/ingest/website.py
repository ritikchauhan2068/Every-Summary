import re

import trafilatura
from bs4 import BeautifulSoup

from sourcewise.config import MAX_TEXT
from sourcewise.domain import Material, Passage, SourceError, split_words
from sourcewise.ingest.network import get_public


def load(url, progress):
    progress("Reading the website")
    raw, content_type, final_url = get_public(url, accept="text/html,text/plain,application/xhtml+xml")
    if content_type and not any(kind in content_type.lower() for kind in ("text/", "xhtml")):
        raise SourceError("This URL does not return readable web text. Upload PDFs under PDF.")
    return extract(raw, final_url, content_type)


def extract(raw, url, content_type="text/html"):
    soup = BeautifulSoup(raw, "html.parser")
    heading = soup.find("meta", property="og:title")
    title = (heading.get("content") if heading else None) or (
        soup.title.get_text(" ", strip=True) if soup.title else None
    ) or url
    if content_type.startswith("text/plain"):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = trafilatura.extract(raw, url=url, favor_precision=True, include_comments=False)
        if not text or len(text) < 100:
            for element in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
                element.decompose()
            root = soup.find("main") or soup.find("article") or soup.body or soup
            text = root.get_text("\n", strip=True)
    if len(re.sub(r"\s+", "", text or "")) < 25:
        raise SourceError("The webpage has too little readable text. It may require sign-in or client-side rendering.")
    if len(text) > MAX_TEXT:
        raise SourceError("The webpage exceeds 200,000 extracted characters. Use a more specific page.")
    return Material(str(title)[:180], "Web page text", [
        Passage(part, f"Website · Section {i}", url) for i, part in enumerate(split_words(text), 1)
    ])
