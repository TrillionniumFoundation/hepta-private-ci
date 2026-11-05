from pathlib import Path
import hashlib
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
P = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
rows = {}

def read(p):
    return json.loads(Path(p).read_text())

def identity(p):
    b = Path(p).read_bytes()
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def add(destination, local, claim=None, actual=False):
    local = Path(local)
    if not local.is_absolute():
        local = ROOT / local
    ident = identity(local)
    assert ident['bytes'] <= 512000, (local, ident['bytes'])
    if claim:
        assert ident['blob'] == claim, (local, ident['blob'], claim)
    destination = destination if destination.startswith(P) else P + destination
    item = {'repository_path': destination, 'local_file': str(local), 'mode': '100644', **ident,
            'actual_object_verified': actual,
            'verification': 'Owning-agent actual create and complete byte-equal GET; root recomputed every local SHA256 and Git identity' if actual else 'Pending actual root create and complete GET'}
    if destination in rows:
        assert rows[destination]['blob'] == ident['blob'], ('collision', destination)
        rows[destination]['actual_object_verified'] |= actual
    else:
        rows[destination] = item

def actual_map(local, prefix, self_blob, base=None, registered=False):
    path = ROOT / local
    data = read(path)
    values = data if isinstance(data, list) else data.get('objects', data.get('items', data.get('records')))
    assert isinstance(values, list)
    for item in values:
        file = Path(item.get('local_file', item.get('local_path', item.get('path', item.get('file')))))
        if not file.is_absolute():
            file = ROOT / file
        claim = item.get('blob', item.get('git_blob', item.get('actual_create_sha')))
        v = item.get('verification', {})
        actual = bool(
            item.get('actual_create_and_full_GET_byteequal')
            or item.get('actual_create_and_get_byte_equal')
            or item.get('actual_object_verified')
            or (item.get('created') and item.get('GET_byte_equal'))
            or (item.get('actual_create_sha') == claim and item.get('get_byte_equal'))
            or (item.get('actual_create') and item.get('full_GET_byteequal'))
            or (isinstance(v, dict) and v.get('actual_create_sha') == claim and v.get('actual_GET_bytes_equal'))
        )
        assert actual, ('missing actual attestation', local, item)
        if registered:
            destination = item.get('repository_path', item.get('repo_path', item.get('repo_relative_path')))
            assert destination
        else:
            name = file.relative_to(ROOT / base).as_posix() if base else file.name
            if name.endswith(('.rs', '.yml')):
                name += '.source.txt'
            destination = prefix + '/' + name
        add(destination, file, claim, True)
    add(prefix + '/actual-delivery-map.json', path, self_blob, True)

actual_map('ci-audit/published-eed4d6-ci-20261105/b08-source-review-v1/registry.actual-v1.json',
           'reviews/b08-original-exit-20261105', 'f8d5bae3fdc2b4f63314da4027ea5a12faca40fe', registered=True)
actual_map('architecture-audit/b11-acl-repair-20261105/identity-candidate-v3/github-readback-map.json',
           'candidate-published/b11-identity-v3', '8f37d0045c2fc139b46267d0f279a4f8a25b08bd',
           base='architecture-audit/b11-acl-repair-20261105/identity-candidate-v3')
actual_map('research-audit/b11-acl-identity-v3-independent-20261105/publication-map.json',
           'reviews/b11-identity-v3-independent', '6d5ca5000b26ab176041748f0df48e78a48f0f0a',
           base='research-audit/b11-acl-identity-v3-independent-20261105')
actual_map('research-audit/b21-intel-current-followup-20261105/publication-map.json',
           'reviews/b21-intel-current-followup', '134809e1ab87d58d57a38567c5c34a0dbc664cb1',
           base='research-audit/b21-intel-current-followup-20261105')
actual_map('architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v2/github-readback-map.json',
           'native-plan/b11-identity-counterfactual', '69d3b2aba239e9dfc818dd22f437f1739ebe474a',
           base='architecture-audit/b11-acl-repair-20261105')
actual_map('ci-audit/published-eed4d6-ci-20261105/snapshot-0003/registry.actual-v1.json',
           'ci/eed-status-1754-20261105', 'aaefec8db8c5f7874129f4143af71a96ac78b124', registered=True)
add('ci/eed-status-1754-20261105/registry.actual-v1.json',
    'ci-audit/published-eed4d6-ci-20261105/snapshot-0003/registry.actual-v1.json',
    'aaefec8db8c5f7874129f4143af71a96ac78b124', True)

