"""Pure data/byte review of the frozen E1+E3 registration proposal.

Does not import project modules, invoke its collector/QA, compile Rust, or use H.
Only this separate review directory receives create-only output.
"""
from pathlib import Path
import ast
import base64
import copy
import difflib
import gzip
import hashlib
import json
import re
import tomllib

D = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/registration-proposal-v1')
E1 = Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
E3 = D.parent
OUT = Path('/tmp/hepta-36fa-e3-registration-independent-review-v1')
A = 'codex-rs/hepta-agentd/src/'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def check(raw, expected):
    actual = pin(raw)
    assert all(actual[k] == expected[k] for k in actual), (actual, expected)
    return actual


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def load(path):
    return json.loads(path.read_bytes())


def replace_once(raw, old, new):
    assert raw.count(old) == 1, ('nonunique replacement', old[:100], raw.count(old))
    return raw.replace(old, new, 1)


def new_file(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(raw)
    assert path.read_bytes() == raw


def methods(source):
    values = {}
    def walk(node, parents):
        for item in ast.iter_child_nodes(node):
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = '.'.join(parents + [item.name])
                if not isinstance(item, ast.ClassDef):
                    values[name] = ast.get_source_segment(source, item)
                walk(item, parents + [item.name])
            else:
                walk(item, parents)
    walk(ast.parse(source), [])
    return values


def constants(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def restore_ast(after, before, changed_methods, added_methods, changed_constants, added_constants):
    btree = ast.parse(before)
    atree = ast.parse(after)
    old_nodes = {}
    def collect(node, parents):
        for item in ast.iter_child_nodes(node):
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                key = '.'.join(parents + [item.name])
                old_nodes[key] = item
                collect(item, parents + [item.name])
            else:
                collect(item, parents)
    collect(btree, [])
    old_constants = {n.targets[0].id: n for n in btree.body
                     if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    def transform(node, parents):
        for field, value in ast.iter_fields(node):
            if not isinstance(value, list):
                if isinstance(value, ast.AST):
                    transform(value, parents)
                continue
            result = []
            for item in value:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    key = '.'.join(parents + [item.name])
                    if key in added_methods:
                        continue
                    if key in changed_methods:
                        item = copy.deepcopy(old_nodes[key])
                    else:
                        transform(item, parents + [item.name])
                elif isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                    name = item.targets[0].id
                    if name in added_constants:
                        continue
                    if name in changed_constants:
                        item = copy.deepcopy(old_constants[name])
                    else:
                        transform(item, parents)
                elif isinstance(item, ast.AST):
                    transform(item, parents)
                result.append(item)
            setattr(node, field, result)
    transform(atree, [])
    assert ast.dump(atree, include_attributes=False) == ast.dump(btree, include_attributes=False)


packet_raw = (D / 'SOURCE_PACKET.json').read_bytes()
assert pin(packet_raw) == {'bytes': 4628695, 'git_blob': '43f723f2de9d8910cf9958ba21f63f2201f8fc79',
                           'sha256': '7085385105a3af327248d37a2b5716be941a74f4fac28527cd8ba1779261ae3e'}
packet = json.loads(packet_raw)
assert packet['state'] == 'ISOLATED_E1_PLUS_E3_PROJECTION_NOT_FINAL_ROOT_UNION'
manifest = load(D / 'MANIFEST.json')
assert pin((D / 'MANIFEST.json').read_bytes())['git_blob'] == '67e8eadcd00da4ab48f17682cb5d5c560ba268b4'
payloads = []
for row in manifest['payloads']:
    payloads.append({'path': row['path'], **check((D / row['path']).read_bytes(), row)})
encoding = load(D / 'ENCODING_MANIFEST.json')
assert len(encoding) == 1
encoded = bytearray()
for part in encoding[0]['parts']:
    assert part['offset'] == len(encoded)
    raw = (D / part['path']).read_bytes()
    check(raw, part)
    assert len(raw) <= 409600
    encoded.extend(raw)
assert len(encoded) == encoding[0]['base64_bytes']
compressed = base64.b64decode(encoded, validate=True)
check(compressed, encoding[0]['gzip'])
assert gzip.decompress(compressed) == packet_raw
check(packet_raw, encoding[0]['raw'])

e1_registration_path = E1 / 'registration-proposal-v1/SOURCE_PACKET.json'
assert pin(e1_registration_path.read_bytes())['git_blob'] == '805b284073ae0ed88207edcd2c87144e9597d8c5'
e1_registration = {x['path']: x['after'].encode() for x in load(e1_registration_path)['images']}
entries = {}
patch = []
for e in packet['entries']:
    path = e['path']
    assert path not in entries
    before = None if e['before_utf8'] is None else e['before_utf8'].encode()
    after = e['after_utf8'].encode()
    assert e['before'] is None if before is None else check(before, e['before'])
    check(after, e['after'])
    assert (D / 'after' / path).read_bytes() == after
    if before is not None:
        assert (D / 'before' / path).read_bytes() == before == e1_registration[path]
    else:
        assert path not in e1_registration and not (D / 'before' / path).exists()
    entries[path] = {'before': before, 'after': after}
    patch.extend(difflib.unified_diff((before or b'').decode().splitlines(True), after.decode().splitlines(True),
                                   fromfile='a/' + path, tofile='b/' + path))
assert len(entries) == 7
assert ''.join(patch).encode() == (D / 'SOURCE_DELTA.patch').read_bytes()

inventory_path = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
assert pin(inventory_path.read_bytes())['git_blob'] == '457adb9bf9ba3a844e9dfa149be49460bb306998'
inventory = load(inventory_path)
canonical_files = {x['path']: x for x in inventory['files']}
assert len(canonical_files) == 15243
source_view, source_original = {}, {}
layers = [
    ('root-service-layer-v1', '0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b'),
    ('late-enrollment-layer-v1', '388bfb3f3ab70e5f39d847c26d2d48daa2c7ead1'),
    ('explicit-callers-increment-v1', 'f1306c1243c83a758385cb592710e4fd30010a78'),
]
source_layer_pins = []
for name, oid in layers:
    raw = (E3 / name / 'SOURCE_PACKET.json').read_bytes()
    assert pin(raw)['git_blob'] == oid
    source_layer_pins.append({'layer': name, **pin(raw)})
    for e in json.loads(raw)['entries']:
        path = e['path']
        before = None if e['before_utf8'] is None else e['before_utf8'].encode()
        after = e['after_utf8'].encode()
        check(after, e['after'])
        if before is not None:
            check(before, e['before'])
        if path in source_view:
            assert source_view[path] == before, path
        else:
            source_original[path] = before
            if before is not None:
                expected = canonical_files[path]
                assert pin(before) == {'bytes': expected['bytes'], 'sha256': expected['sha256'], 'git_blob': expected['working_blob']}, path
            else:
                assert path not in canonical_files
        source_view[path] = after
assert len(source_view) == 21
source_ids = load(D / 'SOURCE_IDENTITIES.json')
assert source_layer_pins == source_ids['layers']
assert {p: pin(v) for p, v in source_view.items()} == source_ids['sources']

e1_source = {}
for layer, oid in [('assembled-source-v1', '1ca7a06948fcae69bf7c8e4c7823627a872c0c62'),
                   ('request-type-import-increment-v1', '36cd9a693ce75070e1225a978575ca6dea5f72c2')]:
    raw = (E1 / layer / 'SOURCE_PACKET.json').read_bytes()
    assert pin(raw)['git_blob'] == oid
    for e in json.loads(raw)['images']:
        if e['path'] in e1_source:
            assert e1_source[e['path']] == e['before'].encode()
        e1_source[e['path']] = e['after'].encode()

table_before = tomllib.loads(entries['CALLERS.toml']['before'].decode())
table_after = tomllib.loads(entries['CALLERS.toml']['after'].decode())
assert list(table_before) == list(table_after)
assert (len(table_before['boundary']), len(table_after['boundary'])) == (650, 666)
assert (len(table_before['protected_file']), len(table_after['protected_file'])) == (451, 470)
unchanged_top = []
for key in table_before:
    if key not in ('boundary', 'protected_file', 'privileged_inventory'):
        assert table_before[key] == table_after[key], key
        unchanged_top.append(key)
old_ids = table_before['privileged_inventory']['required_boundary_ids']
new_ids = table_after['privileged_inventory']['required_boundary_ids']
assert set(table_before['privileged_inventory']) == set(table_after['privileged_inventory']) == {'required_boundary_ids'}
assert len(old_ids) == len(set(old_ids)) == 650
assert set(old_ids) == {r['id'] for r in table_before['boundary']}
assert set(new_ids) == {r['id'] for r in table_after['boundary']}
assert new_ids[:650] == old_ids and len(set(new_ids)) == 666

allowed_old = {
    'root_original_private_sealed_bytes': ['authority_host_resident_enrollment_wire.rs'],
    'learning_frozen_update_scope_constructor': ['authority_host_resident_launch_inputs.rs', 'authority_host_resident_enrollment_profile.rs'],
    'learning_original_owner_snapshot_encode': ['authority_host_resident_launch_inputs.rs', 'authority_host_resident_enrollment_profile.rs'],
    'learning_original_owner_snapshot_decode': ['authority_host_resident_launch_inputs.rs', 'authority_host_resident_enrollment_profile.rs'],
    'learning_original_material_initial_context_check': ['authority_host_resident_launch_inputs.rs'],
    'root_resident_original_register': ['authority_host_resident_launch.rs'],
    'root_resident_original_recover': ['authority_host_resident_launch.rs'],
    'root_resident_original_custody_open': ['authority_host_resident_enrollment.rs'],
    'root_resident_registration_create': ['authority_host_resident_enrollment.rs'],
    'root_resident_registration_recover': ['authority_host_resident_enrollment.rs'],
    'root_resident_original_client_create': ['authority_host_resident_enrollment_connect.rs'],
    'root_resident_original_client_recover': ['authority_host_resident_enrollment_connect.rs'],
    'root_resident_late_enrollment_config': ['production_resident_enrollment.rs'],
    'root_resident_late_enrollment_submit': ['production_resident_enrollment.rs'],
    'learning_original_evaluation_panel_registration': ['authority_host_resident_launch_inputs.rs'],
    'provider_root_resident_learning_registration_v3_into_candidate_service': ['authority_host_resident_launch.rs', 'authority_host_resident_enrollment.rs'],
    'provider_root_resident_candidate_service_v1_run': ['authority_host_resident_cli.rs', 'authority_host_resident_enrollment.rs'],
    'provider_receive_root_candidate_stage_handoff': ['authority_host_resident_launch.rs', 'authority_host_resident_enrollment.rs'],
}
changes = []
for index, old in enumerate(table_before['boundary']):
    new = table_after['boundary'][index]
    if old['id'] not in allowed_old:
        assert new == old
        continue
    extra = [A + n for n in allowed_old[old['id']]]
    assert set(old) == set(new)
    assert {k: v for k, v in old.items() if k != 'product_callers'} == {k: v for k, v in new.items() if k != 'product_callers'}
    assert new['product_callers'] == old['product_callers'] + extra
    assert len(new['product_callers']) == len(set(new['product_callers']))
    for path in extra:
        symbol = old['symbol']
        assert symbol in source_view[path].decode() or symbol.split('::')[-1] in source_view[path].decode(), (path, symbol)
    changes.append({'index': index, 'before': old, 'after': new, 'added_callers': extra})
assert len(changes) == 18 and sum(len(c['added_callers']) for c in changes) == 24

expected_new = [
 ('e3_root_candidate_prepare', 'prepare_host_resident_candidate_v3', 'authority_host_resident_launch.rs', ['authority_host_resident_cli.rs'], None),
 ('e3_root_candidate_recover', 'recover_host_resident_candidate_v3', 'authority_host_resident_launch.rs', ['authority_host_resident_cli.rs'], None),
 ('e3_root_candidate_late_prepare', 'prepare_host_resident_candidate_enrollment_v3', 'authority_host_resident_enrollment.rs', ['authority_host_resident_enrollment_cli.rs'], None),
 ('e3_root_candidate_late_recover', 'recover_host_resident_candidate_enrollment_v3', 'authority_host_resident_enrollment.rs', ['authority_host_resident_enrollment_cli.rs'], None),
 ('e3_root_candidate_late_run', 'RootResidentCandidateEnrollmentServiceV3::run', 'authority_host_resident_enrollment.rs', ['authority_host_resident_enrollment_cli.rs'], 'RootResidentCandidateEnrollmentServiceV3'),
 ('e3_daemon_resident_connect', 'connect_original_resident_enrollment', 'authority_host_resident_enrollment_connect.rs', ['root_resident_enrollment_handoff.rs'], None),
 ('e3_root_resident_handoff_send', 'send_original_resident_enrollment', 'root_resident_enrollment_handoff.rs', ['authority_host_resident_enrollment.rs'], None),
 ('e3_daemon_resident_handoff_receive', 'receive_original_resident_enrollment', 'root_resident_enrollment_handoff.rs', ['production_resident_enrollment.rs'], None),
 ('e3_root_resident_original_process_pin', 'require_original_resident_process_pin', 'root_resident_enrollment_handoff.rs', ['authority_host_resident_enrollment.rs'], None),
 ('e3_root_resident_trust_read', 'OriginalHostTrust::read', 'authority_host_resident_trust_file.rs', ['authority_host_resident_launch.rs', 'authority_host_resident_enrollment.rs'], 'OriginalHostTrust'),
 ('e3_daemon_resident_root_trust_decode', 'OriginalHostTrust::from_root_enrollment', 'authority_host_resident_trust_file.rs', ['authority_host_resident_enrollment_connect.rs'], 'OriginalHostTrust'),
 ('e3_root_resident_trust_construct', 'OriginalHostTrust::from_value', 'authority_host_resident_trust_file.rs', [], 'OriginalHostTrust'),
 ('e3_root_resident_observer_binding', 'OriginalHostTrust::observer', 'authority_host_resident_trust_file.rs', ['authority_host_resident_launch_inputs.rs'], 'OriginalHostTrust'),
 ('e3_root_resident_deployment_read', 'OriginalDeployment::read', 'authority_host_resident_launch_inputs.rs', ['authority_host_resident_launch.rs', 'authority_host_resident_enrollment.rs'], 'OriginalDeployment'),
 ('e3_root_resident_listener_bind', 'ResidentListener::bind_original', 'authority_host_resident_listener.rs', ['authority_host_resident_enrollment.rs'], 'ResidentListener'),
 ('e3_root_resident_listener_accept', 'ResidentListener::accept_original', 'authority_host_resident_listener.rs', ['authority_host_resident_enrollment.rs'], 'ResidentListener'),
]
for row, expected in zip(table_after['boundary'][650:], expected_new, strict=True):
    rid, symbol, definition, callers, receiver = expected
    assert (row['id'], row['symbol'], row['definition_path'], row['product_callers'], row.get('receiver_type')) == (rid, symbol, A + definition, [A + c for c in callers], receiver)
    assert row['caller_markers'] == []
    assert set(row) == {'id', 'symbol', 'definition_path', 'definition_markers', 'product_callers', 'caller_markers'} | ({'receiver_type'} if receiver else set())
    for marker in row['definition_markers']:
        assert marker in source_view[row['definition_path']].decode()
    for path in row['product_callers']:
        assert symbol in source_view[path].decode() or symbol.split('::')[-1] in source_view[path].decode()

old_protected = table_before['protected_file']
new_protected = table_after['protected_file'][451:]
assert table_after['protected_file'][:451] == old_protected
assert table_after['protected_file'][411] == old_protected[411]
assert table_after['protected_file'][422] == old_protected[422]
new_production = {p for p, b in source_original.items() if b is None and not p.endswith('_tests.rs')}
old_source = {p for p, b in source_original.items() if b is not None}
assert len(new_production) == 12 and len(old_source) == 7
assert [r['path'] for r in new_protected] == sorted(new_production) + sorted(old_source)
for row in new_protected:
    assert set(row) == {'path', 'required', 'forbidden'}
    assert row['forbidden'] == ['SigningKey::generate', 'SigningKey::from_bytes', 'permit_all', 'AllowVerifier']
    body = source_view[row['path']].decode()
    assert all(x not in body for x in row['forbidden'])
    assert all(x in body for x in row['required'])
    if row['path'] in new_production:
        assert row['required'] == [body]

insertions = load(D / 'OLD_SOURCE_INSERTIONS.json')
assert {r['path'] for r in insertions} == old_source
for row in insertions:
    path = row['path']
    before, after = source_original[path], source_view[path]
    check(before, row['before']); check(after, row['after'])
    b, a = before.decode().splitlines(True), after.decode().splitlines(True)
    ops = [(tag, i1, i2, j1, j2) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b, a, autojunk=False).get_opcodes() if tag != 'equal']
    assert len(ops) == len(row['operations'])
    required = next(r['required'] for r in new_protected if r['path'] == path)
    assert required == [''.join(a[j1:j2]) for _, _, _, j1, j2 in ops]
    for (tag, i1, i2, j1, j2), supplied in zip(ops, row['operations'], strict=True):
        assert supplied['before_utf8'] == ''.join(b[i1:i2])
        assert supplied['after_utf8'] == ''.join(a[j1:j2])
        assert supplied['old_lines'] == [i1, i2] and supplied['new_lines'] == [j1, j2]
    restored = list(a)
    for _, i1, i2, j1, j2 in reversed(ops):
        restored[j1:j2] = b[i1:i2]
    assert ''.join(restored).encode() == before

# Full raw TOML inverse, beyond parsed equality of its flags and old rows.
def sections(kind, rows):
    return ''.join('\n[[' + kind + ']]\n' + ''.join(k + ' = ' + json.dumps(v, ensure_ascii=False) + '\n' for k, v in row.items()) for row in rows)
appendix = sections('boundary', table_after['boundary'][650:]) + sections('protected_file', new_protected)
restored = replace_once(entries['CALLERS.toml']['after'].decode(), appendix + '\n[authority]\n', '\n[authority]\n')
restored = replace_once(restored, 'required_boundary_ids = ' + json.dumps(new_ids), 'required_boundary_ids = ' + json.dumps(old_ids))
for change in changes:
    rid = change['before']['id']
    marker = '[[boundary]]\nid = ' + json.dumps(rid) + '\n'
    start = restored.index(marker)
    end = restored.find('\n[', start + len(marker))
    if end == -1: end = len(restored)
    block = restored[start:end]
    prior = replace_once(block, 'product_callers = ' + json.dumps(change['after']['product_callers']), 'product_callers = ' + json.dumps(change['before']['product_callers']))
    restored = restored[:start] + prior + restored[end:]
assert restored.encode() == entries['CALLERS.toml']['before']

contract_path = 'qa/b4-no-bypass/ROOT_RESIDENT_E3_PRODUCT_SOURCE_CONTRACT.json'
c = json.loads(entries[contract_path]['after'])
delta = load(D / 'REGISTRATION_DELTA.json')
assert c['authority'] is False and c['not_a_qualification_result'] is True
assert c['original_boundary_count'] == 650 and c['projected_boundary_count'] == 666
assert c['original_protected_count'] == 451 and c['projected_protected_count'] == 470
assert c['new_boundary_rows'] == table_after['boundary'][650:] == delta['new_boundary_rows']
assert c['new_protected_rows'] == new_protected == delta['new_protected_rows']
assert c['old_boundary_additions'] == changes == delta['old_boundary_additions']
assert c['original_protected_prefix_sha256'] == hashlib.sha256(canonical(old_protected)).hexdigest()
assert set(c['production_files']) == new_production
assert set(c['test_files']) == set(source_view) - old_source - new_production
for path, expected in {**c['production_files'], **c['test_files']}.items():
    check(source_view[path], expected)
assert len(c['critical_guard_deletions']) == 12
for attack in c['critical_guard_deletions']:
    body = source_view[A + attack['filename']].decode()
    assert body.count(attack['function']) == 1
    # The QA's original rejects() removes the first marker in the selected
    # function. Two intentional before/after checks are not ambiguous failure.
    function_at = body.index(attack['function'])
    marker_at = body.index(attack['marker'], function_at)
    next_fn = re.search(r'(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+', body[function_at + len(attack['function']):])
    assert marker_at > function_at
    if next_fn is not None:
        assert marker_at < function_at + len(attack['function']) + next_fn.start()
    assert next(r['required'] for r in new_protected if r['path'] == A + attack['filename']) == [body]

e1_contract_path = 'qa/b4-no-bypass/ROOT_HOST_INITIAL_PRODUCT_SOURCE_CONTRACT.json'
e1_before = json.loads(entries[e1_contract_path]['before'])
e1_after = json.loads(entries[e1_contract_path]['after'])
for path, expected in e1_before['production_files'].items():
    check(e1_source[path], expected)
composed = {}
for path in [A + 'authority_host_runtime.rs', A + 'lib.rs']:
    e1body = e1_source[path]
    base = source_original[path]
    e3body = source_view[path]
    # Both E1 and E3 add text to the same original body. Independently apply
    # E3 insertion hunks to E1 at unique unchanged adjacent anchors.
    base_lines, e3_lines = base.decode().splitlines(True), e3body.decode().splitlines(True)
    ops = [o for o in difflib.SequenceMatcher(None, base_lines, e3_lines, autojunk=False).get_opcodes() if o[0] != 'equal']
    value = e1body.decode()
    for tag, i1, i2, j1, j2 in reversed(ops):
        assert tag == 'insert' and i1 == i2
        addition = ''.join(e3_lines[j1:j2])
        if i1 == len(base_lines):
            value += addition
        else:
            anchor = ''.join(base_lines[max(0, i1 - 1):i1])
            assert anchor
            value = replace_once(value, anchor, anchor + addition)
    composed[path] = value.encode()
    assert (D / 'composed-e1-e3-only' / path).read_bytes() == composed[path]
    check(composed[path], e1_after['production_files'][path])
    restored_e1 = composed[path].decode()
    for tag, i1, i2, j1, j2 in ops:
        restored_e1 = replace_once(restored_e1, ''.join(e3_lines[j1:j2]), '')
    assert restored_e1.encode() == e1body
    e1_after['production_files'][path] = e1_before['production_files'][path]
assert e1_after == e1_before
assert (json.dumps(e1_after, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode() == entries[e1_contract_path]['before']
combined_source = dict(source_view, **composed)
old_guard_coverage = []
for index, row in enumerate(old_protected):
    if row['path'] in combined_source:
        body = combined_source[row['path']].decode()
        assert all(x in body for x in row.get('required', [])), (index, row['path'])
        assert all(x not in body for x in row.get('forbidden', [])), (index, row['path'])
        old_guard_coverage.append(index)
for change in e1_before['old_boundary_additions']:
    assert table_after['boundary'][change['index']] == change['after']
assert table_after['boundary'][633:650] == e1_before['new_boundary_rows']

workflow_path = '.github/workflows/hepta-daemon-learning-native.yml'
wb, wa = (entries[workflow_path][k].decode() for k in ('before', 'after'))
pattern = r'parents = (\[[\s\S]*?\n          \])'
mb, ma = re.search(pattern, wb), re.search(pattern, wa)
pb, pa = ast.literal_eval(mb.group(1)), ast.literal_eval(ma.group(1))
assert len(pb) == len(set(pb)) == 54
assert len(pa) == len(set(pa)) == 57
assert pa == pb + c['root_parents'] and set(pb).isdisjoint(c['root_parents'])
assert c['root_parents'] == delta['root_parents']
assert replace_once(wa, ma.group(1), mb.group(1)) == wb
root_test_source = source_view[A + 'root_resident_enrollment_handoff_tests.rs'].decode()
assert root_test_source.count('#[ignore = "requires actual original Root credentials and Linux pidfd"]') == 3
assert len(c['root_parents']) == 3
for name in c['root_parents']:
    assert root_test_source.count('fn ' + name.rsplit('::', 1)[-1] + '(') == 1
assert c['ordinary_tests'] == delta['ordinary_tests'] and len(c['ordinary_tests']) == 2
ordinary_tests = source_view[A + 'authority_host_resident_enrollment_wire_tests.rs'].decode()
for name in c['ordinary_tests']:
    assert ordinary_tests.count('fn ' + name.rsplit('::', 1)[-1] + '(') == 1

qa_reviews = []
for path in ['qa/b4-no-bypass/test_resident_root_source_closure.py', 'qa/b4-no-bypass/test_evaluated_published_read_source_closure.py']:
    before, after = (entries[path][k].decode() for k in ('before', 'after'))
    bm, am = methods(before), methods(after)
    assert set(bm) <= set(am)
    changed = {n for n in bm if bm[n] != am[n]}
    added = set(am) - set(bm)
    bc, ac = constants(before), constants(after)
    changed_constants = {n for n in bc if ac.get(n) != bc[n]}
    added_constants = set(ac) - set(bc)
    if path.endswith('test_resident_root_source_closure.py'):
        assert {x.rsplit('.', 1)[-1] for x in changed} == {'test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof', 'test_root_host_initial_product_exact_source_and_original_guards'}
        assert {x.rsplit('.', 1)[-1] for x in added} == {'test_e3_resident_enrollment_exact_sources_and_closed_rows', 'test_e3_resident_enrollment_guards_and_original_root_lane'}
        assert changed_constants == {'EXPECTED'} and added_constants == {'ROOT_E3_RESIDENT_ENROLLMENT_CASES'}
        assert ac['ROOT_E3_RESIDENT_ENROLLMENT_CASES'] == c['root_parents']
        assert set(ac['EXPECTED']) == set(bc['EXPECTED']) | set(new_ids[650:])
        lookup = {r['id']: r for r in table_after['boundary']}
        for rid, callers in ac['EXPECTED'].items():
            assert lookup[rid]['product_callers'] == callers
        for rid, callers in bc['EXPECTED'].items():
            assert ac['EXPECTED'][rid][:len(callers)] == callers
    else:
        assert {x.rsplit('.', 1)[-1] for x in changed} == {'test_new_typed_edges_and_old_boundary_inventory_are_exact'}
        assert not added and not added_constants
        assert changed_constants == {'ORDINARY_COMPLETE_BOUNDARY_SHA256'}
        keys = ('boundary', 'privileged_inventory', 'authority', 'source_roots', 'ignored_path_fragments')
        assert bc['ORDINARY_COMPLETE_BOUNDARY_SHA256'] == hashlib.sha256(canonical({k: table_before[k] for k in keys})).hexdigest()
        assert ac['ORDINARY_COMPLETE_BOUNDARY_SHA256'] == hashlib.sha256(canonical({k: table_after[k] for k in keys})).hexdigest()
        assert replace_once(after, ac['ORDINARY_COMPLETE_BOUNDARY_SHA256'], bc['ORDINARY_COMPLETE_BOUNDARY_SHA256']).replace('self.assertEqual(len(boundaries), 666)', 'self.assertEqual(len(boundaries), 650)') == before
    restore_ast(after, before, changed, added, changed_constants, added_constants)
    qa_reviews.append({'path': path, 'old_function_count': len(bm), 'unchanged_function_count': len(bm) - len(changed),
                       'changed': sorted(changed), 'added': sorted(added), 'deleted': [],
                       'changed_constants': sorted(changed_constants), 'added_constants': sorted(added_constants),
                       'old_ast_exact_after_explicit_inverse': True,
                       'old_unchanged_functions': {n: pin(bm[n].encode()) for n in bm if n not in changed},
                       'changed_full_diffs': {n: ''.join(difflib.unified_diff(bm[n].splitlines(True), am[n].splitlines(True))) for n in changed}})

allowlist = '.github/blob-size-allowlist.txt'
assert entries[allowlist]['after'] == entries[allowlist]['before'] + (
    '# Exact isolated E1 plus E3 resident source registration projection; no wildcard.\n'
    'sha256:' + hashlib.sha256(entries['CALLERS.toml']['after']).hexdigest() + ' CALLERS.toml\n').encode()

proof = {
 'status': 'PURE_BYTE_AND_STRUCTURE_REVIEW_COMPLETED_NO_PROJECT_CODE_EXECUTION',
 'qualification': False, 'h_calls': 0, 'project_tests_or_collectors_executed': 0,
 'git_publication_performed_by_reviewer': False,
 'exact_packet': pin(packet_raw), 'manifest': pin((D / 'MANIFEST.json').read_bytes()),
 'manifest_payload_checks': payloads, 'packet_source_paths': list(entries),
 'six_preimages_equal_prior_e1_registration_packet': True, 'full_seven_path_patch_exact': True,
 'strict_encoding_roundtrip': {'parts': len(encoding[0]['parts']), 'gzip': pin(compressed), 'raw_equal': True},
 'canonical_inventory_binding': pin(inventory_path.read_bytes()), 'source_layers': source_layer_pins,
 'source_chain': {'paths': 21, 'new_production': 12, 'new_tests': 2, 'old_modified': 7,
                  'all_prior_images_exact': True, 'original_old_images_equal_b608': True},
 'top_level_unchanged': unchanged_top,
 'boundary': {'old': 650, 'new': 666, 'old_required_ids_exact_prefix': True, 'no_duplicate_ids': True,
              'old_rows_changed': 18, 'added_old_callers': 24, 'all_other_old_fields_exact': True,
              'old_row_changes': changes, 'new_rows': table_after['boundary'][650:]},
 'protected': {'old': 451, 'new': 470, 'all_451_old_rows_exact': True,
               'row_411_exact': True, 'row_422_exact': True, 'new_full_source_rows': 12,
               'new_old_path_insertion_rows': 7, 'new_forbidden_set': ['SigningKey::generate', 'SigningKey::from_bytes', 'permit_all', 'AllowVerifier'],
               'touched_old_required_and_forbidden_rows_still_satisfied_in_isolated_composition': old_guard_coverage,
               'new_rows_bind_final_e3_explicit_caller_source': True},
 'entire_callers_raw_inverse_equal': True,
 'e1_source_contract': {'only_two_complete_identity_changes': {p: pin(v) for p, v in composed.items()},
                        'same_original_e1_17_boundary_slice_633_650': True,
                        'old_e1_addition_rows_match': True,
                        'other_contract_fields_exact': True, 'full_json_inverse_equal': True},
 'workflow': {'old_parents': 54, 'new_parents': 57, 'appended': c['root_parents'],
              'old_list_exact_prefix_and_no_duplicates': True, 'full_file_inverse_equal': True,
              'commands_budgets_filters_threads_retries_unchanged': True},
 'qa': qa_reviews, 'new_qa_methods': 2, 'new_guard_deletion_specs': 12,
 'old_allowlist_exact_prefix_single_exact_callers_sha_append': True,
 'scope_limits': ['isolated E1 plus E3 only, excludes E2 union',
                  'no caller collector or QA module imported/executed',
                  'no Rust parsing by compiler, formatting, build, native or runtime test',
                  'textual symbol presence is corroboration, not typed collector discovery',
                  '12 guard deletion cases are read and statically bound, not executed',
                  'Root final composition requires rebinding changed source identities and counts'],
}
raw = (json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
new_file(OUT / 'BYTE_AND_STRUCTURE_REVIEW.json', raw)
print(json.dumps({'output': str(OUT / 'BYTE_AND_STRUCTURE_REVIEW.json'), **pin(raw),
                  'source_paths': len(entries), 'boundary': [650, 666], 'protected': [451, 470],
                  'changed_old_callers': [18, 24], 'root_parents': [54, 57], 'new_qa_methods': 2}, sort_keys=True))
