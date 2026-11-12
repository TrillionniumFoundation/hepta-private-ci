"""Read-only independent collection; never execute or modify Root's collector.

Writes only this new external directory. No Git, H, ref, PR, native process,
source code, formatter or gate operation occurs here.
"""
from pathlib import Path
import base64
import datetime
import hashlib
import json
import re

OUT = Path(__file__).resolve().parent
ROOT = Path('/tmp/hepta-36fa-after2268-20261112')
PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/'
SNAPSHOTS = OUT / 'input-snapshots'
SNAPSHOTS.mkdir(exist_ok=True)
inputs = []
captured = {}


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def stable(path):
    path = Path(path)
    first = path.stat()
    raw = path.read_bytes()
    last = path.stat()
    assert (first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns, first.st_ctime_ns) == (
        last.st_dev, last.st_ino, last.st_size, last.st_mtime_ns, last.st_ctime_ns), str(path)
    assert len(raw) == first.st_size
    return raw


def snapshot(path, label):
    path = Path(path)
    if str(path) in captured:
        return captured[str(path)]
    raw = stable(path)
    target = SNAPSHOTS / label
    earlier = None
    if target.exists() and target.read_bytes() != raw:
        earlier = {'snapshot': str(target), **identity(target.read_bytes())}
        target = target.with_name(target.stem + '.' + identity(raw)['sha256'][:16] + target.suffix)
    if target.exists():
        assert target.read_bytes() == raw, 'do not overwrite frozen input ' + label
    else:
        target.write_bytes(raw)
    row = {'source': str(path), 'snapshot': str(target), **identity(raw)}
    if earlier is not None:
        row['earlier_capture_retained_unchanged'] = earlier
    inputs.append(row)
    captured[str(path)] = (raw, row)
    return raw, row


def jsnapshot(path, label):
    raw, pin = snapshot(path, label)
    return json.loads(raw), pin


def save(name, value):
    (OUT / name).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


plan, plan_pin = jsnapshot('/tmp/hepta-36fa-after2138-20261112/NEXT_CHECKPOINT_PUBLISH_PLAN.json', 'BASE_2268_PUBLISH_PLAN.original.json')
base = dict(plan['files'])
assert len(base) == 2268 and base['README.md'] == '3e8b17601e82f5f7be49d172784bc2c4a452a080'
save('BASE_2268_FILEMAP.json', base)
snapshot(ROOT / 'collect_checkpoint_entries.py', 'ROOT_COLLECTOR.original.py')
known, known_pin = jsnapshot(ROOT / 'PENDING_KNOWN_ENTRIES.json', 'PENDING_KNOWN_ENTRIES.original.json')
known_origins, _ = jsnapshot(ROOT / 'PENDING_KNOWN_PROVENANCE.json', 'PENDING_KNOWN_PROVENANCE.original.json')
uploads_raw, uploads_pin = snapshot(ROOT / 'ROOT_UPLOADS.jsonl', 'ROOT_UPLOADS.original.jsonl')
root_uploads = [json.loads(row) for row in uploads_raw.splitlines()]
queues = []
for name in ('UPLOAD_QUEUE.json', 'EXTRA_UPLOAD_QUEUE.json', 'ADDITIONAL_UPLOAD_QUEUE.json'):
    value, pin = jsnapshot(ROOT / name, name.replace('.json', '.original.json'))
    queues.append((name, value, pin))

full = dict(base)
provenance = {}
local_by_sha = {}
verified_by_sha = {sha: [{'kind': 'existing_2268_baseline', 'source': plan_pin}]
                   for sha in set(base.values())}
collisions = []


def remember(path, sha, origin, verified=False, local=None, expected=None):
    if path.startswith(PREFIX):
        path = path[len(PREFIX):]
    assert path and not path.startswith('/') and all(p not in ('', '.', '..') for p in path.split('/')), path
    assert re.fullmatch('[0-9a-f]{40}', sha), (path, sha)
    if path in full:
        assert full[path] == sha, ('path collision', path, full[path], sha)
    else:
        full[path] = sha
    if path not in base:
        provenance.setdefault(path, []).append(origin)
    if verified:
        verified_by_sha.setdefault(sha, []).append(origin)
    if local:
        raw = stable(local)
        actual = identity(raw)
        assert actual['git_blob'] == sha, ('local content changed', path, actual, sha)
        if expected:
            for key in ('bytes', 'sha256'):
                if key in expected:
                    assert actual[key] == expected[key], (path, key)
        local_by_sha.setdefault(sha, {'local_path': str(local), **actual})


