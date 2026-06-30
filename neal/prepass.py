# Deterministic prepass: raw narration -> a candidate node vocabulary.
#
# No model, no mesh. For each document in a bento's raw_data, wonderlib computes
# Zipf + part-of-speech lexical rarity and surfaces the rare terms that carry the
# document's signal. neal folds those across the corpus into a sparse candidate
# vocabulary -- the corpus-derived starting point the extraction engine will later
# confirm, type, and merge into the graph.
#
# Nothing here is canon. Every candidate is kind: UNKNOWN until a model types it,
# and carries provenance (which documents surfaced it) and the backend that produced
# it. neal does not invent: if the corpus is silent, the term simply is not here.

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Callable

from neal.bento import TEXT_SUFFIXES, Bento, record_stage

# The backend that produced these candidates -- recorded on every record and in
# the manifest, per neal's provenance discipline.
BACKEND = "wonderlib-prepass"

# A profiler maps (text, title) -> an object exposing ``.rare_terms: list[str]``.
# wonderlib.profile_document is the default; tests inject a fake.
Profiler = Callable[..., object]


def _default_profiler() -> Profiler:
    # Lazy: keeps spacy/wonderlib out of import time, so importing the prepass
    # (and unit-testing it with an injected profiler) needs neither.
    from wonderlib import profile_document

    return profile_document


def candidate_vocabulary(
    documents: Iterable[tuple[str, str]],
    *,
    profiler: Profiler | None = None,
) -> list[dict]:
    # profile each (title, text) document and fold rare terms into candidates.
    # returns one record per distinct term -- its surface form, the (sorted, unique)
    # documents that surfaced it, a document count, the producing backend, and an
    # explicit UNKNOWN kind. records are sorted by term for a stable artifact.
    profile = profiler or _default_profiler()
    sources: dict[str, set[str]] = defaultdict(set)
    for title, text in documents:
        prof = profile(text=text, title=title)
        for term in getattr(prof, "rare_terms", []):
            key = term.strip()
            if key:
                sources[key].add(title)

    candidates: list[dict] = []
    for term in sorted(sources):
        provenance = sorted(sources[term])
        candidates.append(
            {
                "term": term,
                "kind": "UNKNOWN",  # the model types it later; unknown until then
                "backend": BACKEND,
                "provenance": {"documents": provenance, "count": len(provenance)},
            }
        )
    return candidates


def _load_documents(bento: Bento) -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    for f in sorted(bento.raw_data.iterdir()):
        if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES:
            docs.append((f.name, f.read_text()))
    return docs


def run_prepass(bento: Bento, *, profiler: Profiler | None = None) -> Path:
    # run the prepass over a bento's raw_data and write the candidate vocabulary.
    # writes outputs/graph/candidates.jsonl (one JSON record per line) and records
    # a prepass stage in the manifest. returns the candidates path.
    documents = _load_documents(bento)
    candidates = candidate_vocabulary(documents, profiler=profiler)

    out = bento.graph / "candidates.jsonl"
    with out.open("w") as fh:
        for record in candidates:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    record_stage(
        bento,
        "prepass",
        {
            "backend": BACKEND,
            "documents": len(documents),
            "candidate_terms": len(candidates),
            "output": str(out.relative_to(bento.root)),
        },
    )
    return out
