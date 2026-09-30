"""Conservative Rust identifier inventory, not a compiler/call-graph proof.

Comments and literals are ignored; qualified names and aliases retain the exact
source identifier. cfg expressions and macro bodies are deliberately retained:
removing them without the compiler's configuration can hide production callers.
"""
from __future__ import annotations

import re

_IDENTIFIER = re.compile(r"(?:r#)?([A-Za-z_][A-Za-z_0-9]*)")
_RAW_STRING = re.compile(r'(?:br|cr|r)(#*)"')


def rust_identifiers(source: str) -> set[str]:
    identifiers: set[str] = set()
    cursor = 0
    while cursor < len(source):
        if source.startswith("//", cursor):
            end = source.find("\n", cursor + 2)
            cursor = len(source) if end < 0 else end + 1
            continue
        if source.startswith("/*", cursor):
            depth = 1
            cursor += 2
            while cursor < len(source) and depth:
                if source.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif source.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            continue
        raw = _RAW_STRING.match(source, cursor)
        if raw:
            terminator = '"' + raw.group(1)
            end = source.find(terminator, raw.end())
            cursor = len(source) if end < 0 else end + len(terminator)
            continue
        if source[cursor] == '"':
            cursor += 1
            while cursor < len(source):
                if source[cursor] == "\\":
                    cursor += 2
                elif source[cursor] == '"':
                    cursor += 1
                    break
                else:
                    cursor += 1
            continue
        # A lifetime is not a character literal. Match only a closed character
        # (including escaped and unicode forms); never skip an arbitrary span.
        if source[cursor] == "'":
            char = re.match(r"'(?:\\u\{[0-9a-fA-F_]+\}|\\x[0-9a-fA-F]{2}|\\.|[^'\\\n])'", source[cursor:])
            if char:
                cursor += char.end()
                continue
        identifier = _IDENTIFIER.match(source, cursor)
        if identifier:
            identifiers.add(identifier.group(1))
            cursor = identifier.end()
        else:
            cursor += 1
    return identifiers


def contains_rust_identifier(source: str, symbol: str) -> bool:
    return symbol in rust_identifiers(source)
