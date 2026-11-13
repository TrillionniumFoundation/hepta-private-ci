"""Prepare the isolated E1 + E3 registration projection without running gates.

The source scanner, QA modules and Rust are read as text only. E2 registration
is deliberately a separate integration dependency, not silently merged here.
"""
from pathlib import Path
import ast
import base64
import copy
import difflib
import gzip
import hashlib
import json
import pprint
import re
import tomllib

ROOT = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1')
E1 = Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
BASE = E1 / 'registration-proposal-v1/after'
OUT = ROOT / 'registration-proposal-v1'
AGENT = 'codex-rs/hepta-agentd/src/'


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def raw_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    assert path.read_bytes() == data


def save_json(path, value):
    data = raw_json(value)
    save(path, data)
    return identity(data)


def replace_once(source, old, new):
    assert source.count(old) == 1, (old[:140], source.count(old))
    result = source.replace(old, new)
    assert result.count(new) == 1, new[:140]
    assert result.replace(new, old) == source
    return result


layers = ['root-service-layer-v1', 'late-enrollment-layer-v1', 'explicit-callers-increment-v1']
view, original, source_pins, layer_pins = {}, {}, {}, []
for layer in layers:
    packet_bytes = (ROOT / layer / 'SOURCE_PACKET.json').read_bytes()
    layer_pins.append({'layer': layer, **identity(packet_bytes)})
    packet = json.loads(packet_bytes)
    for row in packet['entries']:
        path = row['path']
        before = row['before_utf8']
        after = row['after_utf8']
        if before is not None:
            assert identity(before.encode()) == row['before'], path
        assert identity(after.encode()) == row['after'], path
        if path in view:
            assert view[path] == before, (layer, path)
        else:
            original[path] = before
        view[path] = after
        source_pins[path] = row['after']
assert len(view) == 21
assert sum(value is None for value in original.values()) == 14
new_production = sorted(path for path in view if original[path] is None and not path.endswith('_tests.rs'))
new_tests = sorted(path for path in view if path.endswith('_tests.rs'))
modified_originals = sorted(path for path in view if original[path] is not None)
assert (len(new_production), len(new_tests), len(modified_originals)) == (12, 2, 7)

before_callers = (BASE / 'CALLERS.toml').read_bytes()
assert identity(before_callers)['git_blob'] == '8875892749c45665abdce90310a7a47d90308b9b'
base_table = tomllib.loads(before_callers.decode())
assert (len(base_table['boundary']), len(base_table['protected_file'])) == (650, 451)
assert base_table['ignored_path_fragments'] == ['/tests/', '/examples/', '_tests.rs']
assert all(value is False for value in base_table['authority'].values())