for row in root_uploads:
    assert row['full_readback_equal'] is True
    remember(row['path'], row['sha'], {'kind': 'root_full_create_and_readback', 'index': uploads_pin,
             'source_path': row['path']}, True, row.get('local_path'), row)
for path, sha in known.items():
    remember(path, sha, {'kind': 'root_pending_known_mapping', 'index': known_pin,
             'recorded_origin': known_origins[path]}, True)
for name, rows, pin in queues:
    for row in rows:
        remember(row['path'], row['sha'], {'kind': 'root_original_queue', 'index': pin,
                 'queue': name, 'local': row['local_path']}, False, row['local_path'], row)

placements = [
    ('/tmp/hepta-36fa-final-nonrust-evidence-package-v1/PLACEMENT.json', 'NONRUST_V1_PLACEMENT.original.json', 'entries'),
    ('/tmp/hepta-36fa-final-nonrust-evidence-package-v2/PLACEMENT.json', 'NONRUST_V2_PLACEMENT.original.json', 'entries'),
    ('/tmp/hepta-36fa-final-nonrust-fmt-launch-v2/COMPLETE_SUCCESS_ORIGINALS_PLACEMENT.json', 'FRESH2_SUCCESS_PLACEMENT.original.json', 'rows'),
    ('/tmp/hepta-36fa-finalfmt-exact-recovery-v1/PLACEMENT.json', 'FRESH2_RECOVERY_PLACEMENT.original.json', 'files'),
    ('/tmp/hepta-36fa-final-qualification-hold-v1/PLACEMENT.json', 'QUALIFICATION_HOLD_PLACEMENT.original.json', 'files'),
]
for name, label, array in placements:
    value, pin = jsnapshot(name, label)
    for row in value[array]:
        verified = any(row.get(k) is True for k in (
            'readback_equal', 'full_utf8_readback_equal', 'full_github_readback_equal'))
        verification_note = None
        if not verified and row.get('published') is True and row['path'].endswith('.gz'):
            companions = [x for x in value[array] if x.get('path') == row['path'] + '.base64']
            assert len(companions) == 1 and companions[0].get('full_utf8_readback_equal') is True
            companion = companions[0]
            raw = stable(row['local_path'])
            encoded = stable(companion['local_path'])
            assert base64.b64decode(encoded) == raw
            assert identity(raw)['git_blob'] == row['git_blob']
            assert identity(encoded)['git_blob'] == companion['git_blob']
            verified = True
            verification_note = {
                'kind': 'native_created_binary_SHA_and_exact_full_UTF8_companion',
                'direct_binary_full_readback': False,
                'companion_git_blob': companion['git_blob'],
                'original_native_full_utf8_readback_flag_preserved': False,
            }
        assert verified, (name, row)
        remember(row['path'], row.get('git_blob', row.get('sha')), {'kind': 'full_readback_placement',
                 'index': pin, 'source_path': row['path'], 'verification_note': verification_note}, True,
                 row.get('local_path', row.get('local')), row)

failure, failure_pin = jsnapshot('/tmp/hepta-36fa-final-nonrust-fmt-launch-v1/COMPLETE_FAILURE_AND_PROBE_PLACEMENT.json',
                                'ATTEMPT1_FAILURE_AND_PROBE_PLACEMENT.original.json')
