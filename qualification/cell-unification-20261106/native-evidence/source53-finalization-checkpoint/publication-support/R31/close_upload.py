from pathlib import Path
import hashlib
import json
import os

P = Path('r31-formal-root-preparation')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with (P / name).open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    return {'path': str(P / name), **pin(raw)}

plan_raw = (P / 'ROOT-UPLOAD-PLAN.json').read_bytes()
assert pin(plan_raw)['sha256'] == '4d4dc1d9d811c57dc804bf5555f8aa19bfc5adc2f0efe728675d350f51d3cf5f'
plan = json.loads(plan_raw)
ledger_path = Path('publication-ledger.json')
ledger_raw = ledger_path.read_bytes()
assert pin(ledger_raw)['sha256'] == 'c35900b1d89de8df5d0d7b811ed2a3be535559acf1a3cfbe310bde7ec4a352e5'
ledger = json.loads(ledger_raw)
base = json.loads(Path('publication-recovery-prep/checkpoint6-actual-leaf-map.json').read_bytes())
overlay_raw = Path('source53-r30-publication-root-preparation/COMBINED-STAGED-OVERLAY.json').read_bytes()
assert pin(overlay_raw)['sha256'] == '6444ab05472ea1284348cd325950e1757704a5bcf0c851ee8896f78d30eccbe9'
overlay = json.loads(overlay_raw)
known = set(base['files'].values()) | set(overlay['files'].values()) | set(ledger['created_blobs'].values())
observed = {}
created = reused = batch_count = 0
for path in sorted((P / 'upload-batches').glob('batch-*.json')):
    batch = json.loads(path.read_bytes())
    assert batch['errors'] == [] and batch['total_paths'] == 329
    assert batch['plan_sha256'] == pin(plan_raw)['sha256']
    for row in batch['staged']:
        assert row['repo_path'] not in observed
        if row['reused']:
            assert row['git_blob'] in known
            reused += 1
        else:
            assert not row['actual_response'].get('isError')
            assert row['actual_response']['structuredContent']['sha'] == row['git_blob']
            created += 1
        known.add(row['git_blob']); observed[row['repo_path']] = row
    assert batch['completed_paths'] == len(observed)
    batch_count += 1
assert len(observed) == len(plan['files']) == 329
new_binary = []
overlap = []
for row in plan['files']:
    raw = Path(row['local_path']).read_bytes()
    assert pin(raw) == {k: row[k] for k in pin(raw)}, row['path']
    assert observed[row['repo_path']]['git_blob'] == row['git_blob']
    assert observed[row['repo_path']]['binary'] == row['binary']
    if row['repo_path'] in overlay['files']:
        assert overlay['files'][row['repo_path']] == row['git_blob'] and overlay['file_sizes'][row['repo_path']] == row['bytes']
        overlap.append(row['repo_path'])
    overlay['files'][row['repo_path']] = row['git_blob']
    overlay['file_sizes'][row['repo_path']] = row['bytes']
    if row['binary']:
        old = ledger['created_blobs'].get(row['repo_path'])
        assert old is None or old == row['git_blob']
        if old is None:
            ledger['created_blobs'][row['repo_path']] = row['git_blob']; new_binary.append(row['repo_path'])
assert overlap == ['qualification/cell-unification-20261106/native-evidence/r31-workspace-checkpoint/archive/checkpoint-r31-closed.tar.gz']
assert len(overlay['files']) == len(overlay['file_sizes']) == 1103
assert len(new_binary) == 16 and len(ledger['created_blobs']) == 264
assert len(ledger['commits']) == 53 and len(ledger['artifact_checkpoints']) == 6
assert not ledger['branch_created'] and not ledger['pull_request_created']
with (P / 'LEDGER-BEFORE-BINARY-REGISTRATION.json').open('xb') as f:
    f.write(ledger_raw); f.flush(); os.fsync(f.fileno())
overlay['schema'] = 'hepta.root-through-source53-r31-staged-overlay.v1'
overlay_pin = write('COMBINED-STAGED-OVERLAY.json', overlay)
after_pin = write('LEDGER-AFTER-BINARY-REGISTRATION.json', ledger)
after_raw = (P / 'LEDGER-AFTER-BINARY-REGISTRATION.json').read_bytes()
assert ledger_path.read_bytes() == ledger_raw
temp = ledger_path.with_suffix('.r31-registration.tmp')
with temp.open('xb') as f:
    f.write(after_raw); f.flush(); os.fsync(f.fileno())
os.replace(temp, ledger_path)
closure = {'schema': 'hepta.root-source53-r31-formal-upload-closed.v1', 'count': 329, 'bytes': plan['bytes'],
           'actual_create_responses': created, 'existing_actual_Git_object_reuses': reused, 'batch_count': batch_count,
           'all329_raw_and_Git_pins_and_actual_receipts_verified': True, 'identical_existing_archive_overlap': overlap,
           'combined_overlay': overlay_pin,
           'ledger_before': {'path': str(P / 'LEDGER-BEFORE-BINARY-REGISTRATION.json'), **pin(ledger_raw)},
           'ledger_after': after_pin, 'new_binary_paths_registered': new_binary,
           'source_commits': 53, 'binary_paths': 264, 'artifact_checkpoints': 6,
           'original_R31': {'source_commit': ledger['current_source_commit'], 'source_tree': ledger['current_source_tree'],
                            'outer_exit': 0, 'tests_exit': 0, 'counts': {'PASS': 20228, 'FAIL': 0, 'TIMEOUT': 0}, 'reported_skipped': 130},
           'finalizer_results_not_contained_in_this_R31_formal_group': True,
           'original_R29_failure_preserved': True, 'diagnostic_only': True, 'behavior_repair_claimed': False,
           'science': 'HOLD', 'authority': 'DENY_ALL'}
result = write('UPLOAD-CLOSED.json', closure)
print(json.dumps({'closure': result, 'created': created, 'reused': reused, 'ledger': after_pin, 'overlay': overlay_pin}))
