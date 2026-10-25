"""Bounded, non-authorizing diagnostics. Never return untrusted keys or values."""
import hashlib
import json
import math

MAX_INPUT_BYTES = 8 * 1024**2
MAX_DEPTH = 16
MAX_PARSE_DEPTH = 64
MAX_NODES = 10_000
MAX_RECORDS = 128
MAX_OUTPUT_BYTES = 32 * 1024
CRATE_FACTS = '@@rules_rs+//rs:extensions.bzl%crate'
MISSING = object()


class Rejected(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    # Bound nesting without recursion before invoking the JSON parser. Brackets
    # inside quoted/escaped strings are not structure; embedded fact JSON is
    # separately checked when decoded. Parser exceptions still fail closed.
    text = data.decode('utf-8') if isinstance(data, bytes) else data
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in '[{':
            depth += 1
            if depth > MAX_PARSE_DEPTH:
                raise Rejected('json_nesting_limit')
        elif character in ']}':
            depth -= 1
            if depth < 0:
                raise Rejected('json_structure')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected('duplicate_json_key')
            result[key] = value
        return result

    def constant(_value):
        raise Rejected('nonfinite_json_number')

    def floating(token):
        value = float(token)
        if not math.isfinite(value):
            raise Rejected('nonfinite_json_number')
        return value

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def output_size(report):
    # Match the report writer's actual indentation and one-level embedding,
    # rather than bounding only a smaller canonical/compact encoding.
    return len(json.dumps({'bazel_hold_summary': report}, indent=2,
                          ensure_ascii=True, allow_nan=False).encode('ascii'))


def kind(value):
    if value is MISSING:
        return 'missing'
    return {type(None): 'null', bool: 'boolean', int: 'integer', float: 'float',
            str: 'string', list: 'array', dict: 'object'}[type(value)]


def descriptor(value):
    label = kind(value)
    result = {'type': label}
    if value is MISSING:
        return result
    result['canonical_sha256'] = sha(b'bazel-hold-json-v1\0' + encode(value))
    if isinstance(value, str):
        result['utf8_bytes'] = len(value.encode('utf-8'))
    elif isinstance(value, (dict, list)):
        result['count'] = len(value)
    return result


class Difference:
    def __init__(self, report):
        self.report = report
        self.remaining_records = MAX_RECORDS
        self.remaining_nodes = MAX_NODES

    def incomplete(self, reason):
        self.report['complete'] = False
        if reason not in self.report['limits_reached']:
            self.report['limits_reached'].append(reason)

    def emit(self, path, change, old, new):
        if self.remaining_records <= 0:
            self.incomplete('record_limit')
            return
        record = {'path': path, 'change': change,
                  'before': descriptor(old), 'after': descriptor(new)}
        # Do not let even a very long known baseline key exceed the output cap.
        if len(encode(record)) > MAX_OUTPUT_BYTES // 2:
            self.incomplete('path_or_record_bytes')
            return
        self.report['changes'].append(record)
        self.remaining_records -= 1

    def walk(self, old, new, path=(), depth=0):
        if self.remaining_nodes <= 0:
            self.incomplete('node_limit')
            return
        if self.remaining_records <= 0:
            self.incomplete('record_limit')
            return
        self.remaining_nodes -= 1
        self.report['visited_nodes'] += 1
        old_kind, new_kind = kind(old), kind(new)
        if old is MISSING:
            self.emit(path, 'added', old, new)
            return  # No baseline ancestry: no labels/descent into the new subtree.
        if new is MISSING:
            self.emit(path, 'removed', old, new)
            return
        if old_kind != new_kind:
            self.emit(path, 'type_changed', old, new)
            return
        if depth >= MAX_DEPTH:
            if encode(old) != encode(new):
                self.emit(path, 'container_or_scalar_changed', old, new)
            self.incomplete('depth_limit')
            return
        if isinstance(old, dict):
            # Baseline insertion order, then observed insertion order for added
            # keys. Deterministic for fixed input bytes; never print an added key.
            for key in old:
                self.walk(old[key], new.get(key, MISSING), path + ({'known_key': key},), depth + 1)
                if self.remaining_nodes <= 0 or self.remaining_records <= 0:
                    self.incomplete('node_or_record_limit')
                    return
            for key in new:
                if key not in old:
                    raw = key.encode('utf-8')
                    segment = {'unknown_key_sha256': sha(b'bazel-hold-key-v1\0' + raw),
                               'key_utf8_bytes': len(raw)}
                    self.walk(MISSING, new[key], path + (segment,), depth + 1)
                    if self.remaining_nodes <= 0 or self.remaining_records <= 0:
                        self.incomplete('node_or_record_limit')
                        return
            return
        if isinstance(old, list):
            for index in range(max(len(old), len(new))):
                left = old[index] if index < len(old) else MISSING
                right = new[index] if index < len(new) else MISSING
                self.walk(left, right, path + ({'index': index},), depth + 1)
                if self.remaining_nodes <= 0 or self.remaining_records <= 0:
                    self.incomplete('node_or_record_limit')
                    return
            return
        if old != new:
            self.emit(path, 'scalar_changed', old, new)
            # Parse only the independently known crate-fact string schema.
            if (isinstance(old, str) and len(path) == 3
                    and path[0] == {'known_key': 'facts'}
                    and path[1] == {'known_key': CRATE_FACTS}
                    and 'known_key' in path[2]):
                self.walk(strict_json(old), strict_json(new),
                          path + ({'embedded_json': True},), depth + 1)


def summarize(before, after, expected_baseline_blob):
    """Diagnostic only: all acceptance decisions are made by the caller's gates."""
    report = {'format_version': 1, 'status': 'unavailable', 'complete': False,
              'before_raw_sha256': sha(before), 'after_raw_sha256': sha(after),
              'before_bytes': len(before), 'after_bytes': len(after),
              'visited_nodes': 0, 'emitted_records': 0, 'limits_reached': [], 'changes': []}
    if max(len(before), len(after)) > MAX_INPUT_BYTES:
        report['reason'] = 'input_size_limit'
        return report
    actual_blob = hashlib.sha1(b'blob ' + str(len(before)).encode() + b'\0' + before).hexdigest()
    if actual_blob != expected_baseline_blob:
        report['reason'] = 'baseline_identity_mismatch'
        return report
    try:
        left, right = strict_json(before), strict_json(after)
        # Validate all known crate-fact strings even when their bytes are equal.
        for document in (left, right):
            facts = document.get('facts', {}).get(CRATE_FACTS)
            if not isinstance(facts, dict):
                raise Rejected('known_schema_missing')
            if len(facts) > MAX_NODES:
                report.update(reason='embedded_fact_count_limit', limits_reached=['node_limit'])
                return report
            for value in facts.values():
                if not isinstance(value, str):
                    raise Rejected('known_schema_type')
                strict_json(value)
        report['complete'] = True
        Difference(report).walk(left, right)
        report['status'] = 'localized'
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        # Never retain parser exception text, offending keys, or partial labels.
        report.update(status='parse_rejected', complete=False, changes=[], visited_nodes=0,
                      reason='invalid_or_unsupported_json')
    while output_size(report) > MAX_OUTPUT_BYTES and report['changes']:
        report['changes'].pop()
        report['complete'] = False
        if 'output_bytes' not in report['limits_reached']:
            report['limits_reached'].append('output_bytes')
    report['emitted_records'] = len(report['changes'])
    if output_size(report) > MAX_OUTPUT_BYTES:
        return {'format_version': 1, 'status': 'unavailable', 'complete': False,
                'reason': 'output_size_limit'}
    return report
