import base64
from collections import Counter
import datetime
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('ci-audit/recovered-20261105/b16-ai395-cold-bootstrap-v1')
EXPORT = ROOT / 'p4-v3-catalog-readonly-export-v1'
DECODED = EXPORT / 'decoded-verified-v1'
OUTPUT = Path('hepta-audit-fifth/inputs/p4-v3-originals-root-review.json')
TREE = '4a3374e22e16ce5c764288ad018cd9affadf94ea'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def check(raw, expected):
    actual = identity(raw)
    for key in actual:
        if key in expected:
            assert actual[key] == expected[key], (key, actual[key], expected[key])
    return actual


manifest = json.loads((EXPORT / 'export-manifest.json').read_text())
chunks = {}
for batch in sorted((EXPORT / 'transport').glob('batch-*.json')):
    for item in json.loads(batch.read_text())['files']:
        raw = item['text'].encode()
        check(raw, item)
        assert item['path'] not in chunks
        chunks[item['path']] = raw
assert len(chunks) == 64
originals = {}
records = []
for asset in manifest['assets']:
    parts = []
    for item in asset['chunks']:
        raw = chunks.pop(item['path'])
        check(raw, item)
        parts.append(raw)
    encoded = b''.join(parts)
    assert len(encoded) == asset['encoded_bytes']
    compressed = base64.b64decode(encoded, validate=True)
    check(compressed, asset['compressed'])
    raw = gzip.decompress(compressed)
    check(raw, asset['original'])
    assert (DECODED / asset['name']).read_bytes() == raw
    assert asset['name'] not in originals
    originals[asset['name']] = raw
    records.append({'name': asset['name'], 'role': asset['role'], **identity(raw)})
assert not chunks and len(originals) == 36
original_roles = {'original-v3-record', 'original-failed-v3-terminal'}
assert Counter(item['role'] for item in records) == {
    'original-v3-record': 33, 'original-failed-v3-terminal': 1,
    'derived-readonly-analysis': 1, 'derived-complete-case-tuples': 1}
assert sum(item['bytes'] for item in records if item['role'] in original_roles) == 12660133

request = json.loads(originals['request.original.json'])
terminal = json.loads(originals['terminal.json'])
assert terminal['success'] is False and terminal['B_source_applied'] is False
assert not terminal['tests_executed'] and not terminal['test_qualification']
assert len(terminal['errors']) == 1
assert terminal['errors'][0]['message'] == 'unexpected full catalog filter'
assert terminal['source_tree'] == TREE
assert terminal['source_commit'] == '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
assert [command['exit_code'] for command in terminal['commands']] == [0, 0, 0]
expected_commands = [
    ['cargo', 'build', '--locked', '--profile', 'dev-small', '--message-format=json-render-diagnostics',
     '-p', 'codex-arg0', '--bin', 'test_arg0_preflight',
     '-p', 'codex-code-mode-host', '--bin', 'codex-code-mode-host',
     '-p', 'codex-shell-escalation', '--bin', 'codex-execve-wrapper',
     '-p', 'codex-rmcp-client', '--bin', 'test_stdio_server', '--bin', 'test_streamable_http_server',
     '-p', 'codex-exec', '--bin', 'codex-exec'],
    ['cargo', 'metadata', '--locked', '--format-version=1'],
    ['cargo', 'nextest', 'list', '--locked', '--cargo-profile', 'dev-small', '--message-format=json'],
]
guards = []
for command, expected in zip(terminal['commands'], expected_commands, strict=True):
    assert command['argv'] == expected
    assert command == json.loads(originals[command['label'] + '.status.json'])
    assert command['source_before'] == command['source_after'] == TREE
    assert command['tests_executed'] is False
    for stream in ('stdout', 'stderr'):
        check(originals[Path(command[stream]['path']).name], command[stream])
    for side in ('before', 'after'):
        entry = command['source_guard_' + side]
        raw = originals[Path(entry['path']).name]
        check(raw, entry)
        guard = json.loads(raw)
        assert guard['working_tree'] == guard['head_tree'] == TREE
        assert guard['head'] == terminal['source_commit'] and not guard['untracked']
        assert guard['ordinary_index']['sha256'] == '6b39b6b27d164001c9b130487d0d7879be5f80e22a4579d06fd472c2bb8d7ac0'
        guards.append(guard)
assert len(guards) == 6
assert all(guard['guarded_files'] == guards[0]['guarded_files'] for guard in guards)
assert all(guard['ordinary_index'] == guards[0]['ordinary_index'] for guard in guards)
for sdk in ('openssl', 'libcap'):
    assert originals[f'initial.{sdk}-sdk-guard.json'] == originals[f'terminal.{sdk}-sdk-guard.json']
    check(originals[f'initial.{sdk}-sdk-guard.json'], terminal[f'{sdk}_initial_guard'])
    check(originals[f'terminal.{sdk}-sdk-guard.json'], terminal[f'{sdk}_final_guard'])

