from dataclasses import dataclass, field
from typing import Callable


class SourceError(Exception):
    """An action that could not be completed for the submitted source."""


@dataclass
class Passage:
    text: str
    label: str
    url: str = ""
    start: int | None = None
    end: int | None = None
    id: str = ""


@dataclass
class Material:
    title: str
    method: str
    passages: list[Passage]
    code: dict | None = None
    notes: list[str] = field(default_factory=list)


Progress = Callable[[str], None]


def split_words(text: str, size: int = 360, overlap: int = 45):
    words = text.split()
    for start in range(0, len(words), size - overlap):
        yield " ".join(words[start : start + size])
        if start + size >= len(words):
            break
