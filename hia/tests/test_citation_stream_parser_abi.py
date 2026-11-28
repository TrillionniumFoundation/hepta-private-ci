#!/usr/bin/env python3
"""Check literal Citation frames through a fully admitted native33 B3 ABI.

This gate never builds or runs a reference parser. All requests, next states,
event bytes and public-call results are frozen literals. Repetition describes
exact byte data, not a parser model. Internal byte frames need not be UTF8.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SHA = 'f29cc68ea590ddc372c12813d4a0eb59705b353643031c286dd883816809719d'
CORPUS_SHA = '513996cd1f4adc1c58e8acb18c4e16c08a100a3e620277bb9cee475c3478bbf5'
GUARD = bytes(range(1, 34))
INVALID, SHORT = 0xFFFFFFFF, 0xFFFFFFFE
ERRORS = (INVALID, SHORT)
LITERAL_COUNTS = {
    'streams': 13, 'stream_call_templates': 46, 'stream_expanded_calls': 558,
    'raw_cases': 184, 'literal_frame_templates': 230, 'native_calls_planned': 742,
}


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
    require(len(raw) == case['source_bytes'] and len(raw) <= 4137,
            'literal source extent differs')
    if 'source_words_le' in case:
        require(len(case['source_words_le']) == 5
                and raw == words(case['source_words_le'])
                + bytes.fromhex(case['source_payload_hex']), 'literal source fields differ')
    return raw


def literal_bytes(value):
    if set(value) == {'literal_hex'}:
        return bytes.fromhex(value['literal_hex'])
    require(set(value) == {'literal_unit_hex', 'repeat'}
            and type(value['repeat']) is int and 0 <= value['repeat'] <= 1052672,
            'unknown literal byte-data expression')
    return bytes.fromhex(value['literal_unit_hex']) * value['repeat']


def literal_prefix(case):
    expected = case['expected_core_return']
    if expected in ERRORS:
        require(case['expected_written_bytes'] == 0
                and 'expected_output_prefix_hex' not in case
                and 'expected_header_words_le' not in case
                and 'expected_events' not in case, 'error expectation promises output')
        return b''
    require(len(case['expected_header_words_le']) == 6,
            'literal output header extent differs')
    header = words(case['expected_header_words_le'])
    events = case['expected_events']
    records = bytearray()
    payload_bytes = 0
    for event in events:
        payload = bytes.fromhex(event['payload_hex'])
        require(type(event['kind']) is int and 0 <= event['kind'] <= 3,
                'unknown literal event kind')
        records.extend(struct.pack('<2Q', event['kind'], len(payload)))
        records.extend(payload)
        payload_bytes += len(payload)
    prefix = bytes.fromhex(case['expected_output_prefix_hex'])
    require(prefix == header + records and unpack(header)[4:] == (len(events), payload_bytes)
            and len(prefix) == expected == case['expected_written_bytes'],
            'literal event encoding differs from frozen prefix')
    return prefix


class RawFailure(Exception):
    def __init__(self, record):
        self.record = record
        super().__init__(record['label'])


class RawAbi:
    def __init__(self, library, report):
        self.library = ctypes.CDLL(str(library))
        self.function = self.library.codex_hia_citation_stream_parser
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.report = report

    def call(self, case, fill, label):
        raw = frame(case)
        capacity = case['output_capacity']
        workspace = bytes.fromhex(case['workspace_hex'])
        expected = case['expected_core_return']
        require(type(capacity) is int and 0 <= capacity <= 135283
                and len(workspace) <= 32 and len(fill) == 1,
                'call is outside frozen live-buffer extents')
        require(type(expected) is int and (expected in ERRORS or 48 <= expected <= 135266),
                'unknown literal Core expectation')
        prefix = literal_prefix(case)
        require(capacity >= len(prefix), 'literal prefix exceeds output capacity')
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
            'actual_prefix_sha256': digest(actual), 'literal_prefix_sha256': digest(prefix),
            'logical_state_only': case['logical_state_only'], 'passed': False,
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


def decode_events(result, request):
    require(len(result) >= 48, 'native result lacks its header')
    version, op, active, prefix, count, payload_bytes = unpack(result[:48])
    require(version == 1 and op == unpack(request[8:16])[0]
            and active <= 1 and prefix <= 17 + active, 'native header is invalid')
    events, position, payload_total, previous = [], 48, 0, None
    for _ in range(count):
        require(len(result) - position >= 16, 'native record lacks its header')
        kind, size = unpack(result[position:position + 16])
        position += 16
        require(size <= len(result) - position, 'native record exceeds result')
        payload = result[position:position + size]
        position += size
        payload_total += size
        if op == 2:
            require(kind == 3 and count == 1 and size == prefix,
                    'Inspect returned a noncanonical Pending record')
        else:
            require(kind in (0, 1, 2) and ((kind == 2 and size == 0)
                    or (kind in (0, 1) and size > 0)), 'invalid normal event')
            require(kind not in (0, 1) or previous != kind,
                    'adjacent payload events were not coalesced in HIA')
        events.append((kind, payload))
        previous = kind
    require(position == len(result) and payload_total == payload_bytes,
            'native event counts or exact EOF differ')
    if op == 2:
        require(count == 1 and result[16:32] == request[16:32]
                and len(result) == 64 + prefix, 'Inspect changed state or extent')
    elif op == 1:
        require((active, prefix) == (0, 0), 'Finish did not reset state')
    return (active, prefix), events


def stream(probe, item, fill):
    state, body, order, batches = (0, 0), bytearray(), [], {}
    calls = 0
    for index, step in enumerate(item['calls']):
        repeat = step['repeat']
        require(type(repeat) is int and 1 <= repeat <= 257, 'invalid literal repeat count')
        case, name = step['call'], step['public_call']
        raw = frame(case)
        op = unpack(raw[8:16])[0]
        require(case['expected_core_return'] not in ERRORS and not case['logical_state_only'],
                'stream has an error or hypothetical-state fixture')
        if op == 2:
            require(name is None, 'Inspect must not create a public push/finish call')
        else:
            require(op in (0, 1) and isinstance(name, str), 'unknown public operation')
            if name not in batches:
                order.append(name)
                batches[name] = {'visible': bytearray(), 'citations': [],
                                 'input': bytearray(), 'op': op}
            require(name == order[-1] and batches[name]['op'] == op,
                    'noncontiguous or mixed public-call group')
        for iteration in range(repeat):
            require(raw[16:32] == struct.pack('<2Q', *state),
                    'literal continuation is not the actual preceding native state')
            request, result = probe.call(case, fill, f"stream/{item['id']}/{index}/{iteration}")
            next_state, events = decode_events(result, request)
            if op != 2:
                batches[name]['input'].extend(request[40:])
            for kind, payload in events:
                if kind == 0:
                    batches[name]['visible'].extend(payload)
                elif kind == 1:
                    body.extend(payload)
                elif kind == 2:
                    batches[name]['citations'].append(bytes(body))
                    body.clear()
                else:
                    require(op == 2 and state == next_state,
                            'Pending is not a read-only inspection')
            state = next_state
            require(state[0] != 0 or not body, 'inactive state retained uncommitted body')
            calls += 1
    expected = item['expected_public_results']
    require(order == [value['public_call'] for value in expected], 'public call order differs')
    public_results = []
    for value in expected:
        name = value['public_call']
        batch = batches[name]
        visible, citations = bytes(batch['visible']), batch['citations']
        require(visible == literal_bytes(value['visible'])
                and citations == [literal_bytes(v) for v in value['citations']],
                'complete public-call visible/extracted literal differs')
        # Only complete public inputs/results are UTF8; never decode internal fragments.
        batch['input'].decode('utf-8')
        visible.decode('utf-8')
        for body_value in citations:
            body_value.decode('utf-8')
        public_results.append({'public_call': name, 'visible_bytes': len(visible),
                               'visible_sha256': digest(visible),
                               'citation_bytes': [len(v) for v in citations],
                               'citation_sha256': [digest(v) for v in citations]})
    require(struct.pack('<2Q', *state) == words(item['expected_final_state_words'])
            and bytes(body) == literal_bytes(item['expected_pending_body']),
            'final finite state or pending body differs')
    return {'id': item['id'], 'native_calls': calls, 'public_results': public_results,
            'final_state': list(state), 'pending_body_bytes': len(body)}


def verify(args, report):
    directory = args.library_dir.resolve(strict=True)
    native_inputs(directory / 'network_host.so', ROOT / 'hia/network_host.hepta',
                  args.build_profile, report)
    verified_field, expected_count = {
        'full-native33': ('full33_manifest_verified', 33),
        'full-native34': ('full34_manifest_verified', 34),
        'full-native35': ('full35_manifest_verified', 35),
        'full-native36': ('full36_manifest_verified', 36),
        'full-native37': ('full37_manifest_verified', 37),
        'full-native38': ('full38_manifest_verified', 38),
        'full-native39': ('full39_manifest_verified', 39),
        'full-native41': ('full41_manifest_verified', 41),
        'full-native42': ('full42_manifest_verified', 42),
    }[args.build_profile]
    require(report['native_build'][verified_field] is True
            and report['native_build']['module_count'] == expected_count,
            'Citation ABI requires the complete selected native module build')
    bind(Path(__file__), report)
    contract = json.loads(bind(ROOT / 'hia/citation_stream_parser_buffer_contract.json',
                               report, CONTRACT_SHA))
    corpus = json.loads(bind(ROOT / 'hia/tests/citation_stream_parser_oracle_inputs.json',
                             report, CORPUS_SHA))
    source = bind(ROOT / 'hia/citation_stream_parser.hepta', report, contract['source']['sha256'])
    require(contract['source'] == corpus['source'] and len(source) == contract['source']['bytes']
            and corpus['contract']['sha256'] == CONTRACT_SHA
            and contract['schema'] == 'codex.hia.citation-stream-parser-buffer-contract.v1'
            and contract['module'] == 'citation_stream_parser'
            and contract['symbol'] == 'codex_hia_citation_stream_parser'
            and contract['compiler_boundary']['entry_profile'] == 'borrowed-buffers-u32-v1'
            and contract['source_frame']['maximum_source_bytes'] == 4136
            and contract['capacity']['Push_maximum'] == 135266
            and contract['statuses']['invalid'] == INVALID
            and contract['statuses']['short_output'] == SHORT
            and corpus['schema'] == 'codex.hia.citation-stream-parser-oracle-inputs.v1'
            and corpus['counts'] == LITERAL_COUNTS, 'source/contract/corpus identity differs')
    # Bind real owner source; the raw gate does not execute Rust or the public oracles.
    for path in ('codex-rs/utils/stream-parser/src/hia_native_citation_stream_parser.rs',
                 'codex-rs/utils/stream-parser/src/hia_native_citation_stream_parser_wire.rs',
                 'codex-rs/utils/stream-parser/src/citation.rs',
                 'codex-rs/utils/stream-parser/src/citation_additional_tests.rs',
                 'codex-rs/utils/stream-parser/build.rs'):
        bind(ROOT / path, report)
    library = directory / 'libcodex_hia_citation_stream_parser.so'
    require(str(library) in report['inputs'], 'namespaced B3 library was not admitted')
    streams, raw_cases = corpus['streams'], corpus['raw_cases']
    require(len(streams) == LITERAL_COUNTS['streams']
            and sum(len(item['calls']) for item in streams) == LITERAL_COUNTS['stream_call_templates']
            and sum(step['repeat'] for item in streams for step in item['calls'])
            == LITERAL_COUNTS['stream_expanded_calls']
            and len(raw_cases) == LITERAL_COUNTS['raw_cases'], 'literal cardinality differs')
    identifiers = [item['id'] for item in streams + raw_cases]
    require(len(identifiers) == len(set(identifiers)), 'duplicate corpus identifier')
    fill = bytes.fromhex(corpus['case_defaults']['output_initial_fill_hex'])
    require(bytes.fromhex(corpus['case_defaults']['external_guard_hex']) == GUARD,
            'external guard literal differs')
    report['inputs_unchanged_before_load'] = recheck_inputs(report)
    require(report['inputs_unchanged_before_load'], 'input changed before native load')
    probe = RawAbi(library, report)
    for item in streams:
        require(bool(item['calls']), 'empty literal stream')
        report['streams'].append(stream(probe, item, fill))
    for item in raw_cases:
        probe.call(item['call'], fill, f"raw/{item['id']}")
    require(len(report['calls']) == LITERAL_COUNTS['native_calls_planned'],
            'not every frozen literal invocation completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native33', 'full-native34', 'full-native35', 'full-native36', 'full-native37', 'full-native38', 'full-native39', 'full-native41', 'full-native42'],
                        default='full-native33')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {
        'schema': 'codex.hia.citation-stream-parser.raw-abi.v1', 'passed': False,
        'requested_build_profile': args.build_profile,
        'loaded_entry': 'libcodex_hia_citation_stream_parser.so:codex_hia_citation_stream_parser',
        'abi_scope': 'Normal native-selfhost B3 namespaced borrowed-buffers-u32-v1 only.',
        'return_rule': 'Full u64 equals literal Core u32; nonzero high32 is never masked.',
        'semantic_reference': 'Literal states/events/public-call byte data, no parsing model.',
        'large_stream_scope': 'Two planned257x4096 actual byte streams, not >4GiB execution.',
        'hypothetical_state_scope': 'Standalone states are logical fixtures, not authenticated history.',
        'seed_direct_profile_executed': False, 'original_rust_oracle_executed': False,
        'public_owner_qualified': False, 'performance_qualified': False,
        'whole_codex_rewritten': False, 'default_release_migrated': False, 'skipped': 0,
        'literal_templates_expected': LITERAL_COUNTS['literal_frame_templates'],
        'native_calls_expected': LITERAL_COUNTS['native_calls_planned'],
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
            report['native_calls_checked'] = sum(row['passed'] for row in report['calls'])
            output.seek(0)
            output.write(json.dumps(report, indent=2) + '\n')
            output.truncate()
            output.flush()
    print(json.dumps({'passed': report['passed'], 'report': str(args.report),
                      'sha256': digest(args.report.read_bytes()),
                      'native_calls_checked': report['native_calls_checked'],
                      'error': report.get('error')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