old_additions = {
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


def boundary(identifier, symbol, filename, marker, callers, receiver=None):
    row = {'id': 'e3_' + identifier, 'symbol': symbol, 'definition_path': AGENT + filename,
           'definition_markers': [marker], 'product_callers': [AGENT + value for value in callers],
           'caller_markers': []}
    if receiver is not None:
        row['receiver_type'] = receiver
    assert marker in view[row['definition_path']]
    assert row['definition_path'] not in row['product_callers']
    return row


new_boundaries = [
    boundary('root_candidate_prepare', 'prepare_host_resident_candidate_v3', 'authority_host_resident_launch.rs', 'pub fn prepare_host_resident_candidate_v3(', ['authority_host_resident_cli.rs']),
    boundary('root_candidate_recover', 'recover_host_resident_candidate_v3', 'authority_host_resident_launch.rs', 'pub fn recover_host_resident_candidate_v3(', ['authority_host_resident_cli.rs']),
    boundary('root_candidate_late_prepare', 'prepare_host_resident_candidate_enrollment_v3', 'authority_host_resident_enrollment.rs', 'pub async fn prepare_host_resident_candidate_enrollment_v3(', ['authority_host_resident_enrollment_cli.rs']),
    boundary('root_candidate_late_recover', 'recover_host_resident_candidate_enrollment_v3', 'authority_host_resident_enrollment.rs', 'pub async fn recover_host_resident_candidate_enrollment_v3(', ['authority_host_resident_enrollment_cli.rs']),
    boundary('root_candidate_late_run', 'RootResidentCandidateEnrollmentServiceV3::run', 'authority_host_resident_enrollment.rs', 'pub async fn run(self,', ['authority_host_resident_enrollment_cli.rs'], 'RootResidentCandidateEnrollmentServiceV3'),
    boundary('daemon_resident_connect', 'connect_original_resident_enrollment', 'authority_host_resident_enrollment_connect.rs', 'pub(crate) async fn connect_original_resident_enrollment(', ['root_resident_enrollment_handoff.rs']),
    boundary('root_resident_handoff_send', 'send_original_resident_enrollment', 'root_resident_enrollment_handoff.rs', 'pub(crate) fn send_original_resident_enrollment(', ['authority_host_resident_enrollment.rs']),
    boundary('daemon_resident_handoff_receive', 'receive_original_resident_enrollment', 'root_resident_enrollment_handoff.rs', 'pub(crate) async fn receive_original_resident_enrollment(', ['production_resident_enrollment.rs']),
    boundary('root_resident_original_process_pin', 'require_original_resident_process_pin', 'root_resident_enrollment_handoff.rs', 'pub(crate) fn require_original_resident_process_pin(', ['authority_host_resident_enrollment.rs']),
    boundary('root_resident_trust_read', 'OriginalHostTrust::read', 'authority_host_resident_trust_file.rs', 'pub(super) fn read(path:', ['authority_host_resident_launch.rs', 'authority_host_resident_enrollment.rs'], 'OriginalHostTrust'),
    boundary('daemon_resident_root_trust_decode', 'OriginalHostTrust::from_root_enrollment', 'authority_host_resident_trust_file.rs', 'pub(super) fn from_root_enrollment(', ['authority_host_resident_enrollment_connect.rs'], 'OriginalHostTrust'),
    boundary('root_resident_trust_construct', 'OriginalHostTrust::from_value', 'authority_host_resident_trust_file.rs', 'fn from_value(value:', [], 'OriginalHostTrust'),
    boundary('root_resident_observer_binding', 'OriginalHostTrust::observer', 'authority_host_resident_trust_file.rs', 'pub(super) fn observer(', ['authority_host_resident_launch_inputs.rs'], 'OriginalHostTrust'),
    boundary('root_resident_deployment_read', 'OriginalDeployment::read', 'authority_host_resident_launch_inputs.rs', 'pub(super) fn read(', ['authority_host_resident_launch.rs', 'authority_host_resident_enrollment.rs'], 'OriginalDeployment'),
    boundary('root_resident_listener_bind', 'ResidentListener::bind_original', 'authority_host_resident_listener.rs', 'pub(crate) fn bind_original(', ['authority_host_resident_enrollment.rs'], 'ResidentListener'),
    boundary('root_resident_listener_accept', 'ResidentListener::accept_original', 'authority_host_resident_listener.rs', 'pub(crate) async fn accept_original(', ['authority_host_resident_enrollment.rs'], 'ResidentListener'),
]
assert len(new_boundaries) == 16

table = copy.deepcopy(base_table)
changes = []
text = before_callers.decode()
for index, row in enumerate(table['boundary']):
    if row['id'] not in old_additions:
        continue
    old = copy.deepcopy(row)
    added = [AGENT + name for name in old_additions[row['id']]]
    assert set(added).isdisjoint(row['product_callers'])
    row['product_callers'].extend(added)
    blocks = list(re.finditer(r'^\[\[boundary\]\]\n[\s\S]*?(?=^\[\[boundary\]\]|^\[\[protected_file\]\]|^\[authority\]|\Z)', text, re.M))
    found = [match for match in blocks if '\nid = ' + json.dumps(row['id']) + '\n' in match.group()]
    assert len(found) == 1, row['id']
    match = found[0]
    block = match.group()
    old_line = next(line for line in block.splitlines() if line.startswith('product_callers = '))
    new_line = 'product_callers = ' + json.dumps(row['product_callers'])
    new_block = replace_once(block, old_line, new_line)
    text = text[:match.start()] + new_block + text[match.end():]
    changes.append({'index': index, 'before': old, 'after': copy.deepcopy(row), 'added_callers': added})
assert len(changes) == 18

old_ids = table['privileged_inventory']['required_boundary_ids']
assert not set(old_ids).intersection(row['id'] for row in new_boundaries)
new_ids = old_ids + [row['id'] for row in new_boundaries]
inventory_line = next(line for line in text.splitlines() if line.startswith('required_boundary_ids = '))
text = replace_once(text, inventory_line, 'required_boundary_ids = ' + json.dumps(new_ids))
table['privileged_inventory']['required_boundary_ids'] = new_ids
table['boundary'].extend(copy.deepcopy(new_boundaries))

forbidden = ['SigningKey::generate', 'SigningKey::from_bytes', 'permit_all', 'AllowVerifier']
new_guards = []
for path in new_production:
    assert all(marker not in view[path] for marker in forbidden)
    new_guards.append({'path': path, 'required': [view[path]], 'forbidden': forbidden})
old_source_splices = []
for path in modified_originals:
    old_lines, new_lines = original[path].splitlines(True), view[path].splitlines(True)
    opcodes = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False).get_opcodes()
    operations = []
    markers = []
    for tag, left, right, after_left, after_right in opcodes:
        if tag == 'equal':
            continue
        old, new = ''.join(old_lines[left:right]), ''.join(new_lines[after_left:after_right])
        operations.append({'old_lines': [left, right], 'new_lines': [after_left, after_right],
                           'before_utf8': old, 'after_utf8': new})
        if new.strip():
            markers.append(new)
    assert markers
    assert all(marker in view[path] for marker in markers)
    assert all(marker not in view[path] for marker in forbidden)
    new_guards.append({'path': path, 'required': markers, 'forbidden': forbidden})
    old_source_splices.append({'path': path, 'before': identity(original[path].encode()),
                               'after': source_pins[path], 'operations': operations})