catalog = json.loads(originals['03-full-unfiltered-catalog.stdout.original'])
old_catalog_raw = Path(request['case_roster_reference']['original_path']).read_bytes()
check(old_catalog_raw, request['case_roster_reference'])
old_catalog = json.loads(old_catalog_raw)


def catalog_rows(value):
    rows, statuses = [], Counter()
    for suite_id, suite in value['rust-suites'].items():
        assert suite['binary-id'] == suite_id and suite['status'] == 'listed'
        for name, case in suite['testcases'].items():
            assert type(case['ignored']) is bool
            expected = {'status': 'mismatch', 'reason': 'ignored'} if case['ignored'] else {'status': 'matches'}
            assert case['filter-match'] == expected
            rows.append((suite_id, name, case['ignored']))
            statuses[(case['ignored'], json.dumps(case['filter-match'], sort_keys=True))] += 1
    return Counter(rows), statuses


current_cases, current_statuses = catalog_rows(catalog)
old_cases, old_statuses = catalog_rows(old_catalog)
assert current_cases == old_cases and current_statuses == old_statuses
assert len(current_cases) == sum(current_cases.values()) == catalog['test-count'] == 19563
assert sum(count for (_, _, ignored), count in current_cases.items() if ignored) == 57
assert sum(count for (_, _, ignored), count in current_cases.items() if not ignored) == 19506
roles = Counter((s['binary-id'], s['binary-name'], s['package-name'], s['kind'], s['build-platform'])
                for s in catalog['rust-suites'].values())
assert sum(roles.values()) == 363
assert roles == Counter(tuple(row) for row in request['expected_program_roles'])
normal = json.loads(originals['normal-six-before-catalog.json'])
assert len(normal['artifacts']) == 6
messages = [json.loads(line) for line in originals['01-normal-six-helper-build.stdout.original'].splitlines()]
assert [msg for msg in messages if msg.get('reason') == 'build-finished'] == [{'reason': 'build-finished', 'success': True}]
helper_paths = {item['path'] for item in normal['artifacts']}
target = catalog['rust-build-meta']['target-directory']
for entries in catalog['rust-build-meta']['non-test-binaries'].values():
    for entry in entries:
        if entry['kind'] == 'bin-exe':
            helper_paths.add(str(Path(target) / entry['path']))
assert len(helper_paths) == 33

metadata = json.loads(originals['02-full-metadata.stdout.original'])
old_metadata_raw = Path(request['graph_reference']['original_path']).read_bytes()
check(old_metadata_raw, request['graph_reference'])
old_metadata = json.loads(old_metadata_raw)
assert len(metadata['workspace_members']) == 193 and len(metadata['resolve']['nodes']) == 1501
assert {package['id'] for package in metadata['packages']} == {node['id'] for node in metadata['resolve']['nodes']}


def graph(value):
    prefix = 'path+file://' + str(Path(value['workspace_root']).parent)
    def normalize(item):
        if isinstance(item, str):
            return 'path+file://<SOURCE>' + item[len(prefix):] if item.startswith(prefix + '/') else item
        if isinstance(item, list):
            return sorted((normalize(child) for child in item), key=lambda child: json.dumps(child, sort_keys=True))
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        return item
    return normalize({'members': value['workspace_members'], 'default_members': value['workspace_default_members'],
                      'resolve': value['resolve']})


assert graph(metadata) == graph(old_metadata)
review = {
    'schema': 'hepta-root-P4-v3-complete-original-review-v1',
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'verdict': 'PASS_THREE_ORIGINAL_COMMANDS_AND_COMPLETE_ORIGINAL_CATALOG; CONTROLLER_PARSER_FAILURE_PRESERVED',
    'records': records,
    'verified': {
        'all_64_chunks_strict_base64_gzip_full_hashes_and_reopened_local_originals': True,
        'original_record_count': 34, 'derived_record_count': 2, 'original_bytes': 12660133,
        'all_three_original_unfiltered_commands_exit_zero': True,
        'six_source_index_lock_guards_unchanged': True,
        'two_sdk_initial_and_final_guards_byte_equal': True,
        'original_catalog_case_Counter_equal': True, 'nonignored_matches': 19506, 'ignored_mismatches': 57,
        'other_filter_forms': 0, 'program_roles': 363, 'helper_paths': 33,
        'workspace_members': 193, 'resolve_nodes': 1501,
        'full_resolve_graph_equal_after_only_source_ID_prefix_normalization_and_array_order': True,
    },
    'scope_limits': [
        'The P4 controller remains a recorded failure caused by its incorrect all-matches predicate.',
        'No successful command is rerun or changed by this cloud review.',
        '396 current physical output identities still require the separate native read-only completion.',
        'Build/list records do not qualify any test and do not close B16.',
    ],
    'tests_executed': False, 'test_qualification': False,
}
OUTPUT.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(OUTPUT), **identity(OUTPUT.read_bytes()), 'verdict': review['verdict']}))
