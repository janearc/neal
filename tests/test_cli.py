import json
import re
from dataclasses import dataclass

import pytest

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
        return json.dumps(
            [{"term": t, "kind": "character", "confidence": 0.9} for t in terms]
        )


@pytest.fixture(autouse=True)
def home_and_fakes(tmp_path, monkeypatch):
    # every CLI test runs against a temp NEAL_HOME with the prepass profiler and the
    # model both faked -- no spacy, no mesh.
    monkeypatch.setenv("NEAL_HOME", str(tmp_path))
    monkeypatch.setattr("neal.prepass._default_profiler", lambda: _fake_profiler)
    monkeypatch.setattr("neal.cli._model", lambda: _TypingModel())
    return tmp_path


def test_run_from_explicit_source(tmp_path, capsys):
    src = tmp_path / "session.md"
    src.write_text("Mara walked to Riverton.")

    rc = main(["run", str(src)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "bento " in out and "candidate term(s)" in out
    # the candidates artifact exists under the (single) bento
    from neal.bento import list_bentos

    (bento,) = list_bentos()
    candidates = (bento.graph / "candidates.jsonl").read_text()
    assert "Riverton" in candidates
    assert bento.read_manifest()["stages"]["prepass"]["backend"] == "wonderlib-prepass"


def test_run_from_inbox(tmp_path, capsys):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "drop.md").write_text("Tomas whittled.")

    assert main(["run"]) == 0

    from neal.bento import list_bentos

    (bento,) = list_bentos()
    assert "Tomas" in (bento.graph / "candidates.jsonl").read_text()
    assert (tmp_path / "inbox" / "drop.md").exists()  # inbox left intact


def test_ingest_then_prepass_latest(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text("Abe met Zed.")

    assert main(["ingest", str(src)]) == 0
    assert main(["prepass"]) == 0  # default: most recent bento

    out = capsys.readouterr().out
    assert "prepass" in out


def test_ls_lists_bentos(tmp_path, capsys):
    src = tmp_path / "x.md"
    src.write_text("Quill.")
    main(["ingest", str(src)])
    capsys.readouterr()  # drop the ingest line

    assert main(["ls"]) == 0

    out = capsys.readouterr().out
    assert "files=1" in out
    assert "stages=-" in out  # ingested but not yet prepassed


def test_ls_empty(capsys):
    assert main(["ls"]) == 0
    assert capsys.readouterr().out.strip() == "no bentos yet"


def test_prepass_no_bentos_errors(capsys):
    rc = main(["prepass"])

    assert rc == 1
    assert "no bentos yet" in capsys.readouterr().err


def test_build_end_to_end(tmp_path, capsys):
    src = tmp_path / "session.md"
    src.write_text("Mara walked to Riverton.")

    assert main(["build", str(src)]) == 0

    from neal.bento import list_bentos

    (bento,) = list_bentos()
    stages = bento.read_manifest()["stages"]
    assert set(stages) >= {"prepass", "extract", "merge"}
    entities = [
        json.loads(line)
        for line in (bento.graph / "nodes.jsonl").read_text().splitlines()
    ]
    labels = {e["label"] for e in entities}
    assert {"Mara", "Riverton"} <= labels
    assert all(e["kind"] == "character" for e in entities)  # the fake types everything so
    assert (bento.graph / "open_puzzles.jsonl").exists()


def test_build_from_inbox(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "drop.md").write_text("Tomas met Mara.")

    assert main(["build"]) == 0

    from neal.bento import list_bentos

    (bento,) = list_bentos()
    assert bento.read_manifest()["stages"]["merge"]["entities"] >= 1


def test_extract_before_prepass_errors_cleanly(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text("Mara.")
    main(["ingest", str(src)])
    capsys.readouterr()

    rc = main(["extract"])  # no prepass yet

    assert rc == 1
    assert "candidates" in capsys.readouterr().err  # clean message, not a traceback


def test_merge_before_extract_errors_cleanly(tmp_path, capsys):
    src = tmp_path / "s.md"
    src.write_text("Mara.")
    main(["ingest", str(src)])
    main(["prepass"])
    capsys.readouterr()

    rc = main(["merge"])  # no extraction yet

    assert rc == 1
    assert "extraction" in capsys.readouterr().err
