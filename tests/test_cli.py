import json
import re
from dataclasses import dataclass

import pytest

from neal.bento import list_bentos
from neal.cli import main


@dataclass
class FakeProfile:
    rare_terms: list


def _fake_profiler(*, text, title):
    return FakeProfile(rare_terms=[w.strip(".,") for w in text.split() if w[:1].isupper()])


class _TypingModel:
    # a fake ModelClient: types every candidate the prompt lists as a character. lets
    # the CLI tests drive extract/build end-to-end without touching the mesh.
    def complete(self, prompt):
        terms = re.findall(r"^- (.+)$", prompt, re.MULTILINE)
        return json.dumps([{"term": t, "kind": "character", "confidence": 0.9} for t in terms])


@pytest.fixture(autouse=True)
def home_and_fakes(tmp_path, monkeypatch):
    # every CLI test runs against a temp NEAL_HOME with the prepass profiler and the
    # model both faked -- no spacy, no mesh.
    monkeypatch.setenv("NEAL_HOME", str(tmp_path))
    monkeypatch.setattr("neal.prepass._default_profiler", lambda: _fake_profiler)
    monkeypatch.setattr("neal.cli._model", lambda: _TypingModel())
    return tmp_path


def test_new_creates_an_empty_bento_with_its_own_inbox(capsys):
    assert main(["new"]) == 0

    out = capsys.readouterr().out
    assert "bento " in out and "drop files in:" in out
    (bento,) = list_bentos()
    assert bento.inbox.is_dir()
    assert bento.read_manifest()["parent"] is None


def test_new_with_sources_prefills(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text("Mara.")

    assert main(["new", str(src)]) == 0

    assert "pre-filled with 1 file" in capsys.readouterr().out
    (bento,) = list_bentos()
    assert (bento.raw_data / "s.md").exists()


def test_new_from_parent_records_lineage(capsys):
    main(["new"])
    (parent,) = list_bentos()
    capsys.readouterr()

    assert main(["new", "--from", parent.id]) == 0

    assert f"onto {parent.id}" in capsys.readouterr().out
    child = next(b for b in list_bentos() if b.id != parent.id)
    assert child.read_manifest()["parent"] == parent.id


def test_build_end_to_end_from_inbox(capsys):
    main(["new"])
    (bento,) = list_bentos()
    (bento.inbox / "session.md").write_text("Mara walked to Riverton.")
    capsys.readouterr()

    assert main(["build", bento.id]) == 0

    stages = bento.read_manifest()["stages"]
    assert set(stages) >= {"prepass", "extract", "merge"}
    entities = [
        json.loads(line)
        for line in (bento.graph / "nodes.jsonl").read_text().splitlines()
    ]
    assert {"Mara", "Riverton"} <= {e["label"] for e in entities}
    assert (bento.graph / "open_puzzles.jsonl").exists()


def test_build_defaults_to_latest(capsys):
    main(["new"])
    (bento,) = list_bentos()
    (bento.inbox / "n.md").write_text("Tomas met Mara.")
    capsys.readouterr()

    assert main(["build"]) == 0  # no id -> most recent

    assert bento.read_manifest()["stages"]["merge"]["entities"] >= 1


def test_ls_shows_lineage(capsys):
    main(["new"])
    (parent,) = list_bentos()
    main(["new", "--from", parent.id])
    capsys.readouterr()

    assert main(["ls"]) == 0

    out = capsys.readouterr().out
    assert f"<- {parent.id}" in out


def test_ls_empty(capsys):
    assert main(["ls"]) == 0
    assert capsys.readouterr().out.strip() == "no bentos yet"


def test_extract_before_prepass_errors_cleanly(capsys):
    main(["new"])
    (bento,) = list_bentos()
    (bento.inbox / "s.md").write_text("Mara.")
    capsys.readouterr()

    rc = main(["extract", bento.id])  # no prepass/ingest yet

    assert rc == 1
    assert "candidates" in capsys.readouterr().err


def test_merge_before_extract_errors_cleanly(capsys):
    main(["new"])
    (bento,) = list_bentos()
    capsys.readouterr()

    rc = main(["merge", bento.id])  # no extraction yet

    assert rc == 1
    assert "extraction" in capsys.readouterr().err


def test_new_from_missing_parent_errors(capsys):
    rc = main(["new", "--from", "nonexistent"])

    assert rc == 1
    assert "no bento" in capsys.readouterr().err.lower()
