#!/usr/bin/env python3
"""Exercise literal UTF-8 results through the fully bound native36 ELF."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[1]
GUARD = bytes(range(1, 18))
CASES = [
    (b'', (0, 0, 0)),
    (b'hello\0world', (0, 11, 0)),
    ('aé中🦀'.encode(), (0, 10, 0)),
    (b'\xc2\x80\xdf\xbf\xe0\xa0\x80\xed\x9f\xbf', (0, 10, 0)),
    (b'\xee\x80\x80\xf0\x90\x80\x80\xf4\x8f\xbf\xbf', (0, 11, 0)),
    (b'\x80', (1, 0, 1)),
    (b'\xc0\x80', (1, 0, 1)),
    (b'\xc1\xbf', (1, 0, 1)),
    (b'\xf5\x80\x80\x80', (1, 0, 1)),
    (b'\xff', (1, 0, 1)),
    (b'x\xc3(', (1, 1, 1)),
    (b'\xe0\x9f\xbf', (1, 0, 1)),
    (b'\xed\xa0\x80', (1, 0, 1)),
    (b'\xf0\x8f\xbf\xbf', (1, 0, 1)),
    (b'\xf4\x90\x80\x80', (1, 0, 1)),
    (b'x\xe2\x82!', (1, 1, 2)),
    (b'x\xf0\x9f\xa6!', (1, 1, 3)),
    (b'\xc2', (2, 0, 0)),
    (b'x\xe0', (2, 1, 0)),
    (b'x\xe0\xa0', (2, 1, 0)),
    (b'x\xf0', (2, 1, 0)),
    (b'x\xf0\x90', (2, 1, 0)),
    (b'x\xf0\x90\x80', (2, 1, 0)),
    (b'a' * 1_048_577, (0, 1_048_577, 0)),
    (b'a' * 1_048_577 + b'\xe2\x82', (2, 1_048_577, 0)),
]


def verify(directory, report):
    native_inputs(directory / 'network_host.so', ROOT / 'network_host.hepta',
                  'full-native36', report)
    if not report['native_build']['full36_manifest_verified']:
        raise RuntimeError('the complete current36 build was not admitted')
    contract_path = ROOT / 'utf8_stream_buffer_contract.json'
    contract_bytes = contract_path.read_bytes()
    contract = json.loads(contract_bytes)
    source_sha = hashlib.sha256((ROOT / 'utf8_stream.hepta').read_bytes()).hexdigest()
    if (contract['schema'] != 'codex.hia.utf8-stream-buffer.v1'
            or contract['source_sha256'] != source_sha
            or contract['entry_profile'] != 'borrowed-buffers-u32-v1'):
        raise RuntimeError('UTF-8 contract/source binding differs')
    report['inputs'][str(contract_path)] = hashlib.sha256(contract_bytes).hexdigest()
    report['inputs'][str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    library = ctypes.CDLL(str(directory / 'utf8_stream.so'))
    function = library.f0
    function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    function.restype = ctypes.c_uint64
    for index, (raw, expected) in enumerate(CASES):
        for capacity in (0, 31, 32, 48):
            for fill in (0, 0xa5):
                source = bytearray(GUARD + raw + GUARD)
                output = bytearray(GUARD + bytes([fill]) * capacity + GUARD)
                workspace = bytearray(GUARD + b'untouched workspace' + GUARD)
                before = [bytes(value) for value in (source, output, workspace)]
                buffers = [(ctypes.c_ubyte * len(value)).from_buffer(value)
                           for value in (source, output, workspace)]
                pointers = [ctypes.cast(ctypes.byref(value, len(GUARD)), ctypes.c_void_p)
                            for value in buffers]
                returned = function(pointers[0], len(raw), pointers[1], capacity,
                                    pointers[2], len(b'untouched workspace'))
                wanted = bytearray(before[1])
                status = 0xffff_fffe if capacity < 32 else 32
                if capacity >= 32:
                    wanted[len(GUARD):len(GUARD) + 32] = struct.pack('<4Q', 1, *expected)
                passed = (returned == status and bytes(output) == bytes(wanted)
                          and bytes(source) == before[0] and bytes(workspace) == before[2])
                report['calls'].append({'case': index, 'source_bytes': len(raw),
                                        'capacity': capacity, 'fill': fill,
                                        'returned': returned, 'passed': passed})
                if not passed:
                    raise RuntimeError(f'UTF-8 ABI mismatch at literal {index}')
    report['literal_cases'] = len(CASES)
    report['native_calls'] = len(report['calls'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {'schema': 'codex.hia.utf8-stream-abi.v1', 'passed': False, 'calls': [],
              'scope': 'Native36 admission and literal UTF-8 buffers; public Rust tests are separate.'}
    try:
        verify(args.library_dir.resolve(strict=True), report)
        if not recheck_inputs(report):
            raise RuntimeError('bound build/source input changed during execution')
        report['passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'native_calls': report['native_calls'],
                      'literal_cases': report['literal_cases']}))


if __name__ == '__main__':
    main()
