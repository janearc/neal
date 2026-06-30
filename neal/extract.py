# Bounded extraction: type one window's candidates into graph nodes.
#
# The model never reads the corpus. Over a single small window, it confirms and types
# the prepass candidates that actually appear there -- character, place, beat, theme,
# fact, date, quote -- or marks them UNKNOWN. It does not invent: a node is only
# emitted for a candidate the prepass already surfaced and the window genuinely
# contains. Every node carries provenance (document + window + offsets), a confidence,
# and which backend typed it. Parsing is fail-closed: unintelligible model output
# raises rather than fabricating a graph.
#
# Cross-window merge / entity resolution is a separate stage; here a term seen in two
# windows yields two nodes, folded together later.

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from neal.bento import Bento, record_stage
from neal.model import DEFAULT_MODEL, ModelClient
from neal.window import Window, bento_windows

NODE_KINDS = (
    "character",
    "place",
    "beat",
    "theme",
    "fact",
    "date",
    "quote",
    "open-puzzle",
)
UNKNOWN = "UNKNOWN"


class ExtractionError(RuntimeError):
    # the model's output could not be parsed into nodes. fail-closed: neal surfaces
    # this rather than inventing structure the model did not actually return.
    pass


@dataclass(frozen=True)
class Node:
    term: str
    kind: str  # one of NODE_KINDS, or UNKNOWN
    confidence: float  # 0.0-1.0
    backend: str  # which model typed it
    provenance: dict  # {document, window, start, end}

    def to_dict(self) -> dict:
        return asdict(self)


def candidates_in_window(window: Window, candidate_terms: Iterable[str]) -> list[str]:
    # the candidates the prepass surfaced that this window actually contains, in a
    # stable order. case-insensitive substring -- a window only confirms what it holds.
    haystack = window.text.lower()
    return sorted({t for t in candidate_terms if t and t.lower() in haystack})


def build_prompt(window: Window, candidates: list[str]) -> str:
    # ask the model to type ONLY the listed candidates that genuinely appear, never to
    # invent, and to answer with a JSON array and nothing else.
    kinds = ", ".join(NODE_KINDS)
    listed = "\n".join(f"- {c}" for c in candidates)
    return (
        "You are labeling terms from a writer's dictated narration. For each CANDIDATE "
        "term below, decide what kind of story element it is, using ONLY the PASSAGE as "
        "evidence.\n\n"
        f"Allowed kinds: {kinds}. If a candidate does not genuinely appear in the "
        f"passage, or you cannot tell, use {UNKNOWN}. Do NOT invent terms that are not "
        "in the candidate list. Do NOT guess facts not present in the passage.\n\n"
        "Answer with ONLY a JSON array, one object per candidate, each: "
        '{"term": <candidate>, "kind": <kind>, "confidence": <0.0-1.0>}.\n\n'
        f"PASSAGE:\n{window.text}\n\nCANDIDATES:\n{listed}\n"
    )


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def _extract_json_array(response: str) -> list:
    # tolerant: accept a bare array, or one wrapped in prose / ```json fences. anything
    # that does not yield a JSON list is fail-closed.
    fenced = _JSON_FENCE.search(response)
    text = fenced.group(1) if fenced else response
    match = _JSON_ARRAY.search(text)
    if not match:
        raise ExtractionError("no JSON array in model response")
    try:
        # the regex guarantees a [...] match, so a successful parse is always a list.
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ExtractionError(f"model response was not valid JSON: {e}") from e


def parse_nodes(response: str, window: Window, backend: str) -> list[Node]:
    # turn the model's JSON array into typed Nodes, attaching this window's provenance.
    # a row missing a term is skipped; an unknown kind degrades to UNKNOWN; confidence
    # is clamped to [0, 1]. neal types only what the model returned -- no fabrication.
    provenance = {
        "document": window.document,
        "window": window.index,
        "start": window.start,
        "end": window.end,
    }
    nodes: list[Node] = []
    for row in _extract_json_array(response):
        if not isinstance(row, dict):
            continue
        term = str(row.get("term", "")).strip()
        if not term:
            continue
        kind = row.get("kind", UNKNOWN)
        if kind not in NODE_KINDS:
            kind = UNKNOWN
        try:
            confidence = float(row.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        nodes.append(
            Node(
                term=term,
                kind=kind,
                confidence=confidence,
                backend=backend,
                provenance=dict(provenance),
            )
        )
    return nodes


def extract_window(
    window: Window,
    candidates: list[str],
    model: ModelClient,
    *,
    backend: str = DEFAULT_MODEL,
) -> list[Node]:
    # type a single window's candidates. no candidates -> no model call, no nodes.
    if not candidates:
        return []
    response = model.complete(build_prompt(window, candidates))
    return parse_nodes(response, window, backend)


def _candidate_terms(bento: Bento) -> list[str]:
    # the terms the prepass surfaced for this bento.
    path = bento.graph / "candidates.jsonl"
    if not path.is_file():
        raise ExtractionError("no candidates.jsonl -- run the prepass first")
    terms = []
    for line in path.read_text().splitlines():
        if line.strip():
            terms.append(json.loads(line)["term"])
    return terms


def run_extraction(
    bento: Bento,
    model: ModelClient,
    *,
    backend: str = DEFAULT_MODEL,
    max_words: int = 400,
    overlap: int = 40,
) -> Path:
    # type every window's candidates across the bento and write the (unmerged) graph
    # nodes. records an `extract` manifest stage. returns the nodes path.
    terms = _candidate_terms(bento)
    nodes: list[Node] = []
    windows = 0
    calls = 0
    for window in bento_windows(bento, max_words=max_words, overlap=overlap):
        windows += 1
        present = candidates_in_window(window, terms)
        if not present:
            continue
        calls += 1
        nodes.extend(extract_window(window, present, model, backend=backend))

    out = bento.graph / "nodes.jsonl"
    with out.open("w") as fh:
        for node in nodes:
            fh.write(json.dumps(node.to_dict(), sort_keys=True) + "\n")

    record_stage(
        bento,
        "extract",
        {
            "backend": backend,
            "windows": windows,
            "model_calls": calls,
            "nodes": len(nodes),
            "output": str(out.relative_to(bento.root)),
        },
    )
    return out
