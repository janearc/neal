import json

import pytest

from neal.bento import create_bento, ingest
from neal.extract import (
    ExtractionError,
    Node,
    build_prompt,
    candidates_in_window,
    extract_window,
    parse_nodes,
    run_extraction,
)
from neal.window import iter_windows


def _window(text, document="d.md"):
    (w,) = list(iter_windows(text, document, max_words=400))
    return w


class _CannedModel:
    # a ModelClient that returns a fixed response and records the prompt it saw.
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.response


def test_candidates_in_window_keeps_only_present_terms():
    w = _window("Mara walked to Riverton.")
    assert candidates_in_window(w, ["Mara", "Riverton", "Tomas"]) == ["Mara", "Riverton"]


def test_build_prompt_lists_candidates_and_forbids_invention():
    w = _window("Mara walked to Riverton.")
    prompt = build_prompt(w, ["Mara", "Riverton"])
    assert "Mara" in prompt and "Riverton" in prompt
    assert w.text in prompt
    assert "invent" in prompt.lower()


def test_parse_nodes_types_with_provenance_and_clamps_confidence():
    w = _window("Mara walked to Riverton.")
    response = json.dumps(
        [
            {"term": "Mara", "kind": "character", "confidence": 1.7},
            {"term": "Riverton", "kind": "place", "confidence": 0.8},
            {"term": "Glap", "kind": "nonsense-kind", "confidence": 0.5},
        ]
    )

    nodes = parse_nodes(response, w, backend="mistral")

    by_term = {n.term: n for n in nodes}
    assert by_term["Mara"].kind == "character"
    assert by_term["Mara"].confidence == 1.0  # clamped from 1.7
    assert by_term["Riverton"].kind == "place"
    assert by_term["Glap"].kind == "UNKNOWN"  # unknown kind degrades
    assert all(n.backend == "mistral" for n in nodes)
    assert by_term["Mara"].provenance == {
        "document": "d.md",
        "window": 0,
        "start": 0,
        "end": 4,
    }


def test_parse_nodes_tolerates_fenced_json_and_skips_bad_rows():
    w = _window("Mara.")
    response = (
        "Sure! Here is the labeling:\n```json\n"
        '[{"term": "Mara", "kind": "character", "confidence": 0.9}, '
        '{"no_term": true}, "garbage"]\n```\nHope that helps.'
    )

    nodes = parse_nodes(response, w, backend="m")

    assert [n.term for n in nodes] == ["Mara"]  # the rows without a term are skipped


def test_parse_nodes_fail_closed_on_unparseable():
    w = _window("Mara.")
    with pytest.raises(ExtractionError):
        parse_nodes("I refuse to answer in JSON.", w, backend="m")
    with pytest.raises(ExtractionError):
        parse_nodes("[not, valid, json]", w, backend="m")


def test_parse_nodes_bad_confidence_defaults_to_zero():
    w = _window("Mara.")
    response = json.dumps([{"term": "Mara", "kind": "character", "confidence": "high"}])

    (node,) = parse_nodes(response, w, backend="m")

    assert node.confidence == 0.0


def test_extract_window_no_candidates_makes_no_call():
    w = _window("Mara walked.")
    model = _CannedModel("[]")

    assert extract_window(w, [], model) == []
    assert model.prompts == []  # short-circuited, the model was never asked


def test_extract_window_round_trip():
    w = _window("Mara walked to Riverton.")
    model = _CannedModel(json.dumps([{"term": "Mara", "kind": "character", "confidence": 0.9}]))

    nodes = extract_window(w, ["Mara"], model, backend="mistral")

    assert nodes == [
        Node(
            term="Mara",
            kind="character",
            confidence=0.9,
            backend="mistral",
            provenance={"document": "d.md", "window": 0, "start": 0, "end": 4},
        )
    ]


def test_run_extraction_requires_prepass(tmp_path):
    b = create_bento(tmp_path)
    with pytest.raises(ExtractionError, match="run the prepass first"):
        run_extraction(b, _CannedModel("[]"))


def test_run_extraction_writes_nodes_and_records_stage(tmp_path):
    b = create_bento(tmp_path)
    (tmp_path / "s.md").write_text("Mara walked to Riverton with Tomas.")
    ingest(b, [tmp_path / "s.md"])
    # stand in for the prepass output
    (b.graph / "candidates.jsonl").write_text(
        "\n".join(
            json.dumps({"term": t, "kind": "UNKNOWN"}) for t in ("Mara", "Riverton", "Tomas")
        )
    )
    model = _CannedModel(
        json.dumps(
            [
                {"term": "Mara", "kind": "character", "confidence": 0.9},
                {"term": "Riverton", "kind": "place", "confidence": 0.8},
                {"term": "Tomas", "kind": "character", "confidence": 0.7},
            ]
        )
    )

    out = run_extraction(b, model, backend="mistral")

    assert out == b.graph / "nodes.jsonl"
    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert {r["term"] for r in records} == {"Mara", "Riverton", "Tomas"}
    assert all(r["backend"] == "mistral" for r in records)
    stage = b.read_manifest()["stages"]["extract"]
    assert stage["nodes"] == 3
    assert stage["model_calls"] >= 1
    assert stage["output"] == "outputs/graph/nodes.jsonl"


def test_run_extraction_skips_windows_with_no_candidates(tmp_path):
    b = create_bento(tmp_path)
    (tmp_path / "s.md").write_text("nothing of interest happens in this passage at all")
    ingest(b, [tmp_path / "s.md"])
    (b.graph / "candidates.jsonl").write_text(json.dumps({"term": "Riverton", "kind": "UNKNOWN"}))
    model = _CannedModel("[]")

    run_extraction(b, model)

    assert model.prompts == []  # the one window held no candidate, so no model call
    stage = b.read_manifest()["stages"]["extract"]
    assert stage["windows"] == 1
    assert stage["model_calls"] == 0
    assert stage["nodes"] == 0
