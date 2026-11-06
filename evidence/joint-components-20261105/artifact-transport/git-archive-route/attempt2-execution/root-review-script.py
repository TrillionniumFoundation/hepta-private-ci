#!/usr/bin/env python3
"""Independently reopen the actual attempt-2 transport RPC/file observations."""
import base64
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'model_storage/git-archive-transport-attempt2/execution'
DST = ROOT / 'hepta-joint-evidence/evidence/joint-components-20261105/artifact-transport/git-archive-route/attempt2-execution'
sha = lambda b: hashlib.sha256(b).hexdigest()
def read(name):
    return json.loads((SRC / name).read_bytes())
def rpc(name):
    r = read(name)
    assert r.get('isError') is False
    texts = [p['text'] for p in r['content'] if p['type'] == 'text']
    assert len(texts) == 1
    return json.loads(texts[0])

manifest_bytes = (SRC / 'execution-delivery-manifest.json').read_bytes()
assert sha(manifest_bytes) == '84d2e05f282a2ae7637caf6cb664918f335fd505263f28f019ef7ed0befc03e2'
m = json.loads(manifest_bytes)
assert len(m['files']) == 32
for f in m['files']:
    b = (SRC / f['path']).read_bytes()
    assert len(b) == f['bytes'] and sha(b) == f['sha256'], f['path']

term = read('transport-terminal.json')
status = rpc('status-03.raw.json')
assert status['job_id'] == '1a1ae41d122-fc05-5e83'
assert status['state'] == 'succeeded' and status['exit_code'] == 0
assert not status['timed_out'] and status['terminal_publication_confirmed']
assert status['output_complete'] and status['output_durable']
assert all(v is False for v in status['log_truncated'].values())
assert all(v is None for v in status['log_errors'].values())
assert all(v is True for v in status['log_synced'].values())
for stream in ['stdout', 'stderr']:
    actual = (SRC / f'{stream}.raw').read_bytes()
    observed = bytearray()
    for i in range(1, 6):
        q = rpc(f'streams-{i:02d}.raw.json')
        assert q['job_id'] == status['job_id']
        v = q[stream]
        b = bytes.fromhex(v['bytes_hex'])
        assert b.decode('utf-8') == v['text']
        assert v['next_offset'] == v['offset'] + len(b)
        assert actual[v['offset']:v['next_offset']] == b
        assert v['offset'] <= len(observed)
        if v['next_offset'] > len(observed):
            observed.extend(b[len(observed)-v['offset']:])
    assert bytes(observed) == actual
    assert len(actual) == status['log_bytes'][stream]['seen'] == status['log_bytes'][stream]['stored']
assert (SRC / 'stdout.raw').read_bytes().split(b'\n', 1)[1] == (SRC / 'transport-terminal.json').read_bytes()

file_pairs = [
    ('terminal-file.raw.json', ['transport-terminal.json']),
    ('prepared-and-push-intent-files.raw.json', ['prepared-data-commit.json', 'push-intent.json']),
    ('config-initialization-file.raw.json', ['isolated-config-initialization.json']),
    ('owned-release-proof-file.raw.json', ['owned-release-proof.json']),
]
for raw, names in file_pairs:
    o = rpc(raw)
    assert not o['truncated'] and len(o['files']) == len(names)
    for f, name in zip(o['files'], names):
        b = (SRC / name).read_bytes()
        expected_basename = ('hepta-archive-git-transport-attempt2-owned-release-20261106-93bfc-01.json' if name == 'owned-release-proof.json' else name)
        assert f['path'].endswith('/' + expected_basename) and f['eof']
        assert f['size'] == len(b) and f['sha256'] == sha(b)
        assert f['text'].encode('utf-8') == b and f['version']

index = b''
version = None
for offset in [0, 65536, 131072]:
    q = rpc(f'index-chunk-{offset:06d}.raw.json')
    b = base64.b64decode(q['data_base64'], validate=True)
    assert q['offset'] == len(index) == offset
    assert q['next_offset'] == offset + len(b) and q['chunk_sha256'] == sha(b)
    if version is None:
        version = q['version']
    assert q['version'] == version and q['size'] == 168543
    index += b
assert q['eof'] and index == (SRC / 'transport-index.json').read_bytes()
assert index == (ROOT / 'actual-archive-git-readback/data/transport-index.json').read_bytes()

assert term['source_before'] == term['source_after']
assert term['source_after']['commit'] == '6db78eca53a5acdda0d96873d3f4cd65863426f0'
assert term['source_after']['tree'] == 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
assert term['source_after']['dirty'] is False
assert term['configurations_before'] == term['configurations_after']
assert len(term['configurations_before']) == 5 and term['protected_unchanged']
c = read('isolated-config-initialization.json')
for prefix in ['initial', 'configured']:
    b = c[prefix + '_text'].encode()
    assert len(b) == c[prefix + '_bytes'] and sha(b) == c[prefix + '_sha256']
