"""Decode one fixed JSON transport envelope; never execute or repair its content."""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math


MAX_TEXT_BYTES = 65536
JSON_WHITESPACE = ' \t\r\n'


class Schema(Enum):
    SQL_QUERY = 'sql_query'
    SOURCE_READ = 'source_read'
    ROWS_ANSWER = 'rows_answer'
    STRINGS_ANSWER = 'strings_answer'
    QUALIFICATION = 'qualification'


class DecodeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Decoded:
    value: object
    envelope: str
    schema: str
    raw_sha256: str
    body_sha256: str


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DecodeError('duplicate_key')
        result[key] = value
    return result


def _finite_float(token):
    value = float(token)
    if not math.isfinite(value):
        raise DecodeError('nonfinite_number')
    return value


def _reject_constant(token):
    raise DecodeError('nonfinite_number')


def _unicode_scalars(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                item.encode('utf-8')
            except UnicodeEncodeError as exc:
                raise DecodeError('invalid_unicode') from exc
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())


def _matches(value, schema):
    if schema is Schema.SQL_QUERY:
        return (isinstance(value, dict) and set(value) == {'query'} and
                isinstance(value['query'], str) and 1 <= len(value['query']) <= 4000)
    if schema is Schema.SOURCE_READ:
        if not isinstance(value, dict):
            return False
        if set(value) == {'needle'}:
            return isinstance(value['needle'], str) and 1 <= len(value['needle']) <= 128
        return (set(value) == {'start_line', 'line_count'} and
                type(value['start_line']) is int and value['start_line'] >= 1 and
                type(value['line_count']) is int and 1 <= value['line_count'] <= 120)
    if schema is Schema.ROWS_ANSWER:
        return (isinstance(value, list) and len(value) <= 50 and
                all(isinstance(row, list) and len(row) <= 32 and
                    all(cell is None or type(cell) in (str, int, float, bool) for cell in row)
                    for row in value))
    if schema is Schema.STRINGS_ANSWER:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if schema is Schema.QUALIFICATION:
        return isinstance(value, list) and len(value) == 1 and type(value[0]) is int and value[0] == 1
    raise DecodeError('unknown_schema')


def decode(text, *, schema):
    """Accept native JSON or one exact lowercase json fence, then enforce schema.

    No unlabeled fence, Markdown traversal, extraction, coercion, or retry exists.
    SQL_QUERY validates transport shape only. The original read-only SQL worker
    remains mandatory; this function does not authorize or execute a statement.
    """
    if type(text) is not str:
        raise DecodeError('text_type')
    if not isinstance(schema, Schema):
        raise DecodeError('unknown_schema')
    if not text or len(text) > MAX_TEXT_BYTES:
        raise DecodeError('text_size')
    try:
        raw = text.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise DecodeError('invalid_unicode') from exc
    if not raw or len(raw) > MAX_TEXT_BYTES:
        raise DecodeError('text_size')
    body = text.strip(JSON_WHITESPACE)
    envelope = 'native_json'
    if body.startswith('```'):
        if body.startswith('```json\r\n'):
            opening = 9
        elif body.startswith('```json\n'):
            opening = 8
        else:
            raise DecodeError('invalid_envelope')
        if body.endswith('\r\n```'):
            closing = 5
        elif body.endswith('\n```'):
            closing = 4
        else:
            raise DecodeError('invalid_envelope')
        body = body[opening:-closing]
        envelope = 'json_fence'
    try:
        value = json.loads(body, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant, parse_float=_finite_float)
    except DecodeError:
        raise
    except (ValueError, RecursionError) as exc:
        raise DecodeError('invalid_json') from exc
    _unicode_scalars(value)
    if not _matches(value, schema):
        raise DecodeError('schema_mismatch')
    return Decoded(value=value, envelope=envelope, schema=schema.value,
                   raw_sha256=hashlib.sha256(raw).hexdigest(),
                   body_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest())
