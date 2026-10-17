"""Shared bounded strict-JSON admission for independent protocol oracles."""

import json
import math
import re
from typing import Any

MAX_RAW_BYTES = 65536
MAX_RAW_DEPTH = 16
TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
UNSIGNED_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)")


class DuplicateKeyError(ValueError):
    pass


def no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError("duplicate_key")
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
    if type(raw) is not str or len(raw) > MAX_RAW_BYTES:
        raise ValueError("size_exceeded")
    try:
        encoded_bytes = len(raw.encode())
    except UnicodeEncodeError as error:
        raise ValueError("invalid_json") from error
    if encoded_bytes > MAX_RAW_BYTES:
        raise ValueError("size_exceeded")
    if raw_depth(raw) > MAX_RAW_DEPTH:
        raise ValueError("depth_exceeded")
    try:
        value = json.loads(raw, object_pairs_hook=no_duplicate_pairs, parse_constant=reject_non_json_constant)
    except DuplicateKeyError:
        raise
    except ValueError as error:
        raise ValueError("invalid_json") from error
    validate_scalars(value)
    return value


def validate_scalars(value: Any) -> None:
    if type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("invalid_json")
    elif type(value) is str:
        try:
            value.encode()
        except UnicodeEncodeError as error:
            raise ValueError("invalid_json") from error
    elif type(value) is list:
        for item in value:
            validate_scalars(item)
    elif type(value) is dict:
        for key, item in value.items():
            validate_scalars(key)
            validate_scalars(item)


def assert_unsigned_integer_tokens(raw: str) -> None:
    # Call after strict JSON syntax admission. Preserve the native u32 lexical
    # contract without changing the generic parser's admission of JSON floats.
    for match in TOKENS.finditer(raw):
        number = match.group(1)
        if number is not None and UNSIGNED_INTEGER.fullmatch(number) is None:
            raise ValueError("unsigned_integer_token")
