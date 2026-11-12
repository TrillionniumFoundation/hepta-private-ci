import base64
import copy
import datetime
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-final-source-preparation-v2')
ACTUAL = Path('/tmp/hepta-36fa-final-nonrust-fmt-launch-v2')


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
    response = json.loads((ROOT / 'CANONICAL_COMMIT_READ.response.json').read_text())
    commit = json.loads(response['content'])
    assert commit['sha'] == '246d8cb614770252ee42029a5c014f2a4904176a'
    assert commit['tree']['sha'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    parents = [row['sha'] for row in commit['parents']]
    assert parents == ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']
    assert commit['verification']['verified'] is False and commit['verification']['reason'] == 'unsigned'
    # REST normalizes timestamps to UTC and omits the original raw timezone.
    # -0500 is present in the already recovered original parent commit. Neither
    # offset nor a terminal newline is accepted unless the whole canonical Git
    # commit hashes to the independently returned official commit identity.
    candidates = []
    trials = []
    for offset in ('+0000', '-0500'):
        headers = ['tree ' + commit['tree']['sha']] + ['parent ' + parent for parent in parents]
        headers += ['author ' + person(commit['author'], offset), 'committer ' + person(commit['committer'], offset)]
        for tail in ('', '\n'):
            raw = ('\n'.join(headers) + '\n\n' + commit['message'] + tail).encode()
            candidates.append(raw)
            trials.append({'offset': offset, 'terminal_lf': bool(tail), 'bytes': len(raw),
                           'commit_sha': oid('commit', raw), 'matches_official_identity': oid('commit', raw) == commit['sha']})
    matches = [raw for raw in candidates if oid('commit', raw) == commit['sha']]
    assert len(matches) == 1, 'Authentic raw commit identity must match; no guessed commit bytes accepted'
    commit_raw = matches[0]
    save('CANONICAL_COMMIT.raw', commit_raw)
    save('CANONICAL_COMMIT_BYTE_RECOVERY.json', (json.dumps({
        'status': 'exact_official_commit_identity_recovered',
        'metadata_source': 'CANONICAL_COMMIT_READ.response.json',
        'original_parent_raw': '/tmp/hepta-36fa-checkpoint1867-recovery/RECOVERED_PEER_CANONICAL_COMMIT.raw',
        'original_parent_commit': parents[0], 'canonical_commit': commit['sha'],
        'trials': trials, 'exact_match_count': len(matches), 'raw_bytes': pin(commit_raw),
        'limit': 'Lossless reconstruction matched the complete official Git object identity; not a new raw server read.'
    }, sort_keys=True, indent=2) + '\n').encode())
    result_raw = (ACTUAL / 'RESULT.json').read_bytes()
    result = json.loads(result_raw)
    before_raw = (ROOT / 'FINAL_DIRTY_INVENTORY.exact-recovered.json').read_bytes()
    assert pin(before_raw) == result['actual_final_source']['inventory']
    before = json.loads(before_raw)
    assert result['format_source_stable'] and not result['formatter_changed_paths']
    assert before['source']['head'] == parents[0]
    assert before['tracked_entries'] == before['filesystem_entries'] == len(before['files']) == 15188
    after = copy.deepcopy(before)
    after['source'] = {'head': commit['sha'], 'tree': commit['tree']['sha'], 'status': ''}
    for row in after['files']:
        row['index_blob'] = row['working_blob']
        row['index_mode'] = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        row['matches_index'] = True
    after_raw = encoded(after)
    after_pin = save('CANONICAL_CLEAN_INVENTORY.expected.json', after_raw)
    summary = lambda raw: {**pin(raw), 'tracked_entries': 15188, 'filesystem_entries': 15188}
    before_summary, after_summary = summary(before_raw), summary(after_raw)
    prepared = json.loads((ROOT / 'OBJECTS_PREPARED.json').read_bytes())
    objects = list(prepared['objects'])
    assert len(objects) == 61 and all(obj['sha'] != commit['sha'] for obj in objects)
    objects.append({'type': 'commit', 'sha': commit['sha'], 'bytes': len(commit_raw),
                    'sha256': hashlib.sha256(commit_raw).hexdigest(),
                    'raw_base64': base64.b64encode(commit_raw).decode()})
    for item in objects:
        raw = base64.b64decode(item['raw_base64'], validate=True)
        assert oid(item['type'], raw) == item['sha'] and len(raw) == item['bytes']
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
    git_raw = (ACTUAL / 'final.git-state.json').read_bytes()
    packet = {
        'format': 'hepta-final-canonical-source-alignment-packet-v1',
        'source_repo': '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1',
        'complete_leaf_count': 15188,
        'before': {'commit': parents[0], 'tree': before['source']['tree'],
                   'parents': ['86dd56a930277e0d1aef3e475e35c2b5d60b43b7'],
                   'inventory': before_summary, 'git_state': json.loads(git_raw)},
        'after': {'commit': commit['sha'], 'tree': commit['tree']['sha'],
                  'parents': parents, 'inventory': after_summary},
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
        'canonical_commit': commit['sha'], 'canonical_tree': commit['tree']['sha'],
        'canonical_parents': parents, 'authentic_raw_commit': {'type': 'commit', 'sha': commit['sha'], **pin(commit_raw)},
        'actual_before_inventory': before_summary, 'expected_after_inventory': after_summary,
        'expected_after_inventory_limit': 'Prediction using the unchanged original compact serializer. Native must independently produce these exact bytes after its index/HEAD operation; not an observed clean source yet.',
        'actual_final_format_result': pin(result_raw), 'actual_final_git_state': pin(git_raw),
        'packet': packet_pin, 'packet_gzip': gzip_pin, 'packet_parts': parts,
        'objects': {'total': len(objects), 'blob': 54, 'tree': 7, 'commit': 1},
        'source_branch_ref_updated': False, 'native_alignment_started': False, 'qualification': False,
    }
    save('CANONICAL_PACKET_MANIFEST.json', (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({key: value for key, value in manifest.items() if key != 'packet_parts'}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
