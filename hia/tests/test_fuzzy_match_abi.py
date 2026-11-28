#!/usr/bin/env python3
"""Check frozen fuzzy-match frames through the complete native35 B3 ABI.

Expected scalars, states, records and scores are literal data. This gate never
runs a reference lowercase implementation, property lookup or fuzzy matcher.
The stream adapter only transports actual native state and applies native
commands; independent public Rust oracles remain separate required gates.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct

from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SHA = '232249e64ecbda1469b2d4a4da9ed45a9be497aa080deaff8714a8703360fe09'
CORPUS_SHA = '495577b808701e4648740dd66965777dc6fc702e38de5e559ec00b837668843a'
SHARD_BINDINGS = (
    ('fuzzy_match_oracle_streams.json', 'streams', 16),
    ('fuzzy_match_oracle_raw_core.json', 'raw_cases', 157),
    ('fuzzy_match_oracle_raw_hay_max.json', 'raw_cases', 1),
    ('fuzzy_match_oracle_raw_tail.json', 'raw_cases', 14),
)
GUARD = bytes(range(1, 34))
COUNTS = {
    'streams': 16, 'stream_call_templates': 70, 'raw_cases': 172,
    'literal_frame_templates': 242, 'native_calls_planned': 242,
}
STATUSES = {'OK': 0, 'INVALID': 1, 'SHORT': 2, 'COUNTER_OVERFLOW': 3}
HOST_FILES = (
    'hia_native_fuzzy_match.rs', 'hia_native_fuzzy_match_wire.rs',
    'hia_native_fuzzy_match_state.rs', 'hia_native_fuzzy_match_normalize.rs',
    'hia_native_fuzzy_match_matching.rs', 'hia_native_fuzzy_match_overflow.rs',
    'hia_native_fuzzy_match_wire_tests.rs',
    'hia_native_fuzzy_match_transition_tests.rs',
    'fuzzy_match_additional_tests.rs', 'fuzzy_match_large_native_tests.rs', 'lib.rs',
)


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


def load_corpus(report):
    base = ROOT / 'hia/tests'
    encoded = bind(base / 'fuzzy_match_oracle_inputs.json', report, CORPUS_SHA)
    require(len(encoded) <= 512000, 'literal manifest exceeds the source limit')
    manifest = json.loads(encoded)
    files = manifest['data_files']
    require(isinstance(files, list) and len(files) == len(SHARD_BINDINGS)
            and 'streams' not in manifest and 'raw_cases' not in manifest,
            'literal shard manifest shape differs')
    corpus = {key: value for key, value in manifest.items() if key != 'data_files'}
    corpus.update(streams=[], raw_cases=[])
    for entry, (name, kind, count) in zip(files, SHARD_BINDINGS):
        require(entry['path'] == name and entry['kind'] == kind
                and entry['count'] == count and type(entry['bytes']) is int
                and 0 < entry['bytes'] <= 512000,
                'literal shard identity or extent differs')
        raw = bind(base / name, report, entry['sha256'])
        require(len(raw) == entry['bytes'], 'literal shard byte count differs')
        shard = json.loads(raw)
        require(set(shard) == {'schema', 'module', 'kind', 'items'}
                and shard['schema'] == 'codex.hia.fuzzy-match-oracle-shard.v1'
                and shard['module'] == 'fuzzy_match' and shard['kind'] == kind
                and isinstance(shard['items'], list) and len(shard['items']) == count,
                'literal shard content shape differs')
        corpus[kind].extend(shard['items'])
    report['literal_shards_admitted'] = files
    return corpus


def frame(case):
    raw = bytes.fromhex(case['source_hex'])
    require(len(raw) == case['source_bytes'] and len(raw) <= 4417,
            'literal source extent differs')
    if 'source_words_le' in case:
        require(len(case['source_words_le']) == 8
                and len(case['source_state_words_le']) == 32,
                'literal request field extent differs')
        require(raw == words(case['source_words_le'])
                + words(case['source_state_words_le'])
                + bytes.fromhex(case['source_payload_hex']),
                'literal request bytes differ from encoded fields')
    return raw


def literal_prefix(case):
    status = case['expected_core_return']
    require(type(status) is int and status in STATUSES.values(),
            'unknown literal Core status')
    if status != 0:
        require(case['expected_written_bytes'] == 0
                and not any(key in case for key in (
                    'expected_output_prefix_hex', 'expected_header_words_le',
                    'expected_state_words_le', 'expected_records_words_le')),
                'error expectation promises output')
        return b''
    header = case['expected_header_words_le']
    state = case['expected_state_words_le']
    require(len(header) == 16 and len(state) == 32,
            'literal response field extent differs')
    numeric_header = unpack(words(header))
    op = numeric_header[1]
    records = case['expected_records_words_le']
    require(op in range(4) and numeric_header[3] == op
            and all(len(row) == (0, 3, 3, 1)[op] for row in records),
            'literal record shape differs')
    record_bytes = words([value for row in records for value in row])
    prefix = bytes.fromhex(case['expected_output_prefix_hex'])
    require(prefix == words(header) + words(state) + record_bytes
            and numeric_header[0] == 1 and numeric_header[2] == int(state[20])
            and numeric_header[6] == len(records)
            and numeric_header[7] == len(record_bytes)
            and numeric_header[8] == len(prefix) == case['expected_written_bytes']
            and numeric_header[9:] == (0,) * 7,
            'literal response encoding differs from frozen prefix')
    return prefix


class RawFailure(Exception):
    def __init__(self, record):
        self.record = record
        super().__init__(record['label'])


class RawAbi:
    def __init__(self, library, report):
        self.library = ctypes.CDLL(str(library))
        self.function = self.library.codex_hia_fuzzy_match
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.report = report

    def call(self, case, default_fill, label):
        raw = frame(case)
        capacity = case['output_capacity']
        workspace = bytes.fromhex(case['workspace_hex'])
        fill = bytes.fromhex(case.get('output_fill_hex', default_fill.hex()))
        require(type(capacity) is int and 0 <= capacity <= 393640
                and len(workspace) <= 64 and len(fill) == 1,
                'call is outside frozen live-buffer extents')
        expected = case['expected_core_return']
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


def response_records(prefix, operation):
    width = (0, 24, 24, 8)[operation]
    tail = prefix[384:]
    require((width > 0 and len(tail) % width == 0) or (width == 0 and not tail),
            'native record extent differs')
    if width == 0:
        return []
    return [unpack(tail[position:position + width])
            for position in range(0, len(tail), width)]


def stream(probe, item, fill):
    state_bytes = bytes(256)
    hay, needle, indices = [], [], []
    original_hay, original_needle = bytearray(), bytearray()
    calls = item['calls']
    require(bool(calls), 'empty literal stream')
    for position, case in enumerate(calls):
        request = frame(case)
        require(case['expected_core_return'] == 0 and not case['logical_state_only']
                and len(request) >= 320 and request[64:320] == state_bytes,
                'literal stream is not linked to the actual preceding native state')
        header, state = unpack(request[:64]), unpack(state_bytes)
        op, h_count, n_count = header[1], header[4], header[5]
        require(op in range(4), 'stream operation is unknown')
        if op == 0:
            require(position == 0 and h_count == len(bytes.fromhex(item['original_hay_hex']))
                    and n_count == len(bytes.fromhex(item['original_needle_hex'])),
                    'Begin totals differ from complete original byte strings')
        if op == 3:
            h_cursor, n_cursor = state[12], state[13]
            require(state[6] == len(hay) and state[8] == len(needle)
                    and h_cursor + h_count <= len(hay)
                    and n_cursor + n_count <= len(needle),
                    'claimed window is outside the actual native-produced vectors')
            payload = [value for row in hay[h_cursor:h_cursor + h_count] for value in row]
            payload.extend(needle[n_cursor:n_cursor + n_count])
            require(request[320:] == struct.pack('<' + 'Q' * len(payload), *payload),
                    'literal Match window differs from preceding native output')
        raw, prefix = probe.call(case, fill, f"stream/{item['id']}/{position}")
        result_header = unpack(prefix[:128])
        next_state = unpack(prefix[128:384])
        require(result_header[1] == op, 'native operation echo differs')
        records = response_records(prefix, op)
        if op == 1:
            original_hay.extend(raw[320:])
            hay.extend(records)
        elif op == 2:
            original_needle.extend(raw[320:])
            for kind, index, scalar in records:
                if kind == 0:
                    require(index == len(needle), 'Append is not at the exact frontier')
                    needle.append(scalar)
                else:
                    require(kind == 1 and index < len(needle)
                            and needle[index] == 963 and scalar == 962,
                            'ReplaceFinalSigma is not a valid mechanical update')
                    needle[index] = scalar
        elif op == 3:
            if next_state[20] == 2:
                require(not records, 'terminal None exposed partial indices')
                indices.clear()
            else:
                indices.extend(row[0] for row in records)
        state_bytes = prefix[128:384]
    state = unpack(state_bytes)
    require(state[0] == 4, 'stream did not finish')
    if state[2] != 0:
        require(bytes(original_hay) == bytes.fromhex(item['original_hay_hex'])
                and bytes(original_needle) == bytes.fromhex(item['original_needle_hex']),
                'normalization frames differ from the complete original strings')
    expected = item['expected_public']
    if expected is None:
        require(state[20] == 2 and not indices, 'literal terminal None differs')
        result = None
    else:
        require(state[20] == 1
                and indices == [int(value) for value in expected['indices']]
                and state[21] == int(expected['score_bits']),
                'complete mechanically reconstructed literal result differs')
        result = {'indices': indices, 'score_bits': str(state[21])}
    return {'id': item['id'], 'native_calls': len(calls),
            'mechanical_result': result, 'actual_final_state': [str(v) for v in state]}


def verify(args, report):
    directory = args.library_dir.resolve(strict=True)
    native_inputs(directory / 'network_host.so', ROOT / 'hia/network_host.hepta',
                  args.build_profile, report)
    manifest_flag, module_count = {
        'full-native35': ('full35_manifest_verified', 35),
        'full-native36': ('full36_manifest_verified', 36),
        'full-native37': ('full37_manifest_verified', 37),
        'full-native38': ('full38_manifest_verified', 38),
        'full-native39': ('full39_manifest_verified', 39),
    }[args.build_profile]
    require(report['native_build'][manifest_flag] is True
            and report['native_build']['module_count'] == module_count,
            'fuzzy ABI requires the complete selected native module build')
    bind(Path(__file__), report)
    contract = json.loads(bind(ROOT / 'hia/fuzzy_match_buffer_contract.json',
                               report, CONTRACT_SHA))
    corpus = load_corpus(report)
    source = bind(ROOT / 'hia/fuzzy_match.hepta', report, contract['source']['sha256'])
    constants = contract['wire_layout']['constants']
    require(contract['source'] == corpus['source']
            and len(source) == contract['source']['bytes']
            and corpus['contract']['sha256'] == CONTRACT_SHA
            and contract['schema'] == 'codex.hia.fuzzy-match-buffer-contract.v1'
            and contract['module'] == corpus['module'] == 'fuzzy_match'
            and contract['symbol'] == corpus['symbol'] == 'codex_hia_fuzzy_match'
            and contract['compiler_boundary']['entry_profile'] == 'borrowed-buffers-u32-v1'
            and contract['compiler_boundary']['revision']
            == '0de5657a80f96b138525ac7ee9ce11712a83a10d'
            and constants['state_words'] == 32
            and constants['input_payload_offset'] == 320
            and constants['output_records_offset'] == 384
            and constants['utf8_frame_max_bytes'] == 4096
            and contract['capacities']['Match']['required_output_bytes'] == 2048
            and contract['statuses'] == STATUSES
            and corpus['schema'] == 'codex.hia.fuzzy-match-oracle-inputs.v1'
            and corpus['counts'] == COUNTS, 'source/contract/corpus identity differs')
    owner = ROOT / 'codex-rs/utils/fuzzy-match'
    for name in HOST_FILES:
        bind(owner / 'src' / name, report)
    for name in ('build.rs', 'Cargo.toml', 'BUILD.bazel'):
        bind(owner / name, report)
    library = directory / 'libcodex_hia_fuzzy_match.so'
    require(str(library) in report['inputs'], 'namespaced B3 library was not admitted')
    streams, raw_cases = corpus['streams'], corpus['raw_cases']
    all_cases = [case for item in streams for case in item['calls']] + raw_cases
    identifiers = [case['id'] for case in all_cases]
    require(len(streams) == COUNTS['streams']
            and sum(len(item['calls']) for item in streams) == COUNTS['stream_call_templates']
            and len(raw_cases) == COUNTS['raw_cases']
            and len(all_cases) == COUNTS['literal_frame_templates']
            and len(set(identifiers)) == len(identifiers)
            and len({item['id'] for item in streams}) == len(streams),
            'literal cardinality or unique identifiers differ')
    fill = bytes.fromhex(corpus['case_defaults']['output_initial_fill_hex'])
    require(bytes.fromhex(corpus['case_defaults']['external_guard_hex']) == GUARD,
            'external guard literal differs')
    report['inputs_unchanged_before_load'] = recheck_inputs(report)
    require(report['inputs_unchanged_before_load'], 'input changed before native load')
    probe = RawAbi(library, report)
    for item in streams:
        report['streams'].append(stream(probe, item, fill))
    for case in raw_cases:
        probe.call(case, fill, f"raw/{case['id']}")
    require(len(report['calls']) == COUNTS['native_calls_planned'],
            'not every frozen literal invocation completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native35', 'full-native36', 'full-native37', 'full-native38', 'full-native39'], default='full-native35')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {
        'schema': 'codex.hia.fuzzy-match.raw-abi.v1', 'passed': False,
        'requested_build_profile': args.build_profile,
        'loaded_entry': 'libcodex_hia_fuzzy_match.so:codex_hia_fuzzy_match',
        'abi_scope': 'Normal native-selfhost B3 namespaced borrowed-buffers-u32-v1 only.',
        'return_rule': 'Full u64 equals literal Core status; nonzero high32 is never masked.',
        'semantic_reference': 'Literal states/scalars/commands/indices/scores; no algorithm model.',
        'logical_state_scope': 'Huge u64 history is a logical fixture, not an executed history.',
        'large_public_scope': 'Two separate Rust native-only witnesses remain required.',
        'seed_direct_profile_executed': False, 'original_rust_oracle_executed': False,
        'public_owner_qualified': False, 'performance_qualified': False,
        'whole_codex_rewritten': False, 'default_release_migrated': False, 'skipped': 0,
        'literal_templates_expected': COUNTS['literal_frame_templates'],
        'native_calls_expected': COUNTS['native_calls_planned'],
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
