"""Prepare evidence-only V9 entries from immutable, actually registered objects.

This program only reads evidence and writes a proposed registry. It never runs
tests, changes product sources, creates Git objects, or moves a reference.
"""
from pathlib import Path
import hashlib
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
REC = ROOT / 'hepta-audit-fifth/recovery-2113'
OUT = ROOT / 'hepta-audit-fifth/v9'
PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
OUT.mkdir(exist_ok=True)


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


rows = {}
missing = []


def add(local, repo, blob, size=None, sha256=None, origin=None):
    local = Path(local)
    if not local.is_absolute():
        local = ROOT / local
    assert local.is_relative_to(ROOT), local
    if not repo.startswith(PREFIX):
        repo = PREFIX + repo
    assert '..' not in Path(repo).parts
    if repo.endswith('.rs'):
        repo += '.source.txt'
    item = {'path': repo, 'local_file': str(local), 'mode': '100644',
            'git_blob': blob, 'bytes': size, 'sha256': sha256,
            'registration_source': origin}
    if local.exists():
        actual = digest(local.read_bytes())
        assert actual['git_blob'] == blob, (local, actual['git_blob'], blob)
        assert size is None or actual['bytes'] == size, local
        assert sha256 is None or actual['sha256'] == sha256, local
        item.update(actual)
        item['local_complete_bytes_verified'] = True
    else:
        item['local_complete_bytes_verified'] = False
        missing.append(item)
    if repo in rows:
        assert rows[repo]['git_blob'] == blob, (repo, rows[repo]['git_blob'], blob)
    rows[repo] = item


registries = [
    ('architecture-audit/b11-pr4884-ci-20261105/registration-native7-post-v8.json', '8d62f664d17255be5094dbff103f563d40ff7590', 'generated-evidence/b11-pr4884-ci/native7-post-v8-registration.json', None),
    ('ci-audit/published-eed4d6-ci-20261105/b07-source-review-v1/registry.actual-v1.json', '6c10a7fb8a9d4dd47543dd32f5175f85b71b9655', 'reviews/b07-original-exit-independent-20261105/registry.actual-v1.json', None),
    ('ci-audit/b07-complete-originals-recovery-20261105/registry.actual-v1.json', '2f392f54b5dc4a5419a412a68b2bb12fe60c2000', 'reviews/b07-original-exit-independent-20261105/recovery/registry.actual-v1.json', None),
    ('ci-audit/pr4797-recovery-20261105/snapshot-v1/registry.actual.json', 'c8ea433f8be4a958f681acc009356c3c2cf26cd8', 'current-head-ci/post-v8-recovery-20261105/registry.actual.json', None),
    ('research-audit/b11-read-readiness-20261105/publication-map.json', '60e0d0042a8777173e437b67dbc4868333530a54', 'native-plan/b11-read-readiness-20261105/publication-map.json', 'native-plan/b11-read-readiness-20261105/'),
    ('research-audit/b11-read-readiness-20261105/execution-candidate-v2/publication-map.json', '46665cba02d31cfe2ad732e01a6bd1b4cd47c3f7', 'native-plan/b11-read-readiness-20261105/execution-candidate-v2/publication-map.json', 'native-plan/b11-read-readiness-20261105/execution-candidate-v2/'),
    ('research-audit/b11-read-readiness-20261105/cloud-script-gate-history-v1/registry.actual.json', '66e09d96faaf8e3bdeeec1375baa2f9bd6568c3c', 'generated-evidence/b11-read-readiness-python57-20261105/registry.actual.json', None),
    ('ci-audit/b11-read-readiness-independent-20261105/registry.actual-v1.json', '34611317d6d5fda2189a379e020a66ee616c61d8', 'reviews/b11-read-readiness-independent-20261105/registry.actual-v1.json', None),
    ('ci-audit/b11-helper-execution-v2-independent-20261105/registry.actual.json', '87ba7b1b7e26d76607aca43a040fb85a7cbd2a9b', 'reviews/b11-helper-execution-v2-independent-20261105/registry.actual.json', None),
    ('architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v3/github-readback-map.json', '5392123bfe154f349b3b33d546658a6891724738', 'native-plan/b11-identity-counterfactual/counterfactual-workflow-v3/github-readback-map.json', 'native-plan/b11-identity-counterfactual/counterfactual-workflow-v3/'),
    ('ci-audit/acl-counterfactual-wrapper-v3-review-20261105/registry.actual.json', 'b359f6c7580081570bafb6344e46d3d2960cad87', 'reviews/b11-counterfactual-v3-independent-20261105/registry.actual.json', None),
]
extra_config = OUT / 'additional-registries.json'
if extra_config.exists():
    registries.extend(json.loads(extra_config.read_text()))
for local, blob, repo, relative_prefix in registries:
    path = ROOT / local
    doc = json.loads(path.read_text())
    add(path, repo, blob, origin='exact actual registry identity')
    members = doc.get('files', doc.get('objects', doc.get('items')))
    assert isinstance(members, list), local
    for e in members:
        source = e.get('local_file', e.get('local_path', e.get('path')))
        assert source
        target = e.get('repo_path', e.get('repository_path'))
        if target is None:
            assert relative_prefix, (local, source)
            relative = str(Path(source).relative_to(path.parent))
            target = relative_prefix + relative
        add(source, target, e.get('git_blob', e.get('blob')), e.get('bytes'), e.get('sha256'), local)
    for e in doc.get('referenced_existing_postimages', []):
        add(e['local_file'], relative_prefix + 'candidate/' + e['path'], e['blob'], e['bytes'], e['sha256'], local)

for e in json.loads((REC / 'root-actual-objects.json').read_text()):
    assert e['actual_create_and_complete_GET_verified'] is True
    add(e['local_file'], e['path'], e['git_blob'], e['bytes'], e.get('sha256'), 'root complete actual create+GET')

base = {e['path']: e for e in json.loads((REC / 'trees/auditV8-leaves.json').read_text())['leaves']}
unchanged = []
for p in list(rows):
    if p in base:
        assert base[p]['sha'] == rows[p]['git_blob'], ('existing evidence would be overwritten', p)
        unchanged.append(rows.pop(p))
payload = {'schema': 'hepta-v9-proposed-evidence-registry-v1', 'base_commit': '0fc276d03e7d90f2e4fc53d67a0de8b942d51559',
           'base_tree': 'c592f5edf3969f5fc8bf5100b532c2823c4f8f8a', 'evidence_only': True,
           'all_paths_within_continuation': True, 'entry_count': len(rows),
           'items': [rows[k] for k in sorted(rows)], 'already_published_identical': unchanged,
           'missing_local_files': missing}
(OUT / 'registered-evidence-plan.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'entries': len(rows), 'already_in_V8': len(unchanged), 'missing': len(missing),
                  'largest': max((r['bytes'] or 0) for r in rows.values()),
                  'path': str(OUT / 'registered-evidence-plan.json')}))
