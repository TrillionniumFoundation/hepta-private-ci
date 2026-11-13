"""Offline source/identity verification. No candidate import, Git, H, or gates."""
import base64
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTHOR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')
CANONICAL = Path('/tmp/hepta-36fa-new-source-materializer-hold-v1/EXPECTED_CANDIDATE.complete.inventory.json')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def load(path):
    return json.loads(path.read_bytes())

def exact(raw, expected):
    observed = pin(raw)
    assert observed == expected, (observed, expected)
    return observed

def tree(files):
    root = {}
    for path, (mode, oid) in files.items():
        parts = path.split('/')
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            assert isinstance(node, dict)
        assert parts[-1] not in node
        node[parts[-1]] = (mode, oid)
    def digest(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, oid, key = '40000', digest(value), (name + '/').encode()
            else:
                mode, oid = value
                key = name.encode()
            entries.append((key, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(oid)))
        raw = b''.join(raw for _, raw in sorted(entries))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return digest(root)

def mode(row):
    if row['kind'] == 'symlink':
        return '120000'
    assert row['kind'] == 'file'
    return '100755' if row['permissions'] & 0o111 else '100644'

def main():
    packet_raw = (AUTHOR / 'SOURCE_PACKET.json').read_bytes()
    packet_pin = exact(packet_raw, {'bytes': 152573,
        'sha256': '84b79dd4fc36e070f57f3de05982cd7a55130b5af67f7890a98ad187a1219300',
        'git_blob': '12a664ce2905feb8107ae66b303c4975f17a9fe3'})
    packet = json.loads(packet_raw)
    assert packet['actual_maintenance_job'] == '1a1d3eccd3a-392-231'
    assert packet['source_deletions'] == []
    assert len(packet['changes']) == 4
    result_raw = (AUTHOR / 'actual_inputs/RESULT.json').read_bytes()
    assert pin(result_raw)['git_blob'] == 'c9ddc9349881689c2825852c746e8235f83cb921'
    result = json.loads(result_raw)
    assert result['status'] == 'FAILED_MAINTENANCE'
    assert result['attempted_commands'] == ['fix']
    assert result['not_run_commands'] == ['fmt']
    assert result['test_commands_dispatched'] == 0
    assert len(result['stages']) == 1
    stage = result['stages'][0]
    terminal_raw = (AUTHOR / 'actual_inputs/fix.terminal.json').read_bytes()
    assert pin(terminal_raw)['git_blob'] == '63b4ec2d123e8eddaeaef3bccc1490285eab8df2'
    assert json.loads(terminal_raw) == stage
    assert stage['execution']['returncode'] == 101
    assert stage['execution']['timed_out'] is False
    assert stage['execution']['output_limit_exceeded'] is False
    assert stage['raw_log_retained'] is True
    assert result['git_metadata_unchanged'] is True
    assert all(row['status'] == 'verified' for row in result['final_audits'])
    assert result['final_audits'][1]['input_count'] == 24
    assert result['final_audits'][1]['unchanged'] is True

    raw_log = (AUTHOR / 'actual_inputs/fix.raw.exact_recovered.log').read_bytes()
    assert pin(raw_log)['git_blob'] == 'feaf209bf89bcbdc71cdb1787a49c3433745a9cb'
    assert len(raw_log) == stage['execution']['log_bytes']
    assert hashlib.sha256(raw_log).hexdigest() == stage['execution']['log_sha256']
    codes = re.findall(rb'^error\[(E[0-9]+)\]:', raw_log, re.M)
    assert sorted(codes) == sorted([b'E0364', b'E0277', b'E0277', b'E0599', b'E0599', b'E0599'])
    excerpt = (AUTHOR / 'actual_inputs/fix.compiler_errors.original_excerpt.txt').read_bytes()
    assert pin(excerpt)['git_blob'] == 'f7a4e4776d967a893d9b82d770d1e9f08b305ef4'
    assert excerpt in raw_log

    inventory_raw = (AUTHOR / 'ACTUAL_FINAL_INVENTORY.exact_recovered.json').read_bytes()
    inventory_pin = exact(inventory_raw, result['actual_final_source']['inventory'])
    inventory = json.loads(inventory_raw)
    assert len(inventory['files']) == 15237
    rows = {row['path']: row for row in inventory['files']}
    original_inventory_raw = CANONICAL.read_bytes()
    assert pin(original_inventory_raw)['git_blob'] == 'a596ae68859e3263a9ee58e2b5d7334ac9314c34'
    originals = {row['path']: row for row in json.loads(original_inventory_raw)['files']}
    assert rows.keys() == originals.keys()
    changed_from_canonical = [path for path in rows if rows[path] != originals[path]]
    witness_path = 'codex-rs/hepta-learning-ledger/src/witness.rs'
    assert changed_from_canonical == [witness_path]
    physical = {path: (mode(row), row['working_blob']) for path, row in rows.items()}
    baseline_tree = tree(physical)
    assert baseline_tree == '4ed32552042fee522965ea54caf95bbebb31ad43'
    assert baseline_tree == packet['actual_baseline_physical_tree']
    assert inventory_pin == packet['actual_baseline_inventory']

    post_raw = (AUTHOR / 'actual_inputs/final.postimages.json').read_bytes()
    assert pin(post_raw)['git_blob'] == '786b5872a8064d18f6d391b82c7af3813541c0c1'
    post = json.loads(post_raw)
    assert len(post['changes']) == 1
    actual_witness = post['changes'][0]
    assert actual_witness['path'] == witness_path
    assert post['after_inventory_sha256'] == inventory_pin['sha256']
    kept = packet['preserved_actual_fix_postimages']
    assert len(kept) == 1 and kept[0]['path'] == witness_path
    for side in ['before', 'after']:
        body = base64.b64decode(actual_witness[side + '_raw_base64'], validate=True)
        assert body == kept[0][side + '_text'].encode()
        assert pin(body) == kept[0][side]
        assert pin(body)['git_blob'] == actual_witness[side]['working_blob']
        assert body == (AUTHOR / 'preserved_actual_fix' / side / witness_path).read_bytes()
    witness_after = kept[0]['after_text'].encode()
    assert witness_after == (AUTHOR / 'after' / witness_path).read_bytes()
    assert pin(witness_after)['git_blob'] == rows[witness_path]['working_blob']

    changes = {row['path']: row for row in packet['changes']}
    for path, row in changes.items():
        assert path.endswith('_tests.rs')
        assert row['mode'] == '100644'
        for side in ['before', 'after']:
            body = row[side + '_text'].encode()
            exact(body, row[side])
            assert body == (AUTHOR / side / path).read_bytes()
        assert row['before']['git_blob'] == rows[path]['working_blob']
        assert row['before']['git_blob'] == originals[path]['working_blob']
        assert row['before']['bytes'] == rows[path]['bytes']
        assert row['before']['sha256'] == rows[path]['sha256']
        physical[path] = (row['mode'], row['after']['git_blob'])

    prefix = 'codex-rs/hepta-agentd/src/'
    support = changes[prefix + 'circuit_resident_candidate_first_material_support_tests.rs']
    old_use = 'pub(super) use wire::encode_original_report;'
    new_use = 'use wire::encode_original_report;'
    assert support['before_text'].count(old_use) == 1
    assert support['before_text'].replace(old_use, new_use, 1) == support['after_text']

    transport = changes[prefix + 'authority_host_learning_resident_provider_transport_tests.rs']
    peer_pairs = [
      ('Ok(TaskStream { stream, peer: process.peer.clone(), uid: process::PEER_UID,',
       'Ok(TaskStream { stream, peer: crate::AgentdRootAuthorityPeer {\n            pid: process.peer.pid, boot_id: process.peer.boot_id.clone(),\n            process_start_ticks: process.peer.process_start_ticks,\n        }, uid: process::PEER_UID,'),
      ('Ok(RootResidentLearningConsumerV3 { stream, peer: process.peer.clone(), uid: process::PEER_UID,',
       'Ok(RootResidentLearningConsumerV3 { stream, peer: crate::AgentdRootAuthorityPeer {\n        pid: process.peer.pid, boot_id: process.peer.boot_id.clone(),\n        process_start_ticks: process.peer.process_start_ticks,\n    }, uid: process::PEER_UID,'),
      ('let recipient = if wrong_recipient { peer.peer.clone() } else { process::process(std::process::id())? };',
       'let recipient = if wrong_recipient {\n            crate::AgentdRootAuthorityPeer {\n                pid: peer.peer.pid, boot_id: peer.peer.boot_id.clone(),\n                process_start_ticks: peer.peer.process_start_ticks,\n            }\n        } else { process::process(std::process::id())? };'),
    ]
    current = transport['before_text']
    for old, new in peer_pairs:
        assert current.count(old) == 1
        current = current.replace(old, new, 1)
    assert current == transport['after_text']
    for old, new in reversed(peer_pairs):
        assert current.count(new) == 1
        current = current.replace(new, old, 1)
    assert current == transport['before_text']

    source = (AUTHOR / 'references/circuit_task_source.rs').read_text()
    assert pin(source.encode())['git_blob'] == '68cf423686f24d192d015b0c06e86eea530dfc81'
    source_body = re.search(r'fn input\(&self, operation_id: StableId\) -> CellStepInputV1 \{\s*CellStepInputV1 \{(.*?)\n        \}', source, re.S).group(1)
    expected_fields = []
    for line in source_body.splitlines():
        line = line.strip().removesuffix(',')
        if not line:
            continue
        expected_fields.append('operation_id: previous.input().operation_id.clone()' if line == 'operation_id' else line.replace('self.', 'source_a.'))
    assert len(expected_fields) == 9
    assert all('lease_duration_ms' not in field for field in expected_fields)
    mapping_records = []
    projection_specs = [
      ('circuit_original_evaluation_fresh_training_support_tests.rs', '        ', 'anyhow::ensure!(previous.input() == source_a);', 'anyhow::ensure!(previous.input() == &expected_input);'),
      ('circuit_resident_candidate_provider_unstarted_material_tests.rs', '            ', 'anyhow::ensure!(previous.input() == &source_a, "actual A uses this original input");', 'anyhow::ensure!(previous.input() == &expected_input, "actual A uses this original input");'),
    ]
    for name, indent, old, replacement_assert in projection_specs:
        row = changes[prefix + name]
        replacement = indent + '// Match the original Source input projection, retaining the operation\n'
        replacement += indent + '// identity already authenticated by the opaque publication.\n'
        replacement += indent + 'let expected_input = codex_hepta_neuron::CellStepInputV1 {\n'
        replacement += ''.join(indent + '    ' + field + ',\n' for field in expected_fields)
        replacement += indent + '};\n' + indent + replacement_assert
        assert row['before_text'].count(indent + old) == 1
        assert row['before_text'].replace(indent + old, replacement, 1) == row['after_text']
        assert row['after_text'].replace(replacement, indent + old, 1) == row['before_text']
        mapping_records.append({'path': row['path'], 'all_source_projection_fields': expected_fields,
                                'full_file_forward_and_inverse_equal': True})

    peer = (AUTHOR / 'references/root_observation_stream.rs').read_text()
    assert pin(peer.encode())['git_blob'] == '9d3d24bd5104be99372c8a55859360e792120605'
    peer_fields = re.search(r'pub struct AgentdRootAuthorityPeer \{(.*?)\n\}', peer, re.S).group(1)
    assert [s.strip() for s in peer_fields.splitlines() if s.strip()] == [
        'pub pid: u32,', 'pub boot_id: String,', 'pub process_start_ticks: u64,']
    wire = (ROOT / 'inputs/circuit_resident_candidate_first_material_wire_tests.rs').read_bytes()
    tests = (ROOT / 'inputs/circuit_resident_candidate_first_material_tests.rs').read_bytes()
    assert pin(wire)['git_blob'] == '57c57a8dca65e231feac0481c4ba31f4a1407ed0'
    assert pin(tests)['git_blob'] == 'cffa9f294b84565d427be48c5ac099aec3872d9d'
    assert b'pub(super) fn encode_original_report(' in wire
    assert '#[path = "circuit_resident_candidate_first_material_tests.rs"]\nmod tests;' in support['after_text']
    assert b'use super::*;' in tests and b'encode_original_report(' in tests
    for name in ['circuit_resident_candidate_first_material_wire_tests.rs', 'circuit_resident_candidate_first_material_tests.rs']:
        envelope = load(ROOT / 'inputs' / (name + '.GITHUB_GET.original.json'))
        assert envelope['structuredContent']['content'].encode() == (ROOT / 'inputs' / name).read_bytes()

    successor_tree = tree(physical)
    assert successor_tree == '1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1'
    assert successor_tree == packet['expected_successor_physical_tree']
    assert len(physical) == packet['expected_leaf_count'] == 15237
    verification = {
        'schema': 'hepta-fix101-independent-byte-and-source-projection-review-v1',
        'packet': packet_pin,
        'actual_result': pin(result_raw),
        'actual_terminal': pin(terminal_raw),
        'actual_raw_log': pin(raw_log),
        'actual_error_excerpt': pin(excerpt),
        'actual_error_codes': [code.decode() for code in codes],
        'actual_status': {'job': packet['actual_maintenance_job'], 'fix_returncode': 101,
                          'timed_out': False, 'fmt_run': False, 'test_commands': 0,
                          'git_metadata_unchanged': True, 'unchanged_control_inputs': 24},
        'actual_inventory': inventory_pin,
        'actual_full_postimages': pin(post_raw),
        'only_actual_fix_source_change': witness_path,
        'preserved_witness_after': pin(witness_after),
        'four_before_files_match_actual_and_0c59': True,
        'source_deletions': [],
        'source_count': 15237,
        'actual_baseline_physical_tree': baseline_tree,
        'expected_successor_tree': successor_tree,
        'expected_is_not_applied': True,
        'exact_splice_counts': {'private_import': 1, 'metadata_peer': 3, 'typed_input_projection': 2},
        'projection_comparisons': mapping_records,
        'projection_limit': 'Full CellStepInput equality over the original eight Source projection fields plus an operation ID borrowed from the opaque publication. It does not independently authenticate operation ID or compare lease_duration_ms.',
        'peer_is_public_metadata': True,
        'peer_fd_uid_stream_timeout_lifetime_and_negative_assertions_outside_three_splices_unchanged': True,
        'wire_visibility_unchanged_parent_import_narrowed': True,
        'changed_files': [{k: row[k] for k in ['path', 'mode', 'before', 'after']} for row in packet['changes']],
        'method_and_assertion_preservation': 'All bytes outside the six independently reconstructed splices are equal, including cleanup, negative attacks, test attributes, owner checks and all other methods.',
        'execution': {'h': 0, 'rust': 0, 'formatter': 0, 'qa': 0, 'candidate_imports': 0,
                      'git_commands': 0, 'source_or_ref_writes': 0},
    }
    data = (json.dumps(verification, ensure_ascii=False, indent=2) + '\n').encode()
    destination = ROOT / 'FROZEN_BYTE_REVIEW.json'
    if destination.exists():
        assert destination.read_bytes() == data
    else:
        with destination.open('xb') as out:
            out.write(data)
    print(json.dumps({'output': str(destination), **pin(data), 'splices': 6,
                      'baseline_tree': baseline_tree, 'expected_tree': successor_tree}))

if __name__ == '__main__':
    main()
