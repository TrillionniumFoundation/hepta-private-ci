#!/usr/bin/env python3
"""Check frozen ProposedPlan frames against the selected native34/35 B3 entry.

Expected requests, next states, commands and public results are literal data.
This gate does not execute a Rust oracle or a reference parser.
"""
import argparse
import ctypes
import json
from pathlib import Path

from proposed_plan_literal_data import case_data, digest, require
from proposed_plan_command_oracle import stream
from test_network_host_abi import native_inputs, recheck_inputs


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SHA = 'a6da6ce30c23d8bd2b6ccc5cdccba8fbf961e0ce248b88d8fc6b94c23eb68e19'
CORPUS_SHA = '3523844fab9667fe114fad7062ab5e6c7f48cbfdabb8f741d1f81e412759e970'
LITERAL_COUNTS = {
    'streams': 6,
    'stream_call_templates': 23,
    'stream_expanded_calls': 532,
    'raw_cases': 181,
    'literal_frame_templates': 204,
    'native_calls_planned': 713,
}
GUARD = bytes(range(1, 34))


def bind(path, report, expected=None):
    path = path.resolve(strict=True)
    data = path.read_bytes()
    value = digest(data)
    previous = report['inputs'].get(str(path))
    require(previous is None or previous == value, f'input changed: {path}')
    require(expected is None or expected == value, f'input identity mismatch: {path}')
    report['inputs'][str(path)] = value
    return data


class RawFailure(Exception):
    def __init__(self, record):
        self.record = record
        super().__init__(record['label'])


class RawAbi:
    def __init__(self, library, report):
        self.library = ctypes.CDLL(str(library))
        self.function = self.library.codex_hia_proposed_plan_parser
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.report = report

    def call(self, case, iteration, fill, label):
        raw, prefix = case_data(case, iteration)
        capacity = case['output_capacity']
        workspace = bytes.fromhex(case['workspace_hex'])
        expected = case['expected']['return']
        require(type(capacity) is int and 0 <= capacity <= 393313
                and len(workspace) <= 32 and len(fill) == 1,
                'call is outside frozen live-buffer extents')
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
        if (returned >> 32 != 0 or returned != expected
                or not record['source_and_guards_unchanged']
                or not record['workspace_and_guards_unchanged']
                or not record['whole_output_matches']):
            raise RawFailure(record)
        record['passed'] = True
        self.report['active_case'] = None
        return raw, actual


def verify(args, report):
    directory = args.library_dir.resolve(strict=True)
    native_inputs(directory / 'network_host.so', ROOT / 'hia/network_host.hepta',
                  args.build_profile, report)
    verified_field, expected_count = {
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
            'ProposedPlan ABI requires the complete selected native module build')
    bind(Path(__file__), report)
    contract = json.loads(bind(ROOT / 'hia/proposed_plan_parser_buffer_contract.json',
                               report, CONTRACT_SHA))
    corpus = json.loads(bind(ROOT / 'hia/tests/proposed_plan_parser_oracle_inputs.json',
                             report, CORPUS_SHA))
    source = bind(ROOT / 'hia/proposed_plan_parser.hepta', report, contract['source']['sha256'])
    require(contract['source'] == corpus['source']
            and len(source) == contract['source']['bytes']
            and corpus['contract']['sha256'] == CONTRACT_SHA
            and contract['schema'] == 'codex.hia.proposed-plan-parser-buffer-contract.v1'
            and contract['module'] == 'proposed_plan_parser'
            and contract['symbol'] == 'codex_hia_proposed_plan_parser'
            and corpus['schema'] == 'codex.hia.proposed-plan-parser-oracle-inputs.v1'
            and corpus['counts'] == LITERAL_COUNTS, 'source/contract/corpus identity differs')
    for name, wanted in corpus['gate_helpers'].items():
        require(name in ('proposed_plan_literal_data.py', 'proposed_plan_command_oracle.py'),
                'unknown raw-gate helper')
        bind(ROOT / 'hia/tests' / name, report, wanted)
    require(set(corpus['gate_helpers']) ==
            {'proposed_plan_literal_data.py', 'proposed_plan_command_oracle.py'},
            'raw-gate helper identity set differs')
    for path in corpus['host_sources']:
        require(path.startswith('codex-rs/utils/stream-parser/')
                and '..' not in Path(path).parts, 'unexpected public owner source path')
        bind(ROOT / path, report)
    library = directory / 'libcodex_hia_proposed_plan_parser.so'
    require(str(library) in report['inputs'], 'namespaced B3 library was not admitted')
    streams, raw_cases = corpus['streams'], corpus['raw_cases']
    calls = [call for item in streams for call in item['calls']] + raw_cases
    require(len(streams) == LITERAL_COUNTS['streams']
            and len(raw_cases) == LITERAL_COUNTS['raw_cases']
            and len(calls) == LITERAL_COUNTS['literal_frame_templates']
            and sum(call['repeat'] for call in calls) == LITERAL_COUNTS['native_calls_planned'],
            'literal invocation cardinality differs')
    identifiers = [item['id'] for item in streams + raw_cases]
    require(len(identifiers) == len(set(identifiers)), 'duplicate corpus identifier')
    fill = bytes.fromhex(corpus['case_defaults']['output_initial_fill_hex'])
    require(bytes.fromhex(corpus['case_defaults']['external_guard_hex']) == GUARD,
            'external guard literal differs')
    report['inputs_unchanged_before_load'] = recheck_inputs(report)
    require(report['inputs_unchanged_before_load'], 'input changed before native load')
    probe = RawAbi(library, report)
    for item in streams:
        require(item['calls'], 'empty literal stream')
        report['streams'].append(stream(probe, item, fill))
    for item in raw_cases:
        for iteration in range(item['repeat']):
            probe.call(item, iteration, fill, f"raw/{item['id']}/{iteration}")
    require(len(report['calls']) == LITERAL_COUNTS['native_calls_planned'],
            'not every frozen literal invocation completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native34', 'full-native35', 'full-native36', 'full-native37', 'full-native38', 'full-native39', 'full-native41'],
                        default='full-native34')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {
        'schema': 'codex.hia.proposed-plan-parser.raw-abi.v1', 'passed': False,
        'requested_build_profile': args.build_profile,
        'loaded_entry': 'libcodex_hia_proposed_plan_parser.so:codex_hia_proposed_plan_parser',
        'abi_scope': 'Normal native-selfhost B3 namespaced borrowed-buffers-u32-v1 only.',
        'return_rule': 'Full u64 equals literal Core u32; nonzero high32 is never masked.',
        'semantic_reference': 'Frozen requests/states/commands/public bytes; no parsing model.',
        'large_stream_scope': 'Two actual257x4096 whitespace streams; no >4GiB allocation.',
        'hypothetical_state_scope': 'Standalone states do not claim authenticated history.',
        'seed_direct_profile_executed': False, 'original_rust_oracle_executed': False,
        'public_owner_qualified': False, 'performance_qualified': False,
        'whole_codex_rewritten': False, 'default_release_migrated': False, 'skipped': 0,
        'literal_counts_expected': LITERAL_COUNTS,
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
