#!/usr/bin/env python3
"""Check real HIA buffers against literal fixtures and a Python wire model.

This raw ABI gate does not execute or replace the original Rust/public oracle.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import itertools
import json
from pathlib import Path
import random
import struct
import threading


INVALID, SHORT, MAX = 0xFFFFFFFF, 0xFFFFFFFE, (1 << 64) - 1
GUARD = bytes(range(1, 34))
SPACE = set(range(9, 14)) | {32, 133, 160, 5760, 8232, 8233, 8239, 8287, 12288} | set(range(8192, 8203))
TRIM = ''.join(map(chr, sorted(SPACE)))
HEPTA_REVISION = '0de5657a80f96b138525ac7ee9ce11712a83a10d'
COMPILER_SHA = '76fe758bc49499046169a5b4798c31d57366344c23530b35bc489e4008639273'
MODULES = ['seek_sequence', 'utf8_boundaries', 'utf8_prefix', 'metric_tag', 'markdown_location', 'ascii_json_fragment', 'truncate', 'token_budget', 'source_file', 'file_update', 'parser', 'patch_effects', 'unified_diff', 'patch_summary', 'patch_application', 'patch_standalone', 'uuid_find', 'template_parse', 'template_render', 'template_index', 'uuid_matches', 'template_parser', 'prefix_match', 'prefix_admission', 'policy_summary', 'network_domains', 'allowed_prefixes', 'command_dispatch', 'network_host']

FULL_MODULE_PROFILES = {
    'full-native29': MODULES,
    'full-native30': [*MODULES, 'output_lines'],
    'full-native31': [*MODULES, 'output_lines', 'output_item_budget'],
    'full-native32': [*MODULES, 'output_lines', 'output_item_budget', 'format_env_display'],
    'full-native33': [*MODULES, 'output_lines', 'output_item_budget', 'format_env_display', 'citation_stream_parser'],
    'full-native34': [*MODULES, 'output_lines', 'output_item_budget', 'format_env_display', 'citation_stream_parser', 'proposed_plan_parser'],
    'full-native35': [*MODULES, 'output_lines', 'output_item_budget', 'format_env_display', 'citation_stream_parser', 'proposed_plan_parser', 'fuzzy_match'],
    'full-native36': [*MODULES, 'output_lines', 'output_item_budget', 'format_env_display', 'citation_stream_parser', 'proposed_plan_parser', 'fuzzy_match', 'utf8_stream'],
    'full-native37': [*MODULES, 'output_lines', 'output_item_budget', 'format_env_display', 'citation_stream_parser', 'proposed_plan_parser', 'fuzzy_match', 'utf8_stream', 'inline_hidden_tag'],
    'full-native38': [*MODULES, 'output_lines', 'output_item_budget', 'format_env_display', 'citation_stream_parser', 'proposed_plan_parser', 'fuzzy_match', 'utf8_stream', 'inline_hidden_tag', 'retry_decision'],
}
FULL_MODULE_PROFILES['full-native39'] = [*FULL_MODULE_PROFILES['full-native38'], 'datetime_cache']
FULL_MODULE_PROFILES['full-native41'] = [*FULL_MODULE_PROFILES['full-native39'], 'duration_units', 'datetime_arithmetic']


def words(*values):
    return struct.pack('<' + 'Q' * len(values), *values)


def model(raw):
    """Independent contract model, explicitly not the original Rust oracle."""
    host = raw.decode('utf-8').strip(TRIM)
    if not host:
        return 1, b''
    if '://' in host or any(value in host for value in '/?#'):
        return 2, b''
    if host.startswith('['):
        close = host.find(']')
        if close < 0:
            return 3, b''
        rest = host[close + 1:]
        if rest and not (rest.startswith(':') and rest[1:] and all('0' <= c <= '9' for c in rest[1:])):
            return 4, b''
        host = host[1:close]
    elif host.count(':') == 1:
        candidate, port = host.rsplit(':', 1)
        if candidate and port and all('0' <= c <= '9' for c in port):
            host = candidate
    normalized = host.rstrip('.').strip(TRIM).encode('utf-8').lower()
    if not normalized:
        return 1, b''
    if b'*' in normalized:
        return 5, b''
    if any(ord(c) in SPACE for c in normalized.decode('utf-8')):
        return 6, b''
    return 0, normalized


def expected(raw, control, capacity):
    if len(control) != 32:
        return INVALID, b''
    version, mode, count, reserved = struct.unpack('<4Q', control)
    if version != 1 or mode not in (0, 1) or reserved:
        return INVALID, b''
    if (mode == 0 and count) or (mode == 1 and not 0 < count <= len(raw)):
        return INVALID, b''
    try:
        tag, value = model(raw)
    except UnicodeDecodeError:
        return INVALID, b''
    if mode == 0:
        return (SHORT, b'') if capacity < 16 else (0, words(tag, len(value)))
    if tag or len(value) != count:
        return INVALID, b''
    return (SHORT, b'') if capacity < count else (0, value)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_inputs(library, source, profile, report):
    """Bind existing artifacts only; never load or execute native code here."""
    library = library.resolve(strict=True)
    directory = library.parent
    build_path = directory / 'build.json'
    build = json.loads(build_path.read_bytes())
    inputs = report['inputs'] = {}

    def bind(path, expected=None, size=None):
        actual = sha(path)
        inputs[str(path)] = actual
        if expected is not None and actual != expected:
            raise RuntimeError(f'native input identity mismatch: {path}')
        if size is not None and path.stat().st_size != size:
            raise RuntimeError(f'native input size mismatch: {path}')
        return actual

    bind(build_path)
    source_sha = bind(source)
    bind(Path(__file__).resolve())
    if library.name != 'network_host.so':
        raise RuntimeError('raw gate requires the network_host.so f0 entry')
    schema = build.get('schema')
    if profile == 'local-incremental':
        if (schema != 'codex.hia.network-host.local-incremental-build.v1'
                or build.get('passed') is not True
                or build.get('compiler_bootstrap_rerun') is not False
                or build.get('source_sha256') != source_sha
                or build.get('compiler_sha256') != COMPILER_SHA
                or build.get('entry_profile') != 'borrowed-buffers-u32-v1'
                or build.get('protected_unchanged') is not True
                or build.get('inputs_unchanged') is not True
                or build.get('protected_before') != build.get('protected_after')
                or build.get('protected_after', {}).get('head') != HEPTA_REVISION):
            raise RuntimeError('incremental build/source/compiler identity is invalid')
        names = ['network_host.so', 'network_host.o', 'network_host.hepta',
                 'network_host.namespaced.o', 'libcodex_hia_network_host.a',
                 'libcodex_hia_network_host.so', 'compiler.image.bin']
        for name in names:
            expected = build['artifacts'][name]
            bind(directory / name, expected['sha256'], expected['bytes'])
        if (inputs[str(directory / 'compiler.image.bin')] != COMPILER_SHA
                or inputs[str(directory / 'network_host.hepta')] != source_sha
                or build['compilation']['status'] != 'returned'
                or build['compilation']['abi_status'] != 0
                or build['compilation']['image_sha256'] != COMPILER_SHA
                or build['compilation']['produced_sha256'] != inputs[str(directory / 'network_host.o')]
                or build['object_inventory']['object_sha256'] != inputs[str(directory / 'network_host.o')]):
            raise RuntimeError('incremental compiler/object binding is invalid')
        report['native_build'] = {
            'schema': schema, 'profile': profile, 'module_count': 1,
            'compiler_generations_verified': [], 'full29_manifest_verified': False,
            'compiler_bootstrap_rerun': False,
            'scope': 'One existing module compiled by a reused B3; no full twenty-nine-module bootstrap claim.'}
    elif profile in FULL_MODULE_PROFILES:
        modules = FULL_MODULE_PROFILES[profile]
        if schema != 'codex.hia.native-build.v1':
            raise RuntimeError(f'{profile} profile rejects incremental or unknown schemas')
        lock_path = source.parent / 'toolchain.json'
        lock = json.loads(lock_path.read_bytes())
        if (schema != 'codex.hia.native-build.v1' or build.get('status') != 'built'
                or build.get('build_mode') != 'native-selfhost'
                or build.get('compiler_fixed_point') is not True
                or build.get('compiler_sha256') != COMPILER_SHA
                or build.get('toolchain') != lock
                or lock.get('revision') != HEPTA_REVISION
                or lock.get('target') != 'x86_64-unknown-linux-gnu'
                or lock.get('modules') != modules
                or set(build.get('modules', {})) != set(modules)
                or lock.get('entry_profiles') != {'token_budget': 'u64-pair-to-u64-v1', 'prefix_admission': 'u64-pair-to-u64-v1'}):
            raise RuntimeError(f'{profile} lock/compiler/module contract is invalid')
        bind(lock_path, build['toolchain_lock_sha256'])
        bind(source.parent / 'build.py', build['build_driver_sha256'])
        bind(source.parent / 'cargo_build.rs', build['cargo_helper_sha256'])
        generations = build['bootstrap_generations']
        if [item['case'] for item in generations] != ['B1', 'B2', 'B3']:
            raise RuntimeError(f'{profile} requires exactly three ordered compiler generations')
        for index, generation in enumerate(generations):
            name = generation['case']
            image = directory / 'bootstrap' / f'{name}.image.bin'
            if (generation['status'] != 'returned' or generation['abi_status'] != 0
                    or generation['source_unchanged'] is not True
                    or generation['produced_sha256'] != COMPILER_SHA
                    or generation['format'] != ('seed-shared' if index == 0 else 'flat-x86-64')
                    or generation['forbidden_compiler_modules_loaded']
                    or (index and generation['artifact_sha256'] != COMPILER_SHA)):
                raise RuntimeError(f'{profile} compiler generation is invalid: {name}')
            bind(image, COMPILER_SHA, generation['produced_bytes'])
        for name in modules:
            module = build['modules'][name]
            link = module['codex_link_abi']
            symbol = 'codex_hia_' + name
            profile_name = 'u64-pair-to-u64-v1' if name in ('prefix_admission', 'token_budget') else 'borrowed-buffers-u32-v1'
            if (module['entry_profile'] != profile_name
                    or module['compilation']['status'] != 'returned'
                    or module['compilation']['abi_status'] != 0
                    or module['compilation']['image_sha256'] != COMPILER_SHA
                    or module['compilation']['source_unchanged'] is not True
                    or link['symbol'] != symbol or link['defined_symbols'] != [symbol]
                    or link['undefined_symbols'] or link['archive_member'] != 'hia.o'
                    or link['archive'] != f'lib{symbol}.a'
                    or link['library'] != f'lib{symbol}.so'
                    or link['object'] != f'{name}.namespaced.o'):
                raise RuntimeError(f'{profile} module binding is invalid: {name}')
            bind(source.parent / f'{name}.hepta', module['source_sha256'])
            bind(directory / f'{name}.so', module['library_sha256'], module['library_bytes'])
            object_sha = bind(directory / f'{name}.o', module['object_inventory']['object_sha256'])
            if object_sha != module['compilation']['produced_sha256']:
                raise RuntimeError(f'{profile} emitted object mismatch: {name}')
            bind(directory / link['archive'], link['archive_sha256'], link['archive_bytes'])
            bind(directory / link['object'], link['object_sha256'])
            bind(directory / link['library'], link['library_sha256'])
            compilation = module['compilation']
            compiler_input = directory / f'{name}.input.bin'
            input_sha = bind(compiler_input, compilation['source_sha256'], compilation['input_bytes'])
            if (compilation['input_sha256'] != input_sha
                    or compilation['artifact_sha256'] != COMPILER_SHA
                    or compilation['forbidden_compiler_modules_loaded']):
                raise RuntimeError(f'{profile} actual compiler input mismatch: {name}')
            fields = {
                'module': name, 'target': lock['target'], 'mode': 'native-selfhost',
                'revision': lock['revision'], 'symbol': symbol,
                'object': link['object'], 'archive': link['archive'], 'archive_member': 'hia.o',
                'source_sha256': module['source_sha256'],
                'toolchain_lock_sha256': build['toolchain_lock_sha256'],
                'build_driver_sha256': build['build_driver_sha256'],
                'cargo_helper_sha256': build['cargo_helper_sha256'],
                'object_sha256': link['object_sha256'], 'text_sha256': link['text_sha256'],
                'archive_sha256': link['archive_sha256'], 'compiler_sha256': COMPILER_SHA,
                'build_report_sha256': inputs[str(build_path)],
            }
            # Exact field order from the unchanged builder and Cargo helper.
            expected_link = ('codex.hia.static-link.v1\n'
                             + ''.join(f'{key}={value}\n' for key, value in fields.items()))
            receipt = directory / f'{name}.link'
            bind(receipt)
            if receipt.read_bytes() != expected_link.encode('ascii'):
                raise RuntimeError(f'{profile} actual static-link receipt mismatch: {name}')
        if build['modules']['network_host']['source_sha256'] != source_sha:
            raise RuntimeError(f'{profile} network-host source mismatch')
        report['native_build'] = {
            'schema': schema, 'profile': profile, 'module_count': len(modules),
            'compiler_generations_verified': ['B1', 'B2', 'B3'],
            'full29_manifest_verified': profile == 'full-native29',
            'full30_manifest_verified': profile == 'full-native30',
            'full31_manifest_verified': profile == 'full-native31',
            'full32_manifest_verified': profile == 'full-native32',
            'full33_manifest_verified': profile == 'full-native33',
            'full34_manifest_verified': profile == 'full-native34',
            'full35_manifest_verified': profile == 'full-native35',
            'full36_manifest_verified': profile == 'full-native36',
            'full37_manifest_verified': profile == 'full-native37',
            'full38_manifest_verified': profile == 'full-native38',
            'full39_manifest_verified': profile == 'full-native39',
            'full41_manifest_verified': profile == 'full-native41',
            'scope': f'Existing native-selfhost report, all {len(modules)} module artifacts and three fixed-point image identities; no compilation performed by this raw gate.'}
    else:
        raise RuntimeError('unknown native build profile')
    report['compiler_sha256'] = COMPILER_SHA
    report['compiler_bootstrap_executed_by_raw_gate'] = False


def recheck_inputs(report):
    try:
        return all(sha(path) == value for path, value in report['inputs'].items())
    except OSError as error:
        report['input_recheck_error'] = f'{type(error).__name__}: {error}'
        return False


class ProbeFailure(Exception):
    def __init__(self, record):
        self.record = record
        super().__init__(record['label'])


class Probe:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.function = self.library.f0
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = threading.Lock()
        self.largest = 0

    def call(self, raw, control, capacity, label):
        wanted_code, payload = expected(raw, control, capacity)
        source = bytearray(GUARD + raw + GUARD)
        workspace = bytearray(GUARD + control + GUARD)
        output = bytearray(GUARD + b'\xb7' * capacity + GUARD)
        source_before, workspace_before, output_before = bytes(source), bytes(workspace), bytes(output)
        buffers = [(ctypes.c_ubyte * len(value)).from_buffer(value) for value in (source, output, workspace)]
        pointers = [ctypes.cast(ctypes.byref(value, len(GUARD)), ctypes.c_void_p) for value in buffers]
        result = self.function(pointers[0], len(raw), pointers[1], capacity, pointers[2], len(control))
        wanted = bytearray(output_before)
        if wanted_code == 0:
            wanted[len(GUARD):len(GUARD) + len(payload)] = payload
        with self.lock:
            self.counts['calls'] += 1
            self.counts['returned_success' if result == 0 else 'returned_error'] += 1
            self.counts[label.split('/')[0]] += 1
            self.largest = max(self.largest, len(raw))
        if result != wanted_code or source != source_before or workspace != workspace_before or output != wanted:
            raise ProbeFailure({'label': label, 'raw_hex': raw.hex(), 'control_hex': control.hex(),
                                'capacity': capacity, 'expected_return': wanted_code, 'actual_return': result,
                                'expected_output_hex': bytes(wanted).hex(), 'actual_output_hex': bytes(output).hex(),
                                'source_unchanged': source == source_before,
                                'workspace_unchanged': workspace == workspace_before})

    def host(self, value, label):
        raw = value.encode('utf-8')
        self.call(raw, words(1, 0, 0, 0), 23, label + '/plan')
        tag, normalized = model(raw)
        if not tag:
            self.call(raw, words(1, 1, len(normalized), 0), len(normalized) + 9, label + '/run')


def verify(args, report):
    library = args.library.resolve(strict=True)
    source = Path(__file__).resolve().parents[1] / 'network_host.hepta'
    native_inputs(library, source, args.build_profile, report)
    probe = Probe(library)
    report['probe'] = probe
    literal = [('', 1, ''), (' \t\n', 1, ''), ('EXAMPLE.COM.', 0, 'example.com'),
               ('Api.Example.COM.:443', 0, 'api.example.com'), ('[AbC. ]:80', 0, 'abc.'),
               ('[ .AbC ]', 0, '.abc'), ('[A..]:999999', 0, 'a'), ('[]', 1, ''),
               ('[', 3, ''), ('[a]oops', 4, ''), (' [a]oops ', 4, ''), ('[a]:', 4, ''),
               ('[a]:１２', 4, ''), ('a:１２', 0, 'a:１２'), ('a:abc', 0, 'a:abc'),
               (':123', 0, ':123'), ('a:b:c', 0, 'a:b:c'), ('[::1]:999999', 0, '::1'),
               ('ÄBC', 0, 'Äbc'), ('a\0b', 0, 'a\0b'), ('[a?]* ', 2, ''),
               ('[a* ', 3, ''), ('[a*]oops ', 4, ''), ('a* b', 5, ''), ('a b', 6, ''),
               ('\u0085A\u00a0', 0, 'a'), ('\u001cA\u001f', 0, '\u001ca\u001f'),
               ('a. :80', 0, 'a.'), ('A..:80', 0, 'a'), ('[. ]', 0, '.'), ('[ .]', 1, '')]
    for index, (raw, tag, normalized) in enumerate(literal):
        if model(raw.encode()) != (tag, normalized.encode()):
            raise RuntimeError(f'literal fixture/model mismatch: {index}')
        probe.host(raw, f'literal/{index}')
    report['literal_fixtures'] = len(literal)
    for point in sorted(SPACE | {8, 14, 28, 29, 30, 31, 132, 134, 159, 161, 5761, 6158, 8203, 8234, 8288, 65279}):
        char = chr(point)
        for shape in (char, char + 'A' + char, 'A' + char + 'B', '[' + char + 'A.' + char + ']:80'):
            probe.host(shape, f'unicode/{point}')
    alphabet = 'a:. []/*0'
    enumerated = 0
    for count in range(5):
        for values in itertools.product(alphabet, repeat=count):
            probe.host(''.join(values), f'enumerated/{enumerated}')
            enumerated += 1
    report['enumerated_hosts'] = enumerated
    rng = random.Random(0x17_0DE)
    choices = list('AaZz09:. []/?#*\x00\t\r\n') + ['Ä', 'é', '中', '😀', '\u0085', '\u00a0', '\u2003', '\u200b', '\ufeff']
    for index in range(1024):
        value = ''.join(rng.choice(choices) for _ in range(rng.randrange(81)))
        probe.host(value, f'random/{index}')
    for raw in (b'a', b'', b'[x]oops', b'a b', b'\xff', b'[\xc0\x80]'):
        base = words(1, 0, 0, 0)
        controls = [base[:length] for length in range(32)] + [base + b'\0', base + words(0)]
        controls += [words(*values) for values in ((0, 0, 0, 0), (2, 0, 0, 0), (MAX, 0, 0, 0),
                     (1, 2, 0, 0), (1, MAX, 0, 0), (1, 0, 1, 0), (1, 0, MAX, 0),
                     (1, 0, 0, 1), (1, 0, 0, MAX), (1, 1, 0, 0), (1, 1, MAX, 0))]
        for control in controls:
            for capacity in (0, 15, 16, 17):
                probe.call(raw, control, capacity, 'malformed-control')
    malformed = [bytes([value]) for value in range(128, 256)]
    malformed += [b'\xc0\x80', b'\xc1\xbf', b'\xe0\x80\x80', b'\xed\xa0\x80',
                  b'\xed\xbf\xbf', b'\xf0\x80\x80\x80', b'\xf4\x90\x80\x80', b'\xf5\x80\x80\x80']
    for value in ['é'.encode(), '中'.encode(), '😀'.encode()]:
        malformed.extend(value[:length] for length in range(1, len(value)))
    for index, raw in enumerate(malformed):
        for prefix in (b'', b'A' * 7, b'http://', b'*'):
            for capacity in (0, 16):
                probe.call(prefix + raw, words(1, 0, 0, 0), capacity, f'malformed-utf8/{index}')
    for raw in (b'', b'ABC', b'[ABC]:80', b'a b', 'Ä中😀'.encode(), b'[AbC. ]:80'):
        for capacity in (0, 1, 7, 8, 15, 16, 17, 32):
            probe.call(raw, words(1, 0, 0, 0), capacity, 'output-boundary/plan')
        tag, normalized = model(raw)
        for count in {0, 1, len(normalized), len(normalized) + 1, MAX}:
            for capacity in {0, max(0, len(normalized) - 1), len(normalized), len(normalized) + 1}:
                probe.call(raw, words(1, 1, count, 0), capacity, 'output-boundary/run')
    for raw in (b'DEF', b'x y', b'[AB]:1', b'a', b'\xffxx'):
        probe.call(raw, words(1, 1, 3, 0), 12, 'revalidated-run')
    large = ['A' * 2_097_153, 'http://' + 'A' * 2_097_153,
             '[' + 'A' * 2_097_153, 'A' * 2_097_153 + '*',
             '\u2003' * 65_537 + 'AbC.' + '\u2003' * 65_537]
    for index, value in enumerate(large):
        probe.host(value, f'large/{index}')
    concurrent = ['a', 'ÄBC', '[AbC. ]:80', 'a b', '[a]oops', '\0', '\u2003A\u2003', '[::1]:123']
    def work(index):
        probe.host(concurrent[index % len(concurrent)], f'concurrent/{index}')
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(work, range(256)))
    report['concurrent_hosts_included'] = 256
    report['counts'] = dict(probe.counts)
    report['maximum_source_bytes'] = probe.largest
    report['inputs_unchanged'] = recheck_inputs(report)
    if not report['inputs_unchanged']:
        raise RuntimeError('source or native input changed during the raw ABI gate')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--build-profile', choices=['full-native29', 'full-native30', 'full-native31', 'full-native32', 'full-native33', 'full-native34', 'full-native35', 'full-native36', 'full-native37', 'full-native38', 'full-native39', 'full-native41', 'local-incremental'],
                        default='full-native29', help='Default requires all twenty-nine modules; local incremental evidence must be selected explicitly.')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise SystemExit('report must be new; preserve prior results')
    report = {'schema': 'codex.hia.network-host.raw-abi.v1', 'passed': False,
              'requested_build_profile': args.build_profile,
              'semantic_reference': 'Literal fixtures and independent Python contract/wire model',
              'original_rust_oracle_executed': False, 'public_owner_qualified': False,
              'performance_qualified': False, 'skipped': 0}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    try:
        verify(args, report)
        report['passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        if isinstance(error, ProbeFailure):
            failure = args.report.with_name(args.report.stem + '-failure.json')
            failure.write_text(json.dumps(error.record, indent=2) + '\n')
            report['failure_case'] = {'path': str(failure), 'sha256': sha(failure)}
    finally:
        probe = report.pop('probe', None)
        if probe is not None:
            report['counts'] = dict(probe.counts)
            report['maximum_source_bytes'] = probe.largest
        if 'inputs' in report:
            report['inputs_unchanged'] = recheck_inputs(report)
            report['passed'] &= report['inputs_unchanged']
        args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'report': str(args.report), 'sha256': sha(args.report),
                          'counts': report.get('counts'), 'error': report.get('error')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
