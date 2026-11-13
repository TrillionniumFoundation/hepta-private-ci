#!/usr/bin/env python3
"""Read captured originals only. No admission import, H, subprocess, or Git write."""
import ast
import base64
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent
CODE = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/qualification-admission.HOLD.py')
CFG = Path('/tmp/hepta-36fa-final-qualification-admission-execution-candidate-v1/QUALIFICATION_CONFIG.execution-candidate.json')
BASE = Path('/tmp')
ROOTS = {
    'archive160': BASE / 'hepta-36fa-v8-single-archive-restore-v3-actual',
    'materialization3bb': BASE / 'hepta-36fa-coordinator-a489-materializer-runtime-v1',
    'staging410': BASE / 'hepta-36fa-coordinator-a489-maintenance-staging-v1',
    'maintenance41e': BASE / 'hepta-36fa-coordinator-a489-maintenance-runtime-v1',
    'format50f': BASE / 'hepta-36fa-coordinator-a489-final-nonrust-format-runtime-v1',
    'canonical5a9': BASE / 'hepta-36fa-coordinator-a489-final-canonical-runtime-v1',
    'source65a': BASE / 'hepta-36fa-final-source-qualification-b608-runtime-v1',
}

def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                git_blob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())

def load(path):
    return json.loads(path.read_bytes())

def pin(row):
    return {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}

def sdk_json(value):
    if not isinstance(value, dict) or value.get('isError') is True:
        return None
    if 'data_base64' in value:
        return value
    for item in value.get('content', []):
        if isinstance(item, dict) and item.get('type') == 'text':
            try:
                return json.loads(item['text'])
            except (ValueError, KeyError):
                pass
    return None

source = CODE.read_text()
tree = ast.parse(source)
const = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        key = node.targets[0].id
        try:
            const[key] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'Path':
                const[key] = ast.literal_eval(node.value.args[0])

assert identity(CODE.read_bytes())['git_blob'] == 'c77e3be6230d3267c08333be582f69f23c016fb9'
assert identity(CFG.read_bytes())['git_blob'] == '720abbdfa96bca8c7e6aaf633a800693960d80db'
cfg = load(CFG)
expected = {}

def expect(path, expected_pin, consumer):
    expected_pin = pin(expected_pin)
    if path in expected:
        assert expected[path]['pin'] == expected_pin, (path, 'conflicting pinned expected bytes')
        expected[path]['consumers'].append(consumer)
    else:
        expected[path] = {'path': path, 'pin': expected_pin, 'consumers': [consumer]}

for name, value in const['FIXED_INPUTS'].items():
    expect(value['path'], value['pin'], 'FIXED_INPUTS.' + name)
for name, value in const['ACTUAL_PROOFS'].items():
    for part in ('result', 'supervisor'):
        expect(value[part + '_path'], value[part], 'ACTUAL_PROOFS.' + name + '.' + part)
for name in ('canonical_alignment',):
    for part in ('result', 'supervisor'):
        expect(cfg[name][part + '_path'], cfg[name][part], 'cfg.' + name + '.' + part)

catalogs = {}
for group in ('materialization3bb', 'maintenance41e', 'format50f', 'canonical5a9', 'archive160'):
    path = ROOTS[group] / 'ARTIFACTS.json'
    obj = load(path)
    rows = obj.get('files') if isinstance(obj, dict) else obj
    assert isinstance(rows, list), (group, type(obj))
    catalogs[group] = {row['name']: row for row in rows}

artifact_groups = {
    'materialization3bb': ('MATERIALIZATION_CONTROL', ['final.git-metadata.json.gz']),
    'maintenance41e': ('MAINTENANCE_CONTROL', ['SOURCE_GIT_METADATA.before.json.gz', 'SOURCE_GIT_METADATA.after.json.gz',
                                            'SOURCE_GIT_STATE.before.json', 'final.git-state.json']),
    'format50f': ('FINAL_FORMAT_CONTROL', ['INPUT_IDENTITIES.json', 'SOURCE_GIT_METADATA.before.json.gz',
                                       'SOURCE_GIT_METADATA.after.json.gz', 'final.git-state.json',
                                       'final.inventory.json.gz', 'fmt.after.postimages.json.gz']),
    'canonical5a9': ('CANONICAL_CONTROL', ['GIT_METADATA.before.json.gz', 'GIT_METADATA.final.json.gz',
                                         'GIT_METADATA.allowed-actual-delta.json', 'INDEX.final.raw.gz',
                                         'INDEX.final.audit.json.gz', 'INDEX.complete-entry-delta.json.gz',
                                         'GIT_STATE.final.json']),
}
for group, (control, names) in artifact_groups.items():
    for name in names:
        expect(const[control] + '/run/' + name, catalogs[group][name], 'captured ARTIFACTS + _artifact:' + group)

