# Windowing: cut a document into small, bounded windows the model can actually hold.
#
# The engine never reads the whole corpus at once -- it reasons over one window at a
# time and folds results into the graph. A window is a contiguous span of one
# document, carrying provenance (the document name and its word offsets) so every
# node extracted later can point back to exactly where it came from. Windows overlap
# by a few words so a sentence straddling a boundary is seen whole at least once.

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from neal.bento import TEXT_SUFFIXES, Bento

# small by design: built for the tiniest backend (Apple on-device), so the bigger
# model benefits too. words, not tokens -- deterministic and backend-agnostic.
DEFAULT_MAX_WORDS = 400
DEFAULT_OVERLAP = 40


@dataclass(frozen=True)
class Window:
    document: str  # source document name (provenance)
    index: int  # 0-based window number within the document
    start: int  # word offset of the first word (inclusive)
    end: int  # word offset just past the last word (exclusive)
    text: str  # the window's text


def iter_windows(
    text: str,
    document: str,
    *,
    max_words: int = DEFAULT_MAX_WORDS,
    overlap: int = DEFAULT_OVERLAP,
) -> Iterator[Window]:
    # split `text` into windows of at most `max_words`, each overlapping the previous
    # by `overlap` words. empty text yields nothing.
    if max_words <= 0:
        raise ValueError("max_words must be positive")
    if not 0 <= overlap < max_words:
        raise ValueError("overlap must be >= 0 and < max_words")
    words = text.split()
    if not words:
        return
    step = max_words - overlap
    start = 0
    index = 0
    n = len(words)
    while start < n:
        chunk = words[start : start + max_words]
        yield Window(
            document=document,
            index=index,
            start=start,
            end=start + len(chunk),
            text=" ".join(chunk),
        )
        if start + max_words >= n:  # this window reached the end
            break
        start += step
        index += 1


def bento_windows(
    bento: Bento,
    *,
    max_words: int = DEFAULT_MAX_WORDS,
    overlap: int = DEFAULT_OVERLAP,
) -> Iterator[Window]:
    # windows across all of a bento's raw_data, in stable (filename, index) order.
    for f in sorted(bento.raw_data.iterdir()):
        if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES:
            yield from iter_windows(
                f.read_text(), f.name, max_words=max_words, overlap=overlap
            )
