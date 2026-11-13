import base64
import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
N = Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-format-runtime-v1')
X = Path('/tmp/hepta-36fa-a489-final-nonrust-exact-recovery-v1')
F = Path('/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1')
P = Path('/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1')
OLD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
TREE = '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
JOB = '1a1d4a979d9-392-50f'
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def three(row):
    return {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}

def read(path, sha=None):
    raw = Path(path).read_bytes()
    if sha is not None:
        assert pin(raw)['git_blob'] == sha, str(path)
    return raw

def obj(path, sha=None):
    return json.loads(read(path, sha))

def unwrap(value):
    if isinstance(value, dict) and 'content' in value:
        assert value.get('isError') is not True
        items = [c['text'] for c in value['content'] if c.get('type') == 'text']
        assert len(items) == 1
        return json.loads(items[0])
    return value

def sdk(name):
    return unwrap(obj(N / name))

def tree_hash(rows):
    root = {}
    for row in rows:
        node = root
        parts = row['path'].split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (row['mode'], row['git_blob'])
    def walk(node):
        entries = []
        for name, item in node.items():
            mode, sha = ('40000', walk(item)) if isinstance(item, dict) else item
            entries.append((name, mode, sha))
        entries.sort(key=lambda e: (e[0] + ('/' if e[1] == '40000' else '')).encode())
        raw = b''.join(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
                       for name, mode, sha in entries)
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return walk(root)

native_review = obj(N / 'ACTUAL_RUNTIME_READBACK_REVIEW.json', '8bbab678f620fa87da2370b909cc1a6f587319c9')
result_raw = read(N / 'RESULT.json', '800869ed57256984964dd3c8b9f29e09c496438a')
result = json.loads(result_raw)
artifacts_raw = read(N / 'ARTIFACTS.json', '0119bbc670ec82b93b5235d9e512f61f58baf409')
artifacts = json.loads(artifacts_raw)
amap = {x['name']: x for x in artifacts['files']}
assert len(amap) == len(artifacts['files']) == 210
normal_raw = read(N / 'STATUS_02.original.json', '0f7aee8fb7c354f234732b5791e78d63671cd894')
normal = unwrap(json.loads(normal_raw))
request_raw = read(N / 'ACTUAL_PROCESS_INPUT.original.json', '9ca09c7e486277f72669173c649290d2124d794e')
request = json.loads(request_raw)
approval_raw = read(R / 'ROOT_FINAL_NONRUST_FORMAT_EXACT_APPROVAL.json', '355674e5538e91757ea50b7264315eed426460f0')
assert native_review['engineering_approval'] == pin(approval_raw)
assert native_review['request'] == pin(request_raw)
admission = sdk('MAIN_ADMISSION.original.json')
assert admission['audit_recorded'] and not admission['local_record_pending'] and not admission['reused']
assert admission['launch']['ok'] is True and admission['job']['id'] == JOB
assert admission['job']['env_keys'] == [] and admission['job']['launch_state'] == 'launched'
for key in ('args', 'cwd', 'executable', 'host', 'idempotency_key'):
    assert admission['job'][key] == request[key], key
assert request['timeout_seconds'] == 2100
assert normal['job_id'] == JOB and normal['state'] == 'succeeded' and normal['exit_code'] == 0
for key in ('audit_recorded', 'output_complete', 'output_durable', 'terminal_publication_confirmed'):
    assert normal[key] is True, key
for key in ('automatic_retry', 'cancelled', 'timed_out'):
    assert normal[key] is False, key
for stream in ('stdout', 'stderr'):
    assert normal['log_errors'][stream] is None and normal['log_synced'][stream] is True
    assert normal['log_truncated'][stream] is False

# Replay every original binary-read receipt, retaining Python integer precision.
groups = defaultdict(list)
sdk_files = sorted(p for p in N.iterdir() if re.fullmatch(r'.+\.READ_[0-9]{2}\.original\.json', p.name))
assert len(sdk_files) == 49
for path in sdk_files:
    observation = unwrap(json.loads(path.read_bytes()))
    block = base64.b64decode(observation['data_base64'], validate=True)
    assert hashlib.sha256(block).hexdigest() == observation['chunk_sha256']
    assert observation['next_offset'] == observation['offset'] + len(block)
    assert observation['path'].startswith(CONTROL + '/')
    groups[observation['path']].append((observation, block, path))
