import hashlib
import json
import pathlib

root = pathlib.Path('r29-formal-root-preparation')
raw = (root / 'ROOT-UPLOAD-PLAN.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == '9797f4f48c3ae26303c36d44528736bc291ea3d0541e7807b5afc3a9080690bc'
plan = json.loads(raw)
by_path = {row['repo_path']: row for row in plan['files']}
known = set(json.loads(pathlib.Path('publication-recovery-prep/checkpoint6-actual-leaf-map.json').read_bytes())['files'].values())
known.update(json.loads(pathlib.Path('publication-ledger.json').read_bytes())['created_blobs'].values())
done = {}
for path in sorted((root / 'upload-batches').glob('batch-*.json')):
    batch = json.loads(path.read_bytes())
    assert not batch['errors']
    for row in batch['staged']:
        expected = by_path[row['repo_path']]
        assert row['git_blob'] == expected['git_blob'] and row['repo_path'] not in done
        if row['reused']:
            assert row['git_blob'] in known
        else:
            assert row['actual_response']['structuredContent']['sha'] == row['git_blob']
            assert not row['actual_response']['isError']
        done[row['repo_path']] = row['git_blob']
        known.add(row['git_blob'])
    assert batch['completed_paths'] == len(done)
next_rows = []
for row in plan['files']:
    if row['repo_path'] in done:
        continue
    raw = pathlib.Path(row['local_path']).read_bytes()
    assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['git_blob']
    next_rows.append({**row, 'known_actual_git_blob': row['git_blob'] in known})
    if len(next_rows) == 8:
        break
print(json.dumps({'completed': len(done), 'total': len(plan['files']), 'next': next_rows}))