canonical = cfg['canonical_alignment']
for name, value in [
    ('driver.py', const['CANONICAL_DRIVER_PIN']),
    ('APPROVED_CONFIG.json', canonical['approved_config']),
    ('CANONICAL_PACKET.json', canonical['canonical_packet']),
    ('run/ARTIFACTS.json', canonical['artifacts']),
    ('run/COMMANDS.json', canonical['commands']),
    ('run/MUTATION_PROGRESS.json', canonical['progress']),
    ('run/INPUTS.final.json', canonical['inputs']),
]:
    expect(const['CANONICAL_CONTROL'] + '/' + name, value, '_validate_canonical')

# Only the fixed seven already captured operation directories are searched.
# Restrict candidates to actual binary READ SDKs, excluding Git copies of SDKs.
groups = defaultdict(list)
bad_reads = []
for group, root in ROOTS.items():
    for path in root.rglob('*.json'):
        if 'READ' not in path.name or not path.name.endswith('original.json'):
            continue
        if any(tag in path.name for tag in ('.PUBLISH_', '.GITHUB', '.Git_', '.GET.')):
            continue
        obj = sdk_json(load(path))
        if not isinstance(obj, dict) or not {'data_base64', 'path', 'offset', 'size', 'version'} <= obj.keys():
            continue
        if obj['path'] not in expected:
            continue
        raw = base64.b64decode(obj['data_base64'], validate=True)
        assert hashlib.sha256(raw).hexdigest() == obj['chunk_sha256'], str(path)
        assert obj['next_offset'] == obj['offset'] + len(raw), str(path)
        groups[(obj['path'], obj['version'])].append((obj, raw, path, group))

complete_reads = defaultdict(list)
for (path, version), chunks in groups.items():
    unique = {}
    for obj, raw, local, group in chunks:
        offset = obj['offset']
        if offset in unique:
            assert unique[offset][1] == raw, (path, version, offset)
        else:
            unique[offset] = (obj, raw, local, group)
    offset = 0
    parts = []
    rows = []
    for start in sorted(unique):
        obj, raw, local, group = unique[start]
        if start != offset:
            break
        parts.append(raw)
        rows.append({'sdk': str(local), 'sdk_pin': identity(local.read_bytes()),
                     'operation_group': group, 'offset': start, 'next_offset': obj['next_offset'],
                     'chunk_sha256': obj['chunk_sha256'], 'eof': obj.get('eof')})
        offset += len(raw)
    final = unique[max(unique)][0]
    if offset == final['size'] and final.get('eof') is True:
        whole = b''.join(parts)
        assert identity(whole) == expected[path]['pin'], (path, identity(whole), expected[path]['pin'])
        complete_reads[path].append({'version': version, 'complete_pin': identity(whole), 'chunks': rows,
                                     'historical_complete_read': True, 'current_availability': 'Unknown'})
    else:
        bad_reads.append({'path': path, 'version': version, 'contiguous_bytes': offset,
                          'recorded_size': final['size'], 'classification': 'available capture subset, not full read'})

staged = defaultdict(list)
for group, root in ROOTS.items():
    p = root / 'STAGING_READBACK.json'
    if not p.exists():
        continue
    obj = load(p)
    for row in obj['files']:
        path = row['path']
        if path not in expected:
            continue
        assert pin(row) == expected[path]['pin'], path
        staged[path].append({'record': str(p), 'record_pin': identity(p.read_bytes()), 'operation_group': group,
                             'observed_staging_row': row, 'current_availability': 'Unknown'})

producers = defaultdict(list)
for group, (control, names) in artifact_groups.items():
    for name in names:
        path = const[control] + '/run/' + name
        producers[path].append({'catalog': str(ROOTS[group] / 'ARTIFACTS.json'),
                               'catalog_pin': identity((ROOTS[group] / 'ARTIFACTS.json').read_bytes()),
                               'name': name, 'pin': pin(catalogs[group][name]),
                               'scope': 'Original retained artifact catalog plus frozen producer/control output path'})

rows = []
for path in sorted(expected):
    row = dict(expected[path])
    row['captured_complete_reads'] = complete_reads.get(path, [])
    row['captured_staging'] = staged.get(path, [])
    row['captured_artifact_binding'] = producers.get(path, [])
    row['historical_path_evidence'] = ('actual_complete_binary_read' if row['captured_complete_reads'] else
                                       'actual_staging_record' if row['captured_staging'] else
                                       'captured_producer_artifact_binding' if row['captured_artifact_binding'] else
                                       'content_pin_known_no_original_path_read_in_finite_input_set')
    row['present_path_availability'] = 'Unknown; this audit performs no live native probe'
    rows.append(row)

