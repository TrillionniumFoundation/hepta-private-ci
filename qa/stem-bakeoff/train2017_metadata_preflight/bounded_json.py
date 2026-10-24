"""Bounded top-level COCO JSON arrays; no extraction, networking, or selection."""

import codecs
import hashlib
import json
import math


class PreflightError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PreflightError(message)


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def finite_float(value):
    number = float(value)
    require(math.isfinite(number), "nonfinite JSON number")
    return number


def reject_constant(_value):
    raise PreflightError("nonfinite JSON constant")


def strict_json(raw):
    return json.loads(
        raw,
        object_pairs_hook=strict_pairs,
        parse_float=finite_float,
        parse_constant=reject_constant,
    )


class StreamJSON:
    """Emit object-array records while hashing every input byte through EOF.

    Only COCO's `info` object and named arrays are accepted. Row dictionaries
    remain bounded even for unknown nested fields such as segmentation.
    """

    def __init__(self, stream, byte_limit, buffer_limit=4 * 1024**2):
        self.stream, self.byte_limit, self.buffer_limit = (
            stream,
            byte_limit,
            buffer_limit,
        )
        self.buffer, self.eof, self.total_bytes = "", False, 0
        self.sha256 = hashlib.sha256()
        self.utf8 = codecs.getincrementaldecoder("utf-8")()
        self.decoder = json.JSONDecoder(
            object_pairs_hook=strict_pairs,
            parse_float=finite_float,
            parse_constant=reject_constant,
        )
        self.keys, self.max_buffer_chars = set(), 0

    def fill(self):
        if self.eof:
            return False
        require(
            len(self.buffer) < self.buffer_limit, "JSON record exceeds buffer limit"
        )
        raw = self.stream.read(
            min(
                256 * 1024,
                self.buffer_limit - len(self.buffer),
                self.byte_limit + 1 - self.total_bytes,
            )
        )
        self.total_bytes += len(raw)
        require(self.total_bytes <= self.byte_limit, "JSON member exceeds byte limit")
        self.sha256.update(raw)
        self.eof = not raw
        self.buffer += self.utf8.decode(raw, final=self.eof)
        self.max_buffer_chars = max(self.max_buffer_chars, len(self.buffer))
        return bool(raw)

    def peek(self):
        while True:
            self.buffer = self.buffer.lstrip(" \t\r\n")
            if self.buffer:
                return self.buffer[0]
            if not self.fill():
                return None

    def char(self, expected):
        require(self.peek() == expected, f"expected JSON delimiter {expected!r}")
        self.buffer = self.buffer[1:]

    def value(self, initial):
        require(self.peek() == initial, "unexpected JSON record type")
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError:
                if not self.fill():
                    raise PreflightError("invalid or truncated JSON") from None
            else:
                self.buffer = self.buffer[end:]
                return value

    def items(self, arrays):
        self.char("{")
        while self.peek() != "}":
            key = self.value('"')
            require(key not in self.keys, "duplicate top-level JSON key")
            require(key in arrays or key == "info", "unknown top-level JSON key")
            self.keys.add(key)
            self.char(":")
            if key == "info":
                self.value("{")
            else:
                self.char("[")
                if self.peek() != "]":
                    while True:
                        yield key, self.value("{")
                        if self.peek() == "]":
                            break
                        self.char(",")
                self.char("]")
            if self.peek() == "}":
                break
            self.char(",")
            require(self.peek() != "}", "trailing object comma")
        self.char("}")
        require(self.peek() is None, "trailing JSON material")
        require(self.keys == set(arrays) | {"info"}, "missing top-level JSON member")
