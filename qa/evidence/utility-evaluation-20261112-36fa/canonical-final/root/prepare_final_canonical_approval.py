import base64
import collections
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-after2268-20261112')
PREP = Path('/tmp/hepta-36fa-final-source-preparation-v2')
PLAN = Path('/tmp/hepta-36fa-final-canonical-alignment-plan-v1')
ACTUAL = Path('/tmp/hepta-36fa-final-nonrust-fmt-launch-v2')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def commit_oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def read(directory, name):
    raw = (directory / name).read_bytes()
    return raw, json.loads(raw)


def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    p = ROOT / name
    if p.exists():
        assert p.read_bytes() == raw, name
    else:
        p.write_bytes(raw)
    return identity(raw)


def main():
    manifest_raw, manifest = read(PREP, 'CANONICAL_PACKET_MANIFEST.json')
    packet_raw, packet = read(PREP, 'CANONICAL_PACKET.json')
    assert identity(packet_raw) == manifest['packet']
    assert collections.Counter(x['type'] for x in packet['objects']) == {'blob': 54, 'tree': 7, 'commit': 1}
    seen = set()
    for row in packet['objects']:
        raw = base64.b64decode(row['raw_base64'], validate=True)
        assert row['sha'] not in seen
        seen.add(row['sha'])
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
        assert commit_oid(row['type'], raw) == row['sha']
    raw_commit = (PREP / 'CANONICAL_COMMIT.raw').read_bytes()
    assert commit_oid('commit', raw_commit) == manifest['canonical_commit'] == '246d8cb614770252ee42029a5c014f2a4904176a'
    commit_read = json.loads(read(PREP, 'CANONICAL_COMMIT_READ.response.json')[1]['content'])
    assert commit_read['sha'] == manifest['canonical_commit']
    assert commit_read['tree']['sha'] == manifest['canonical_tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    assert [x['sha'] for x in commit_read['parents']] == manifest['canonical_parents']
    result_raw, result = read(ACTUAL, 'RESULT.json')
    normal_raw, normal_envelope = read(ACTUAL, 'STATUS_RETRY01.original.json')
    assert normal_envelope['isError'] is False and len(normal_envelope['content']) == 1
    normal = json.loads(normal_envelope['content'][0]['text'])
    assert normal['job_id'] == '1a1d1cb5f1a-2564-1c7c'
    assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
    for key in ('timed_out', 'cancelled', 'automatic_retry'):
        assert normal[key] is False
    for key in ('output_complete', 'output_durable', 'terminal_publication_confirmed'):
        assert normal[key] is True
    assert not any(normal['log_truncated'].values())
    assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
    assert result['format_source_stable'] and result['formatter_changed_paths'] == []
    assert result['attempted_commands'] == ['fmt'] and result['not_run_commands'] == []
    assert {x['check']: x['status'] for x in result['final_audits']} == {
        'actual_complete_source_and_git': 'verified', 'original_inputs': 'verified',
        'same_source_coordination_lock': 'verified'}
    assert manifest['actual_final_format_result'] == identity(result_raw)
    before_raw, before = read(PREP, 'FINAL_DIRTY_INVENTORY.exact-recovered.json')
    after_raw, after = read(PREP, 'CANONICAL_CLEAN_INVENTORY.expected.json')
    assert identity(before_raw) == result['actual_final_source']['inventory']
    for value in (before, after):
        assert value['tracked_entries'] == value['filesystem_entries'] == len(value['files']) == 15188
    for old, new in zip(before['files'], after['files']):
        assert {k:v for k,v in old.items() if k not in ('index_blob','index_mode','matches_index')} == {
            k:v for k,v in new.items() if k not in ('index_blob','index_mode','matches_index')}
        assert new['index_blob'] == new['working_blob'] and new['matches_index'] is True
        assert new['index_mode'] == ('120000' if new['kind'] == 'symlink' else ('100755' if new['permissions'] & 0o111 else '100644'))
    assert after['source'] == {'head': manifest['canonical_commit'], 'tree': manifest['canonical_tree'], 'status': ''}
    git_raw, git_state = read(ACTUAL, 'final.git-state.json')
    cfg = read(PLAN, 'WAITING_CONFIG.json')[1]
    driver_raw = (PLAN / 'driver.HOLD.py').read_bytes()
    assert identity(driver_raw) == cfg['driver']
    peer_path = Path('/tmp/hepta-36fa-canonical-alignment-peer-review-v1/REVIEW.json')
    peer_raw = peer_path.read_bytes()
    assert identity(peer_raw)['git_blob'] == '4dd84b7e67d3112150212e80e5dfe221e1d6fa4e'
    actual_root_path = ROOT / 'ROOT_ACTUAL_FINAL_FMT_COMPLETION_REVIEW.json'
    actual_root_raw = actual_root_path.read_bytes()
    assert identity(actual_root_raw)['git_blob'] == '17a0b6bbfb5c807481efc78e13565d1e43e42507'
    native_actual = '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/final-nonrust-fmt-v2'
    cfg.update({
        'status': 'ROOT_APPROVED_FOR_ONE_CANONICAL_ALIGNMENT',
        'root_execution_approved': True,
        'actual_final_postimages_reviewed': True,
        'reviewed_formatter_changed_paths': [],
        'after_commit': manifest['canonical_commit'], 'after_tree': manifest['canonical_tree'],
        'after_parents': manifest['canonical_parents'],
        'before_inventory': manifest['actual_before_inventory'],
        'after_inventory': manifest['expected_after_inventory'],
        'canonical_object_count': len(packet['objects']),
        'canonical_packet': manifest['packet'],
        'expected_before_git_state': git_state,
        'final_format': {
            'job_id': normal['job_id'],
            'result_path': native_actual + '/RESULT.json', 'result': identity(result_raw),
            'supervisor_path': cfg['control_dir'] + '/FINAL_FORMAT_NORMAL.original.json',
            'supervisor': identity(normal_raw),
            'git_state_path': native_actual + '/final.git-state.json', 'git_state': identity(git_raw),
        },
    })
    assert packet['before'] == {'commit': cfg['before_commit'], 'tree': cfg['before_tree'],
                               'parents': cfg['before_parents'], 'inventory': cfg['before_inventory'],
                               'git_state': cfg['expected_before_git_state']}
    assert packet['after'] == {'commit': cfg['after_commit'], 'tree': cfg['after_tree'],
                              'parents': cfg['after_parents'], 'inventory': cfg['after_inventory']}
    cfg_pin = save('APPROVED_FINAL_CANONICAL_ALIGNMENT_CONFIG.json', cfg)
    review = {
        'format': 'hepta-root-final-canonical-alignment-input-approval-v1',
        'status': 'INPUTS_APPROVED_EXACT_LAUNCH_REVIEW_STILL_REQUIRED',
        'config': cfg_pin, 'driver': cfg['driver'], 'canonical_packet': manifest['packet'],
        'canonical_packet_manifest': identity(manifest_raw),
        'canonical_commit': cfg['after_commit'], 'canonical_tree': cfg['after_tree'],
        'canonical_parents': cfg['after_parents'], 'canonical_objects': manifest['objects'],
        'actual_final_format_review': identity(actual_root_raw),
        'actual_final_format': cfg['final_format'],
        'before_inventory': cfg['before_inventory'], 'expected_after_inventory': cfg['after_inventory'],
        'expected_after_inventory_limit': manifest['expected_after_inventory_limit'],
        'independent_driver_peer_review': identity(peer_raw),
        'reviewed_invariants': [
            'All62 provided raw objects match exact type, length, SHA256 and Git object identity; canonical commit matches the actual server-issued commit and sole parent.',
            'Actual complete15188 physical inventory and successful original final formatter are bound; all11 applied after-images previously reviewed; formatter changed zero source paths.',
            'Existing driver765ada remains byte-for-byte unchanged; original action600/record180/outer900 and actual shared source EX lock/same-UID build guard remain unchanged.',
            'Only exact missing canonical Git objects, an explicit whole-index tree/stat transition and detached HEAD CAS are authorized; physical source files, config, branch refs and existing objects must remain unchanged.',
            'The entire physical tree must equal the canonical snapshot before index/HEAD writes; complete raw Git metadata and complete index flags/stat/checksum/cache-tree are audited.',
            'Expected clean inventory is only a deterministic projection until native independently observes the exact full original-serializer bytes.',
            'Any failure preserves partial original state without rollback, automatic retry or status promotion.',
        ],
        'source_branch_ref_updated': False, 'native_alignment_started': False,
        'qualification': False, 'real_qualified_task_chain_results': 0,
        'next_required': 'Freeze the exact four-file bootstrap and seven-field900-second launch; Root reviews those exact bytes before a single native request.',
    }
    review_pin = save('ROOT_FINAL_CANONICAL_INPUT_APPROVAL.json', review)
    print(json.dumps({'config': cfg_pin, 'input_approval': review_pin}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