assert len(new_guards) == 19
table['protected_file'].extend(copy.deepcopy(new_guards))


def toml_rows(name, rows):
    return ''.join('\n[[' + name + ']]\n' + ''.join(
        key + ' = ' + json.dumps(value, ensure_ascii=False) + '\n'
        for key, value in row.items()) for row in rows)


appendix = toml_rows('boundary', new_boundaries) + toml_rows('protected_file', new_guards)
text = replace_once(text, '\n[authority]\n', appendix + '\n[authority]\n')
assert tomllib.loads(text) == table
assert len(table['boundary']) == 666 and len(table['protected_file']) == 470
assert table['protected_file'][:451] == base_table['protected_file']
assert table['boundary'][633:650] == base_table['boundary'][633:650]
for index, row in enumerate(base_table['boundary']):
    if row['id'] in old_additions:
        restored = copy.deepcopy(table['boundary'][index])
        restored['product_callers'] = row['product_callers']
        assert restored == row
    else:
        assert table['boundary'][index] == row
assert table['protected_file'][411] == base_table['protected_file'][411]
assert table['protected_file'][422] == base_table['protected_file'][422]

required_old = []
for index, row in enumerate(base_table['protected_file'][:442]):
    if row['path'] in view:
        assert all(marker in view[row['path']] for marker in row['required'])
        required_old.append(index)
assert required_old == [30, 71, 74, 83, 114, 159, 161, 162, 163, 314, 441]

root_cases = [
    'root_production_handoff::resident_enrollment::tests::exact_v3_framing_preserves_original_sealed_bytes_and_root_pidfd',
    'root_production_handoff::resident_enrollment::tests::v1_marker_cannot_enter_the_v3_resident_handoff',
    'root_production_handoff::resident_enrollment::tests::sealed_file_alias_cannot_replace_the_original_root_pidfd',
]
ordinary_cases = [
    'authority_host_runtime::resident_launch::enrollment::wire::tests::translated_monotonic_deadline_never_renews_the_original_window',
    'authority_host_runtime::resident_launch::enrollment::wire::tests::expired_and_overlong_original_windows_are_refused_without_waiting',
]
for name in root_cases:
    assert 'fn ' + name.rsplit('::', 1)[-1] + '(' in view[AGENT + 'root_resident_enrollment_handoff_tests.rs']
for name in ordinary_cases:
    assert 'fn ' + name.rsplit('::', 1)[-1] + '(' in view[AGENT + 'authority_host_resident_enrollment_wire_tests.rs']
assert view[AGENT + 'root_resident_enrollment_handoff_tests.rs'].count(
    '#[ignore = "requires actual original Root credentials and Linux pidfd"]') == 3