directory_mapping = [
    ('/tmp/hepta-36fa-final-nonrust-fmt-launch-v1', 'final-format-attempt1/launch'),
    ('/tmp/hepta-36fa-finalfmt-v1-concurrency-observation', 'final-format-attempt1-concurrency-observation'),
    ('/tmp/hepta-36fa-final-nonrust-fmt-v2', 'final-format-attempt2/preparation'),
    ('/tmp/hepta-36fa-final-nonrust-fmt-launch-v2', 'final-format-attempt2/launch'),
]
for row in failure['files']:
    assert row['github_full_readback_equal'] is True
    matches = [(Path(directory), prefix) for directory, prefix in directory_mapping
               if Path(row['local_path']).parent == Path(directory)]
    assert len(matches) == 1
    directory, prefix = matches[0]
    remember(prefix + '/' + Path(row['local_path']).name, row['git_blob'],
             {'kind': 'native_original_failure_probe_full_readback', 'index': failure_pin,
              'path_mapping': 'Unchanged Root collector directory mapping'}, True, row['local_path'], row)

# Enumerate the same explicit directories as Root's read collector. Native may
# have completed additional immutable reads after Root generated its queues.
for directory, prefix in directory_mapping:
    for local in sorted(Path(directory).iterdir()):
        if not local.is_file():
            continue
        if local.name.endswith('.GITHUB.original.json') and local.stat().st_size > 400000:
            continue
        raw = stable(local)
        pin = identity(raw)
        if pin['bytes'] > 400000 and pin['git_blob'] not in verified_by_sha:
            # Original collector permits large controls only when the exact
            # immutable blob has already been read back. Do not create it here.
            assert pin['git_blob'] in {
                '4e208dbc01db65103137918e42ef5b80247281fd', '8bdc74ba9b6c7e009b478c21c87b6d546821797a',
                '19b2efc91b032c85a5774056e2a57632dbc28be1', 'b423b3e7603df510cf6c9d2c8f1009f39bdaeff6'}, (str(local), pin)
            verified_by_sha[pin['git_blob']] = [{'kind': 'exact_large_control_explicitly_verified_by_root_collector'}]
        remember(prefix + '/' + local.name, pin['git_blob'], {'kind': 'same_explicit_collector_directory_snapshot',
                 'directory': directory, 'local': str(local)}, False, local, pin)

# Current Root approval/review files are evidence only. Copy their bytes into
# this preparation; never modify or invoke them and never treat HOLD as execution.
for local in sorted(ROOT.iterdir()):
    if not local.is_file() or local.name == 'ROOT_UPLOADS.jsonl':
        continue
    if not local.name.startswith(('ROOT_', 'verify_', 'APPROVED_')):
        continue
    raw, pin = snapshot(local, 'ROOT_CURRENT_' + local.name)
    remember('root-post2268/' + local.name, pin['git_blob'],
             {'kind': 'current_root_review_or_control_snapshot', 'input': pin,
              'execution_claim': 'No execution inferred from this preparation or approval file'}, False, local, pin)

extra_fixed = [
    ('/tmp/hepta-36fa-final-qualification-peer-review-v1/REVIEW.json', 'final-qualification-peer-review-v1/REVIEW.json', '163c7b4dacccdc5ce9b72970aaa5352448cdcaa9'),
    ('/tmp/hepta-36fa-final-qualification-hold-v1/PLACEMENT.json', 'final-qualification-hold-v1/PLACEMENT.json', '2a39b54eed3c10d2e1455bb15206a5e70757e198'),
    ('/tmp/hepta-36fa-finalfmt-exact-recovery-v1/PLACEMENT.json', 'final-nonrust-fmt-v2/exact-recovery/PLACEMENT.json', '40da83e30e00d8b5f202ee052568fca402947115'),
    ('/tmp/hepta-36fa-final-nonrust-fmt-launch-v2/COMPLETE_SUCCESS_ORIGINALS_PLACEMENT.json', 'final-nonrust-fmt-v2/COMPLETE_SUCCESS_ORIGINALS_PLACEMENT.json', 'd8258ae891a519ed16a542ddb64c269c3bc224b4'),
    ('/tmp/hepta-36fa-final-nonrust-fmt-launch-v1/COMPLETE_FAILURE_AND_PROBE_PLACEMENT.json', 'final-format-attempt1/launch/COMPLETE_FAILURE_AND_PROBE_PLACEMENT.json', 'c1a9807a383966e80e7474a38740f768b2452263'),
]
for local, path, sha in extra_fixed:
    remember(path, sha, {'kind': 'agent_full_readback_immutable_handoff', 'local': local}, True, local)

