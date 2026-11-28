#!/usr/bin/env python3
"""Check literal item-budget frames through the admitted B3 namespaced ABI.

This gate loads the selected complete native build; it never builds one.
It does not execute the Rust public oracle or reconstruct its cost algorithm.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SHA = '696aa8373b3ef73dc724aa3ffd2350f2182246c3c5a7a4080f46b267c2e0fc46'
CORPUS_SHA = '1d11aacf42801d0b6830a457adaf8ac27ee4f89a7c64547c3b50d551bbf502f8'
GUARD = bytes(range(1, 34))
OK, INVALID, SHORT = 88, 0xFFFFFFFF, 0xFFFFFFFE
STATE_BYTES = 72
MAX_RAW_FRAME = 97  # Includes the literal one-byte-oversize INVALID case.
LITERAL_COUNTS = {'streams': 12, 'stream_calls': 63, 'raw_cases': 80, 'literal_frames': 143}


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
    require(len(raw) == case['source_frame_bytes'] and len(raw) <= MAX_RAW_FRAME,
            'literal source extent differs')
    if 'source_words_le' in case:
        require(raw == words(case['source_words_le']), 'literal source words differ')
    return raw


class RawFailure(Exception):
    def __init__(self, record):
        self.record = record
        super().__init__(record['label'])


class Probe:
    def __init__(self, library, report):
        self.library = ctypes.CDLL(str(library))
        self.function = self.library.codex_hia_output_item_budget
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.report = report

    def call(self, case, fill, label):
        raw = frame(case)
        capacity = case['output_capacity']
        workspace = bytes.fromhex(case['workspace_hex'])
        expected = case['expected_core_status']
        require(type(capacity) is int and 0 <= capacity <= 104
                and len(workspace) <= 3 and len(fill) == 1,
                'call is outside the frozen live-buffer extents')
        require(expected in (OK, INVALID, SHORT), 'unknown Core expectation')
        prefix = b''
        if expected == OK:
            prefix = bytes.fromhex(case['expected_output_prefix_hex'])
            require(capacity >= OK and len(prefix) == OK
                    and prefix == words(case['expected_output_words_le'])
                    and case['expected_written_bytes'] == OK,
                    'complete literal success output differs')
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
        if expected == OK:
            wanted[len(GUARD):len(GUARD) + OK] = prefix
        payload = bytes(output[len(GUARD):len(GUARD) + OK]) if capacity >= OK else b''
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
            'actual_prefix_hex': payload.hex(),
            'literal_prefix_hex': prefix.hex() if expected == OK else None,
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
        return raw, payload


def verify(args, report):
    directory = args.library_dir.resolve(strict=True)
    native_inputs(directory / 'network_host.so', ROOT / 'hia/network_host.hepta',
                  args.build_profile, report)
    verified_field, expected_count = {
        'full-native31': ('full31_manifest_verified', 31),
        'full-native32': ('full32_manifest_verified', 32),
        'full-native33': ('full33_manifest_verified', 33),
        'full-native34': ('full34_manifest_verified', 34),
        'full-native35': ('full35_manifest_verified', 35),
        'full-native36': ('full36_manifest_verified', 36),
        'full-native37': ('full37_manifest_verified', 37),
        'full-native38': ('full38_manifest_verified', 38),
        'full-native39': ('full39_manifest_verified', 39),
        'full-native41': ('full41_manifest_verified', 41),
    }[args.build_profile]
    require(report['native_build'][verified_field] is True
            and report['native_build']['module_count'] == expected_count,
            'item-budget raw ABI requires the complete requested module build')
    bind(Path(__file__), report)
    contract = json.loads(bind(ROOT / 'hia/output_item_budget_buffer_contract.json',
                               report, CONTRACT_SHA))
    corpus = json.loads(bind(ROOT / 'hia/tests/output_item_budget_oracle_inputs.json',
                             report, CORPUS_SHA))
    source = bind(ROOT / 'hia/output_item_budget.hepta', report, contract['source']['sha256'])
    require(contract['source'] == corpus['source'] and len(source) == contract['source']['bytes']
            and contract['schema'] == 'codex.hia.output-item-budget-buffer-contract.v1'
            and contract['module'] == 'output_item_budget'
            and contract['symbol'] == 'codex_hia_output_item_budget'
            and contract['source_frame']['admissible_lengths'] == [40, 80, 88, 96]
            and contract['source_frame']['state_bytes'] == STATE_BYTES
            and contract['output']['written_bytes'] == OK
            and [item['value'] for item in contract['statuses']] == [OK, INVALID, SHORT]
            and contract['compiler_boundary']['entry_profile'] == 'borrowed-buffers-u32-v1'
            and corpus['schema'] == 'codex.hia.output-item-budget-oracle-inputs.v1'
            and corpus['counts'] == LITERAL_COUNTS,
            'source/contract/corpus identity differs')
    # Capture the host source, without claiming this raw gate executes it.
    for path in ('codex-rs/utils/output-truncation/src/hia_native.rs',
                 'codex-rs/utils/output-truncation/src/lib.rs',
                 'codex-rs/utils/output-truncation/build.rs'):
        bind(ROOT / path, report)
    library = directory / 'libcodex_hia_output_item_budget.so'
    require(str(library) in report['inputs'], 'namespaced library was not admitted')
    report['inputs_unchanged_before_load'] = recheck_inputs(report)
    require(report['inputs_unchanged_before_load'], 'input changed before native load')
    streams, raw_cases = corpus['streams'], corpus['raw_cases']
    require(len(streams) == LITERAL_COUNTS['streams']
            and sum(len(item['calls']) for item in streams) == LITERAL_COUNTS['stream_calls']
            and len(raw_cases) == LITERAL_COUNTS['raw_cases'],
            'frozen literal cardinality differs')
    identifiers = [item['id'] for item in streams + raw_cases]
    require(len(identifiers) == len(set(identifiers)), 'duplicate corpus identifier')
    fill = bytes.fromhex(corpus['case_defaults']['output_initial_fill_hex'])
    probe = Probe(library, report)
    for stream in streams:
        require(bool(stream['calls']), 'empty literal stream')
        actual_state = None
        for index, case in enumerate(stream['calls']):
            raw = frame(case)
            require(case['expected_core_status'] == OK, 'stream contains an error fixture')
            if index == 0:
                require(len(raw) == 40 and raw[:8] == struct.pack('<Q', 0),
                        'literal stream does not start with Init')
            else:
                require(raw[8:80] == actual_state,
                        'literal continuation differs from the actual previous state')
            _, result = probe.call(case, fill, f"stream/{stream['id']}/{index}")
            actual_state = result[:STATE_BYTES]
        state_words = struct.unpack('<9Q', actual_state)
        require(state_words[1] == 2 and state_words[5] == state_words[6]
                and result[STATE_BYTES:] == struct.pack('<2Q', 4, 0),
                'literal stream did not reach Finish')
        report['streams'].append({'id': stream['id'], 'calls': len(stream['calls']),
                                  'final_prefix_hex': result.hex()})
    for item in raw_cases:
        probe.call(item['call'], fill, f"raw/{item['id']}")
    require(len(report['calls']) == LITERAL_COUNTS['literal_frames'],
            'not every frozen literal frame completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native31', 'full-native32', 'full-native33', 'full-native34', 'full-native35', 'full-native36', 'full-native37', 'full-native38', 'full-native39', 'full-native41'],
                        default='full-native31')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {
        'schema': 'codex.hia.output-item-budget.raw-abi.v1', 'passed': False,
        'requested_build_profile': args.build_profile,
        'loaded_entry': 'libcodex_hia_output_item_budget.so:codex_hia_output_item_budget',
        'abi_scope': 'Normal native-selfhost B3 namespaced borrowed-buffers-u32-v1 only.',
        'return_rule': 'Full u64 equals the literal Core u32; nonzero high word is never masked.',
        'semantic_reference': 'Frozen complete literal frames and outputs; no cost-algorithm model.',
        'seed_direct_profile_executed': False, 'original_rust_oracle_executed': False,
        'public_owner_qualified': False, 'performance_qualified': False,
        'whole_output_truncation_qualified': False, 'skipped': 0,
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
                report['inputs_unchanged_after_calls'] = recheck_inputs(report)
                report['passed'] &= report['inputs_unchanged_after_calls']
                if not report['inputs_unchanged_after_calls']:
                    report.setdefault('error', 'source or native input changed during the gate')
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