workflow_path = '.github/workflows/hepta-daemon-learning-native.yml'
workflow_before = (BASE / workflow_path).read_text()
match = re.search(r'parents = (\[[\s\S]*?\n          \])', workflow_before)
assert match
parents_before = ast.literal_eval(match.group(1))
assert len(parents_before) == 54 and len(set(parents_before)) == 54
assert set(parents_before).isdisjoint(root_cases)
old_array = match.group(1)
new_array = old_array[:-len('          ]')] + ''.join('              ' + json.dumps(name) + ',\n' for name in root_cases) + '          ]'
workflow_after = replace_once(workflow_before, old_array, new_array)
assert ast.literal_eval(new_array) == parents_before + root_cases

# Reconstruct only the E1+E3 overlap for the existing exact E1 contract. E2 is
# deliberately absent from this isolated projection; its final merge must
# rebind all changed contract files and global counts to Root's complete view.
e1_images = {}
for layer in ['assembled-source-v1', 'request-type-import-increment-v1']:
    for row in json.loads((E1 / layer / 'SOURCE_PACKET.json').read_text())['images']:
        e1_images[row['path']] = row['after']
e1_contract_path = 'qa/b4-no-bypass/ROOT_HOST_INITIAL_PRODUCT_SOURCE_CONTRACT.json'
e1_contract_before = (BASE / e1_contract_path).read_bytes()
e1_contract = json.loads(e1_contract_before)
for path, expected in e1_contract['production_files'].items():
    assert identity(e1_images[path].encode()) == expected, path
composition = []
pending_composed = {}
mounts = json.loads((ROOT / 'root-service-layer-v1/EXACT_MOUNT_SPLICES.json').read_text())
for path in [AGENT + 'authority_host_runtime.rs', AGENT + 'lib.rs']:
    source = e1_images[path]
    before = source
    for mount in mounts:
        if mount['path'] == path:
            source = replace_once(source, mount['anchor'], mount['anchor'] + mount['insert_after'])
    late_before = json.loads((ROOT / 'late-enrollment-layer-v1/SOURCE_PACKET.json').read_text())
    row = next(row for row in late_before['entries'] if row['path'] == path)
    assert row['after_utf8'].startswith(row['before_utf8']), path
    tail = row['after_utf8'][len(row['before_utf8']):]
    source += tail
    inverse = source[:-len(tail)]
    for mount in reversed(mounts):
        if mount['path'] == path:
            inverse = replace_once(inverse, mount['anchor'] + mount['insert_after'], mount['anchor'])
    assert inverse == before
    assert all(marker in source for guard in table['protected_file'] if guard['path'] == path for marker in guard['required'])
    e1_contract['production_files'][path] = identity(source.encode())
    composition.append({'path': path, 'e1_before': identity(before.encode()),
                        'e1_e3_after': identity(source.encode()), 'inverse_equal': True})
    pending_composed[path] = source.encode()
e1_contract_after = raw_json(e1_contract)

critical = [
    ('authority_host_resident_cli.rs', 'fn run(', 'let work = codex_hepta_agentd::RootResidentCandidateServiceV1::run(service, cancellation.clone());'),
    ('authority_host_resident_launch.rs', 'fn prepare(', 'if unsafe { libc::geteuid() } != 0'),
    ('authority_host_resident_launch_inputs.rs', 'fn read(', 'OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)'),
    ('authority_host_resident_trust_file.rs', 'fn observer(', '.require_signer_binding(LearningEvidenceRoleV1::Observer, signer, now)'),
    ('authority_host_resident_enrollment.rs', 'async fn prepare_enrollment(', 'crate::root_production_handoff::send_original_resident_enrollment('),
    ('authority_host_resident_enrollment_cli.rs', 'fn run(', 'let work = codex_hepta_agentd::RootResidentCandidateEnrollmentServiceV3::run(service, cancellation.clone());'),
    ('authority_host_resident_enrollment_connect.rs', 'async fn connect_original_resident_enrollment(', 'packet.consumer.pid != std::process::id()'),
    ('authority_host_resident_enrollment_profile.rs', 'fn original(', 'if profile.binding() != digest(&self.binding)?'),
    ('authority_host_resident_enrollment_wire.rs', 'fn read(', 'crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;'),
    ('authority_host_resident_listener.rs', 'fn bind_original(', 'validate_lane_paths(&[&path], config.peer_gid)?;'),
    ('production_resident_enrollment.rs', 'async fn run_original(', 'config.with_root_resident_learning_enrollment()?'),
    ('root_resident_enrollment_handoff.rs', 'async fn receive_original_resident_enrollment(', 'require_root_pin(&pidfd, peer.pid as u32)?;'),
]
for name, function, marker in critical:
    assert view[AGENT + name].count(function) == 1, name
    assert marker in view[AGENT + name], name