old_sdk_path = ROOTS['materialization3bb'] / 'RESULT_READ_01.original.json'
old_sdk = sdk_json(load(old_sdk_path))
actual_old = base64.b64decode(old_sdk['data_base64'], validate=True)
old_result = (ROOTS['materialization3bb'] / 'RESULT.json').read_bytes()
assert actual_old == old_result
assert old_sdk['path'] == cfg['isolated_materialization']['result_path']
assert identity(old_result) == cfg['isolated_materialization']['result']
old_admission = sdk_json(load(ROOTS['materialization3bb'] / 'MAIN_ADMISSION.original.json'))
new_admission = sdk_json(load(ROOTS['source65a'] / 'MAIN_ADMISSION.original.json'))
new_result = load(ROOTS['source65a'] / 'SOURCE_HANDOFF_RESULT.json')
new_normal = sdk_json(load(ROOTS['source65a'] / 'STATUS_01.original.json'))
new_stdout = (ROOTS['source65a'] / 'stdout.complete').read_bytes()
assert new_result['driver_main_entered'] is False and new_result['driver_returncode'] is None
assert repr(old_sdk['path']) in new_result['error'] and new_result['error'].startswith('FileNotFoundError:')
assert new_normal['job_id'] == '1a1d4f0c3d4-392-65a' and new_normal['exit_code'] == 1
assert all(new_normal[k] is False for k in ('timed_out', 'cancelled', 'automatic_retry'))
assert new_normal['log_bytes']['stdout'] == {'seen': 838, 'stored': 838}
assert len(new_stdout) == 838 and new_normal['log_bytes']['stderr'] == {'seen': 0, 'stored': 0}
assert old_admission['job']['host'] == new_admission['job']['host'] == 'desktop'
assert old_admission['job']['ssh_target'] == new_admission['job']['ssh_target'] == 'desktop-ts'

result = {
    'format': 'source65a-captured-history-path-provenance-independent-v1',
    'audit_scope': 'Pure local captured-original read/AST/hash only. No native probe, H, Git write, candidate import, main or source edit.',
    'code': dict(path=str(CODE), **identity(CODE.read_bytes())),
    'config': dict(path=str(CFG), **identity(CFG.read_bytes())),
    'operation_directories': {key: str(value) for key, value in ROOTS.items()},
    'primary': {
        'historical_successful_read_sdk': dict(path=str(old_sdk_path), **identity(old_sdk_path.read_bytes())),
        'observed_path': old_sdk['path'], 'version': old_sdk['version'],
        'offset': old_sdk['offset'], 'next_offset': old_sdk['next_offset'], 'eof': old_sdk['eof'],
        'body_matches_original_result': True, 'body_pin': identity(old_result),
        'historical_job_id': old_admission['job']['id'], 'failed_job_id': new_normal['job_id'],
        'both_host_selectors': {'host': 'desktop', 'ssh_target': 'desktop-ts'},
        'host_selector_limit': 'A matching host selector is not independent proof of unchanged server, filesystem or mount namespace.',
        'new_result': new_result, 'new_result_pin': identity((ROOTS['source65a'] / 'SOURCE_HANDOFF_RESULT.json').read_bytes()),
        'new_normal_pin': identity((ROOTS['source65a'] / 'STATUS_01.original.json').read_bytes()),
        'stdout_pin': identity(new_stdout),
        'path_typo_hypothesis': 'Not supported: configured path is byte-identical to actual successful historical read path.',
        'proven_failure': 'The historical RESULT pathname lookup/open raised ENOENT during 65a before original source-driver main.',
        'unknown': ['which path component was absent', 'cause or actor of absence', 'deletion versus any other filesystem/context explanation',
                    'current availability of other historical proof paths', 'current source equality; no initial Git baseline had been installed'],
        'no_tests_started': True,
    },
    'finite_crosscheck_counts': {'unique_historical_or_canonical_receipt_paths': len(rows),
                                 'classifications': dict(Counter(row['historical_path_evidence'] for row in rows)),
                                 'path_or_pin_disagreements_in_complete_reads_and_staging': 0},
    'rows': rows, 'incomplete_capture_groups': bad_reads,
    'limit': 'A matched historical path/receipt proves a past observation, never present availability. Missing captured SDK coverage is Unknown, not a failed file or a typo.',
}
dest = OUT / 'CAPTURED_PATH_MATRIX.json'
with dest.open('x') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps({'output': str(dest), **identity(dest.read_bytes()), 'counts': result['finite_crosscheck_counts'],
                  'unresolved_paths': [r['path'] for r in rows if r['historical_path_evidence'].startswith('content_pin_known')],
                  'incomplete_capture_groups': len(bad_reads)}, ensure_ascii=False))
