from app.review.chunker import build_chunks, chunk_hunks, diff_hunks


def test_gutter_uses_new_file_line_numbers():
    base = "a\nb\nc\n"
    head = "a\nB\nc\nd\n"
    (hunk,) = diff_hunks(base, head)
    lines = hunk.splitlines()
    assert "      - b" in lines
    assert "    2 + B" in lines
    assert "    4 + d" in lines
    assert "    1   a" in lines


def test_identical_files_have_no_hunks():
    assert diff_hunks("x\n", "x\n") == []


def test_added_file_is_split_when_oversized():
    head = "\n".join(f"line {i}" for i in range(200))
    chunks = build_chunks("", head, max_chars=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)


def test_small_hunks_are_packed_together():
    chunks = chunk_hunks(["one", "two", "three"], max_chars=1000)
    assert len(chunks) == 1
