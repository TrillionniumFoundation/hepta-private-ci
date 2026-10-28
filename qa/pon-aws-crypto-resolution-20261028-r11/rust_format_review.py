"""Static token comparison for the retained hosted Rust-format delta.

This is a narrowly scoped lexer/import comparison, not a Rust parser or a proof
of program equivalence. Native compilation remains independently required.
"""

import re


TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<line>//[^\n]*)|(?P<block>/\*.*?\*/)|"
    r'(?P<string>b?"(?:\\.|[^"\\])*")|'
    r"(?P<char>b?'(?:\\.|[^'\\])')|"
    r"(?P<word>[A-Za-z_][A-Za-z_0-9]*|[0-9][A-Za-z_0-9]*)|(?P<punct>.)",
    re.S,
)


def tokens(text):
    result = []
    cursor = 0
    while cursor < len(text):
        raw = re.match(r'(?:br|r)(#+)?"', text[cursor:])
        if raw:
            end_marker = '"' + (raw.group(1) or "")
            end = text.find(end_marker, cursor + raw.end())
            if end < 0:
                raise ValueError("unterminated raw string")
            end += len(end_marker)
            result.append(text[cursor:end])
            cursor = end
            continue
        match = TOKEN.match(text, cursor)
        if match is None:
            raise ValueError("unrecognized token")
        cursor = match.end()
        if match.lastgroup == "space":
            continue
        value = match.group()
        if match.lastgroup in {"line", "block"}:
            # Formatting may wrap a comment; its non-whitespace words remain.
            value = " ".join(value.split())
        result.append(value)
    return result


def split_top(values):
    pieces, current, depth = [], [], 0
    for value in values:
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
        if value == "," and depth == 0:
            if current:
                pieces.append(current)
            current = []
        else:
            current.append(value)
    if depth:
        raise ValueError("unbalanced use tree")
    if current:
        pieces.append(current)
    return pieces


def expand_use(values, prefix=()):
    if "{" not in values:
        values = tuple(values)
        if values and values[0] == "self":
            return [prefix[:-2] + values[1:]]
        return [prefix + values]
    opening = values.index("{")
    if values[-1] != "}":
        raise ValueError("unsupported use tree suffix")
    nested_prefix = prefix + tuple(values[:opening])
    result = []
    for part in split_top(values[opening + 1 : -1]):
        result.extend(expand_use(part, nested_prefix))
    return result


def normalized(text):
    raw = tokens(text)
    result, cursor = [], 0
    while cursor < len(raw):
        start, prefix = cursor, []
        while raw[cursor : cursor + 2] == ["#", "["]:
            depth, end = 1, cursor + 2
            while end < len(raw) and depth:
                depth += (raw[end] == "[") - (raw[end] == "]")
                end += 1
            if depth:
                raise ValueError("unterminated attribute")
            prefix.extend(raw[cursor:end])
            cursor = end
        if cursor < len(raw) and raw[cursor] == "pub":
            prefix.append(raw[cursor])
            cursor += 1
            if cursor < len(raw) and raw[cursor] == "(":
                end = raw.index(")", cursor) + 1
                prefix.extend(raw[cursor:end])
                cursor = end
        if cursor < len(raw) and raw[cursor] == "use":
            end = raw.index(";", cursor)
            result.extend(
                ("use", tuple(prefix), path)
                for path in expand_use(raw[cursor + 1 : end])
            )
            cursor = end + 1
        else:
            result.append(("token", raw[start]))
            cursor = start + 1
    ordered, pending = [], []
    for node in result + [("end",)]:
        if node[0] == "use":
            pending.append(node)
        else:
            ordered.extend(sorted(pending))
            pending = []
            ordered.append(node)
    return ordered


def compare(before, after):
    return normalized(before.decode()) == normalized(after.decode())
