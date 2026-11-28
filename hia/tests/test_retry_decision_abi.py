#!/usr/bin/env python3
"""Check literal retry decisions, u64 progression and atomic native38 ABI errors."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[1]
MAX = (1 << 64) - 1
INVALID, SHORT = 0xFFFFFFFF, 0xFFFFFFFE
GUARD = bytes(range(1, 18))


def request(attempt=0, maximum=1, rate=0, server=0, transport=0, kind=0, status=200):
    return [1, attempt, maximum, rate, server, transport, kind, status]


def cases():
    # Boolean rows and expected next attempts are literal, independent of HIA.
    never = [False] * 8
    rate = [False, True, False, True, False, True, False, True]
    server = [False, False, True, True, False, False, True, True]
    transport = [False, False, False, False, True, True, True, True]
    policies = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0),
                (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
    rows = []
    for status, expected in [(100, never), (200, never), (299, never), (400, never),
                             (428, never), (429, rate), (430, never), (499, never),
                             (500, server), (503, server), (599, server),
                             (600, never), (999, never)]:
        for ordinal, (a, b, c) in enumerate(policies):
            frame = request(rate=a, server=b, transport=c, status=status)
            rows.append((f'http-{status}-policy-{ordinal}', frame, [1, 1] if expected[ordinal] else [0, 0]))
    for kind, expected in [(1, transport), (2, transport), (3, transport), (4, never)]:
        for ordinal, (a, b, c) in enumerate(policies):
            frame = request(rate=a, server=b, transport=c, kind=kind, status=0)
            rows.append((f'kind-{kind}-policy-{ordinal}', frame, [1, 1] if expected[ordinal] else [0, 0]))
    rows.extend([
        ('zero-limit', request(maximum=0, rate=1, server=1, transport=1, status=429), [0, 0]),
        ('equal-limit', request(attempt=5, maximum=5, transport=1, kind=1, status=0), [0, 0]),
        ('max-next', request(attempt=MAX - 1, maximum=MAX, transport=1, kind=1, status=0), [1, MAX]),
        ('equal-max', request(attempt=MAX, maximum=MAX, transport=1, kind=1, status=0), [0, 0]),
        ('past-limit', request(attempt=MAX, maximum=0, rate=1, status=429), [0, 0]),
        ('full-u64-counter', request(attempt=4_294_967_295, maximum=4_294_967_296, rate=1, status=429), [1, 4_294_967_296]),
    ])
    for index, value in [(0, 0), (0, 2), (3, 2), (4, 2), (5, 2), (6, 5), (6, MAX),
                         (7, 99), (7, 1000), (7, MAX)]:
        frame = request()
        frame[index] = value
        rows.append((f'invalid-word-{index}-{value}', frame, None))
    rows.extend([
        ('status-on-timeout', request(kind=1, status=100), None),
        ('status-on-other', request(kind=4, status=1), None),
    ])
    encoded = [(label, struct.pack('<8Q', *frame), b'', expected) for label, frame, expected in rows]
    normal = struct.pack('<8Q', *request())
    encoded.extend([
        ('empty-request', b'', b'', None),
        ('short-request', normal[:-1], b'', None),
        ('long-request', normal + b'\0', b'', None),
        ('nonempty-workspace', normal, b'x', None),
    ])
    return encoded


def verify(directory, report, profile='full-native38'):
    native_inputs(directory / 'network_host.so', ROOT / 'network_host.hepta', profile, report)
    verified = {'full-native38': 'full38_manifest_verified', 'full-native39': 'full39_manifest_verified', 'full-native41': 'full41_manifest_verified'}[profile]
    if not report['native_build'][verified]:
        raise RuntimeError('the requested complete build was not admitted')
    contract_path = ROOT / 'retry_decision_buffer_contract.json'
    contract_bytes = contract_path.read_bytes()
    contract = json.loads(contract_bytes)
    source = (ROOT / 'retry_decision.hepta').read_bytes()
    if (contract['schema'] != 'codex.hia.retry-decision-buffer.v1'
            or contract['source_sha256'] != hashlib.sha256(source).hexdigest()
            or contract['source_bytes'] != len(source)):
        raise RuntimeError('retry source/contract binding differs')
    report['inputs'][str(contract_path)] = hashlib.sha256(contract_bytes).hexdigest()
    report['inputs'][str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    function = ctypes.CDLL(str(directory / 'retry_decision.so')).f0
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    function.restype = ctypes.c_uint64
    literals = cases()
    for label, raw, workspace, expected in literals:
        for capacity in (0, 15, 16, 24):
            for fill in (0, 0xA5):
                source = bytearray(GUARD + raw + GUARD)
                output = bytearray(GUARD + bytes([fill]) * capacity + GUARD)
                scratch = bytearray(GUARD + workspace + GUARD)
                before = [bytes(item) for item in (source, output, scratch)]
                buffers = [(ctypes.c_ubyte * len(item)).from_buffer(item) for item in (source, output, scratch)]
                pointers = [ctypes.cast(ctypes.byref(item, len(GUARD)), ctypes.c_void_p) for item in buffers]
                result = function(pointers[0], len(raw), pointers[1], capacity, pointers[2], len(workspace))
                expected_status = SHORT if capacity < 16 else INVALID if expected is None else 16
                expected_output = bytearray(before[1])
                if expected_status == 16:
                    expected_output[len(GUARD):len(GUARD) + 16] = struct.pack('<2Q', *expected)
                passed = (result == expected_status and bytes(output) == bytes(expected_output)
                          and bytes(source) == before[0] and bytes(scratch) == before[2])
                report['calls'].append({'case': label, 'capacity': capacity, 'fill': fill,
                                        'returned': result, 'passed': passed})
                if not passed:
                    raise RuntimeError(f'retry literal mismatch at {label}, capacity {capacity}, fill {fill}')
    report['literal_cases'] = len(literals)
    report['native_calls'] = len(report['calls'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native38', 'full-native39', 'full-native41'], default='full-native38')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {'schema': 'codex.hia.retry-decision-abi.v1', 'passed': False, 'calls': [],
              'requested_build_profile': args.build_profile,
              'scope': 'Exact selected-build literal retry states, full-width attempts, capacities and guards; public async provider tests are separate.'}
    try:
        verify(args.library_dir.resolve(strict=True), report, args.build_profile)
        if not recheck_inputs(report):
            raise RuntimeError('bound input changed during raw execution')
        report['passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'literal_cases': report['literal_cases'], 'native_calls': report['native_calls']}))


if __name__ == '__main__':
    main()
