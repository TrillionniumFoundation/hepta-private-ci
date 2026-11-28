#!/usr/bin/env python3
"""Check literal format-env-display frames through the admitted B3 ABI.

This gate loads the selected complete native build; it never builds one. It does not
sort keys with a Python comparator or execute the Rust public oracle. The
literal streams contain every expected native request, state and result.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SHA = '984eb93cf8f70f41a293b2d3214119aac343db57e2908203c97d36a785009ce2'
CORPUS_SHA = '9e107735a6df7aedd6dbfa2deec40526f399c5ef1d32af413fb253ddf442b29a'
GUARD = bytes(range(1, 34))
INVALID, SHORT, OVERFLOW = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
ERRORS = (INVALID, SHORT, OVERFLOW)
MAX_RAW_FRAME = 8401  # Includes the one-byte-oversize INVALID literal.
LITERAL_COUNTS = {'streams': 22, 'stream_calls': 71, 'raw_cases': 160, 'literal_frames': 231}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def words(values):
    require(all(isinstance(value, str) and value.isascii() and value.isdecimal()
                and 0 <= int(value) < 1 << 64 for value in values),
            'literal word is not an unsigned decimal u64')
    return struct.pack('<' + 'Q' * len(values), *(int(value) for value in values))


def unpack(data):
    require(len(data) % 8 == 0, 'word extent is not aligned')
    return struct.unpack('<' + 'Q' * (len(data) // 8), data)


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
    raw = bytes.fromhex(case['source_hex'])
    require(len(raw) == case['source_bytes'] and len(raw) <= MAX_RAW_FRAME,
            'literal source extent differs')
    if 'source_words_le' in case:
        require(raw == words(case['source_words_le']) + bytes.fromhex(case['source_payload_hex']),
                'literal source words or payload differ')
    return raw


class RawFailure(Exception):
    def __init__(self, record):
        self.record = record
        super().__init__(record['label'])


class RawAbi:
    def __init__(self, library, report):
        self.library = ctypes.CDLL(str(library))
        self.function = self.library.codex_hia_format_env_display
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.report = report

    def call(self, case, fill, label):
        raw = frame(case)
        capacity = case['output_capacity']
        workspace = bytes.fromhex(case['workspace_hex'])
        expected = case['expected_core_return']
        require(type(capacity) is int and 0 <= capacity <= 4179
                and len(workspace) <= 3 and len(fill) == 1,
                'call is outside frozen live-buffer extents')
        require(type(expected) is int and (expected in ERRORS or 32 <= expected <= 4162),
                'unknown literal Core expectation')
        prefix = b''
        if expected not in ERRORS:
            prefix = bytes.fromhex(case['expected_output_prefix_hex'])
            require(prefix == words(case['expected_output_words_le'])
                    + bytes.fromhex(case['expected_payload_hex'])
                    and len(prefix) == expected == case['expected_written_bytes']
                    and capacity >= expected, 'complete literal success output differs')
        else:
            require(case['expected_written_bytes'] == 0
                    and 'expected_output_prefix_hex' not in case
                    and 'expected_output_words_le' not in case,
                    'error expectation promises output')
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
        wanted = bytearray(before[1])
        wanted[len(GUARD):len(GUARD) + len(prefix)] = prefix
        actual = bytes(output[len(GUARD):len(GUARD) + len(prefix)])
        record = {
            'label': label, 'source_bytes': len(raw), 'source_sha256': digest(raw),
            'output_capacity': capacity, 'workspace_bytes': len(workspace),
            'expected_core_return': expected, 'actual_return_u64': str(returned),
            'return_high_u32': returned >> 32,
            'core_return_u32': returned & 0xFFFFFFFF if returned >> 32 == 0 else None,
            'source_and_guards_unchanged': bytes(source) == before[0],
            'workspace_and_guards_unchanged': bytes(work) == before[2],
            'whole_output_matches': bytes(output) == bytes(wanted),
            'expected_output_sha256': digest(wanted),
            'actual_output_sha256': digest(output),
            'actual_prefix_hex': actual.hex(), 'literal_prefix_hex': prefix.hex(),
            'logical_continuation_only': case['logical_continuation_only'],
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
        return raw, actual


def sort_stream(probe, stream, fill):
    keys = [bytes.fromhex(value) for value in stream['keys_hex']]
    indices = list(range(len(keys)))
    result = None
    for index, case in enumerate(stream['calls']):
        raw = frame(case)
        if index == 0:
            require(raw == struct.pack('<3Q', 1, 0, len(keys)), 'sort stream init differs')
        else:
            require(raw[:16] == struct.pack('<2Q', 1, 1)
                    and raw[16:160] == result[8:152], 'sort state is not actual previous state')
            action = unpack(result[:8])[0]
            state = unpack(result[8:152])
            left, right = state[9:11]
            require(left < len(indices) and right < len(indices), 'request outside host indices')
            reply = unpack(raw[160:208])
            if action == 0:
                li, ri = indices[left], indices[right]
                left_key, right_key = keys[li], keys[ri]
                count = reply[5]
                offset = state[11]
                require(reply[:5] == (0, li, ri, len(left_key), len(right_key))
                        and count <= 4096, 'comparison reply changed stable key binding')
                left_bytes = left_key[offset:offset + count]
                right_bytes = right_key[offset:offset + count]
                require(len(left_bytes) == count == len(right_bytes)
                        and raw[208:] == left_bytes + right_bytes,
                        'literal comparison bytes differ from requested keys')
            else:
                require(action == 1 and reply == (1, 0, 0, 0, 0, 0) and len(raw) == 208,
                        'sort stream contains a non-swap acknowledgment')
                # Mechanically apply only the native-requested swap, exactly once.
                indices[left], indices[right] = indices[right], indices[left]
        require(case['expected_core_return'] == 152, 'sort stream has an error fixture')
        _, result = probe.call(case, fill, f"stream/{stream['id']}/{index}")
    require(result is not None and unpack(result[:8]) == (2,)
            and indices == stream['expected_original_indices'],
            'sort stream did not reach literal Done/index order')
    return {'id': stream['id'], 'calls': len(stream['calls']), 'indices': indices}


def byte_stream(probe, stream, fill):
    kind = stream['kind']
    require(kind in ('mask', 'join'), 'unknown byte stream kind')
    header = 32 if kind == 'mask' else 64
    result = None
    emitted = bytearray()
    for index, case in enumerate(stream['calls']):
        raw = frame(case)
        require(case['expected_core_return'] not in ERRORS, 'stream contains an error fixture')
        if index == 0:
            if kind == 'mask':
                require(raw[:16] == struct.pack('<2Q', 1, 2)
                        and unpack(raw[24:40]) == (0, 0), 'mask stream is not initial')
            else:
                require(len(raw) == 24 and raw[:16] == struct.pack('<2Q', 1, 3),
                        'join stream does not start with JoinInit')
        else:
            op = 2 if kind == 'mask' else 4
            require(raw[:16] == struct.pack('<2Q', 1, op)
                    and raw[16:header + 8] == result[8:header],
                    'literal continuation differs from actual previous state')
        _, result = probe.call(case, fill, f"stream/{stream['id']}/{index}")
        require(unpack(result[:8])[0] == len(result) - header, 'payload length differs')
        emitted.extend(result[header:])
    state = unpack(result[8:header])
    require(state[-1] == 1 and bytes(emitted) == bytes.fromhex(stream['expected_payload_hex']),
            'byte stream did not reach literal complete output')
    if kind == 'mask':
        require(state[0] == state[1], 'mask ended before full key')
    else:
        require(state[0] == state[1], 'join ended before every part')
    return {'id': stream['id'], 'calls': len(stream['calls']),
            'output_bytes': len(emitted), 'output_sha256': digest(emitted)}


def verify(args, report):
    directory = args.library_dir.resolve(strict=True)
    native_inputs(directory / 'network_host.so', ROOT / 'hia/network_host.hepta',
                  args.build_profile, report)
    verified_field, expected_count = {
        'full-native32': ('full32_manifest_verified', 32),
        'full-native33': ('full33_manifest_verified', 33),
        'full-native34': ('full34_manifest_verified', 34),
        'full-native35': ('full35_manifest_verified', 35),
        'full-native36': ('full36_manifest_verified', 36),
        'full-native37': ('full37_manifest_verified', 37),
        'full-native38': ('full38_manifest_verified', 38),
        'full-native39': ('full39_manifest_verified', 39),
    }[args.build_profile]
    require(report['native_build'][verified_field] is True
            and report['native_build']['module_count'] == expected_count,
            'format-env-display ABI requires the complete selected native module build')
    bind(Path(__file__), report)
    contract = json.loads(bind(ROOT / 'hia/format_env_display_buffer_contract.json',
                               report, CONTRACT_SHA))
    corpus = json.loads(bind(ROOT / 'hia/tests/format_env_display_oracle_inputs.json',
                             report, CORPUS_SHA))
    source = bind(ROOT / 'hia/format_env_display.hepta', report, contract['source']['sha256'])
    require(contract['source'] == corpus['source'] and len(source) == contract['source']['bytes']
            and corpus['contract']['sha256'] == CONTRACT_SHA
            and contract['schema'] == 'codex.hia.format-env-display-buffer-contract.v1'
            and contract['module'] == 'format_env_display'
            and contract['symbol'] == 'codex_hia_format_env_display'
            and contract['source_frame']['chunk_bytes'] == 4096
            and len(contract['source_frame']['sort_state_word_order']) == 18
            and len(contract['source_frame']['mask_state_word_order']) == 3
            and len(contract['source_frame']['join_state_word_order']) == 7
            and contract['statuses']['invalid'] == INVALID
            and contract['statuses']['short_output'] == SHORT
            and contract['statuses']['arithmetic_overflow'] == OVERFLOW
            and contract['compiler_boundary']['entry_profile'] == 'borrowed-buffers-u32-v1'
            and corpus['schema'] == 'codex.hia.format-env-display-oracle-inputs.v1'
            and corpus['counts'] == LITERAL_COUNTS,
            'source/contract/corpus identity differs')
    # Record real host source inputs; this raw gate does not execute Rust or its tests.
    for path in ('codex-rs/utils/cli/src/hia_native_format_env_display.rs',
                 'codex-rs/utils/cli/src/hia_native_format_env_display_wire.rs',
                 'codex-rs/utils/cli/src/format_env_display.rs',
                 'codex-rs/utils/cli/src/format_env_display_additional_tests.rs',
                 'codex-rs/utils/cli/build.rs'):
        bind(ROOT / path, report)
    library = directory / 'libcodex_hia_format_env_display.so'
    require(str(library) in report['inputs'], 'namespaced library was not admitted')
    streams, raw_cases = corpus['streams'], corpus['raw_cases']
    require(len(streams) == LITERAL_COUNTS['streams']
            and sum(len(item['calls']) for item in streams) == LITERAL_COUNTS['stream_calls']
            and len(raw_cases) == LITERAL_COUNTS['raw_cases'], 'literal cardinality differs')
    identifiers = [item['id'] for item in streams + raw_cases]
    require(len(identifiers) == len(set(identifiers)), 'duplicate corpus identifier')
    fill = bytes.fromhex(corpus['case_defaults']['output_initial_fill_hex'])
    report['inputs_unchanged_before_load'] = recheck_inputs(report)
    require(report['inputs_unchanged_before_load'], 'input changed before native load')
    probe = RawAbi(library, report)
    for stream in streams:
        require(bool(stream['calls']), 'empty literal stream')
        row = (sort_stream(probe, stream, fill) if stream['kind'] == 'sort'
               else byte_stream(probe, stream, fill))
        report['streams'].append(row)
    for item in raw_cases:
        probe.call(item['call'], fill, f"raw/{item['id']}")
    require(len(report['calls']) == LITERAL_COUNTS['literal_frames'],
            'not every frozen literal frame completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native32', 'full-native33', 'full-native34', 'full-native35', 'full-native36', 'full-native37', 'full-native38', 'full-native39'],
                        default='full-native32')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {
        'schema': 'codex.hia.format-env-display.raw-abi.v1', 'passed': False,
        'requested_build_profile': args.build_profile,
        'loaded_entry': 'libcodex_hia_format_env_display.so:codex_hia_format_env_display',
        'abi_scope': 'Normal native-selfhost B3 namespaced borrowed-buffers-u32-v1 only.',
        'return_rule': 'Full u64 equals the literal Core u32; nonzero high word is never masked.',
        'semantic_reference': 'Frozen literal requests/states/results, without a sorting model.',
        'large_length_scope': 'Logical tiny-fragment continuation cases, not full >4GiB executions.',
        'seed_direct_profile_executed': False, 'original_rust_oracle_executed': False,
        'public_owner_qualified': False, 'performance_qualified': False,
        'whole_codex_rewritten': False, 'default_release_migrated': False, 'skipped': 0,
        'literal_frames_expected': LITERAL_COUNTS['literal_frames'],
        'calls_started': 0, 'calls': [], 'streams': [], 'active_case': None,
    }
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
                try:
                    unchanged = recheck_inputs(report)
                    report['inputs_unchanged_after_calls'] = unchanged
                    report['passed'] = report['passed'] and unchanged
                    if not unchanged:
                        report.setdefault('error', 'source or native input changed during gate')
                except BaseException as error:
                    report['passed'] = False
                    report['input_recheck_error'] = f'{type(error).__name__}: {error}'
            report['literal_frames_checked'] = sum(row['passed'] for row in report['calls'])
            output.seek(0)
            output.write(json.dumps(report, indent=2) + '\n')
            output.truncate()
            output.flush()
    print(json.dumps({'passed': report['passed'], 'report': str(args.report),
                      'sha256': digest(args.report.read_bytes()),
                      'literal_frames_checked': report['literal_frames_checked'],
                      'error': report.get('error')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
