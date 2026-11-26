#!/usr/bin/env python3
"""Admit native37 and check literal generic inline parser state/commands."""
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


def frame(mode, count=0, position=0, length=0, index=0, keep=0,
          action=0, take=0, consume=0, tag=0):
    return [1, mode, count, position, length, index, keep,
            action, take, consume, tag, 0]


def cases():
    # Each expected state is literal; no substring/suffix oracle computes it.
    rows = [
        ('begin', b'', b'', frame(0, 9, 7, 2, 1, 3), frame(0, position=MAX)),
        ('first', b'qabvxy', b'ab', frame(1, position=MAX), frame(1, 1, 1, 2)),
        ('shorter-tie', b'qabvxy', b'a', frame(1, 1, 1, 2), frame(1, 2, 1, 2)),
        ('same-tie', b'qabvxy', b'ab', frame(1, 2, 1, 2), frame(1, 3, 1, 2)),
        ('longer-tie', b'qabvxy', b'ab', frame(1, 1, 1, 1), frame(1, 2, 1, 2, 1)),
        ('earlier', b'0aXlong!?tail', b'a', frame(1, 1, 3, 4), frame(1, 2, 1, 1, 1)),
        ('unicode-prefix', 'abcé'.encode(), 'éb'.encode(), frame(1, position=MAX), frame(1, 1, MAX, keep=2)),
        ('unicode-two-byte', 'x\u0080'.encode(), '\u0080z'.encode(), frame(1, position=MAX), frame(1, 1, MAX, keep=2)),
        ('word-tail-7', b'!abcdefg?', b'abcdefg', frame(1, position=MAX), frame(1, 1, 1, 7)),
        ('word-exact-8', b'!abcdefgh?', b'abcdefgh', frame(1, position=MAX), frame(1, 1, 1, 8)),
        ('word-tail-9', b'!abcdefghi?', b'abcdefghi', frame(1, position=MAX), frame(1, 1, 1, 9)),
        ('word-tail-15', b'!abcdefghijklmno?', b'abcdefghijklmno', frame(1, position=MAX), frame(1, 1, 1, 15)),
        ('word-exact-16', b'!abcdefghijklmnop?', b'abcdefghijklmnop', frame(1, position=MAX), frame(1, 1, 1, 16)),
        ('word-tail-17', b'!abcdefghijklmnopq?', b'abcdefghijklmnopq', frame(1, position=MAX), frame(1, 1, 1, 17)),
        ('word-mismatch-next', b'aaaaaaaXaaaaaaaaY', b'aaaaaaaaY', frame(1, position=MAX), frame(1, 1, 8, 9)),
        ('word-tail-mismatch', b'abcdefghXabcdefghY', b'abcdefghY', frame(1, position=MAX), frame(1, 1, 9, 9)),
        ('word-no-match', b'abcdefghX', b'abcdefghY', frame(1, position=MAX), frame(1, 1, MAX)),
        ('word-prefix-retention', b'!abcdefghijklmnop', b'abcdefghijklmnopq', frame(1, position=MAX), frame(1, 1, MAX, keep=16)),
        ('word-unicode-prefix', '!ééééé'.encode(), 'éééééz'.encode(), frame(1, position=MAX), frame(1, 1, MAX, keep=10)),
        ('word-close', b'xxabcdefgh!', b'abcdefgh', frame(3), frame(3, action=4, take=2, consume=10)),
        ('empty-source', b'', b'a', frame(1, position=MAX), frame(1, 1, MAX)),
        ('open-command', b'qabvxy', b'', frame(2, 3, 1, 2), frame(2, 3, 1, 2, action=2, take=1, consume=3)),
        ('visible-command', 'abcé'.encode(), b'', frame(2, 1, MAX, keep=2), frame(2, 1, MAX, keep=2, action=1, take=3, consume=3)),
        ('first-unicode-close', 'xééz'.encode(), 'é'.encode(), frame(3), frame(3, action=4, take=1, consume=3)),
        ('body-prefix', 'abcé'.encode(), 'éb'.encode(), frame(3), frame(3, keep=2, action=3, take=3, consume=3)),
        ('empty-body', b'', b'/', frame(3), frame(3, action=3)),
        ('eof-visible', b'<a', b'', frame(4), frame(4, action=5, take=2, consume=2)),
        ('eof-active', b'</', b'', frame(4, 1), frame(4, 1, action=6, take=2, consume=2)),
        ('eof-empty-active', b'', b'', frame(4, 1), frame(4, 1, action=6)),
        ('empty-opener', b'x', b'', frame(1, position=MAX), None),
        ('ordinal-overflow', b'x', b'a', frame(1, MAX, MAX), None),
        ('position-outside', b'x', b'a', frame(1, 1, 2, 1), None),
        ('zero-match', b'x', b'a', frame(1, 1, 0, 0), None),
        ('match-outside', b'x', b'a', frame(1, 1, 0, 2), None),
        ('index-outside', b'x', b'a', frame(1, 1, 0, 1, 1), None),
        ('keep-outside', b'x', b'a', frame(1, 1, MAX, keep=2), None),
        ('fold-suffix-splits-scalar', 'xéz'.encode(), b'a', frame(1, 1, MAX, keep=2), None),
        ('fold-opener-start-splits-scalar', 'xéz'.encode(), b'a', frame(1, 1, 2, 1), None),
        ('fold-opener-end-splits-scalar', 'xéz'.encode(), b'a', frame(1, 1, 1, 1), None),
        ('resolve-suffix-splits-scalar', 'xéz'.encode(), b'', frame(2, 1, MAX, keep=2), None),
        ('resolve-opener-start-splits-scalar', 'xéz'.encode(), b'', frame(2, 1, 2, 1), None),
        ('resolve-opener-end-splits-scalar', 'xéz'.encode(), b'', frame(2, 1, 1, 1), None),
        ('fold-scalar-boundaries-valid', 'xéz'.encode(), b'a', frame(1, 2, 1, 2, keep=3), frame(1, 3, 1, 2, keep=3)),
        ('resolve-scalar-boundaries-valid', 'xéz'.encode(), b'', frame(2, 2, 1, 2, keep=3), frame(2, 2, 1, 2, keep=3, action=2, take=1, consume=3)),
        ('absent-length', b'x', b'a', frame(1, 1, MAX, 1), None),
        ('absent-index', b'x', b'a', frame(1, 1, MAX, index=1), None),
        ('unseen-prefix', b'x', b'a', frame(1, position=MAX, keep=1), None),
        ('empty-spec-list', b'x', b'', frame(2, position=MAX), None),
        ('close-ordinal', b'x', b'a', frame(3, 1), None),
        ('close-stale-state', b'x', b'a', frame(3, position=1), None),
        ('empty-closer', b'x', b'', frame(3), None),
        ('bad-active-flag', b'x', b'', frame(4, 2), None),
        ('eof-stale-state', b'x', b'', frame(4, keep=1), None),
    ]
    for field, value in [(0, 0), (1, 5), (7, 1), (8, 1), (9, 1), (10, 1), (11, 1)]:
        bad = frame(0)
        bad[field] = value
        rows.append((f'bad-header-{field}', b'', b'', bad, None))
    rows.extend([
        ('large-pending', b'a' * 1_048_577 + b'<', b'<>', frame(1, position=MAX), frame(1, 1, MAX, keep=1)),
        ('large-delimiter-prefix', b'x' * 1_048_577, b'x' * 1_048_577 + b'$', frame(1, position=MAX), frame(1, 1, MAX, keep=1_048_577)),
        ('large-delimiter-match', b'x' * 1_048_577 + b'$body', b'x' * 1_048_577 + b'$', frame(1, position=MAX), frame(1, 1, 0, 1_048_578)),
    ])
    return rows


