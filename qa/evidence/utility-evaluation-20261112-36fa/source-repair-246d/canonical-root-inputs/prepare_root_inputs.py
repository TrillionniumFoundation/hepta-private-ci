"""Bind the actual formatted source to one exact canonical alignment request."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-v1')
PACK = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1')
FMT = Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1')
PROPOSAL = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
SOURCE = Path('/tmp/hepta-36fa-source-repair-canonical-source-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def jbytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def main():
    original_cfg = json.loads(Path('/tmp/hepta-36fa-after2268-20261112/APPROVED_FINAL_CANONICAL_ALIGNMENT_CONFIG.json').read_text())
    packet_raw = (PACK / 'CANONICAL_PACKET.json').read_bytes()
    packet = json.loads(packet_raw)
    dirty = (PROPOSAL / 'actual-finalfmt-exact-recovery/final.inventory.exact-recovered.json').read_bytes()
    expected_clean = (PACK / 'CANONICAL_CLEAN_INVENTORY.expected.json').read_bytes()
    result_raw = (FMT / 'RESULT.original.json').read_bytes()
    result = json.loads(result_raw)
    git_raw = (FMT / 'final.git-state.json').read_bytes()
    normal_raw = (FMT / 'STATUS_01.original.json').read_bytes()
    normal = json.loads(json.loads(normal_raw)['content'][0]['text'])
    before, after = packet['before'], packet['after']
    assert packet['format'] == 'hepta-final-canonical-source-alignment-packet-v1'
    assert before['commit'] == '246d8cb614770252ee42029a5c014f2a4904176a'
    assert before['tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    assert before['parents'] == ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']
    assert after['commit'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
    assert after['tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e' and after['parents'] == [before['commit']]
    assert pin(dirty) == result['actual_final_source']['inventory']
    assert {key: before['inventory'][key] for key in pin(dirty)} == pin(dirty)
    assert before['git_state'] == json.loads(git_raw)
    assert normal['job_id'] == '1a1d2107dce-2564-1c98' and normal['state'] == 'succeeded' and normal['exit_code'] == 0
    assert normal['output_complete'] and normal['output_durable'] and not normal['timed_out']
    assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED' and result['formatter_changed_paths'] == []
    assert result['actual_final_source']['postimages']['all_actual_physical_tree'] == after['tree']
    assert all(row['status'] == 'verified' for row in result['final_audits']) and result['git_metadata_unchanged']
    predicted = copy.deepcopy(json.loads(dirty))
    predicted['source'] = {'head': after['commit'], 'tree': after['tree'], 'status': ''}
    for row in predicted['files']:
        row['index_blob'] = row['working_blob']
        row['matches_index'] = True
    assert jbytes(predicted) == expected_clean
    assert {key: after['inventory'][key] for key in pin(expected_clean)} == pin(expected_clean)
    assert all(endpoint['inventory']['tracked_entries'] == endpoint['inventory']['filesystem_entries'] == 15188
               for endpoint in [before, after])

    expected_objects = {}
    application = json.loads((PROPOSAL / 'NONRUST_APPLY_PACKET.json').read_text())
    for change in application['changes']:
        raw = base64.b64decode(change['after_base64'], validate=True)
        expected_objects[change['after']['git_blob']] = ('blob', raw)
    for path in SOURCE.glob('*.TREE_READ.original.json'):
        tree = json.loads(json.loads(path.read_text())['content'])
        entries = sorted(tree['tree'], key=lambda row: (row['path'] + ('/' if row['type'] == 'tree' else '')).encode())
        raw = b''.join(('40000' if row['mode'] == '040000' else row['mode']).encode() + b' ' + row['path'].encode() + b'\0' + bytes.fromhex(row['sha']) for row in entries)
        assert oid('tree', raw) == tree['sha'] and tree['truncated'] is False
        expected_objects[tree['sha']] = ('tree', raw)
    commit_raw = (PACK / 'CANONICAL_COMMIT.raw').read_bytes()
    assert oid('commit', commit_raw) == after['commit']
    actual_commit = json.loads(json.loads((SOURCE / 'CANONICAL_COMMIT_READ.original.json').read_text())['content'])
    assert actual_commit['sha'] == after['commit'] and actual_commit['tree']['sha'] == after['tree']
    assert [row['sha'] for row in actual_commit['parents']] == after['parents']
    expected_objects[after['commit']] = ('commit', commit_raw)
    assert len(expected_objects) == len(packet['objects']) == 10
    observed = {}
    for row in packet['objects']:
        raw = base64.b64decode(row['raw_base64'], validate=True)
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'] and oid(row['type'], raw) == row['sha']
        assert row['sha'] not in observed
        observed[row['sha']] = (row['type'], raw)
    assert observed == expected_objects
    driver = (OUT / 'driver.HOLD.py').read_bytes()
    assert pin(driver)['git_blob'] == '4952e13c052d9e83d448d09897ff9c09c31552c5'
    ast.parse(driver)
    cfg = copy.deepcopy(original_cfg)
    native_control = '/home/qian-qi/hepta-utility-36fa-evidence/source-repair-canonical-alignment-v1'
    native_fmt = '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/source-repair-246d-fmt-v1'
    cfg.update(before_commit=before['commit'], before_tree=before['tree'], before_parents=before['parents'],
               before_inventory=before['inventory'], expected_before_git_state=before['git_state'],
               after_commit=after['commit'], after_tree=after['tree'], after_parents=after['parents'],
               after_inventory=after['inventory'], driver=pin(driver), canonical_packet=pin(packet_raw),
               canonical_object_count=10, control_dir=native_control, output_dir=native_control + '/run',
               final_format={'job_id': normal['job_id'], 'result': pin(result_raw), 'result_path': native_fmt + '/RESULT.json',
                             'git_state': pin(git_raw), 'git_state_path': native_fmt + '/final.git-state.json',
                             'supervisor': pin(normal_raw), 'supervisor_path': native_control + '/FINAL_FORMAT_NORMAL.original.json'})
    for key in ['physical_source_writes_authorized', 'cargo_or_formatter_authorized', 'test_commands_authorized',
                'remote_ref_updates_authorized', 'dependency_installation_authorized']:
        assert cfg[key] is False
    assert (cfg['action_seconds'], cfg['record_seconds'], cfg['outer_seconds']) == (600, 180, 900)
    cfg_raw = (json.dumps(cfg, sort_keys=True, indent=2) + '\n').encode()
    (OUT / 'APPROVED_CONFIG.json').write_bytes(cfg_raw)
    review = {'format': 'hepta-root-source-repair-canonical-input-approval-v1',
              'decision': 'APPROVED_INPUTS_PENDING_EXACT_TYPED_LAUNCH', 'driver': pin(driver), 'config': pin(cfg_raw),
              'canonical_packet': pin(packet_raw), 'before': before, 'after_expected_only': after,
              'canonical_objects': {'blobs': 5, 'trees': 4, 'commit': 1, 'all_exact_reconstructed_and_verified': True},
              'actual_fmt_result': pin(result_raw), 'actual_fmt_normal': pin(normal_raw), 'actual_fmt_Git_state': pin(git_raw),
              'actual_fmt_postimage_review': '109785d5727862cbb05d665e65b444b761e1c837',
              'dirty_inventory_exact_recovered_from_actual_pins': True, 'clean_inventory_is_expected_not_yet_observed': True,
              'clean_projection_only_changes_source_identity_and_index_bindings': True,
              'all_46_functions_byte_identical_to_original_canonical_driver': True,
              'only_four_driver_constants_changed': ['CONTROL', 'OLD', 'OLD_TREE', 'OLD_PARENTS'],
              'scope': 'Import exact ten immutable objects, verify both complete snapshots, align index and detached HEAD by expected-old CAS. Physical source bytes/modes and source branch refs stay outside mutation scope.',
              'budgets_seconds': {'action': 600, 'record': 180, 'outer': 900},
              'full_metadata_and_object_scope_audits_preserved': True, 'same_EX_lock_and_global_active_build_guard_preserved': True,
              'automatic_retry_or_rollback_authorized': False, 'source_ref_updated': False,
              'native_alignment_already_executed': False, 'qualification': False, 'real_qualified_task_chains': 0}
    (OUT / 'ROOT_INPUT_APPROVAL.json').write_text(json.dumps(review, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'config': pin(cfg_raw), 'approval': pin((OUT / 'ROOT_INPUT_APPROVAL.json').read_bytes()),
                      'packet': pin(packet_raw), 'before_inventory': before['inventory'],
                      'expected_after_inventory': after['inventory'], 'object_count': 10}, indent=2))


if __name__ == '__main__':
    main()
