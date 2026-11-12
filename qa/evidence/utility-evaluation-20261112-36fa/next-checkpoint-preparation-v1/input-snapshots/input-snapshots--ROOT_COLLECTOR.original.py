import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-after2268-20261112')
PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/'
BASE = json.loads(Path('/tmp/hepta-36fa-after2138-20261112/NEXT_CHECKPOINT_PUBLISH_PLAN.json').read_text())['files']
assert len(BASE) == 2268
known = {}
provenance = {}
queue = []


def remember(path, sha, origin):
    if path.startswith(PREFIX):
        path = path[len(PREFIX):]
    assert path and not path.startswith('/') and all(part not in ('', '.', '..') for part in path.split('/'))
    if path in BASE:
        assert BASE[path] == sha, path
        return
    if path in known:
        assert known[path] == sha, path
        return
    known[path] = sha
    provenance[path] = origin


for line in (ROOT / 'ROOT_UPLOADS.jsonl').read_text().splitlines():
    row = json.loads(line)
    assert row['full_readback_equal']
    remember(row['path'], row['sha'], 'Root create and full readback')

for path in [Path('/tmp/hepta-36fa-final-nonrust-evidence-package-v1/PLACEMENT.json'),
             Path('/tmp/hepta-36fa-final-nonrust-evidence-package-v2/PLACEMENT.json')]:
    value = json.loads(path.read_text())
    for row in value['entries']:
        assert row['readback_equal'] and row['mode'] == '100644' and row['type'] == 'blob'
        remember(row['path'], row['git_blob'], str(path))

published_shas = set(known.values()) | set(BASE.values())
# These larger exact launch inputs were independently pinned by Root and the
# native executor recorded full GitHub readback. Publication SDK echoes are
# redundant transport copies; original H SDK records are retained separately.
published_shas.update({
    '4e208dbc01db65103137918e42ef5b80247281fd',
    '8bdc74ba9b6c7e009b478c21c87b6d546821797a',
    '19b2efc91b032c85a5774056e2a57632dbc28be1',
    'b423b3e7603df510cf6c9d2c8f1009f39bdaeff6',
})


def add_local(local, path):
    local = Path(local)
    raw = local.read_bytes()
    raw.decode()
    sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if path in BASE:
        assert BASE[path] == sha
        return
    if path in known:
        assert known[path] == sha
        return
    if sha in published_shas:
        remember(path, sha, 'Identical already full-readback Git blob; alias is not a new observation')
        return
    assert len(raw) <= 400000, (path, len(raw))
    queue.append({'path': path, 'local_path': str(local), 'bytes': len(raw),
                  'sha256': hashlib.sha256(raw).hexdigest(), 'sha': sha})


for directory, prefix in [
    ('/tmp/hepta-36fa-final-nonrust-fmt-launch-v1', 'final-format-attempt1/launch'),
    ('/tmp/hepta-36fa-finalfmt-v1-concurrency-observation', 'final-format-attempt1-concurrency-observation'),
    ('/tmp/hepta-36fa-final-nonrust-fmt-v2', 'final-format-attempt2/preparation'),
    ('/tmp/hepta-36fa-final-nonrust-fmt-launch-v2', 'final-format-attempt2/launch'),
]:
    for local in sorted(Path(directory).iterdir()):
        if not local.is_file():
            continue
        if local.name.endswith('.GITHUB.original.json') and local.stat().st_size > 400000:
            continue
        add_local(local, prefix + '/' + local.name)

for version in ('v1', 'v2'):
    directory = Path('/tmp/hepta-36fa-final-source-preparation-' + version)
    for name in ['prepare_canonical_objects.py', 'OBJECTS_PREPARED_MANIFEST.json',
                 'V2_REPLACEMENT_BLOB_PUBLISHED.json', 'CANDIDATE_TREE_INPUT.json',
                 'CANDIDATE_TREE_CREATE.response.json', 'CANDIDATE_TREE_READ.response.json',
                 'FINAL_DIRTY_INVENTORY.candidate.prediction.json']:
        local = directory / name
        if local.exists():
            add_local(local, 'final-source-object-preparation-' + version + '/' + name)

add_local('/tmp/hepta-36fa-canonical-alignment-peer-review-v1/REVIEW.json',
          'final-canonical-alignment-peer-review-v1/REVIEW.json')
add_local('/tmp/hepta-36fa-final-nonrust-evidence-package-v2/PLACEMENT.json',
          'postformat-final-nonrust-archive-v2/PLACEMENT.json')

assert len({row['path'] for row in queue}) == len(queue)
assert not set(known) & {row['path'] for row in queue}
(ROOT / 'PENDING_KNOWN_ENTRIES.json').write_text(json.dumps(known, sort_keys=True, indent=2) + '\n')
(ROOT / 'PENDING_KNOWN_PROVENANCE.json').write_text(json.dumps(provenance, sort_keys=True, indent=2) + '\n')
(ROOT / 'ADDITIONAL_UPLOAD_QUEUE.json').write_text(json.dumps(queue, sort_keys=True, indent=2) + '\n')
print(json.dumps({'base_files': len(BASE), 'known_new_paths': len(known),
                  'to_upload': len(queue), 'upload_bytes': sum(row['bytes'] for row in queue),
                  'maximum_upload': max([0] + [row['bytes'] for row in queue])}, sort_keys=True))