def verify(directory, report):
    native_inputs(directory / 'network_host.so', ROOT / 'network_host.hepta', 'full-native37', report)
    if not report['native_build']['full37_manifest_verified']:
        raise RuntimeError('the complete native37 build was not admitted')
    contract_path = ROOT / 'inline_hidden_tag_buffer_contract.json'
    contract_bytes = contract_path.read_bytes()
    contract = json.loads(contract_bytes)
    source = (ROOT / 'inline_hidden_tag.hepta').read_bytes()
    if (contract['schema'] != 'codex.hia.inline-hidden-tag-buffer.v1'
            or contract['source_sha256'] != hashlib.sha256(source).hexdigest()
            or contract['source_bytes'] != len(source)):
        raise RuntimeError('inline source/contract binding differs')
    report['inputs'][str(contract_path)] = hashlib.sha256(contract_bytes).hexdigest()
    report['inputs'][str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    library = ctypes.CDLL(str(directory / 'inline_hidden_tag.so'))
    function = library.f0
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    function.restype = ctypes.c_uint64
    literals = cases()
    for label, raw, delimiter, request, response in literals:
        for capacity in (0, 95, 96, 112):
            for fill in (0, 0xA5):
                source = bytearray(GUARD + raw + GUARD)
                needle = bytearray(GUARD + delimiter + GUARD)
                payload = struct.pack('<12Q', *request) + bytes([fill]) * max(0, capacity - 96)
                output = bytearray(GUARD + payload + GUARD)
                before = [bytes(item) for item in (source, output, needle)]
                buffers = [(ctypes.c_ubyte * len(item)).from_buffer(item) for item in (source, output, needle)]
                pointers = [ctypes.cast(ctypes.byref(item, len(GUARD)), ctypes.c_void_p) for item in buffers]
                returned = function(pointers[0], len(raw), pointers[1], capacity, pointers[2], len(delimiter))
                expected_status = SHORT if capacity < 96 else INVALID if response is None else 96
                expected_output = bytearray(before[1])
                if expected_status == 96:
                    expected_output[len(GUARD):len(GUARD) + 96] = struct.pack('<12Q', *response)
                passed = (returned == expected_status and bytes(output) == bytes(expected_output)
                          and bytes(source) == before[0] and bytes(needle) == before[2])
                report['calls'].append({'case': label, 'capacity': capacity, 'fill': fill,
                                        'returned': returned, 'passed': passed})
                if not passed:
                    raise RuntimeError(f'inline literal mismatch at {label}, capacity {capacity}, fill {fill}')
    report['literal_cases'] = len(literals)
    report['native_calls'] = len(report['calls'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {'schema': 'codex.hia.inline-hidden-tag-abi.v1', 'passed': False, 'calls': [],
              'scope': 'Exact native37 literal state, selection, capacities and guards; original public owner tests are separate.'}
    try:
        verify(args.library_dir.resolve(strict=True), report)
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
