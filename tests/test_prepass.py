import json
from dataclasses import dataclass

import pytest

from neal.bento import create_bento, ingest
from neal.prepass import BACKEND, candidate_vocabulary, run_prepass


@dataclass
class FakeProfile:
    rare_terms: list


def fake_profiler(*, text, title):
    # a deterministic stand-in for wonderlib: "rare" == capitalized tokens.
    terms = [w.strip(".,") for w in text.split() if w[:1].isupper()]
    return FakeProfile(rare_terms=terms)


def test_candidate_vocabulary_aggregates_with_provenance():
    docs = [
        ("s1.md", "Mara walked to Riverton."),
        ("s2.md", "Mara paused."),
    ]

    cands = candidate_vocabulary(docs, profiler=fake_profiler)

    by_term = {c["term"]: c for c in cands}
    assert by_term["Mara"]["provenance"]["documents"] == ["s1.md", "s2.md"]
    assert by_term["Mara"]["provenance"]["count"] == 2
    assert by_term["Riverton"]["provenance"]["count"] == 1
    # canon discipline: nothing typed, everything attributed
    assert all(c["kind"] == "UNKNOWN" for c in cands)
    assert all(c["backend"] == BACKEND for c in cands)


def test_candidate_vocabulary_is_sorted_and_deduped():
    cands = candidate_vocabulary([("d.md", "Zed Zed Abe")], profiler=fake_profiler)

    terms = [c["term"] for c in cands]
    assert terms == sorted(terms)
    assert terms.count("Zed") == 1  # one record per distinct term


def test_provenance_documents_are_unique_within_a_doc():
    cands = candidate_vocabulary([("d.md", "Zed Zed")], profiler=fake_profiler)

    (zed,) = cands
    assert zed["provenance"]["documents"] == ["d.md"]
    assert zed["provenance"]["count"] == 1


def test_run_prepass_writes_candidates_and_records_stage(tmp_path):
    b = create_bento(tmp_path)
    (tmp_path / "n.md").write_text("Mara met Tomas.")
    ingest(b, [tmp_path / "n.md"])

    out = run_prepass(b, profiler=fake_profiler)

    assert out == b.graph / "candidates.jsonl"
    records = [json.loads(line) for line in out.read_text().splitlines()]
    terms = {r["term"] for r in records}
    assert {"Mara", "Tomas"} <= terms

    stage = b.read_manifest()["stages"]["prepass"]
    assert stage["documents"] == 1
    assert stage["candidate_terms"] == len(records)
    assert stage["backend"] == BACKEND
    assert stage["output"] == "outputs/graph/candidates.jsonl"


def _spacy_model_available() -> bool:
    try:
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _spacy_model_available(), reason="wonderlib/en_core_web_sm not installed"
)
def test_real_wonderlib_prepass_smoke(tmp_path):
    # end-to-end through the real wonderlib profiler when it's available.
    b = create_bento(tmp_path)
    (tmp_path / "r.md").write_text(
        "The phantasmagorical denouement bewildered Aurelio in Llanfairpwllgwyngyll."
    )
    ingest(b, [tmp_path / "r.md"])

    out = run_prepass(b)  # real wonderlib, no injected profiler

    # It ran and produced a well-formed artifact; the exact term set is wonderlib's.
    for line in out.read_text().splitlines():
        json.loads(line)
    assert b.read_manifest()["stages"]["prepass"]["backend"] == BACKEND
