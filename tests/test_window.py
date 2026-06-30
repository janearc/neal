import pytest

from neal.bento import create_bento, ingest
from neal.window import bento_windows, iter_windows


def _numbered(n):
    # "w0 w1 ... w{n-1}" -- word i is literally "w{i}", so offsets are checkable.
    return " ".join(f"w{i}" for i in range(n))


def test_empty_text_yields_nothing():
    assert list(iter_windows("", "d.md")) == []
    assert list(iter_windows("   \n  ", "d.md")) == []


def test_short_text_is_one_window_covering_all():
    (w,) = list(iter_windows("a b c", "d.md", max_words=400))
    assert (w.document, w.index, w.start, w.end, w.text) == ("d.md", 0, 0, 3, "a b c")


def test_long_text_windows_overlap_and_reach_the_end():
    windows = list(iter_windows(_numbered(1000), "d.md", max_words=400, overlap=40))

    assert [w.index for w in windows] == [0, 1, 2]
    assert [(w.start, w.end) for w in windows] == [(0, 400), (360, 760), (720, 1000)]
    # each window holds at most max_words
    assert all(len(w.text.split()) <= 400 for w in windows)
    # consecutive windows overlap by exactly `overlap` words
    assert windows[0].end - windows[1].start == 40
    assert windows[1].end - windows[2].start == 40
    # the span is fully covered, first word to last
    assert windows[0].text.startswith("w0 ")
    assert windows[-1].text.endswith(" w999")


def test_no_overlap_tiles_exactly():
    windows = list(iter_windows(_numbered(10), "d.md", max_words=5, overlap=0))
    assert [(w.start, w.end) for w in windows] == [(0, 5), (5, 10)]


def test_validation():
    with pytest.raises(ValueError, match="max_words must be positive"):
        list(iter_windows("a b", "d.md", max_words=0))
    with pytest.raises(ValueError, match="overlap"):
        list(iter_windows("a b", "d.md", max_words=5, overlap=5))
    with pytest.raises(ValueError, match="overlap"):
        list(iter_windows("a b", "d.md", max_words=5, overlap=-1))


def test_bento_windows_spans_raw_data_in_order(tmp_path):
    b = create_bento(tmp_path)
    (tmp_path / "a.md").write_text(_numbered(3))
    (tmp_path / "b.md").write_text(_numbered(2))
    ingest(b, [tmp_path / "a.md", tmp_path / "b.md"])

    windows = list(bento_windows(b, max_words=400))

    assert [(w.document, w.index) for w in windows] == [("a.md", 0), ("b.md", 0)]
