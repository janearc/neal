from dataclasses import dataclass

import pytest

from neal.cli import main


@dataclass
class FakeProfile:
    rare_terms: list


def _fake_profiler(*, text, title):
    return FakeProfile(rare_terms=[w.strip(".,") for w in text.split() if w[:1].isupper()])


@pytest.fixture(autouse=True)
def home_and_profiler(tmp_path, monkeypatch):
    # every CLI test runs against a temp NEAL_HOME with the prepass profiler faked.
    monkeypatch.setenv("NEAL_HOME", str(tmp_path))
    monkeypatch.setattr("neal.prepass._default_profiler", lambda: _fake_profiler)
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
