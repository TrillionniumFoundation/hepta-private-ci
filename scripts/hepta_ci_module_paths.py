"""Bounded lexical proof for top-level literal Rust module paths.

This is not a Rust parser. Unsupported or incomplete input remains opaque;
macro expansion, nested module resolution and cfg evaluation are never guessed.
"""

import re


RAW = re.compile(r'(br|cr|r)(#*)"')
IDENT = re.compile(r"(?:r#)?[^\W\d]\w*", re.UNICODE)
CHAR = re.compile(
    r"'(?:[^'\\\r\n]|\\(?:[nrt0\\'\"]|x[0-9a-fA-F]{2}|u\{[0-9a-fA-F_]+\}))'"
)
SPACE = re.compile(r"\s+")
BLOCK_MARKER = re.compile(r"/\*|\*/")
STRING = re.compile(r'"(?:\\.|[^"\\])*"', re.S)
NUMBER = re.compile(r"[0-9]+")
PUNCTUATION = set("()[]{}#!=:;,.<>+-*/%&|^?@$~")
CLOSING = {")": "(", "]": "[", "}": "{"}
MAX_BYTES = 1 << 20
MAX_DEPTH = 128
MAX_TOKENS = 131_072


def _tokens(text):
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("module scan byte bound")
    tokens, pairs, stack = [], {}, []
    position, size = 0, len(text)
    while position < size:
        start = position
        first = text[position]
        if first.isspace():
            position = SPACE.match(text, position).end()
            continue
        if first == "/" and text.startswith("//", position):
            end = text.find("\n", position)
            position = size if end < 0 else end + 1
            continue
        if first == "/" and text.startswith("/*", position):
            depth = 1
            position += 2
            while position < size and depth:
                marker = BLOCK_MARKER.search(text, position)
                if marker is None:
                    raise ValueError("unfinished module comment")
                if marker[0] == "/*":
                    depth += 1
                    if depth > MAX_DEPTH:
                        raise ValueError("module comment depth bound")
                else:
                    depth -= 1
                position = marker.end()
            if depth:
                raise ValueError("unfinished module comment")
            continue
        # Most source tokens are identifiers or punctuation. Dispatch by the
        # first character before trying literal parsers over entire crates.
        raw = RAW.match(text, position) if first in "rbc" else None
        if first in PUNCTUATION:
            position += 1
            kind = "punctuation"
        elif first in "0123456789":
            position = NUMBER.match(text, position).end()
            kind = "number"
        elif raw:
            if len(raw[2]) > 255:
                raise ValueError("unsupported raw string delimiter")
            end = text.find('"' + raw[2], raw.end())
            if end < 0:
                raise ValueError("unfinished raw string")
            position = end + 1 + len(raw[2])
            kind = "string" if raw[1] == "r" else "literal"
        elif first == '"' or first in "bc" and text[position + 1 : position + 2] == '"':
            prefix = first != '"'
            literal = STRING.match(text, position + int(prefix))
            if literal is None:
                raise ValueError("unfinished string")
            position = literal.end()
            kind = "literal" if prefix else "string"
        elif first == "'" or first == "b" and text[position + 1 : position + 2] == "'":
            offset = 1 if first == "b" else 0
            character = CHAR.match(text, position + offset)
            lifetime = IDENT.match(text, position + 1) if not offset else None
            if character:
                position = character.end()
                kind = "literal"
            elif lifetime:
                position = lifetime.end()
                kind = "lifetime"
            else:
                raise ValueError("unsupported character or lifetime")
        else:
            identifier = IDENT.match(text, position)
            if identifier:
                position = identifier.end()
                kind = "identifier"
            else:
                raise ValueError("unsupported module source token")
        value = text[start:position]
        if kind == "identifier":
            # Rust permits raw spellings for built-in attributes as well as
            # module names. They retain their normal attribute semantics.
            value = value.removeprefix("r#")
        index = len(tokens)
        tokens.append((kind, value, len(stack)))
        if len(tokens) > MAX_TOKENS:
            raise ValueError("module token bound")
        if kind == "punctuation" and value in "([{":
            stack.append((value, index))
            if len(stack) > MAX_DEPTH:
                raise ValueError("module delimiter depth bound")
        elif kind == "punctuation" and value in ")]}":
            if not stack or stack[-1][0] != CLOSING[value]:
                raise ValueError("mismatched module delimiter")
            _, opening = stack.pop()
            pairs[opening] = index
    if stack:
        raise ValueError("unfinished module delimiter")
    return tokens, pairs


def literal_module_paths(text: str) -> tuple[list[str], bool]:
    """Return literal spellings plus whether any module-path context is unknown."""
    # No module attribute can exist without its introducing token. Includes
    # and ordinary outlined modules retain their separate existing discovery.
    if "#" not in text or ("path" not in text and "mod" not in text):
        return [], False
    try:
        tokens, pairs = _tokens(text)
    except (ValueError, UnicodeError):
        return [], True
    attributes = {}
    for index, (_, value, _) in enumerate(tokens):
        if value != "#":
            continue
        opening = index + 1
        inner = opening < len(tokens) and tokens[opening][1] == "!"
        opening += int(inner)
        if opening in pairs and tokens[opening][1] == "[":
            end = pairs[opening]
            body = tokens[opening + 1 : end]
            attributes[index] = (end, body, inner)
    paths, opaque, seen = [], False, set()
    has_path = any(body and body[0][1] == "path" for _, body, _ in attributes.values())
    for start in sorted(attributes):
        if start in seen:
            continue
        group, cursor = [], start
        while cursor in attributes:
            seen.add(cursor)
            end, body, inner = attributes[cursor]
            group.append((body, inner))
            cursor = end + 1
        names = [body[0][1] if body else "" for body, _ in group]
        if "cfg_attr" in names and (
            has_path or any(token[1] == "path" for body, _ in group for token in body)
        ):
            opaque = True
        declaration = cursor
        if declaration < len(tokens) and tokens[declaration][1] == "pub":
            declaration += 1
            if declaration in pairs and tokens[declaration][1] == "(":
                declaration = pairs[declaration] + 1
        module = declaration < len(tokens) and tokens[declaration][1] == "mod"
        if module and any(
            body and not inner and body[0][1] not in {"cfg", "path", "allow"}
            for body, inner in group
        ):
            opaque = True
        if any(
            inner
            and body
            and body[0][1]
            not in {"cfg", "allow", "deny", "warn", "forbid", "doc", "recursion_limit"}
            for body, inner in group
        ):
            opaque = True
        for body, inner in group:
            if not body or body[0][1] != "path":
                continue
            if len(body) != 3 or body[1][1] != "=" or body[2][0] != "string":
                opaque = True
                continue
            paths.append(body[2][1])
            outlined = (
                module
                and declaration + 2 < len(tokens)
                and tokens[declaration + 1][0] == "identifier"
                and tokens[declaration + 2][1] == ";"
            )
            if inner or tokens[start][2] != 0 or not outlined:
                opaque = True
    return paths, opaque
