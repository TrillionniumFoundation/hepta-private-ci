"""Actual raw ABI qualification; this Python grammar is not the Rust owner oracle."""
from pathlib import Path
import argparse
import ctypes
import gzip
import hashlib
import itertools
import json
import random
import struct
import time
import traceback

from template_parse_oracle.admission import admit, require

SHORT, INVALID = 0xFFFFFFFE, 0xFFFFFFFF
SPACE = frozenset(map(chr, [*range(9, 14), 32, 133, 160, 5760,
                          *range(8192, 8203), 8232, 8233, 8239, 8287, 12288]))


def identity(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def reference(source):
    """Express the buffer contract independently; UTF-8 admission uses CPython."""
    source.decode('utf-8')
    records = []

    def literal(start, end):
        if start < end:
            previous = records and records[-1][0] in (1, 2)
            records.append((2 if previous else 1, start, end))

    cursor, start = 0, 0
    while cursor < len(source):
        if source.startswith((b'{{{{', b'}}}}'), cursor):
            literal(start, cursor)
            literal(cursor, cursor + 2)
            cursor += 4
            start = cursor
        elif source.startswith(b'{{', cursor):
            opening = cursor
            begin = cursor + 2
            nested = source.find(b'{{', begin)
            closing = source.find(b'}}', begin)
            if nested >= 0 and (closing < 0 or nested < closing):
                return [], 2, opening
            if closing < 0:
                return [], 4, opening
            name = source[begin:closing].decode('utf-8')
            left, right = 0, len(name)
            while left < right and name[left] in SPACE:
                left += 1
            while right > left and name[right - 1] in SPACE:
                right -= 1
            if left == right:
                return [], 1, opening
            name_start = begin + len(name[:left].encode())
            name_end = begin + len(name[:right].encode())
            literal(start, opening)
            records.append((3, name_start, name_end))
            cursor = closing + 2
            start = cursor
        elif source.startswith(b'}}', cursor):
            return [], 3, cursor
        else:
            cursor += 1
    literal(start, len(source))
    return records, 0, 0


class Native:
    def __init__(self, producer, library_dir, output):
        self.build, library, inputs = admit(producer, library_dir)
        self.bindings = [{'path': name, **row} for name, row in inputs.items()]
        self.bindings.append(identity(Path(__file__).resolve()))
        self.library = ctypes.CDLL(str(library))
        self.entry = self.library.codex_hia_template_parse
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p,
                              ctypes.c_uint64, ctypes.c_void_p, ctypes.c_uint64]
        self.entry.restype = ctypes.c_uint64
        self.counts = {'calls': 0, 'query': 0, 'emit': 0, 'semantic_errors': 0, 'errors_no_write': 0}
        self.categories = {}
        self.path = output / 'calls.jsonl.gz'
        self.file = self.path.open('xb')
        self.trace = gzip.GzipFile(filename='', fileobj=self.file, mode='wb', mtime=0)
        self.digest = hashlib.sha256()
        self.trace_bytes = 0
        self.last = None

    def call(self, source, frame, capacity, status_expected, *, result=None, operation=None, category):
        prefix, suffix = bytes(range(17)), bytes(range(239, 256))
        source_bytes, workspace_bytes = prefix + source + suffix, prefix + frame + suffix
        before = prefix + b'\xA5' * capacity + suffix
        s = ctypes.create_string_buffer(source_bytes, len(source_bytes))
        w = ctypes.create_string_buffer(workspace_bytes, len(workspace_bytes))
        o = ctypes.create_string_buffer(before, len(before))
        self.last = {'category': category, 'source_bytes': len(source), 'source_sha256': hashlib.sha256(source).hexdigest(),
                     'frame_hex': frame.hex(), 'capacity': capacity, 'expected_status': status_expected}
        if len(source) <= 256:
            self.last['source_hex'] = source.hex()
        status = self.entry(ctypes.addressof(s) + 17, len(source), ctypes.addressof(o) + 17,
                            capacity, ctypes.addressof(w) + 17, len(frame))
        self.counts['calls'] += 1
        assert status == status_expected, (self.last, status)
        assert s.raw == source_bytes and w.raw == workspace_bytes, (self.last, 'input modified')
        after = o.raw
        assert after[:17] == prefix and after[17 + capacity:] == suffix, (self.last, 'canary modified')
        payload = after[17:17 + capacity]
        if status:
            assert after == before, (self.last, 'nonzero return modified output')
            self.counts['errors_no_write'] += 1
        else:
            records, error, start = result
            required = 64 + 24 * len(records)
            written = 64 if operation == 0 or error else required
            expected = struct.pack('<8Q', 1, operation, len(source), len(records), required, written, error, start)
            if operation == 1 and not error:
                expected += b''.join(struct.pack('<3Q', *row) for row in records)
            assert payload[:written] == expected, (self.last, 'native plan differs', payload[:min(written, 256)].hex(), expected[:256].hex())
            assert payload[written:] == b'\xA5' * (capacity - written), (self.last, 'unused tail changed')
            self.counts['query' if operation == 0 else 'emit'] += 1
            self.counts['semantic_errors'] += bool(error)
        self.categories[category] = self.categories.get(category, 0) + 1
        row = {**self.last, 'actual_status': status, 'output_sha256': hashlib.sha256(payload).hexdigest(),
               'inputs_and_canaries_unchanged': True}
        encoded = (json.dumps(row, separators=(',', ':')) + '\n').encode()
        self.trace.write(encoded)
        self.digest.update(encoded)
        self.trace_bytes += len(encoded)

    def exercise(self, source, category, extra=11):
        try:
            result = reference(source)
        except UnicodeDecodeError:
            for operation in (0, 1):
                self.call(source, struct.pack('<4Q', 1, operation, 0, 0), 80, INVALID,
                          operation=operation, category=category + '_invalid_utf8')
            return
        for operation in (0, 1):
            capacity = (64 if operation == 0 else 64 + 24 * len(result[0])) + extra
            self.call(source, struct.pack('<4Q', 1, operation, 0, 0), capacity, 0,
                      result=result, operation=operation, category=category)

    def finish(self):
        self.trace.close()
        self.file.close()
        for row in self.bindings:
            assert identity(Path(row['path'])) == row
        return {'bindings': self.bindings, 'counts': self.counts, 'categories': self.categories,
                'call_trace': identity(self.path), 'uncompressed_trace_bytes': self.trace_bytes,
                'uncompressed_trace_sha256': self.digest.hexdigest(), 'all_bound_inputs_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--producer', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    producer = args.producer.resolve(strict=True)
    library_dir = args.library_dir.resolve(strict=True)
    report_path = args.report.resolve()
    output = (args.work_dir or report_path.with_name(report_path.stem + '-files')).resolve()
    for path in (report_path, output):
        require(not path.is_relative_to(producer) and not path.is_relative_to(library_dir),
                'qualification output cannot overwrite producing source or native inputs')
        require(not path.exists(), 'execution output already exists; prior evidence is immutable')
    require(not report_path.is_relative_to(output), 'the report must be outside its work directory')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic_ns()
    native = None
    report = {'schema': 'codex.hia.template-parse-formal-abi.v1', 'passed': False,
              'controller': identity(Path(__file__).resolve()), 'producer': str(producer),
              'library_dir': str(library_dir), 'work_dir': str(output),
              'scope': 'Actual full-build native framing, UTF-8, ordered parse-plan and atomic no-write observations. The independent Python checker is only a buffer-contract reference, not complete original Rust equivalence.',
              'cargo_qualified': False, 'original_rust_differential_qualified': False,
              'concurrent_execution': False, 'invented_oversized_pointer_ranges_used': False,
              'whole_codex_rewritten': False, 'legacy_retirement': False, 'tests_skipped': 0}
    try:
        native = Native(producer, library_dir, output)
        report['formal_module_count'] = len(native.build['modules'])
        frame = struct.pack('<4Q', 1, 0, 0, 0)
        for size in range(32):
            native.call(b'{{a}}', frame[:size], 64, SHORT, category='short_workspace')
        for size in range(64):
            native.call(b'{{a}}', frame, size, SHORT, category='short_output')
            native.call(b'}}\xff', b'\xff' * 40, size, SHORT, category='minimum_capacity_precedes_other_errors')
        for size in range(33, 81):
            native.call(b'{{a}}', frame + b'\x72' * (size - 32), 88, INVALID, category='workspace_exact_length')
        for index in range(4):
            for value in sorted({0, 1, 2, 3, 255, (1 << 64) - 1, *(1 << bit for bit in range(64))}):
                words = [1, 0, 0, 0]
                words[index] = value
                if not (words[0] == 1 and words[1] in (0, 1) and words[2:] == [0, 0]):
                    native.call(b'{{a}}', struct.pack('<4Q', *words), 88, INVALID, category='invalid_frame_words')
        for data in (b'a', b'{{x}}', b'a{{x}}{{{{b}}}}c{{z}}', b'{{x}}' * 65):
            result = reference(data)
            required = 64 + 24 * len(result[0])
            for capacity in sorted({64, 65, 71, 72, 87, required - 1}):
                if capacity < required:
                    native.call(data, struct.pack('<4Q', 1, 1, 0, 0), capacity, SHORT,
                                category='emit_short_atomic')
            native.exercise(data, 'exact_capacity', extra=0)
            native.call(data, frame, required + 19, 0, result=result, operation=0, category='query_large_tail')
        # Exhaust every brace-only word through length 13, including overlapping
        # two/four-brace delimiters and every inner/outer error order.
        brace_cases = 0
        for length in range(14):
            for letters in itertools.product(b'{}', repeat=length):
                native.exercise(bytes(letters), 'exhaustive_brace_runs')
                brace_cases += 1
        report['brace_cases'] = brace_cases
        tokens = ['x', '{', '}', '{{', '}}', '{{{{', '}}}}', '{{a}}', '{{ a }}', '{{}}',
                  '{{x', '{{{{x}}', '\x00', '\n', '\r\n', '名', '😀', '\u3000', '\u0085', '\ufeff']
        rng = random.Random(2026111518)
        for _ in range(3000):
            text = ''.join(rng.choice(tokens) for _ in range(rng.randrange(1, 20)))
            native.exercise(text.encode(), 'deterministic_token_combinations')
        for space in sorted(SPACE):
            for text in ('{{' + space + '}}', 'é{{' + space + 'x' + space + '}}😀',
                         '{{x' + space + 'y}}', space + '{{x}}' + space):
                native.exercise(text.encode(), 'unicode_whitespace_exact_set')
        for scalar in [*range(0x1C, 0x20), 0x180E, 0x200B, 0x200C, 0x2060, 0xFEFF, 0x10FFFF]:
            native.exercise(('{{' + chr(scalar) + '}}').encode(), 'non_whitespace_names')
        sample = 'é{{ \u3000名😀\u0085 }}尾'.encode()
        for index in range(len(sample)):
            for value in range(256):
                native.exercise(sample[:index] + bytes([value]) + sample[index + 1:], 'all_byte_position_mutations')
        report['all_byte_position_mutations'] = len(sample) * 256
        malformed = [b'\xff', b'\xc0\xaf', b'\xc1\xbf', b'\xe0\x80\x80', b'\xed\xa0\x80',
                     b'\xf0\x80\x80\x80', b'\xf4\x90\x80\x80', b'\xf5\x80\x80\x80', b'\xe2\x82', b'\x80']
        for data in malformed:
            for surrounding in (data, b'}}' + data, data + b'{{x}}', b'{{' + data + b'}}'):
                native.exercise(surrounding, 'full_utf8_precedes_semantic_errors')
        for scalar in [0, 1, 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFFFF, 0x10000, 0x10FFFF]:
            data = chr(scalar).encode()
            native.exercise(data + b'{{x}}' + data, 'unicode_encoding_endpoints')
            for length in range(1, len(data)):
                native.exercise(b'{{' + data[:length] + b'}}', 'truncated_utf8_endpoint')
        for data in (b'x' * (2 * 1024 * 1024 + 7), b'{{x}}' * 65537,
                     ('\u3000' * 349527 + '{{x}}').encode()):
            native.exercise(data, 'large_real_buffers')
            report['largest_source_bytes'] = max(report.get('largest_source_bytes', 0), len(data))
            report['largest_output_bytes'] = max(report.get('largest_output_bytes', 0), 64 + 24 * len(reference(data)[0]))
        for i in range(128):
            native.exercise(('pre{{ x' + str(i) + ' }}post').encode(), 'independent_interleaving')
            native.exercise(b'{{ }}', 'independent_interleaving')
            native.exercise(b'{{{{}}}}', 'independent_interleaving')
        report['independent_interleavings'] = 128
        report['passed'] = True
    except BaseException:
        report['exception'] = traceback.format_exc()
        if native is not None:
            report['last_request'] = native.last
        raise
    finally:
        try:
            if native is not None:
                report.update(native.finish())
        except BaseException:
            report['passed'] = False
            report['terminal_verification_exception'] = traceback.format_exc()
            raise
        finally:
            report['elapsed_ns'] = time.monotonic_ns() - started
            report_path.write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'passed': report['passed'], 'report': identity(report_path)}), flush=True)


if __name__ == '__main__':
    main()
