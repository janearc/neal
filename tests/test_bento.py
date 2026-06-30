import pytest

from neal.bento import (
    create_bento,
    ingest,
    ingest_inbox,
    list_bentos,
    neal_home,
    parent_of,
    record_stage,
    resolve_bento,
)


def test_create_bento_lays_out_the_tree(tmp_path):
    b = create_bento(tmp_path)
    assert b.raw_data.is_dir()
    assert b.graph.is_dir() and b.cards.is_dir() and b.render.is_dir()
    assert b.manifest_path.is_file()
    m = b.read_manifest()
    assert m["bento_id"] == b.id
    assert m["raw_data"] == {"files": [], "count": 0}
    assert m["stages"] == {}


def test_ingest_copies_never_moves(tmp_path):
    src = tmp_path / "session1.md"
    src.write_text("# narration\n\nhe walked.")
    b = create_bento(tmp_path)

    copied = ingest(b, [src])

    assert copied == ["session1.md"]
    assert src.exists()  # source is left in place
    assert (b.raw_data / "session1.md").read_text() == src.read_text()
    m = b.read_manifest()
    assert m["raw_data"]["count"] == 1
    assert "session1.md" in m["raw_data"]["files"]


def test_ingest_walks_directories_and_filters_suffix(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (corpus / "a.md").write_text("alpha")
    (corpus / "sub" / "b.txt").write_text("beta")
    (corpus / "skip.bin").write_text("nope")
    b = create_bento(tmp_path)

    copied = ingest(b, [corpus])

    assert set(copied) == {"a.md", "b.txt"}


def test_ingest_is_idempotent_on_manifest(tmp_path):
    src = tmp_path / "s.md"
    src.write_text("same bytes")
    b = create_bento(tmp_path)

    ingest(b, [src])
    ingest(b, [src])  # identical name + bytes -> no duplicate manifest entry

    m = b.read_manifest()
    assert m["raw_data"]["files"].count("s.md") == 1
    assert m["raw_data"]["count"] == 1


def test_name_collision_between_distinct_sources_is_not_clobbered(tmp_path):
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "dup.md").write_text("first")
    (d2 / "dup.md").write_text("second")
    b = create_bento(tmp_path)

    ingest(b, [d1 / "dup.md"])
    ingest(b, [d2 / "dup.md"])

    contents = sorted(p.read_text() for p in b.raw_data.glob("*.md"))
    assert contents == ["first", "second"]


def test_neal_home_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("NEAL_HOME", str(tmp_path / "home"))
    assert neal_home() == tmp_path / "home"


def test_create_bento_has_its_own_inbox(tmp_path):
    b = create_bento(tmp_path)
    assert b.inbox.is_dir()
    assert b.inbox == b.root / "inbox"


def test_ingest_inbox_snapshots_the_bentos_own_inbox(tmp_path):
    b = create_bento(tmp_path)
    (b.inbox / "drop.md").write_text("dropped narration")

    copied = ingest_inbox(b)

    assert copied == ["drop.md"]
    assert (b.raw_data / "drop.md").read_text() == "dropped narration"
    assert (b.inbox / "drop.md").exists()  # inbox file left in place


def test_create_bento_records_and_validates_parent(tmp_path):
    first = create_bento(tmp_path, bento_id="parent-1")
    child = create_bento(tmp_path, bento_id="child-1", parent=first.id)

    assert child.read_manifest()["parent"] == "parent-1"
    assert parent_of(child) == "parent-1"
    assert parent_of(first) is None

    with pytest.raises(LookupError, match="does not exist"):
        create_bento(tmp_path, parent="nope")


def test_record_stage(tmp_path):
    b = create_bento(tmp_path)

    record_stage(b, "prepass", {"backend": "x", "documents": 2})

    stage = b.read_manifest()["stages"]["prepass"]
    assert stage["backend"] == "x"
    assert stage["documents"] == 2
    assert "ran_at" in stage


def test_list_bentos_empty_then_ordered(tmp_path):
    assert list_bentos(tmp_path) == []
    first = create_bento(tmp_path, bento_id="aaaa-1")
    second = create_bento(tmp_path, bento_id="bbbb-2")

    listed = list_bentos(tmp_path)

    assert [b.id for b in listed] == [first.id, second.id]  # oldest first by created


def test_resolve_bento_latest_and_exact(tmp_path):
    create_bento(tmp_path, bento_id="old")
    newest = create_bento(tmp_path, bento_id="new")

    assert resolve_bento(None, tmp_path).id == newest.id
    assert resolve_bento("latest", tmp_path).id == newest.id
    assert resolve_bento("old", tmp_path).id == "old"


def test_resolve_bento_unique_prefix(tmp_path):
    create_bento(tmp_path, bento_id="abc-123")

    assert resolve_bento("abc", tmp_path).id == "abc-123"


def test_resolve_bento_errors(tmp_path):
    with pytest.raises(LookupError, match="no bentos yet"):
        resolve_bento(None, tmp_path)

    create_bento(tmp_path, bento_id="dup-1")
    create_bento(tmp_path, bento_id="dup-2")
    with pytest.raises(LookupError, match="no bento matching"):
        resolve_bento("zzz", tmp_path)
    with pytest.raises(LookupError, match="ambiguous"):
        resolve_bento("dup", tmp_path)