contract_path = 'qa/b4-no-bypass/ROOT_RESIDENT_E3_PRODUCT_SOURCE_CONTRACT.json'
contract = {
    'format': 'hepta.e3.resident-source-contract.v1',
    'view': 'isolated E1 registration plus three frozen E3 layers; E2 union remains a later explicit integration',
    'original_boundary_count': 650, 'projected_boundary_count': 666,
    'original_protected_count': 451, 'projected_protected_count': 470,
    'original_protected_prefix_sha256': hashlib.sha256(canonical(base_table['protected_file'])).hexdigest(),
    'old_boundary_additions': changes, 'new_boundary_rows': new_boundaries,
    'new_protected_rows': new_guards,
    'production_files': {path: source_pins[path] for path in new_production},
    'test_files': {path: source_pins[path] for path in new_tests},
    'root_parents': root_cases, 'ordinary_tests': ordinary_cases,
    'critical_guard_deletions': [{'filename': name, 'function': function, 'marker': marker} for name, function, marker in critical],
    'authority': False,
    'not_a_qualification_result': True,
}
contract_raw = raw_json(contract)

root_qa_path = 'qa/b4-no-bypass/test_resident_root_source_closure.py'
root_qa_before = (BASE / root_qa_path).read_text()
root_qa = root_qa_before
assignments = {node.targets[0].id: node for node in ast.parse(root_qa).body
               if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
expected = ast.literal_eval(assignments['EXPECTED'].value)
for change in changes:
    if change['after']['id'] in expected:
        assert expected[change['after']['id']] == change['before']['product_callers']
        expected[change['after']['id']] = change['after']['product_callers']
for row in new_boundaries:
    assert row['id'] not in expected
    expected[row['id']] = row['product_callers']
old_expected = ast.get_source_segment(root_qa, assignments['EXPECTED'])
root_qa = replace_once(root_qa, old_expected, 'EXPECTED = ' + pprint.pformat(expected, width=100, sort_dicts=False))
root_qa = replace_once(root_qa, 'ROOT_CUSTODY_CASES = ', 'ROOT_E3_RESIDENT_ENROLLMENT_CASES = ' + repr(root_cases) + '\nROOT_CUSTODY_CASES = ')
root_qa = replace_once(root_qa,
    '        self.assertTrue(set(ROOT_HOST_GENERATION_CASES).issubset(parents))\n',
    '        self.assertTrue(set(ROOT_HOST_GENERATION_CASES).issubset(parents))\n        self.assertTrue(set(ROOT_E3_RESIDENT_ENROLLMENT_CASES).issubset(parents))\n')
root_qa = replace_once(root_qa,
    'self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES) + len(ROOT_CUSTODY_CASES) + len(ROOT_HOST_GENERATION_CASES))',
    'self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES) + len(ROOT_CUSTODY_CASES) + len(ROOT_HOST_GENERATION_CASES) + len(ROOT_E3_RESIDENT_ENROLLMENT_CASES))')
root_qa = replace_once(root_qa, hashlib.sha256(e1_contract_before).hexdigest(), hashlib.sha256(e1_contract_after).hexdigest())
root_qa = replace_once(root_qa, 'self.assertEqual(len(current["boundary"]), 650)', 'self.assertEqual(len(current["boundary"]), 666)')
root_qa = replace_once(root_qa, 'self.assertEqual(len(current["protected_file"]), 451)', 'self.assertEqual(len(current["protected_file"]), 470)')
root_qa = replace_once(root_qa, 'current["boundary"][-17:]', 'current["boundary"][633:650]')

new_methods = '''    def test_e3_resident_enrollment_exact_sources_and_closed_rows(self):
        raw = (ROOT / "qa/b4-no-bypass/ROOT_RESIDENT_E3_PRODUCT_SOURCE_CONTRACT.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "CONTRACT_SHA")
        contract = json.loads(raw)
        current = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        self.assertEqual(len(current["boundary"]), contract["projected_boundary_count"])
        self.assertEqual(len(current["protected_file"]), contract["projected_protected_count"])
        prefix = json.dumps(current["protected_file"][:451], sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(prefix).hexdigest(), contract["original_protected_prefix_sha256"])
        self.assertEqual(current["boundary"][650:666], contract["new_boundary_rows"])
        self.assertEqual(current["protected_file"][451:470], contract["new_protected_rows"])
        for change in contract["old_boundary_additions"]:
            self.assertEqual(current["boundary"][change["index"]], change["after"])
        for path, expected in {**contract["production_files"], **contract["test_files"]}.items():
            with self.subTest(e3_source=path):
                body = (ROOT / path).read_bytes()
                actual = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                          "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\\0" + body).hexdigest()}
                self.assertEqual(actual, expected)

    def test_e3_resident_enrollment_guards_and_original_root_lane(self):
        raw = (ROOT / "qa/b4-no-bypass/ROOT_RESIDENT_E3_PRODUCT_SOURCE_CONTRACT.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "CONTRACT_SHA")
        contract = json.loads(raw)
        for attack in contract["critical_guard_deletions"]:
            with self.subTest(e3_guard=attack["filename"]):
                self.rejects(attack["filename"], attack["function"], attack["marker"])
        parent = (ROOT / (AGENT + "root_production_handoff.rs")).read_text()
        handoff = (ROOT / (AGENT + "root_resident_enrollment_handoff.rs")).read_text()
        cases = (ROOT / (AGENT + "root_resident_enrollment_handoff_tests.rs")).read_text()
        self.assertIn('#[path = "root_resident_enrollment_handoff.rs"]\\nmod resident_enrollment;', parent)
        self.assertIn('#[path = "root_resident_enrollment_handoff_tests.rs"]\\nmod tests;', handoff)
        self.assertEqual(contract["root_parents"], ROOT_E3_RESIDENT_ENROLLMENT_CASES)
        self.assertEqual(len(ROOT_E3_RESIDENT_ENROLLMENT_CASES), len(set(ROOT_E3_RESIDENT_ENROLLMENT_CASES)))
        self.assertTrue(set(ROOT_E3_RESIDENT_ENROLLMENT_CASES).isdisjoint(ROOT_CASES + ROOT_ISSUER_CASES + ROOT_CUSTODY_CASES + ROOT_HOST_GENERATION_CASES))
        for parent in ROOT_E3_RESIDENT_ENROLLMENT_CASES:
            self.assertIn("fn " + parent.rsplit("::", 1)[-1] + "(", cases)
        self.assertEqual(cases.count('#[ignore = "requires actual original Root credentials and Linux pidfd"]'), 3)


'''.replace('CONTRACT_SHA', hashlib.sha256(contract_raw).hexdigest())
root_qa = replace_once(root_qa, 'if __name__ == "__main__":\n', new_methods + 'if __name__ == "__main__":\n')
ast.parse(root_qa)

ordinary_qa_path = 'qa/b4-no-bypass/test_evaluated_published_read_source_closure.py'
ordinary_qa_before = (BASE / ordinary_qa_path).read_text()
ordinary_qa = replace_once(ordinary_qa_before, 'self.assertEqual(len(boundaries), 650)', 'self.assertEqual(len(boundaries), 666)')
checked_keys = ('boundary', 'privileged_inventory', 'authority', 'source_roots', 'ignored_path_fragments')
old_complete = hashlib.sha256(canonical({key: base_table[key] for key in checked_keys})).hexdigest()
new_complete = hashlib.sha256(canonical({key: table[key] for key in checked_keys})).hexdigest()
ordinary_qa = replace_once(ordinary_qa, old_complete, new_complete)
ast.parse(ordinary_qa)

allowlist_path = '.github/blob-size-allowlist.txt'
allowlist_before = (BASE / allowlist_path).read_bytes()
allowlist_after = allowlist_before + (
    '# Exact isolated E1 plus E3 resident source registration projection; no wildcard.\n'
    'sha256:' + hashlib.sha256(text.encode()).hexdigest() + ' CALLERS.toml\n').encode()

outputs = {
    'CALLERS.toml': (before_callers, text.encode()),
    workflow_path: (workflow_before.encode(), workflow_after.encode()),
    allowlist_path: (allowlist_before, allowlist_after),
    e1_contract_path: (e1_contract_before, e1_contract_after),
    contract_path: (None, contract_raw),
    root_qa_path: (root_qa_before.encode(), root_qa.encode()),
    ordinary_qa_path: (ordinary_qa_before.encode(), ordinary_qa.encode()),
}

method_review = []
for path, before, after in [(root_qa_path, root_qa_before, root_qa), (ordinary_qa_path, ordinary_qa_before, ordinary_qa)]:
    def methods(source):
        return {node.name: ast.get_source_segment(source, node) for node in ast.walk(ast.parse(source))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    old_methods, new_methods_map = methods(before), methods(after)
    assert set(old_methods).issubset(new_methods_map)
    changed = [name for name in old_methods if old_methods[name] != new_methods_map[name]]
    unchanged = [name for name in old_methods if old_methods[name] == new_methods_map[name]]
    added = sorted(set(new_methods_map) - set(old_methods))
    if path == root_qa_path:
        assert changed == [
            'test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof',
            'test_root_host_initial_product_exact_source_and_original_guards',
        ], changed
        assert len(added) == 2
    else:
        assert changed == ['test_new_typed_edges_and_old_boundary_inventory_are_exact']
        assert not added
    method_review.append({'path': path, 'old_count': len(old_methods), 'unchanged': unchanged,
                          'explicitly_migrated': changed, 'added': added, 'deleted': []})

entries = []
patch = []
for path, body in pending_composed.items():
    save(OUT / 'composed-e1-e3-only' / path, body)
for path, (before, after) in sorted(outputs.items()):
    if before is not None:
        save(OUT / 'before' / path, before)
    save(OUT / 'after' / path, after)
    entries.append({'path': path, 'before': identity(before) if before is not None else None,
                    'after': identity(after), 'before_utf8': before.decode() if before is not None else None,
                    'after_utf8': after.decode()})
    patch.extend(difflib.unified_diff((before or b'').decode().splitlines(True), after.decode().splitlines(True),
                                    fromfile='a/' + path, tofile='b/' + path))

obligations = {
    'state': 'ISOLATED_E1_PLUS_E3_PROJECTION_NOT_FINAL_ROOT_UNION',
    'e2_source_registration_excluded': True,
    'final_integration_required': [
        'Root must combine E2 boundary/caller/protection rows without dropping any E1 or E3 row.',
        'Rebind complete source identities for all E1 contract files modified by the final E2/E3 composition; this projection binds only E1 plus E3.',
        'Combine both independent launcher flags in the one original duplicate-FD set; the Root composition already handles their shared FLAGS length.',
        'Recompute exact total rows, inventory SHA, protected prefix/slices, complete source contract hashes and Root parents after the E2 registration layer.',
        'Run the unchanged full scanner and required source/native qualification only under Root future exact authorization; this packet supplies no execution permission.',
    ],
    'unchanged_rules': ['scanner bytes', 'typed receiver resolver', 'source roots', 'ignore fragments', 'old forbidden rows', 'old function ordering', 'all authority flags false', 'Root ignored-only single-thread retries-zero JUnit exact-name selection', 'original budgets'],
    'non_boundaries_explained': {
        'EnrollmentProfile::capture/original': 'Private copying and revalidation of public data; original freeze/snapshot edges are registered, and the complete new file is protected. No owner or verified stage receipt is constructed.',
        'wire Process metadata and monotonic helpers': 'Private data/time checks, no process authority descriptor or stage owner is returned; complete wire body protection retains all checks.',
        'production_resident_enrollment::run_original': 'Private ordinary orchestration is protected as a complete file. The actual privileged opt-in, enrollment submit and fixed receive entries are separately registered.',
    },
    'explicit_remaining_product_gap': 'The non-Root Material-only Source loan and real protected deployment owners are not supplied by E3 enrollment metadata; missing actual inputs must refuse.',
}

review = {
    'scope': obligations['state'], 'base_callers': identity(before_callers),
    'rust_layers': layer_pins, 'rust_union': {'coverage': 21, 'new_production': 12, 'new_test_files': 2, 'modified_original_paths': 7},
    'old_boundary_rows': 650, 'old_boundary_rows_with_caller_append': 18,
    'new_caller_edges': sum(len(change['added_callers']) for change in changes),
    'new_boundary_rows': 16, 'projected_boundary_rows': 666,
    'old_protected_rows_unchanged': 451, 'new_protected_rows': 19, 'projected_protected_rows': 470,
    'b608_touched_protected_rows_required_text_preserved': required_old,
    'row_411_and_422_objects_preserved': True,
    'root_parents_projection': {'before': 54, 'after': 57, 'appended': root_cases},
    'ordinary_new_rust_tests': ordinary_cases,
    'qa_method_comparison': method_review,
    'new_guard_deletion_cases_prepared_not_run': 12,
    'new_boundary_unregistered_caller_cases_prepared_not_run': 16,
    'e1_contract_exact_composition': composition,
    'old_boundary_fields_except_product_callers_equal': True,
    'all_existing_scanner_rules_and_authority_flags_equal': True,
    'performed': ['Python standard-library parse of TOML/JSON/Python text', 'complete frozen byte identity and exact source layer chaining', 'fixed string changes and inverse checks', 'complete old row object equality', 'QA method byte comparison'],
    'not_performed': ['original scanner or collector', 'QA execution', 'Rust compile', 'Rust tests', 'formatter', 'H', 'Git source writes', 'ref updates'],
    'limitations': obligations['final_integration_required'],
}

packet = {'format': 'hepta-source-packet-v1', 'state': obligations['state'],
          'base_source_commit': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
          'prerequisites': {'e1_registration_manifest': 'be7ca52a22448ea36ff8f756d7f038a8a8b82bdc', 'e3_layers': layer_pins},
          'entries': entries}
packet_raw = raw_json(packet)
save(OUT / 'SOURCE_PACKET.json', packet_raw)
save(OUT / 'SOURCE_DELTA.patch', ''.join(patch).encode())
save_json(OUT / 'REGISTRATION_DELTA.json', {'old_boundary_additions': changes, 'new_boundary_rows': new_boundaries, 'new_protected_rows': new_guards, 'root_parents': root_cases, 'ordinary_tests': ordinary_cases})
save_json(OUT / 'OLD_SOURCE_INSERTIONS.json', old_source_splices)
save_json(OUT / 'INTEGRATION_OBLIGATIONS.json', obligations)
save_json(OUT / 'QA_METHOD_PRESERVATION.json', method_review)
save_json(OUT / 'REVIEW.json', review)
save_json(OUT / 'SOURCE_IDENTITIES.json', {'layers': layer_pins, 'sources': source_pins})
save(OUT / 'prepare_registration.py', Path(__file__).read_bytes())

# Large evidence remains reconstructible through bounded parts; the proposal
# CALLERS source itself has its exact, narrowly appended allowlist identity.
encoding = []
for name in ['SOURCE_PACKET.json', 'SOURCE_DELTA.patch']:
    body = (OUT / name).read_bytes()
    if len(body) <= 512000:
        continue
    compressed = gzip.compress(body, mtime=0)
    encoded = base64.b64encode(compressed)
    parts = []
    for i, offset in enumerate(range(0, len(encoded), 409600)):
        data = encoded[offset:offset + 409600]
        path = 'encoded/' + name.replace('.', '_') + f'.part-{i:02d}.b64'
        save(OUT / path, data)
        parts.append({'path': path, 'offset': offset, **identity(data)})
    rebuilt = b''.join((OUT / row['path']).read_bytes() for row in parts)
    assert base64.b64decode(rebuilt, validate=True) == compressed
    assert gzip.decompress(compressed) == body
    encoding.append({'raw_path': name, 'raw': identity(body), 'gzip': identity(compressed),
                     'base64_bytes': len(encoded), 'parts': parts, 'lossless_complete': True})
save_json(OUT / 'ENCODING_MANIFEST.json', encoding)
payloads = []
for path in sorted(OUT.iterdir()):
    if path.is_file():
        payloads.append({'path': path.name, **identity(path.read_bytes())})
for path in sorted((OUT / 'encoded').glob('*')):
    payloads.append({'path': path.relative_to(OUT).as_posix(), **identity(path.read_bytes())})
manifest = {'format': 'hepta-local-registration-proposal-v1', 'state': obligations['state'],
            'durability': 'local complete bytes and computed identities; no Git create or full GET asserted',
            'source_entries': [{key: row[key] for key in ['path', 'before', 'after']} for row in entries],
            'payloads': payloads}
manifest_pin = save_json(OUT / 'MANIFEST.json', manifest)
print(json.dumps({'packet': identity(packet_raw), 'manifest': manifest_pin, 'review': identity((OUT / 'REVIEW.json').read_bytes()),
                  'source_paths': len(entries), 'boundaries': 666, 'protected': 470, 'root_parents': 57}, sort_keys=True))