# The native6 registry is added by its explicitly verified metadata file after
# the owning agent finishes materializing all original archive chunks.
extra = ROOT / 'hepta-audit-fifth/v8-additional-actual-registries.json'
if extra.exists():
    for r in read(extra):
        actual_map(r['local'], r['prefix'], r['self_blob'], r.get('base'), r.get('registered', False))

add('reviews/b11-counterfactual-wrapper-independent.json',
    'ci-audit/acl-counterfactual-wrapper-review-20261105/independent-review.json',
    '7d5ef2f8e53b89524c0937f01d25a2cd3e83aef5', True)
for file in sorted((ROOT / 'ci-audit/published-eed4d6-ci-20261105/queue-followup-v2').iterdir()):
    if file.is_file():
        add('ci/queue-followup-v2/' + file.name, file)
for rel, file in [
    ('ci/b11-native6/first-snapshot-1743.json', 'architecture-audit/b11-pr4884-ci-20261105/native6-first-snapshot-1743.json'),
    ('ci/b11-native6/snapshot-1749.json', 'architecture-audit/b11-pr4884-ci-20261105/native6-snapshot-1749.json'),
    ('ci/b11-native7/first-snapshot-1800.json', 'architecture-audit/b11-pr4884-ci-20261105/native7-first-snapshot-1800.json'),
    ('reviews/v7-publication-root-receipt.json', 'hepta-audit-fifth/v7-publication-root-receipt.json'),
]:
    add(rel, file)
for name in [
    'b08-original-contract-root-closure-v1.json', 'b11-identity-two-path-publication-v1.json',
    'b11-identity-counterfactual-publication-v1.json', 'post-v7-ci-waiting-ui-and-api-v1.json',
    'b11-native6-root-original-verification-v1.json', 'b11-native6-artifacts-api.json',
    'b11-native6-actual-merge-leaves.json',
]:
    add('reviews/' + name, 'hepta-audit-fifth/inputs/' + name)
for name in [
    'verify_b08_original_contract.py', 'verify_b11_native6_originals.py',
    'build_v8_deliverables.py', 'append_v8_postcut.py', 'build_v8_registration.py', 'build_v8_index.py',
]:
    add('reviews/reproduction/' + name, 'hepta-audit-fifth/' + name)
add('reviews/reproduction/v8-additional-actual-registries.json', 'hepta-audit-fifth/v8-additional-actual-registries.json')
for name in ['LATEST.zh-CN.md', 'CONTINUATION_PROGRESS_V7.zh-CN.md',
             'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md', 'continuation-blocker-progress-v6.json']:
    add(name, 'hepta-audit-fifth/v8-deliverables/' + name)

actual_file = ROOT / 'hepta-audit-fifth/v8-root-actual-objects.json'
if actual_file.exists():
    for actual in read(actual_file):
        assert actual['actual_create_sha'] == actual['blob'] and actual['full_GET_byte_equal'] is True
        for row in rows.values():
            if row['blob'] == actual['blob']:
                assert row['bytes'] == actual['bytes'] and row['sha256'] == actual['sha256']
                row.update(actual_object_verified=True, verification=actual['verification'],
                           actual_create_sha=actual['actual_create_sha'], full_GET_byte_equal=True)

items = list(rows.values())
result = {'schema': 'hepta-evidence-only-registration-plan-v8-pending-actual',
          'base_audit_commit': 'e3cc8c09acd1feb3e1a79155cafc4b9779a765c7',
          'base_audit_tree': '059c79a3b6ae08f5e2d6ed9e1b2e19004d23aeb0',
          'evidence_only': True, 'all_blockers_closed': False, 'whole_product_qualified': False,
          'counts': {'CLOSED_SCOPED': 11, 'OPEN': 11, 'SCIENTIFIC_HOLD': 1},
          'entry_count': len(items), 'items': items}
(ROOT / 'hepta-audit-fifth/registration-plan-v8-pending.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
pending = [r for r in items if not r['actual_object_verified']]
(ROOT / 'hepta-audit-fifth/v8-pending-actual-objects.json').write_text(json.dumps(pending, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'entries': len(items), 'already_actual': len(items) - len(pending), 'pending': len(pending),
                  'total_bytes': sum(r['bytes'] for r in items), 'largest': max(r['bytes'] for r in items)}, ensure_ascii=False))
