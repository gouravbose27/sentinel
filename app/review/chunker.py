import difflib

CONTEXT_LINES = 3


def diff_hunks(base: str, head: str, context: int = CONTEXT_LINES) -> list[str]:
    """Render changes as text hunks whose gutter carries new-file line numbers.

    Format per line: 5-char new line number, marker ('+' added, '-' removed, ' ' context), code.
    Removed lines have a blank line number.
    """
    a, b = base.splitlines(), head.splitlines()
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    hunks: list[str] = []
    for group in matcher.get_grouped_opcodes(context):
        lines: list[str] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines.extend(f"{k + 1:>5}   {b[k]}" for k in range(j1, j2))
                continue
            if tag in ("replace", "delete"):
                lines.extend(f"      - {a[k]}" for k in range(i1, i2))
            if tag in ("replace", "insert"):
                lines.extend(f"{k + 1:>5} + {b[k]}" for k in range(j1, j2))
        hunks.append("\n".join(lines))
    return hunks


def chunk_hunks(hunks: list[str], max_chars: int) -> list[str]:
    """Pack hunks into chunks no larger than max_chars, splitting oversized hunks by line."""
    pieces: list[str] = []
    for hunk in hunks:
        if len(hunk) <= max_chars:
            pieces.append(hunk)
            continue
        current: list[str] = []
        size = 0
        for line in hunk.splitlines():
            if current and size + len(line) + 1 > max_chars:
                pieces.append("\n".join(current))
                current, size = [], 0
            current.append(line)
            size += len(line) + 1
        if current:
            pieces.append("\n".join(current))

    chunks: list[str] = []
    buffer: list[str] = []
    size = 0
    for piece in pieces:
        if buffer and size + len(piece) + 5 > max_chars:
            chunks.append("\n ...\n".join(buffer))
            buffer, size = [], 0
        buffer.append(piece)
        size += len(piece) + 5
    if buffer:
        chunks.append("\n ...\n".join(buffer))
    return chunks


def build_chunks(base: str, head: str, max_chars: int) -> list[str]:
    return chunk_hunks(diff_hunks(base, head), max_chars)
