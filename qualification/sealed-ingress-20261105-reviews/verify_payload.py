"""Read-only verification of the frozen second evidence package.

Only this script's sibling review outputs are written. No source, archive,
Git checkout, native job or submitted payload is modified.
"""
from pathlib import Path
import datetime
import hashlib
import json
import posixpath
import re

ROOT = Path('/workspace/scratch/0c901b844a27')
OUT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'integration/sealed-qualification'
PREFIX = 'qualification/sealed-ingress-20261105/'
FIRST_PREFIX = 'qualification/runtime-convergence-20261105/'
PIN = 'a9efffacf0409231767b81ee7a86633e9a0037d508d4db9ed7720ab2c71e11e8'
FIRST_PIN = '09b8fb64816e0465c44904095369cee2fdd9eaa8aa7c1a3637e80b40523a569e'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


payload_path = ROOT / 'integration/final-second-evidence-payload.json'
raw = payload_path.read_bytes()
assert digest(raw) == PIN
assert len(raw) == 3687470 and len(raw.decode()) == 3686928
payload = json.loads(raw)
assert len(payload) == 172
by_path = {}
metadata = []
for row in payload:
    path = row['path']
    assert path.startswith(PREFIX)
    rel = path[len(PREFIX):]
    assert posixpath.normpath(rel) == rel and not rel.startswith('../')
    assert rel not in by_path
    data = (ARCHIVE / rel).read_bytes()
    assert data == row['content'].encode()
    assert digest(data) == row['sha256']
    assert len(data) == row['bytes']
    assert git_blob(data) == row['expected_blob']
    by_path[rel] = row
    metadata.append({key: value for key, value in row.items() if key != 'content'})
assert set(by_path) == {
    str(path.relative_to(ARCHIVE)) for path in ARCHIVE.rglob('*') if path.is_file()
}

first_path = ROOT / 'integration/final-first-evidence-payload.json'
first_raw = first_path.read_bytes()
assert digest(first_raw) == FIRST_PIN
first = json.loads(first_raw)
assert len(first) == 69
published = {row['path']: row['content'].encode() for row in payload + first}
assert len(published) == 241
for row in first:
    assert row['path'].startswith(FIRST_PREFIX)
    data = (ROOT / 'integration/qualification' / row['path'][len(FIRST_PREFIX):]).read_bytes()
    assert data == row['content'].encode()
    assert digest(data) == row['sha256'] and git_blob(data) == row['expected_blob']
    assert len(data) == row['bytes']

index = json.loads((ARCHIVE / 'native-artifact-manifest.json').read_bytes())
indexed = set()
for row in index['files']:
    rel = row['path']
    assert rel not in indexed
    indexed.add(rel)
    data = (ARCHIVE / rel).read_bytes()
    assert digest(data) == row['sha256'] and len(data) == row['bytes']
assert len(indexed) == 171
assert set(by_path) - indexed == {'native-artifact-manifest.json'}
assert indexed <= set(by_path)

old_raw = (ROOT / 'adaptive/evidence-audit/second-preflight/snapshot-manifest.json').read_bytes()
old = {row['path']: row for row in json.loads(old_raw)['files']}
added = sorted(set(by_path) - set(old))
removed = sorted(set(old) - set(by_path))
changed = sorted(path for path in set(old) & set(by_path)
                 if old[path]['sha256'] != by_path[path]['sha256'])
unchanged = sorted(path for path in set(old) & set(by_path)
                   if old[path]['sha256'] == by_path[path]['sha256'])
assert len(added) == 50 and not removed and len(unchanged) == 116
assert changed == ['README.md', 'native-artifact-manifest.json',
                   'native-source-manifest.json', 'native-validation.md',
                   'negative-controls/manifest.json', 'validation.json']
assert all(path in unchanged for path in old if path.startswith('native-round2'))

links = []
for row in payload:
    if not row['path'].endswith('.md'):
        continue
    text = row['content']
    for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
        target = match.group(1).split('#', 1)[0]
        if not target or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(row['path']), target))
        assert resolved in published, (row['path'], target, resolved)
        links.append({'source': row['path'], 'line': text[:match.start()].count('\n') + 1,
                      'target': target, 'resolved_repository_path': resolved,
                      'target_sha256': digest(published[resolved])})

bundle_checks = []
for folder in ['native-round2', 'native-round2-gate-v2']:
    manifest = json.loads((ARCHIVE / folder / 'runtime-bundle-manifest.json').read_bytes())
    for row in manifest['files']:
        data = (ARCHIVE / folder / row['path']).read_bytes()
        assert digest(data) == row['sha256'] and len(data) == row['bytes']
    bundle_checks.append({'directory': folder, 'indexed_files': len(manifest['files']),
                          'all_hashes_sizes_match': True, 'preflight_bytes_unchanged': True})

history_manifest = json.loads((ROOT / 'adaptive/second-history-provenance/manifest.json').read_bytes())
for row in history_manifest['files']:
    data = published[row['path']]
    assert digest(data) == row['sha256'] and len(data) == row['bytes']
    assert git_blob(data) == row['git_blob']

convergence = json.loads((ARCHIVE / 'convergence-target-review.json').read_bytes())
assert digest((ARCHIVE / 'convergence-target.md').read_bytes()) == convergence['reviewed_document']['sha256']
for field, hash_field in [('canonical_review_local_path', 'canonical_review_sha256'),
                         ('source_manifest_local_path', 'source_manifest_sha256')]:
    record = convergence['existing_source_review']
    assert digest((ROOT / record[field]).read_bytes()) == record[hash_field]

write('reviewed-payload-file-manifest.json', metadata)
result = {
    'schema': 'hepta.sealed-ingress-final-payload-mechanical-check.v1',
    'recorded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'payload': {'sha256': PIN, 'bytes': len(raw), 'characters': len(raw.decode()),
                'files': len(payload), 'all_content_sha_size_gitblob_match': True,
                'complete_local_inventory_matches': True},
    'first_payload': {'sha256': FIRST_PIN, 'files': len(first), 'unchanged': True},
    'artifact_index': {'sha256': digest((ARCHIVE / 'native-artifact-manifest.json').read_bytes()),
                       'entries': len(indexed), 'only_unindexed': 'native-artifact-manifest.json'},
    'delta_from_preflight': {'prior_manifest_sha256': digest(old_raw), 'added': added,
                             'changed': changed, 'removed': removed, 'unchanged': unchanged},
    'relative_markdown_links': {'count': len(links), 'all_resolve': True,
                                'layout': 'Published qualification/* namespaces from both exact payloads',
                                'links': links},
    'frozen_bundle_checks': bundle_checks,
    'history_provenance_package': {'files': 5, 'all_original_digests_preserved': True},
    'convergence_target_and_canonical_source_references_match': True,
    'issues': [],
    'activity': 'Read-only local archive verification; only sibling review outputs written.'
}
assert digest(payload_path.read_bytes()) == PIN
assert digest(first_path.read_bytes()) == FIRST_PIN
write('payload-mechanical-check.json', result)
print(json.dumps({'files': len(payload), 'index_entries': len(indexed),
                  'relative_links': len(links), 'unchanged': len(unchanged),
                  'added': len(added), 'changed': len(changed), 'issues': []}))
