"""Locate a literal Rust mutation marker across formatting-only changes.

This helper only chooses the bytes to mutate. The unchanged protected-source
verifier still decides whether deleting or replacing those bytes is rejected.
Quoted literals remain whole tokens; whitespace inside them is significant.
"""
import re


_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]')


def _tokens(source, start=0, end=None):
    raw = [(match.group(), match.start(), match.end())
           for match in _TOKEN.finditer(source, start, len(source) if end is None else end)]
    return [token for index, token in enumerate(raw)
            if not (token[0] == "," and
                    (index + 1 == len(raw) or raw[index + 1][0] in (")", "}", "]")))]


def source_marker_span(source, marker, start=0, end=None):
    """Return exact source offsets, or fail if the marker's tokens are absent."""
    limit = len(source) if end is None else end
    exact = source.find(marker, start, limit)
    if exact >= 0:
        return exact, exact + len(marker)
    expected = [token[0] for token in _tokens(marker)]
    if not expected:
        raise ValueError("empty Rust mutation marker")
    actual = _tokens(source, start, limit)
    width = len(expected)
    for index in range(len(actual) - width + 1):
        if [token[0] for token in actual[index:index + width]] == expected:
            return actual[index][1], actual[index + width - 1][2]
    raise ValueError(f"Rust mutation marker not found: {marker!r}")
