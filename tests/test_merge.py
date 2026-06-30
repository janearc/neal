import json

import pytest

from neal.bento import create_bento
from neal.merge import Entity, MergeError, merge_nodes, propose_merges, run_merge


def _node(term, kind, confidence, *, document="d.md", window=0, backend="mistral"):
    return {
        "term": term,
        "kind": kind,
        "confidence": confidence,
        "backend": backend,
        "provenance": {"document": document, "window": window, "start": 0, "end": 1},
    }


def test_merge_folds_co_mentions_and_aggregates_provenance():
    raw = [
        _node("Mara", "character", 0.9, window=0),
        _node("Mara", "character", 0.7, window=1),
        _node("mara", "character", 0.6, window=2),  # surface variant, same entity
    ]

    (entity,) = merge_nodes(raw)

    assert entity.label == "Mara"  # most common surface form
    assert entity.kind == "character"
    assert entity.aliases == ["Mara", "mara"]
    assert entity.support == 3
    assert entity.confidence == 0.9  # max over the chosen kind
    assert len(entity.provenance) == 3
    assert entity.id == "character:mara"
    assert entity.kind_alternatives == []


def test_merge_surfaces_kind_conflict_rather_than_hiding_it():
    raw = [
        _node("Riverton", "place", 0.8),
        _node("Riverton", "place", 0.7),
        _node("Riverton", "character", 0.9),  # one window mis-typed it
    ]

    (entity,) = merge_nodes(raw)

    assert entity.kind == "place"  # 0.8 + 0.7 > 0.9
    assert entity.kind_alternatives == ["character"]  # the disagreement is recorded


def test_merge_deprioritizes_unknown():
    raw = [
        _node("Tomas", "UNKNOWN", 0.95),
        _node("Tomas", "character", 0.5),
    ]

    (entity,) = merge_nodes(raw)

    assert entity.kind == "character"  # UNKNOWN only wins if nothing else does
    assert entity.kind_alternatives == ["UNKNOWN"]


def test_merge_rejects_already_merged_input():
    with pytest.raises(MergeError, match="expected raw extract output"):
        merge_nodes([{"label": "Mara", "kind": "character"}])  # Entity-shaped, no 'term'


def test_propose_merges_suggests_near_duplicates_same_kind_only():
    entities = [
        Entity("character:mara", "Mara", "character", ["Mara"], 0.9, 1, ["m"], [], []),
        Entity("character:mira", "Mira", "character", ["Mira"], 0.8, 1, ["m"], [], []),
        Entity("place:mara", "Mara", "place", ["Mara"], 0.7, 1, ["m"], [], []),
    ]

    puzzles = propose_merges(entities)

    # Mara/Mira (same kind, near) is surfaced; the cross-kind Mara/Mara pair is not.
    assert len(puzzles) == 1
    p = puzzles[0]
    assert p["kind"] == "open-puzzle"
    assert {p["a"], p["b"]} == {"character:mara", "character:mira"}
    assert "same character" in p["question"]
    assert 0 < p["similarity"] <= 1


def test_propose_merges_ignores_dissimilar():
    entities = [
        Entity("place:riverton", "Riverton", "place", ["Riverton"], 0.9, 1, ["m"], [], []),
        Entity("place:carthage", "Carthage", "place", ["Carthage"], 0.9, 1, ["m"], [], []),
    ]

    assert propose_merges(entities) == []


def test_run_merge_writes_canonical_graph_and_puzzles(tmp_path):
    b = create_bento(tmp_path)
    raw = [
        _node("Mara", "character", 0.9, window=0),
        _node("Mara", "character", 0.7, window=1),
        _node("Mira", "character", 0.8, window=2),  # near-duplicate -> open-puzzle
    ]
    (b.graph / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in raw))

    out = run_merge(b)

    assert out == b.graph / "nodes.jsonl"
    entities = [json.loads(line) for line in out.read_text().splitlines()]
    assert {e["label"] for e in entities} == {"Mara", "Mira"}

    puzzles = [
        json.loads(line)
        for line in (b.graph / "open_puzzles.jsonl").read_text().splitlines()
    ]
    assert len(puzzles) == 1 and puzzles[0]["kind"] == "open-puzzle"

    stage = b.read_manifest()["stages"]["merge"]
    assert stage["raw_nodes"] == 3
    assert stage["entities"] == 2
    assert stage["open_puzzles"] == 1

    # canon discipline: re-running on the now-merged file is refused, not silently wrong
    with pytest.raises(MergeError):
        run_merge(b)


def test_run_merge_requires_extraction(tmp_path):
    b = create_bento(tmp_path)
    with pytest.raises(MergeError, match="run extraction first"):
        run_merge(b)
