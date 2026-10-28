"""Structural Rust method ownership checks, without claiming compilation.

Qualified registrations name a direct method of a module-level impl. Macro
expansion, type resolution and active cfg selection remain compiler concerns.
Unsupported qualified forms fail closed instead of matching scattered names.
"""

import re


TOKEN = re.compile(
    r"\s+|//[^\n]*|/\*|(?:br|cr|r)\#*\"|(?:b|c)?\""
    r"|b?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\r\n])'"
    r"|(?:r\#)?[A-Za-z_][A-Za-z_0-9]*|::|->|=>|.",
    re.DOTALL,
)
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
PAIRS = {"{": "}", "(": ")", "[": "]", "<": ">"}


def rust_tokens(source: str) -> list[str]:
    """Exclude literals and nested comments while retaining Rust delimiters."""
    result = []
    position = 0
    while position < len(source):
        match = TOKEN.match(source, position)
        token = match.group()
        position = match.end()
        if token.isspace() or token.startswith("//"):
            continue
        if token == "/*":
            depth = 1
            while depth and position < len(source):
                if source.startswith("/*", position):
                    depth += 1
                    position += 2
                elif source.startswith("*/", position):
                    depth -= 1
                    position += 2
                else:
                    position += 1
            if depth:
                return []
            continue
        if token.endswith('"'):
            if "r" in token:
                ending = '"' + "#" * token.count("#")
                end = source.find(ending, position)
                if end < 0:
                    return []
                position = end + len(ending)
            else:
                while position < len(source) and source[position] != '"':
                    position += 2 if source[position] == "\\" else 1
                if position >= len(source):
                    return []
                position += 1
            result.append("literal")
        elif token.endswith("'") and len(token) > 1:
            result.append("literal")
        else:
            result.append(token.removeprefix("r#"))
    return result


def group_end(tokens: list[str], start: int) -> int:
    opening, closing = tokens[start], PAIRS[tokens[start]]
    depth = 1
    for index in range(start + 1, len(tokens)):
        depth += (tokens[index] == opening) - (tokens[index] == closing)
        if depth == 0:
            return index
    return len(tokens)


def item_body(tokens: list[str], start: int, end: int) -> int:
    index = start
    while index < end and tokens[index] not in {"{", ";", "}"}:
        if tokens[index] in {"(", "[", "<"}:
            index = group_end(tokens, index)
        index += 1
    return index if index < end and tokens[index] == "{" else end


def impl_owner(header: list[str]) -> str | None:
    """Read the implemented type, never a generic parameter or trait name."""
    index = group_end(header, 0) + 1 if header and header[0] == "<" else 0
    owner_start = index
    end = len(header)
    while index < end:
        token = header[index]
        if token == "where":
            end = index
            break
        if token == "for":
            owner_start = index + 1
        if token in {"<", "(", "["}:
            index = group_end(header, index)
        index += 1
    index = owner_start
    if index < end and header[index] == "::":
        index += 1
    owner = None
    while index < end:
        if not NAME.fullmatch(header[index]):
            return None
        owner = header[index]
        index += 1
        if index < end and header[index] == "<":
            index = group_end(header, index) + 1
        if index == end:
            return owner
        if index >= end or header[index] != "::":
            return None
        index += 1
    return None


def qualified_rust_method(source: str, symbol: str) -> bool:
    """Require a method definition directly inside the named type's impl."""
    requested = re.fullmatch(r"([A-Za-z_]\w*)::([A-Za-z_]\w*)", symbol, re.ASCII)
    if requested is None:
        return False
    owner, method = requested.groups()
    tokens = rust_tokens(source)
    brackets = []
    for token in tokens:
        if token in {"{", "(", "["}:
            brackets.append(PAIRS[token])
        elif token in {"}", ")", "]"}:
            if not brackets or brackets.pop() != token:
                return False
    if brackets:
        return False
    regions = [(0, len(tokens))]
    while regions:
        start, end = regions.pop()
        index = start
        while index < end:
            token = tokens[index]
            at_item = index == start or tokens[index - 1] in {
                ";",
                "}",
                "]",
                "unsafe",
                "default",
            }
            if (
                token == "mod"
                and index + 2 < end
                and NAME.fullmatch(tokens[index + 1])
                and tokens[index + 2] == "{"
            ):
                closing = group_end(tokens, index + 2)
                if closing < end:
                    regions.append((index + 3, closing))
                index = closing + 1
                continue
            if token == "impl" and at_item:
                body = item_body(tokens, index + 1, end)
                if body < end:
                    closing = group_end(tokens, body)
                    if closing < end and impl_owner(tokens[index + 1 : body]) == owner:
                        member = body + 1
                        while member < closing:
                            if tokens[member : member + 2] == ["fn", method]:
                                function_body = item_body(tokens, member + 2, closing)
                                if function_body < closing:
                                    return True
                            if tokens[member] in {"{", "(", "["}:
                                member = group_end(tokens, member)
                            member += 1
                    index = closing + 1
                    continue
            if token in {"{", "(", "["}:
                index = group_end(tokens, index)
            index += 1
    return False
