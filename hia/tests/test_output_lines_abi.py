#!/usr/bin/env python3
"""Check the frozen output-lines corpus through the admitted B3 namespaced ABI.

This gate neither builds native code nor runs the original Rust public oracle.
Seed direct-byte wrappers are a different ABI and are not accepted here.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[2]
CORPUS_SHA = '43a724456cad25140e71a5923a61e3f09234c5446c1a47839b0142376ff2b9d8'
ADAPTER_SHA = 'd7acad7e4c12583783f0288c45ac856c65cb043f881ec150e128343ac339cb45'
GUARD = bytes(range(1, 34))
OK, INVALID, SHORT, OVERFLOW = 32, 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
MAX_FRAME = 1_048_577  # Includes the literal one-byte-oversize Core cases.
PARTITION_LIMIT = 64  # Extra partitions only; all 82 literal frames still run.


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def words(values):
    require(all(isinstance(value, str) and value.isascii() and value.isdecimal()
                and 0 <= int(value) < 1 << 64 for value in values),
            'corpus word is not an unsigned decimal u64')
    return struct.pack('<' + 'Q' * len(values), *(int(value) for value in values))


def bind(path, report, expected=None):
    path = path.resolve(strict=True)
    data = path.read_bytes()
    value = digest(data)
    previous = report['inputs'].get(str(path))
    require(previous is None or previous == value, f'input changed: {path}')
    require(expected is None or expected == value, f'input identity mismatch: {path}')
    report['inputs'][str(path)] = value
    return data


def frame(case):
    if 'source_hex' in case:
        require('source_header_words_le' not in case and 'chunk_parts' not in case,
                'raw source cannot also have a normalized header')
        raw = bytes.fromhex(case['source_hex'])
    else:
        header = words(case['source_header_words_le'])
        require(len(header) == 32, 'source header must contain four words')
        parts, length = [], 32
        for part in case['chunk_parts']:
            value = bytes.fromhex(part['hex'])
            repeat = part['repeat']
            require(type(repeat) is int and repeat >= 0, 'invalid repeat recipe')
            length += len(value) * repeat
            require(length <= MAX_FRAME, 'recipe exceeds the frozen frame bound')
            parts.append(value * repeat)
        raw = header + b''.join(parts)
    require(len(raw) == case['source_frame_bytes'] and len(raw) <= MAX_FRAME,
            'materialized source differs from its literal extent')
    return raw


class RawFailure(Exception):
    def __init__(self, record):
        self.record = record
        super().__init__(record['label'])


class Probe:
    def __init__(self, library, report):
        self.library = ctypes.CDLL(str(library))
        self.function = self.library.codex_hia_output_lines
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.report = report

    def call(self, raw, capacity, workspace, fill, expected, prefix, label, family):
        require(0 <= len(raw) <= MAX_FRAME and type(capacity) is int
                and 0 <= capacity <= 64 and len(workspace) <= 3 and len(fill) == 1,
                'call is outside the frozen live-buffer extents')
        require(expected in (OK, INVALID, SHORT, OVERFLOW), 'unknown Core expectation')
        require(prefix is None or (expected == OK and len(prefix) == 32),
                'unexpected literal output shape')
        source = bytearray(GUARD + raw + GUARD)
        output = bytearray(GUARD + fill * capacity + GUARD)
        work = bytearray(GUARD + workspace + GUARD)
        before = [bytes(value) for value in (source, output, work)]
        buffers = [(ctypes.c_ubyte * len(value)).from_buffer(value)
                   for value in (source, output, work)]
        pointers = [ctypes.cast(ctypes.byref(value, len(GUARD)), ctypes.c_void_p)
                    for value in buffers]
        self.report['active_case'] = label
        self.report['calls_started'] += 1
        returned = self.function(pointers[0], len(raw), pointers[1], capacity,
                                 pointers[2], len(workspace))
        payload = bytes(output[len(GUARD):len(GUARD) + 32]) if capacity >= 32 else b''
        wanted = bytearray(before[1])
        if expected == OK:
            require(capacity >= 32, 'success expectation has short output')
            wanted[len(GUARD):len(GUARD) + 32] = prefix if prefix is not None else payload
        record = {
            'label': label, 'family': family, 'source_bytes': len(raw),
            'source_sha256': digest(raw), 'output_capacity': capacity,
            'workspace_bytes': len(workspace), 'expected_core_return': expected,
            'actual_return_u64': str(returned), 'return_high_u32': returned >> 32,
            'core_return_u32': returned & 0xFFFFFFFF if returned >> 32 == 0 else None,
            'source_and_guards_unchanged': bytes(source) == before[0],
            'workspace_and_guards_unchanged': bytes(work) == before[2],
            'whole_output_matches': bytes(output) == bytes(wanted),
            'expected_output_sha256': digest(wanted),
            'actual_output_sha256': digest(output),
            'actual_prefix_hex': payload.hex(),
            'literal_prefix_hex': None if prefix is None else prefix.hex(),
            'passed': False,
        }
        self.report['calls'].append(record)
        if (returned != expected or returned >> 32 != 0
                or not record['source_and_guards_unchanged']
                or not record['workspace_and_guards_unchanged']
                or not record['whole_output_matches']):
            raise RawFailure(record)
        record['passed'] = True
        self.report['active_case'] = None
        return payload


def literal_call(probe, case, defaults, label):
    merged = {**defaults, **case}
    raw = frame(case)
    expected = case['expected_core_status']
    prefix = None
    if expected == OK:
        prefix = bytes.fromhex(case['expected_output_prefix_hex'])
        require(prefix == words(case['expected_output_words_le']) and len(prefix) == 32
                and case['expected_written_bytes'] == 32, 'literal output disagrees')
    else:
        require(case['expected_written_bytes'] == 0
                and 'expected_output_prefix_hex' not in case
                and 'expected_output_words_le' not in case, 'error promises output')
    payload = probe.call(raw, merged['output_capacity'], bytes.fromhex(merged['workspace_hex']),
                         bytes.fromhex(merged['output_initial_fill_hex']), expected, prefix,
                         label, 'literal')
    return raw, payload


def partition(probe, chunks, final, label):
    require(bool(chunks), 'partition must include at least one call')
    state, consumed = b'\0' * 24, 0
    for index, chunk in enumerate(chunks):
        payload = probe.call(struct.pack('<Q', 1) + state + chunk, 48, b'', b'\xa5',
                             OK, None, f'{label}/{index}', 'derived-partition')
        consumed += len(chunk)
        lf, seen, last, total = struct.unpack('<4Q', payload)
        require(seen == int(consumed != 0) and last in (0, 1)
                and lf <= consumed and total <= consumed
                and (seen != 0 or (lf == 0 and last == 0))
                and (last == 0 or lf != 0)
                and total == lf + int(seen == 1 and last == 0),
                'partition returned inconsistent state')
        state = payload[:24]
    require(payload == final, f'partition final differs from literal: {label}')
    probe.report['partitions'].append({'label': label, 'chunks': len(chunks),
                                       'bytes': consumed, 'final_prefix_hex': payload.hex()})


def verify(args, report):
    directory = args.library_dir.resolve(strict=True)
    native_inputs(directory / 'network_host.so', ROOT / 'hia/network_host.hepta',
                  args.build_profile, report)
    verified_field, expected_count = {
        'full-native30': ('full30_manifest_verified', 30),
        'full-native31': ('full31_manifest_verified', 31),
        'full-native32': ('full32_manifest_verified', 32),
        'full-native33': ('full33_manifest_verified', 33),
        'full-native34': ('full34_manifest_verified', 34),
        'full-native35': ('full35_manifest_verified', 35),
        'full-native36': ('full36_manifest_verified', 36),
        'full-native37': ('full37_manifest_verified', 37),
    }[args.build_profile]
    require(report['native_build'][verified_field] is True
            and report['native_build']['module_count'] == expected_count,
            'raw output-lines requires the complete selected native module build')
    bind(Path(__file__), report)
    contract = json.loads(bind(ROOT / 'hia/output_lines_buffer_contract.json', report))
    corpus = json.loads(bind(ROOT / 'hia/tests/output_lines_oracle_inputs.json', report, CORPUS_SHA))
    source = bind(ROOT / 'hia/output_lines.hepta', report, contract['source']['sha256'])
    require(contract['source'] == corpus['source'] and len(source) == contract['source']['bytes']
            and contract['schema'] == 'codex.hia.output-lines-buffer-contract.v1'
            and contract['module'] == 'output_lines'
            and contract['symbol'] == 'codex_hia_output_lines'
            and contract['source_frame']['header_bytes'] == 32
            and contract['source_frame']['maximum_source_bytes'] == 1_048_576
            and contract['output']['written_bytes'] == 32
            and [item['value'] for item in contract['statuses']]
                == [OK, INVALID, SHORT, OVERFLOW]
            and contract['compiler_boundary']['entry_profile'] == 'borrowed-buffers-u32-v1'
            and corpus['schema'] == 'codex.hia.output-lines-oracle-inputs.v1',
            'source/contract/corpus identity differs')
    bind(ROOT / 'codex-rs/utils/string/src/hia_native_output_lines.rs', report, ADAPTER_SHA)
    for path in ('codex-rs/utils/string/src/lib.rs', 'codex-rs/utils/string/build.rs',
                 'codex-rs/utils/output-truncation/src/lib.rs'):
        bind(ROOT / path, report)
    library = directory / 'libcodex_hia_output_lines.so'
    require(str(library) in report['inputs'], 'namespaced library was not admitted')
    report['inputs_unchanged_before_load'] = recheck_inputs(report)
    require(report['inputs_unchanged_before_load'], 'input changed before native load')
    streams, raw_cases = corpus['streams'], corpus['raw_cases']
    require(len(streams) == 28 and sum(len(item['calls']) for item in streams) == 54
            and len(raw_cases) == 28, 'frozen corpus cardinality differs')
    ids = [item['id'] for item in streams + raw_cases]
    require(len(ids) == len(set(ids)), 'duplicate corpus identifiers')
    probe = Probe(library, report)
    groups, small = {}, {}
    for stream in streams:
        state = words(stream['initial_state'])
        pieces, total_bytes = [], 0
        require(len(state) == 24 and stream['calls'], 'invalid stream state')
        for index, case in enumerate(stream['calls']):
            require(case['expected_core_status'] == OK
                    and words(case['source_header_words_le'][1:]) == state,
                    'literal stream does not carry the actual prior raw state')
            raw, result = literal_call(probe, case, corpus['case_defaults'],
                                       f"stream/{stream['id']}/{index}")
            state = result[:24]
            pieces.append(raw[32:])
            total_bytes += len(raw) - 32
        whole = b''.join(pieces)
        require(total_bytes == stream['expected_total_chunk_bytes']
                and result[24:] == words([stream['expected_final_line_count']]),
                'literal stream total differs')
        report['streams'].append({'id': stream['id'], 'domain': stream['domain'],
                                  'calls': len(stream['calls']), 'bytes': total_bytes,
                                  'sha256': digest(whole), 'final_prefix_hex': result.hex()})
        if 'partition_equivalence_group' in stream:
            groups.setdefault(stream['partition_equivalence_group'], []).append(
                (words(stream['initial_state']), whole, result))
        if stream['domain'] == 'public-valid-utf8':
            whole.decode('utf-8')
            if len(whole) <= PARTITION_LIMIT:
                require(words(stream['initial_state']) == b'\0' * 24,
                        'public partition fixture has a seeded history')
                require(whole not in small or small[whole] == result,
                        'same public bytes have conflicting literal results')
                small[whole] = result
    for item in raw_cases:
        literal_call(probe, item['call'], corpus['case_defaults'], f"raw/{item['id']}")
    require(len(report['calls']) == 82, 'not every literal frame completed')
    for name, values in groups.items():
        require(len(values) >= 2 and all(value == values[0] for value in values),
                f'literal partition bytes or final state differ: {name}')
    report['literal_partition_groups'] = {name: len(values) for name, values in groups.items()}
    for index, (whole, final) in enumerate(small.items()):
        for split in range(len(whole) + 1):
            partition(probe, [whole[:split], whole[split:]], final, f'split/{index}/{split}')
        partition(probe, [bytes([value]) for value in whole] or [b''], final,
                  f'byte-partition/{index}')
    report['bounded_partition_inputs'] = len(small)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native30', 'full-native31', 'full-native32', 'full-native33', 'full-native34', 'full-native35', 'full-native36', 'full-native37'],
                        default='full-native30')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {
        'schema': 'codex.hia.output-lines.raw-abi.v1', 'passed': False,
        'requested_build_profile': args.build_profile,
        'loaded_entry': 'libcodex_hia_output_lines.so:codex_hia_output_lines',
        'abi_scope': 'Normal native-selfhost B3 namespaced borrowed-buffers-u32-v1 only.',
        'return_rule': 'Full u64 must equal the literal Core u32; nonzero high word is never masked or accepted.',
        'call_pass_scope': 'ABI/status/guard checks and any literal prefix. Derived final equality is recorded separately in partitions.',
        'seed_direct_profile_executed': False,
        'seed_direct_extent_note': 'The seed direct wrapper returns ABI_EXTENT<<32 for the two oversize frames; it cannot prove their Core rejection. This gate rejects seed-only builds.',
        'original_rust_oracle_executed': False, 'public_owner_qualified': False,
        'performance_qualified': False, 'whole_output_truncation_qualified': False,
        'skipped': 0, 'literal_frames_expected': 82, 'calls_started': 0,
        'calls': [], 'streams': [], 'partitions': [], 'active_case': None,
    }
    # Reserve one new report; never replace an earlier run or input file.
    with args.report.open('x', encoding='utf-8') as output:
        output.write(json.dumps(report, indent=2) + '\n')
        output.flush()
        try:
            verify(args, report)
            report['passed'] = True
        except BaseException as error:
            report['error'] = f'{type(error).__name__}: {error}'
            if isinstance(error, RawFailure):
                report['failure_case'] = error.record
        finally:
            if 'inputs' in report:
                report['inputs_unchanged_after_calls'] = recheck_inputs(report)
                report['passed'] &= report['inputs_unchanged_after_calls']
                if not report['inputs_unchanged_after_calls']:
                    report.setdefault('error', 'source or native input changed during the gate')
            report['literal_frames_checked'] = sum(
                row['family'] == 'literal' and row['passed'] for row in report['calls'])
            report['derived_calls_checked'] = sum(
                row['family'] == 'derived-partition' and row['passed'] for row in report['calls'])
            report['derived_partitions_checked'] = len(report['partitions'])
            output.seek(0)
            output.write(json.dumps(report, indent=2) + '\n')
            output.truncate()
            output.flush()
    print(json.dumps({'passed': report['passed'], 'report': str(args.report),
                      'sha256': digest(args.report.read_bytes()),
                      'literal_frames_checked': report['literal_frames_checked'],
                      'derived_calls_checked': report['derived_calls_checked'],
                      'error': report.get('error')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
