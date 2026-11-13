import difflib
import hashlib
import json
from pathlib import Path

D = Path(__file__).resolve().parent
P = D.parent
I = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
inventory = {r['path']: r for r in json.loads(I.read_text())['files']}

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def save(name, obj):
    path = D / name
    assert not path.exists(), name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n')

previous = json.loads((P / 'root-service-layer-v1/SOURCE_PACKET.json').read_text())
previous = {x['path']: x for x in previous['entries']}
rows = []
splices = []
patch = []
for after in sorted((D / 'after').rglob('*.rs')):
    relative = after.relative_to(D / 'after').as_posix()
    before = D / 'before' / relative
    a = after.read_bytes()
    b = before.read_bytes() if before.exists() else b''
    if before.exists():
        expected = previous.get(relative)
        if expected:
            assert pin(b) == expected['after']
            assert b.decode() == expected['after_utf8']
            provenance = 'exact root-service-layer-v1 after'
        else:
            old = inventory[relative]
            assert (len(b), hashlib.sha256(b).hexdigest(), pin(b)['git_blob']) == (old['bytes'], old['sha256'], old['working_blob'])
            provenance = 'actual b608 inventory and full original body'
    else:
        assert relative not in inventory and relative not in previous
        provenance = 'new local proposal source'
    operations = []
    matcher = difflib.SequenceMatcher(None, b.splitlines(True), a.splitlines(True), autojunk=False)
    for kind, i, j, k, l in matcher.get_opcodes():
        if kind != 'equal':
            operations.append({'before_lines': [i, j], 'after_lines': [k, l],
                               'old_utf8': b''.join(b.splitlines(True)[i:j]).decode(),
                               'new_utf8': b''.join(a.splitlines(True)[k:l]).decode()})
    forward = b.splitlines(True)
    for op in reversed(operations):
        i, j = op['before_lines']; forward[i:j] = op['new_utf8'].encode().splitlines(True)
    assert b''.join(forward) == a
    reverse = a.splitlines(True)
    for op in reversed(operations):
        i, j = op['after_lines']; reverse[i:j] = op['old_utf8'].encode().splitlines(True)
    assert b''.join(reverse) == b
    splices.append({'path': relative, 'operations': operations, 'forward_equal': True, 'inverse_equal': True})
    rows.append({'path': relative, 'before': pin(b) if before.exists() else None,
                 'after': pin(a), 'before_utf8': b.decode() if before.exists() else None,
                 'after_utf8': a.decode(), 'provenance': provenance})
    patch.extend(difflib.unified_diff(b.decode().splitlines(True), a.decode().splitlines(True),
                                    fromfile='a/' + relative if before.exists() else '/dev/null', tofile='b/' + relative))

assert len(rows) == 20
assert sum(r['before'] is None for r in rows) == 10
assert sum(r['path'].endswith('_tests.rs') for r in rows) == 2
for r in rows:
    if r['before'] is None:
        assert len(r['after_utf8'].splitlines()) < 500
protected = ['config_resident_learning.rs', 'resident_learning_delivery.rs',
             'authority_host_learning_resident_transport.rs', 'learning_owner_command_channel.rs',
             'authority_host_learning_candidate_service.rs']
assert all(not any(r['path'].endswith('/' + name) for r in rows) for name in protected)
refs = []
for source in sorted((P / 'references').rglob('*.rs')):
    relative = source.relative_to(P / 'references').as_posix()
    if relative not in inventory:
        continue
    b = source.read_bytes(); actual = inventory[relative]
    assert (pin(b)['git_blob'], len(b), hashlib.sha256(b).hexdigest()) == (actual['working_blob'], actual['bytes'], actual['sha256'])
    sdk = P / 'reference-sdk' / (actual['working_blob'] + '.json')
    refs.append({'path': relative, **pin(b), 'original_sdk_available': sdk.exists()})
methods = []
import re
for r in rows:
    if r['path'].endswith('_tests.rs'):
        methods.extend({'path': r['path'], 'method': name} for name in re.findall(r'^fn ([a-z_0-9]+)\([^\n]*\) -> (?:io::Result|Result)', r['after_utf8'], re.M) if name not in ['root_pin','require_root'])
assert len(methods) == 5
packet = {'format': 'hepta-local-source-packet-v1', 'base_commit': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
          'base_tree': '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638',
          'prerequisites': ['root-service-layer-v1/0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b'], 'entries': rows}
save('SOURCE_PACKET.json', packet)
(D / 'SOURCE_DELTA.patch').write_text(''.join(patch))
save('EXACT_SOURCE_SPLICES.json', splices)
save('SOURCE_REFERENCES.json', refs)
save('STATIC_BYTE_REVIEW.json', {
    'state': 'LOCAL_PROPOSAL_UNFORMATTED_UNCOMPILED_UNEXECUTED',
    'paths': 20, 'modified_existing': 10, 'new_production': 8, 'new_tests_files': 2,
    'all_forward_and_inverse_equal': True, 'all_preimages_exact': True,
    'all_new_files_under_500_lines': True, 'new_test_methods': methods,
    'ignored_root_methods': 3, 'ordinary_methods': 2,
    'original_core_paths_not_changed': protected,
    'no_h': True, 'no_source_git_creation': True, 'no_refs': True,
    'no_rust_execution': True, 'no_formatter': True, 'no_qa_or_collector_execution': True,
    'no_end_to_end_claim': True,
    'required_integration': ['E2 task install before V3 opt-in', 'real non-Root Material Source loan',
                             'CALLERS/protected/Root-inventory/allowlist registration', 'actual Rust and original source/native gates'],
})
payloads = ['SOURCE_PACKET.json','SOURCE_DELTA.patch','EXACT_SOURCE_SPLICES.json','SOURCE_REFERENCES.json','STATIC_BYTE_REVIEW.json','README.md','freeze_layer.py']
save('MANIFEST.json', {'format': 'hepta-local-source-manifest-v1', 'state': 'computed_local_only_no_source_git_publication',
                       'sources': [{k:r[k] for k in ['path','before','after','provenance']} for r in rows],
                       'payloads': [{'path': name, **pin((D/name).read_bytes())} for name in payloads]})
for name in payloads + ['MANIFEST.json']:
    print(name, json.dumps(pin((D / name).read_bytes())))
