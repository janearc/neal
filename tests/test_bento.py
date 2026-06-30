from neal.bento import (
    create_bento,
    inbox,
    ingest,
    ingest_inbox,
    neal_home,
    record_stage,
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
    assert inbox() == tmp_path / "home" / "inbox"


def test_ingest_inbox_seeds_from_inbox_and_leaves_it(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "inbox").mkdir(parents=True)
    (home / "inbox" / "drop.md").write_text("dropped narration")
    monkeypatch.setenv("NEAL_HOME", str(home))

    b = ingest_inbox()

    assert (b.raw_data / "drop.md").read_text() == "dropped narration"
    assert (home / "inbox" / "drop.md").exists()  # inbox file untouched


def test_record_stage(tmp_path):
    b = create_bento(tmp_path)

    record_stage(b, "prepass", {"backend": "x", "documents": 2})

    stage = b.read_manifest()["stages"]["prepass"]
    assert stage["backend"] == "x"
    assert stage["documents"] == 2
    assert "ran_at" in stage
