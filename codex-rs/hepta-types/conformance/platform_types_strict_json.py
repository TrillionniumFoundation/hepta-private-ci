"""Shared bounded strict-JSON admission for independent protocol oracles."""

import json
import re
from typing import Any

MAX_RAW_BYTES = 65536
MAX_RAW_DEPTH = 16
TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
UNSIGNED_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)")


def no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def raw_depth(value: str) -> int:
    depth = maximum = 0
    quoted = escaped = False
    for character in value:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            maximum = max(maximum, depth)
        elif character in "]}":
            depth -= 1
    return maximum


def reject_non_json_constant(value: str) -> Any:
    raise ValueError("invalid_json")


def parse_strict_json(raw: str) -> Any:
    if type(raw) is not str or len(raw) > MAX_RAW_BYTES or len(raw.encode()) > MAX_RAW_BYTES:
        raise ValueError("size_exceeded")
    if raw_depth(raw) > MAX_RAW_DEPTH:
        raise ValueError("depth_exceeded")
    return json.loads(raw, object_pairs_hook=no_duplicate_pairs, parse_constant=reject_non_json_constant)


def assert_unsigned_integer_tokens(raw: str) -> None:
    # Call after strict JSON syntax admission. Preserve the native u32 lexical
    # contract without changing the generic parser's admission of JSON floats.
    for match in TOKENS.finditer(raw):
        number = match.group(1)
        if number is not None and UNSIGNED_INTEGER.fullmatch(number) is None:
            raise ValueError("unsigned_integer_token")