for version in ('v1', 'v2'):
    directory = Path('/tmp/hepta-36fa-final-source-preparation-' + version)
    for name in ('prepare_canonical_objects.py', 'OBJECTS_PREPARED_MANIFEST.json',
                 'V2_REPLACEMENT_BLOB_PUBLISHED.json', 'CANDIDATE_TREE_INPUT.json',
                 'CANDIDATE_TREE_CREATE.response.json', 'CANDIDATE_TREE_READ.response.json',
                 'FINAL_DIRTY_INVENTORY.candidate.prediction.json'):
        local = directory / name
        if local.exists():
            raw = stable(local); pin = identity(raw)
            remember('final-source-object-preparation-' + version + '/' + name, pin['git_blob'],
                     {'kind': 'same_root_collector_preparation_object', 'local': str(local)}, False, local, pin)

assert full['checkpoints/README_2268FILES_BEFORE_FINAL_NONRUST.md'] == base['README.md']
assert all(full[path] == sha for path, sha in base.items())
increment = {path: sha for path, sha in sorted(full.items()) if path not in base}
unverified = sorted(set(increment.values()) - set(verified_by_sha))
upload = []
for sha in unverified:
    assert sha in local_by_sha, ('missing unverified object content', sha)
    row = local_by_sha[sha]
    assert row['bytes'] <= 400000, row
    stable(row['local_path']).decode('utf-8')
    upload.append({**row, 'paths': [p for p, s in increment.items() if s == sha]})

aliases = {sha: sorted(p for p, value in full.items() if value == sha)
           for sha in set(increment.values())}
aliases = {sha: paths for sha, paths in aliases.items() if len(paths) > 1}
save('INCREMENTAL_FILEMAP.json', increment)
save('FULL_FILEMAP_BEFORE_README_REPLACEMENT.json', dict(sorted(full.items())))
save('PATH_PROVENANCE.json', provenance)
save('INPUT_SNAPSHOT_INDEX.json', inputs)
save('BLOB_VERIFICATION_PROVENANCE.json', verified_by_sha)
save('UNPUBLISHED_SMALL_OBJECT_QUEUE.json', upload)
save('IDENTICAL_BLOB_PATH_ALIASES.json', aliases)
save('BASE_PRESERVATION_REVIEW.json', {
    'status': 'all_2268_existing_paths_same_sha_before_readme_draft',
    'existing_paths': len(base), 'removed_paths': [], 'changed_paths': [],
    'new_paths': len(increment), 'combined_count_before_additional_canonical_results': len(full),
    'previous_readme': base['README.md'],
    'previous_readme_archived_as': 'checkpoints/README_2268FILES_BEFORE_FINAL_NONRUST.md',
    'new_readme_not_yet_substituted': True,
    'actual_real_qualified_task_chains': 0,
    'commit_ref_PR_H_source_updates': False,
})
save('COLLECTION_SUMMARY.json', {
    'format': 'hepta-independent-next-evidence-preparation-v1',
    'prepared_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'base_files': len(base), 'increment_paths': len(increment), 'combined_files': len(full),
    'unique_new_blob_identities': len(set(increment.values())),
    'objects_already_verified_or_existing': len(set(increment.values()) & set(verified_by_sha)),
    'unique_unpublished_small_objects': len(upload), 'upload_bytes': sum(r['bytes'] for r in upload),
    'maximum_new_upload': max([0] + [r['bytes'] for r in upload]),
    'input_snapshot_count': len(inputs),
    'root_files_written': False, 'original_collector_executed': False,
    'current_readme_unchanged': True, 'commit_created': False, 'ref_or_PR_updated': False,
    'pending': ['Upload and full-readback only the listed small objects',
                'Draft new README/PR without inventing canonical-alignment or qualification results',
                'Root supplements actual new canonical and future alignment/gates before publication'],
})
print((OUT / 'COLLECTION_SUMMARY.json').read_text())
