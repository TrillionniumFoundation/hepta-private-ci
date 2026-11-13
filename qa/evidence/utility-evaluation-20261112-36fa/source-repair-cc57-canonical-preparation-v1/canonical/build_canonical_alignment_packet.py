#!/usr/bin/env python3
"""Prepare authentic cc57 object transport and a clearly predicted clean inventory."""
import base64
import copy
import datetime
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1')
OFFICIAL = Path('/tmp/hepta-36fa-source-repair-canonical-source-v1')
DIAGNOSIS = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
ACTUAL = Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1')
OLD = '246d8cb614770252ee42029a5c014f2a4904176a'
OLD_TREE = 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
OLD_PARENTS = ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']
NEW = 'cc57c7198db6293ccca562253c42fffbe2a04633'
NEW_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': oid('blob', raw)}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def save(name, raw):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return pin(raw)


def person(value, offset):
    stamp = int(datetime.datetime.fromisoformat(value['date'].replace('Z', '+00:00')).timestamp())
    return f"{value['name']} <{value['email']}> {stamp} {offset}"


def main():
    ROOT.mkdir(exist_ok=True)
    metadata_raw = (OFFICIAL / 'CANONICAL_COMMIT_READ.original.json').read_bytes()
    response = json.loads(metadata_raw)
    commit = json.loads(response['content'])
    assert commit['sha'] == NEW and commit['tree']['sha'] == NEW_TREE
    parents = [row['sha'] for row in commit['parents']]
    assert parents == [OLD]
    assert commit['verification']['verified'] is False and commit['verification']['reason'] == 'unsigned'
    request = json.loads((OFFICIAL / 'CANONICAL_COMMIT_REQUEST.json').read_bytes())
    assert request['message'] == commit['message'] and request['parent_sha'] == OLD and request['tree_sha'] == NEW_TREE
    parent_raw = Path('/tmp/hepta-36fa-final-source-preparation-v2/CANONICAL_COMMIT.raw').read_bytes()
    assert oid('commit', parent_raw) == OLD
    assert b' -0500\n' in parent_raw and not parent_raw.endswith(b'\n')
    # The API normalizes timestamp offsets. Only a full canonical Git object hash
    # match to the already-created official commit can authenticate reconstruction.
    candidates, trials = [], []
    for offset in ('+0000', '-0500'):
        headers = ['tree ' + NEW_TREE, 'parent ' + OLD]
        headers += ['author ' + person(commit['author'], offset),
                    'committer ' + person(commit['committer'], offset)]
        for tail in ('', '\n'):
            raw = ('\n'.join(headers) + '\n\n' + commit['message'] + tail).encode()
            trials.append({'offset': offset, 'terminal_lf': bool(tail), 'bytes': len(raw),
                           'commit_sha': oid('commit', raw), 'matches_official_identity': oid('commit', raw) == NEW})
            if oid('commit', raw) == NEW:
                candidates.append(raw)
    assert len(candidates) == 1, 'No guessed commit bytes may enter transport'
    commit_raw = candidates[0]
    save('CANONICAL_COMMIT.raw', commit_raw)
    save('CANONICAL_COMMIT_BYTE_RECOVERY.json', (json.dumps({
        'status': 'exact_official_commit_identity_recovered',
        'official_metadata': pin(metadata_raw), 'official_commit': NEW,
        'original_parent_raw': pin(parent_raw), 'original_parent_commit': OLD,
        'trials': trials, 'exact_match_count': 1, 'raw_bytes': pin(commit_raw),
        'limit': 'Exact original raw commit bytes are recovered by the independent official Git commit SHA. This is not a new raw server read and creates no commit or ref.'
    }, sort_keys=True, indent=2) + '\n').encode())

    result_raw = (ACTUAL / 'RESULT.original.json').read_bytes()
    result = json.loads(result_raw)
    assert pin(result_raw) == {'bytes': 7097, 'sha256': 'f0a8fd1bb8b6b3b4aa71cf5e9a0683cb4d4e0d7b532cc0cde43bedff4244544f', 'git_blob': '6cb1b8d6af25907ca0fea5d9bd0f787062dbef94'}
    assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
    assert result['format_source_stable'] is True and result['formatter_changed_paths'] == []
    assert result['stages'][0]['execution']['returncode'] == 0 and not result['stages'][0]['execution']['timed_out']
    assert all(a['status'] == 'verified' for a in result['final_audits'])
    before_raw = (DIAGNOSIS / 'actual-finalfmt-exact-recovery/final.inventory.exact-recovered.json').read_bytes()
    assert pin(before_raw) == result['actual_final_source']['inventory']
    before = json.loads(before_raw)
    assert before['source']['head'] == OLD and before['source']['tree'] == OLD_TREE
    assert before['tracked_entries'] == before['filesystem_entries'] == len(before['files']) == 15188
    assert encoded(before) == before_raw
    after = copy.deepcopy(before)
    after['source'] = {'head': NEW, 'tree': NEW_TREE, 'status': ''}
    for row in after['files']:
        row['index_blob'] = row['working_blob']
        row['index_mode'] = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        row['matches_index'] = True
    after_raw = encoded(after)
    after_pin = save('CANONICAL_CLEAN_INVENTORY.expected.json', after_raw)
    physical_keys = ('path', 'kind', 'bytes', 'sha256', 'working_blob', 'permissions', 'stable')
    assert [{k: r[k] for k in physical_keys} for r in before['files']] == [{k: r[k] for k in physical_keys} for r in after['files']]
    summary = lambda raw: {**pin(raw), 'tracked_entries': 15188, 'filesystem_entries': 15188}
    before_summary, after_summary = summary(before_raw), summary(after_raw)

    changes = json.loads((DIAGNOSIS / 'NONRUST_APPLY_PACKET.json').read_bytes())['changes']
    tree_plan = json.loads((DIAGNOSIS / 'CANONICAL_OBJECT_TREE_PLAN.json').read_bytes())
    assert tree_plan['base_commit'] == OLD and tree_plan['expected_candidate_tree'] == NEW_TREE
    objects = []
    def add(kind, sha, raw):
        assert oid(kind, raw) == sha and all(obj['sha'] != sha for obj in objects)
        objects.append({'type': kind, 'sha': sha, 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(),
                        'raw_base64': base64.b64encode(raw).decode()})
    for change in changes:
        raw = base64.b64decode(change['after_base64'], validate=True)
        assert pin(raw) == change['after']
        add('blob', change['after']['git_blob'], raw)
    for tree in tree_plan['trees_in_dependency_order']:
        raw = base64.b64decode(tree['after']['raw_base64'], validate=True)
        assert len(raw) == tree['after']['raw_bytes'] and hashlib.sha256(raw).hexdigest() == tree['after']['raw_sha256']
        add('tree', tree['after']['sha'], raw)
    add('commit', NEW, commit_raw)
    assert len(objects) == 10
    assert [sum(obj['type'] == kind for obj in objects) for kind in ('blob', 'tree', 'commit')] == [5, 4, 1]

    artifacts_raw = (ACTUAL / 'ARTIFACTS.original.json').read_bytes()
    artifacts = json.loads(artifacts_raw)
    git_raw = (ACTUAL / 'final.git-state.json').read_bytes()
    git_record = next(row for row in artifacts['files'] if row['name'] == 'final.git-state.json')
    assert pin(git_raw) == {k: git_record[k] for k in ('bytes', 'sha256', 'git_blob')}
    assert git_raw == (ACTUAL / 'SOURCE_GIT_STATE.before.original.json').read_bytes()
    git_state = json.loads(git_raw)
    assert git_state['head'] == OLD and git_state['tree'] == OLD_TREE
    packet = {
        'format': 'hepta-final-canonical-source-alignment-packet-v1',
        'source_repo': '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1',
        'complete_leaf_count': 15188,
        'before': {'commit': OLD, 'tree': OLD_TREE, 'parents': OLD_PARENTS,
                   'inventory': before_summary, 'git_state': git_state},
        'after': {'commit': NEW, 'tree': NEW_TREE, 'parents': [OLD], 'inventory': after_summary},
        'objects': objects,
    }
    packet_raw = encoded(packet)
    packet_pin = save('CANONICAL_PACKET.json', packet_raw)
    compressed = gzip.compress(packet_raw, mtime=0)
    gzip_pin = save('CANONICAL_PACKET.json.gz', compressed)
    parts = []
    for number, offset in enumerate(range(0, len(compressed), 196605), 1):
        body = compressed[offset:offset + 196605]
        transport = base64.b64encode(body) + b'\n'
        name = f'CANONICAL_PACKET.json.gz.part{number:03d}.b64'
        parts.append({'path': name, 'gzip_offset': offset, 'decoded': pin(body), 'encoded': save(name, transport)})
    manifest = {
        'format': 'hepta-canonical-alignment-packet-manifest-v1',
        'status': 'authentic_commit_and_packet_prepared_native_alignment_not_started',
        'canonical_commit': NEW, 'canonical_tree': NEW_TREE, 'canonical_parents': [OLD],
        'authentic_raw_commit': {'type': 'commit', 'sha': NEW, **pin(commit_raw)},
        'actual_before_inventory': before_summary, 'expected_after_inventory': after_summary,
        'expected_after_inventory_limit': 'Prediction using the unchanged original compact serializer. Native must independently produce these exact bytes after its index/HEAD operation; no observed clean cc57 source is claimed.',
        'actual_final_format_result': pin(result_raw), 'actual_final_git_state': pin(git_raw),
        'original_artifact_manifest': pin(artifacts_raw),
        'packet': packet_pin, 'packet_gzip': gzip_pin, 'packet_parts': parts,
        'objects': {'total': 10, 'blob': 5, 'tree': 4, 'commit': 1},
        'source_branch_ref_updated': False, 'native_alignment_started': False, 'qualification': False,
        'physical_source_bytes_and_modes_unchanged_in_projection': True,
    }
    save('CANONICAL_PACKET_MANIFEST.json', (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({key: value for key, value in manifest.items() if key != 'packet_parts'}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