assert c['configured_text'] == c['initial_text'] + '[remote "transport"]\n\turl = https://github.com/TrillionniumFoundation/hepta-private-ci.git\n'
assert c['credential_or_http_header_settings_written'] is False
assert c['original_five_configurations_modified'] is False
assert term['isolated_config_before_sha256'] == term['isolated_config_after_sha256'] == c['configured_sha256']
assert term['isolated_config_init_sha256'] == c['initial_sha256']
assert term['push_attempts'] == 1 and term['push_command_succeeded']
push = [v for v in term['operations'] if v['operation'] == 'single-empty-lease-push']
assert len(push) == 1 and push[0]['returncode'] == 0 and not push[0]['timed_out']
assert term['remote_ref_before'] is None
assert term['remote_ref_after'] == term['planned_commit'] == m['commit'] == '860dc2d8045f18808b9c5516f86edaef6e830734'
assert term['planned_tree'] == m['tree'] == 'ba8da0b1dad8ba8777c0be85bbdc3ae8d1c0cb26'
prepared = read('prepared-data-commit.json')
intent = read('push-intent.json')
assert prepared['commit'] == term['planned_commit'] and prepared['tree'] == term['planned_tree']
assert len(prepared['paths']) == 166
assert prepared['index_sha256'] == sha(index)
assert intent['commit'] == prepared['commit']
assert term['total_raw_bytes'] == 670306272 and term['total_envelope_bytes'] == 893742124
assert term['transport_blob_count'] == 166
assert not term['automatic_retry'] and not term['native_reexecution'] and not term['source_or_native_qualification']

release = read('owned-release-proof.json')
rs = rpc('owned-release-status.raw.json')
assert rs['state'] == 'succeeded' and rs['exit_code'] == 0 and not rs['timed_out']
assert release['job_id'] == status['job_id']
assert release['owned_processes_clear'] and not release['failures']
assert not release['processes_killed'] and not release['mutations_performed']
assert release['expected_original_invocation'] == 'b9ea9dce252e423b82c353392bf8ba52'
assert release['original_authoritative_terminal']['at_unix_ms'] == status['at_unix_ms']
assert release['systemctl']['fields']['LoadState'] == 'not-found'
assert all(not q['exists'] and not q['owned_pids'] for q in release['exact_cgroups'])
assert release['original_root_processes'][0]['pid'] == 1652334
assert release['original_root_processes'][0]['expected_start_ticks'] is None
assert not release['original_root_processes'][0]['present']
for stream in ['stdout', 'stderr']:
    assert bytes.fromhex(rpc('owned-release-streams.raw.json')[stream]['bytes_hex']) == (SRC / f'owned-release-{stream}.raw').read_bytes()

report = {
    'schema': 'root-actual-archive-git-attempt2-review-v1',
    'status': 'VERIFIED_ACTUAL_SINGLE_PUSH_AND_RELEASE',
    'manifest_sha256': sha(manifest_bytes),
    'verified_original_files': len(m['files']),
    'verified_original_bytes': sum(f['bytes'] for f in m['files']),
    'job_id': status['job_id'], 'terminal_state': status['state'],
    'exit_code': status['exit_code'], 'terminal_unix_ms': status['at_unix_ms'],
    'stdout_bytes': len((SRC/'stdout.raw').read_bytes()), 'stderr_bytes': 0,
    'actual_paged_streams_exact': True, 'terminal_file_exact_stdout_suffix': True,
    'actual_file_rpc_bytes_reopened': True, 'actual_index_three_versioned_chunks_exact': True,
    'desktop_index_equal_independent_git_index': True,
    'single_push': push[0], 'commit': term['planned_commit'], 'tree': term['planned_tree'],
    'transport_blob_count': 166, 'total_raw_archive_bytes': 670306272,
    'source_and_five_configurations_before_after_equal': True,
    'new_bare_configuration_only_expected_public_url_initialization': True,
    'exact_owned_unit_cgroup_and_observed_pid_clear': True,
    'release_proof_sha256': sha((SRC/'owned-release-proof.json').read_bytes()),
    'start_ticks_not_observed_and_not_invented': True,
    'full_cloud_archive_and_member_consumer': 'separate_pending_consumer_at_this_review',
    'new_native_credit': False,
    'local_reviewer_preparation_history': ['Initial reviewer asserted the local release filename was also the remote basename; it stopped before output/copy. Corrected to the actual observed remote basename, preserving content/size/SHA/version checks. No transport rerun or source change.'],
    'scope': 'Original captured RPCs and delivered bytes independently reopened; source/config snapshots do not prove transient concurrent state or all runtime dependencies. No network/native/credential operation issued by this review.'
}
out = ROOT / 'transport-route-review/attempt2-execution-review.json'
out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
DST.mkdir(parents=True, exist_ok=True)
for name in [f['path'] for f in m['files']] + ['execution-delivery-manifest.json']:
    target = DST/name
    if target.exists():
        assert target.read_bytes() == (SRC/name).read_bytes()
    else:
        shutil.copy2(SRC/name, target)
shutil.copy2(out, DST/'root-review.json')
shutil.copy2(Path(__file__), DST/'root-review-script.py')
print(json.dumps({'status': report['status'], 'verified_files': 32, 'report_sha256': sha(out.read_bytes()), 'report_bytes': out.stat().st_size, 'destination': str(DST)}))
