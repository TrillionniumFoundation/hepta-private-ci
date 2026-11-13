"""Compose only frozen source bytes. No Rust, QA, formatter, H or refs."""
from pathlib import Path
import hashlib
import json
import shutil
import stat

OUT = Path('/tmp/hepta-36fa-at-b-composed-candidate-v1')
BASE = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
INPUTS = [
    ('ROOT89_MAP.json', BASE / 'EXACT_COMPOSED_OVERLAY_89.json',
     '23d710dbda6f7d88ef6b693c1e77933d168b0177'),
    ('AT_SOURCE_PACKET.json', Path('/tmp/hepta-36fa-fresh-material-trainer-split-v1/SOURCE_PACKET.json'),
     'a72dc791ed6026ae49b0500a52dc295f9b3622ad'),
    ('B_SOURCE_PACKET.json', Path('/tmp/hepta-36fa-b-preheld-objective-increment-v1/SOURCE_PACKET.json'),
     '9cb773cee4b42aba80d5836a9e4443f0be1f34fb'),
    ('ORIGINAL_AGENTD_SRC_MAP.json', BASE / 'ORIGINAL_AGENTD_SRC_MAP.json',
     'a27a9ae3949b8632bbcdbe59189081b200dc5165'),
    ('ORIGINAL_LEDGER_SRC_MAP.json', BASE / 'ORIGINAL_LEDGER_SRC_MAP.json',
     'd0e417f969579fc1b724876ddf0e18dc041378d8'),
]


def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def jwrite(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def safe_path(value):
    path = Path(value)
    assert not path.is_absolute() and '..' not in path.parts and str(path) == value, value
    return path


def read_regular(path):
    mode = path.lstat().st_mode
    assert stat.S_ISREG(mode) and not path.is_symlink(), str(path)
    return path.read_bytes(), stat.S_IMODE(mode)


OUT.mkdir(parents=True, exist_ok=True)
overlay = OUT / 'overlay'
assert not overlay.exists(), 'Fresh isolated output only; do not overwrite a composed candidate'
(OUT / 'inputs').mkdir(exist_ok=True)
inputs = {}
input_rows = []
for name, source, expected in INPUTS:
    data, _ = read_regular(source)
    identity = pin(data)
    assert identity['git_blob'] == expected, (name, identity)
    destination = OUT / 'inputs' / name
    assert not destination.exists(), str(destination)
    destination.write_bytes(data)
    inputs[name] = json.loads(data)
    input_rows.append({'name': name, 'original_local_path': str(source), **identity})

base = inputs['ROOT89_MAP.json']
base_directory = Path(base['local_overlay_directory'])
assert base['source_commit'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
agentd_original = inputs['ORIGINAL_AGENTD_SRC_MAP.json']
ledger_original = inputs['ORIGINAL_LEDGER_SRC_MAP.json']
assert agentd_original['commit'] == ledger_original['commit'] == base['source_commit']
original = {**agentd_original['files'], **ledger_original['files']}

base_rows = base['rust_files'] + base['non_rust_prepared']
assert len({row['path'] for row in base_rows}) == len(base_rows)
rows = {}
before_checks = []
for row in base_rows:
    relative = safe_path(row['path'])
    data, physical_mode = read_regular(base_directory / relative)
    assert pin(data) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}, row['path']
    if row['path'].endswith('.rs'):
        assert row['original_git_blob'] == original.get(row['path']), row['path']
    destination = overlay / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_directory / relative, destination)
    git_mode = '100755' if physical_mode & 0o111 else '100644'
    rows[row['path']] = {**row, 'mode': git_mode}
    before_checks.append({'path': row['path'], 'pin': pin(data),
                          'physical_mode': oct(physical_mode), 'copied_exactly': True})

operations = []
layers = [
    ('material-only-before-original-trainer', 'AT_SOURCE_PACKET.json'),
    ('B-preheld-objective-separation', 'B_SOURCE_PACKET.json'),
]
for layer, input_name in layers:
    packet = inputs[input_name]
    packet_pin = next(row['git_blob'] for row in input_rows if row['name'] == input_name)
    assert packet['qualification'] is False
    for change in packet['changes']:
        relative = safe_path(change['path'])
        destination = overlay / relative
        before = change['before']
        if before is None:
            assert not destination.exists() and change['path'] not in rows
            assert change['path'] not in original
            assert change.get('before_text') in (None, '')
            original_blob = None
        else:
            existing, physical_mode = read_regular(destination)
            assert pin(existing) == before, (layer, change['path'], 'before pin')
            assert existing.decode() == change['before_text'], (layer, change['path'], 'before bytes')
            assert rows[change['path']]['mode'] == change['mode'], change['path']
            original_blob = rows[change['path']]['original_git_blob']
        after = change['after_text'].encode()
        assert pin(after) == change['after'], (layer, change['path'], 'after pin')
        assert change['mode'] == '100644'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(after)
        destination.chmod(0o644)
        rows[change['path']] = {'path': change['path'], 'mode': change['mode'],
                                **change['after'], 'original_git_blob': original_blob,
                                'last_layer': layer}
        operations.append({'layer': layer, 'packet': packet_pin, 'path': change['path'],
                           'before': before, 'after': change['after'],
                           'exact_preimage_and_postimage_verified': True})