assert len(groups) == 46
review_paths = {v['native_path']: v for v in native_review['native_reads']}
assert set(groups) == set(review_paths)
read_rows = []
for native_path, chunks in sorted(groups.items()):
    chunks.sort(key=lambda v: v[0]['offset'])
    cursor = 0
    version, size = chunks[0][0]['version'], chunks[0][0]['size']
    body = bytearray()
    receipt_pins = []
    for i, (observation, block, path) in enumerate(chunks):
        assert observation['offset'] == cursor and observation['version'] == version and observation['size'] == size
        cursor = observation['next_offset']
        assert observation['eof'] is (i == len(chunks) - 1)
        body.extend(block)
        receipt_pins.append({'name': path.name, **pin(path.read_bytes())})
    body = bytes(body)
    assert cursor == size == len(body)
    row = review_paths[native_path]
    assert pin(body) == three(row) and version == row['version']
    assert body == read(N / row['local_name'])
    expected_sdks = {v['sdk']: v['sdk_identity'] for v in row['observations']}
    assert expected_sdks == {p['name']: three(p) for p in receipt_pins}
    artifact_name = native_path.removeprefix(CONTROL + '/run/')
    if artifact_name in amap:
        assert pin(body) == three(amap[artifact_name])
    read_rows.append({'native_path': native_path, 'local_name': row['local_name'],
                      **pin(body), 'version': version, 'original_receipts': receipt_pins})

stream = sdk('STREAM_01.original.json')
assert stream['audit_recorded'] is True and stream['job_id'] == JOB
stream_pins = {}
for name, expected_size in [('stdout', 1298), ('stderr', 0)]:
    s = stream[name]
    raw = bytes.fromhex(s['bytes_hex'])
    assert raw.decode('utf-8') == s['text']
    assert s['offset'] == 0 and s['next_offset'] == s['size'] == len(raw) == expected_size and s['eof'] is True
    assert normal['log_bytes'][name] == {'seen': expected_size, 'stored': expected_size}
    assert raw == read(N / (name.upper() + '.complete.original.txt'))
    stream_pins[name] = pin(raw)

assert result['source_commit'] == OLD and result['source_tree'] == 'a489b394666b8141840275128a780605b024cde0'
assert result['source_repo'] == '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
assert result['parents'] == ['cc57c7198db6293ccca562253c42fffbe2a04633']
assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
assert result['attempted_commands'] == ['fmt'] and result['not_run_commands'] == []
assert result['test_commands_dispatched'] == 0
for key in ('fix_dispatched', 'automatic_retry', 'source_ref_updates', 'qualification', 'requires_fence_refresh_review'):
    assert result[key] is False, key
assert result['format_source_stable'] and result['nonrust_application_complete'] and result['git_metadata_unchanged']
assert result['formatter_changed_paths'] == []
assert len(result['stages']) == 1
stage = result['stages'][0]
assert stage == obj(N / 'fmt.terminal.json', '1d12f8870768081a3f35c32aaa9daab61e68a788')
assert stage['argv'] == ['just', 'fmt', '--base', 'c0f78493f815780f68b9bf5e390a21314d79311f']
assert stage['timeout_seconds'] == 900 and stage['execution_outcome'] == 'completed' and stage['command_returned']
execution = obj(N / 'fmt.execute_logged.original.json')
assert execution == stage['execution']
assert execution == {'log_bytes': 0, 'log_sha256': hashlib.sha256(b'').hexdigest(), 'observed_failed_tests': 0,
                     'observed_passed_tests': 0, 'output_limit_exceeded': False, 'returncode': 0, 'timed_out': False}
assert read(N / 'fmt.raw.log') == b''
audits = result['final_audits']
assert [a['check'] for a in audits] == ['actual_complete_source_and_git', 'original_inputs', 'same_source_coordination_lock']
assert all(a['status'] == 'verified' for a in audits)
assert audits[0]['git_metadata_unchanged'] and audits[1]['unchanged'] and audits[1]['input_count'] == 28
assert len(obj(N / 'INPUT_IDENTITIES.json')) == 28
commands = obj(N / 'READONLY_COMMANDS.json')
assert len(commands) == 38 and all(c['returncode'] == 0 and c['purpose'] == 'read-only preflight/evidence' for c in commands)
state_names = ['SOURCE_GIT_STATE.before.json', 'apply.after.git-state.json', 'fmt.after.git-state.json', 'final.git-state.json']
states = [read(N / n, 'aef9e645b81c2a7f349b11d546c5555b1475c906') for n in state_names]
assert len(set(states)) == 1
metadata = [read(N / ('SOURCE_GIT_METADATA.' + suffix + '.json'), '42e3986f6a5f06d8518067f0d9dd2ec3e6b46c6a') for suffix in ['before', 'after']]
assert metadata[0] == metadata[1]
for suffix, raw in zip(['before', 'after'], metadata):
    assert gzip.decompress(read(N / ('SOURCE_GIT_METADATA.' + suffix + '.json.gz'))) == raw