removals = []
for path in base['explicit_removals']:
    relative = safe_path(path)
    assert not (base_directory / relative).exists()
    assert not (overlay / relative).exists()
    assert path not in rows
    original_blob = original.get(path)
    removals.append({'path': path, 'original_git_blob': original_blob,
                     'present_in_original_cc57_directory': original_blob is not None,
                     'present_in_base89_overlay': False, 'present_in_composed_overlay': False,
                     'meaning': 'Preserved exclusion of the obsolete candidate-only helper path; '
                                'not a deletion from the original cc57 repository.'})

helper = 'codex-rs/hepta-agentd/src/cell_q24_training_shared_readback_support_tests.rs'
assert rows[helper]['git_blob'] == '265e80b2763cbf4f2a530e2e1400f364ee1b1711'
assert rows[helper]['original_git_blob'] is None

rust = [rows[path] for path in sorted(rows) if path.endswith('.rs')]
non_rust = [rows[path] for path in sorted(rows) if not path.endswith('.rs')]


def classify(group):
    answer = {'new': 0, 'modified': 0, 'unchanged_original': 0}
    for row in group:
        if row['original_git_blob'] is None:
            answer['new'] += 1
        elif row['original_git_blob'] == row['git_blob']:
            answer['unchanged_original'] += 1
        else:
            answer['modified'] += 1
    return answer


actual_paths = sorted(str(file.relative_to(overlay)) for file in overlay.rglob('*') if file.is_file())
assert actual_paths == sorted(rows)
after_checks = []
for path in actual_paths:
    data, physical_mode = read_regular(overlay / path)
    row = rows[path]
    assert pin(data) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    assert ('100755' if physical_mode & 0o111 else '100644') == row['mode']
    after_checks.append({'path': path, 'pin': pin(data), 'physical_mode': oct(physical_mode)})

# The old directory remains a source of evidence; compare all its bytes again.
for row in base_rows:
    data, _ = read_regular(base_directory / row['path'])
    assert pin(data) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
for name, source, expected in INPUTS:
    assert pin(source.read_bytes())['git_blob'] == expected

composition = {
    'format': 'hepta-exact-at-B-source-overlay-v1',
    'status': 'Prepared exact overlay; B independent peer pending at freeze; no execution authorization',
    'source_commit': base['source_commit'], 'source_tree': base['source_tree'],
    'source_ref_changed': False, 'qualification': False, 'real_qualified_task_chains': 0,
    'base_map': next(row for row in input_rows if row['name'] == 'ROOT89_MAP.json'),
    'base_coverage': {'rust': len(base['rust_files']), 'non_rust': len(base['non_rust_prepared'])},
    'inputs': input_rows, 'inherited_base_layers': base['layers'],
    'appended_layers': [{'name': name, 'packet': next(row['git_blob'] for row in input_rows if row['name'] == file)}
                        for name, file in layers],
    'operations': operations, 'explicit_removals': list(base['explicit_removals']),
    'removal_classification': removals, 'retained_renamed_helper': rows[helper],
    'rust_source_coverage': len(rust), 'non_rust_source_coverage': len(non_rust),
    'overlay_covered_paths': len(rows), 'rust_classification': classify(rust),
    'non_rust_classification': classify(non_rust), 'rust_files': rust,
    'non_rust_prepared': non_rust, 'local_overlay_directory': str(overlay),
    'local_full_bytes_verified': True, 'all_layer_preimages_and_postimages_verified': True,
    'base89_directory_and_input_files_unchanged': True,
    'full_repository_materialized': False, 'full_repository_file_count': None,
    'full_repository_rust_file_count': None,
    'inherited_conditional_inventory_numbers_not_promoted': base['conditional_inventory_arithmetic_only'],
    'inventory_count_limit': 'Overlay coverage is actual. A full source inventory must be produced '
                             'from the unchanged complete cc57 source. Excluding the old candidate-only '
                             'helper must not subtract a file absent from cc57.',
    'qa_preservation_scope_inherited_unchanged': base['qa_preservation_scope'],
    'B_independent_peer_status': 'pending at this composition freeze',
    'git_full_readback_status': 'pending; see separate availability ledger before final map',
    'format_compile_or_behavioral_tests_run': False,
    'current_blockers': list(base['current_blockers']),
}
jwrite('LOCAL_COMPOSITION.json', composition)
jwrite('LOCAL_BYTE_VERIFICATION.json', {
    'format': 'hepta-at-B-pure-local-byte-review-v1', 'qualification': False,
    'copied_base_paths': before_checks, 'final_paths': after_checks,
    'operations': operations, 'base89_unchanged': True,
    'explicit_removals': removals, 'all_source_bytes_checked': True,
    'full_repository_materialized': False, 'executed_Rust_or_QA': False,
})
jwrite('GIT_READBACK_INPUTS.json', {
    'inputs': input_rows,
    'final_sources': [{'path': row['path'], **{key: row[key] for key in ('bytes', 'sha256', 'git_blob')}}
                      for row in sorted(rows.values(), key=lambda row: row['path'])],
})
print(json.dumps({'local_composition': pin((OUT / 'LOCAL_COMPOSITION.json').read_bytes()),
                  'rust': len(rust), 'non_rust': len(non_rust), 'total': len(rows),
                  'rust_classification': classify(rust), 'non_rust_classification': classify(non_rust),
                  'exact_layer_operations': len(operations), 'base89_unchanged': True,
                  'git_readback': 'pending'}, indent=2))