ex = obj(N / 'SOURCE_COORDINATION_EX.json', '005c63fedcccb60696d1c4845d9baebd3672bb71')
assert (ex['device'], ex['inode'], ex['uid'], ex['mode'], ex['nlink']) == (2050, 50139448, 1000, 384, 1)
assert ex['lock_acquired'] == 'LOCK_EX|LOCK_NB'

# Independent byte replay of all five large alias groups against actual producer receipts.
manifest = obj(X / 'MANIFEST.json', '4190771ba8365cf7b66e573452f33625ddd0e8da')
assert len(manifest['all_alias_record_proofs']) == 5
part_count = 0
distinct_parts = set()
large_rows = []
for group in manifest['all_alias_record_proofs']:
    chunks = []
    for part in group['parts']:
        raw = read(X / part['name'])
        assert pin(raw) == three(part) == three(amap[part['name']])
        assert raw.endswith(b'\n') and b'\n' not in raw[:-1]
        block = base64.b64decode(raw[:-1], validate=True)
        assert len(block) == part['decoded_bytes'] and hashlib.sha256(block).hexdigest() == part['decoded_sha256']
        assert sum(map(len, chunks)) == part['decoded_offset']
        chunks.append(block)
        distinct_parts.add(part['git_blob'])
        part_count += 1
    packed = b''.join(chunks)
    assert pin(packed) == group['gzip'] == three(amap[group['name']])
    raw = gzip.decompress(packed)
    raw_name = group['name'].removesuffix('.gz')
    assert pin(raw) == group['raw'] == three(amap[raw_name])
    recovered = 'final.inventory.exact_recovered.json' if raw_name.endswith('inventory.json') else raw_name.replace('.json', '.exact_recovered.json')
    assert raw == read(X / recovered)
    large_rows.append({'producer_name': raw_name, 'recovered_name': recovered, **pin(raw), 'gzip': pin(packed), 'original_parts': len(chunks)})
assert (part_count, len(distinct_parts)) == (23, 10)

before_raw = read('/tmp/hepta-36fa-a489-maintenance-actual-inventory-recovery-v1/final.inventory.exact_recovered.json', '4a77b645fd76a980ef746997efbd09fcd8f233ba')
after_raw = read(X / 'final.inventory.exact_recovered.json', 'e3ce3d7bba028e29efca751c6f43fde124b05ea0')
assert after_raw == read(F / 'EXPECTED_AFTER_INVENTORY.json')
before, after = json.loads(before_raw), json.loads(after_raw)
assert len(before['files']) == len(after['files']) == before['tracked_entries'] == after['tracked_entries'] == after['filesystem_entries'] == 15243
bm, fm = ({r['path']: r for r in v['files']} for v in [before, after])
assert len(bm) == len(fm) == 15243 and set(bm) == set(fm)
changed = sorted(p for p in bm if bm[p] != fm[p])
strict = obj(P / 'NONRUST_PACKET.json', 'ab032ffdfd8b540a0d3a82558d8a07e70ab0c548')
proposal = obj(F / 'SOURCE_PACKET.json', 'b3490071b2b109aa1854afd3353952890b8e0eab')
sm = {c['path']: c for c in strict['changes']}
pm = {c['path']: c for c in proposal['changes']}
assert changed == sorted(sm) == sorted(pm) == result['applied_paths'] and len(changed) == 4
for name, expected_stage in [('apply.after.postimages.exact_recovered.json', 'apply.after'), ('final.postimages.exact_recovered.json', 'final')]:
    transition = obj(X / name)
    assert transition['base_inventory_sha256'] == pin(before_raw)['sha256']
    assert transition['after_inventory_sha256'] == pin(after_raw)['sha256']
    assert transition['source_commit_unchanged'] == OLD and transition['stage'] == expected_stage
    assert transition['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True and transition['qualification'] is False
    assert [c['path'] for c in transition['changes']] == changed
    for c in transition['changes']:
        p = c['path']
        assert c['before'] == bm[p] == pm[p]['before'] and c['after'] == fm[p] == pm[p]['after']
        for side in ['before', 'after']:
            raw = base64.b64decode(c[side + '_raw_base64'], validate=True)
            row = c[side]
            assert pin(raw) == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
            assert pin(raw) == sm[p][side]
            if side == 'after':
                assert raw == base64.b64decode(sm[p]['after_base64'], validate=True)
for i, path in enumerate(changed, 1):
    attempt = obj(N / ('APPLY.%03d.attempt.json' % i))
    complete = obj(N / ('APPLY.%03d.completed.json' % i))
    temporary = obj(N / ('APPLY.%03d.temporary.json' % i))
    assert attempt['path'] == complete['path'] == temporary['source'] == path
    assert attempt['before'] == sm[path]['before'] and attempt['after'] == complete['after'] == sm[path]['after']
    assert attempt['status'] == 'attempted' and attempt['rollback'] is False and complete['status'] == 'observed_complete'

empty_raw = read(N / 'fmt.after.postimages.json', 'f5c7643422eecfcde833cffc4cb61004f4f682ea')
empty = json.loads(empty_raw)
assert empty['changes'] == [] and empty['base_inventory_sha256'] == empty['after_inventory_sha256'] == pin(after_raw)['sha256']
assert gzip.decompress(read(N / 'fmt.after.postimages.json.gz')) == empty_raw
assert base64.b64decode(read(N / 'fmt.after.postimages.json.gz.part-001.b64').strip(), validate=True) == read(N / 'fmt.after.postimages.json.gz')
rows = []
for row in after['files']:
    assert row['stable'] is True and row['kind'] in ['file', 'symlink']
    mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
    rows.append({'path': row['path'], 'kind': row['kind'], 'mode': mode, 'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']})
assert rows == obj(R / 'PROPOSED_NONRUST_8EBB_GRAPH.json')['files']
assert tree_hash(rows) == TREE
assert sum(not row['matches_index'] for row in after['files']) == len(after['source']['status'].splitlines()) == 21
assert result['actual_final_source']['inventory'] == pin(after_raw)
assert result['actual_final_source']['postimages']['all_actual_physical_tree'] == TREE

report = {
    'format': 'hepta-root-actual-50f-source-and-runtime-closure-v1',
    'status': 'ACTUAL_FOUR_APPLICATIONS_AND_ORIGINAL_FMT_COMPLETE',
    'engineering_approval': pin(approval_raw), 'request': pin(request_raw), 'job_id': JOB,
    'admission': pin(read(N / 'MAIN_ADMISSION.original.json')), 'normal': pin(normal_raw),
    'result': pin(result_raw), 'producer_artifacts': pin(artifacts_raw), 'producer_artifact_count': 210,
    'native_review': pin(read(N / 'ACTUAL_RUNTIME_READBACK_REVIEW.json')),
    'original_read_sdk_count': len(sdk_files), 'complete_actual_native_paths': read_rows,
    'streams': stream_pins, 'readonly_commands_returned_zero': 38, 'final_input_identities': 28,
    'actual_final_audits': audits, 'four_git_state_paths_fullbytes_equal': {'paths': state_names, **pin(states[0])},
    'two_metadata_paths_fullbytes_equal': pin(metadata[0]), 'native_integer_handling': 'Only Python integers; original raw bytes retained.',
    'large_alias_records': large_rows, 'original_alias_parts': part_count, 'distinct_part_bodies': len(distinct_parts),
    'large_recovery_provenance': 'Exact offline reconstruction from already held complete source bytes, checked against actual producer raw/gzip/all-part pins. Not a second H whole-file read.',
    'before_inventory': pin(before_raw), 'after_inventory': pin(after_raw), 'unchanged_inventory_rows': 15239,
    'actual_applied_paths': changed, 'actual_formatter_changed_paths': [], 'actual_physical_tree': TREE,
    'complete_source_leaves': 15243, 'actual_dirty_paths_count': 21, 'source_head_unchanged': OLD,
    'source_index_tree_unchanged': 'a489b394666b8141840275128a780605b024cde0',
    'proposal_and_strict_packet_complete_rows_and_raws_equal': True,
    'source_semantic_review_repeated': False, 'prior_source_semantic_peer': '7dce432cbecd7b349db5e8599a8e1c58a0b7f4bf',
    'new_H_calls': 0, 'new_source_or_ref_writes': 0, 'qualification': False, 'real_qualified_chains': 0,
    'not_observed': ['canonical alignment', 'source gates', 'native qualification', 'real authorized task/evaluation/consumer/process-cold chain'],
    'local_observer_notes': ['An earlier read-only directory inspection requested fmt.execute.json; actual original name is fmt.execute_logged.original.json. No H/source action or replacement execution resulted.'],
}
raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
(R / 'ROOT_50F_ACTUAL_SOURCE_RUNTIME_CLOSURE.json').write_bytes(raw)
print(json.dumps({'review': pin(raw), 'job': JOB, 'tree': TREE, 'leaves': len(rows), 'SDKs': len(sdk_files), 'paths': len(groups), 'changed': changed, 'qualification': False}, ensure_ascii=False))
