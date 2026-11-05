"""Recheck native7's preserved complete originals after scratch recovery."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path('/workspace/scratch/07dd58cc9630')
P = ROOT / 'architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127429723742'
OUT = ROOT / 'hepta-audit-fifth/recovery-2113/b11-native7-root-original-verification-v2.json'


def dig(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


v = json.loads((P / 'artifact-verification.json').read_text())
archive = Path(v['original_archive']['path'])
assert all(dig(archive.read_bytes())[k] == v['original_archive'][k] for k in dig(archive.read_bytes()))
api = json.loads((P / 'terminal-api-envelopes.json').read_text())
artifacts = api['artifacts']['structuredContent']['artifacts']
official = next(a for a in artifacts if a['id'] == 13442075776)
assert official['size_in_bytes'] == archive.stat().st_size
assert official['digest'] == 'sha256:' + dig(archive.read_bytes())['sha256']
z = zipfile.ZipFile(archive)
assert z.testzip() is None
members = [i.filename for i in z.infolist() if not i.is_dir()]
assert len(members) == len(v['members']) == 16
for row in v['members']:
    b = z.read(row['name'])
    assert b == (P / 'members' / row['name']).read_bytes()
    assert all(dig(b)[k] == row[k] for k in dig(b))
job = (P / 'job.log').read_bytes()
assert api['log']['structuredContent']['content'].encode('utf-8') == job
run = json.loads(api['run']['structuredContent']['content'])
jobs = json.loads(api['jobs']['structuredContent']['content'])['jobs']
assert run['id'] == 42079845181 and run['conclusion'] == 'failure'
assert run['head_sha'] == '0f6148ea3fbe9d1263354791d5cc63c7e66d4628'
assert len(jobs) == 1 and jobs[0]['id'] == 127429723742 and jobs[0]['conclusion'] == 'failure'
base = P / 'members/b11-token-mechanism-probe'
terminal = json.loads((base / 'acl-identity-counterfactual/counterfactual-terminal.json').read_text())
assert terminal['status'] == 'INVALID_OR_NOT_RUN'
for key in ('physical_counterfactual_qualified', 'physical_oracle_reached', 'source_mutated', 'source_mutation_attempted', 'restored_exact_original_bytes'):
    assert terminal[key] is False
assert terminal['restore_error'] is None
assert not (base / 'acl-identity-counterfactual/negative-command.json').exists()
assert not (base / 'acl-identity-counterfactual/positive-source.original').exists()
assert (base / 'original-bazel-exit-code.txt').read_text().strip() == '3'
assert (base / 'console-copy-exit-code.txt').read_text().strip() == '0'
assert not (base / 'source-status-before.txt').read_text().strip()
assert not (base / 'source-status-after.txt').read_text().strip()
actual = json.loads((ROOT / 'hepta-audit-fifth/recovery-2113/native7-actual-merge-source.json').read_text())
assert [p['sha'] for p in actual['commit']['parents']] == [
    'eed4d6bb61b789b19f60facc79f9e031765fa4c9', '0f6148ea3fbe9d1263354791d5cc63c7e66d4628']
assert (base / 'source-head-tree.txt').read_text().splitlines() == [actual['commit']['sha'], actual['tree_sha']]
leaves = {x['path']: x for x in actual['selected']}
rows = []
for line in (base / 'source-leaves.txt').read_text().splitlines():
    mode, kind, rest = line.split(' ', 2)
    sha, path = rest.split('\t')
    assert [mode, kind, sha] == [leaves[path]['mode'], leaves[path]['type'], leaves[path]['sha']]
    rows.append(path)
assert len(rows) == 77 and len(set(rows)) == 77
entry = json.loads((base / 'acl-identity-counterfactual/source-entry.json').read_text())
assert entry['head'] == actual['commit']['sha'] and entry['head_tree'] == actual['tree_sha']
assert entry['status'] == []
assert entry['source_canonical_git_blob'] == leaves['codex-rs/windows-sandbox-rs/src/acl_deny.rs']['sha']
logs = list((P / 'members/bazel-execution-logs/failed-test-logs').glob('invocation-*/targets/0000/test.log'))
assert len(logs) == 1
log = logs[0].read_text()
summaries = re.findall(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([0-9.]+)s$', log, re.M)
assert len(summaries) == 2
assert [sum(int(s[i]) for s in summaries) for i in (1, 2, 3)] == [147, 7, 2]
assert all(sum(int(s[i]) for i in range(1, 6)) == 156 for s in summaries)
xml = ET.parse(logs[0].with_suffix('.xml')).getroot()
assert len(xml.findall('.//testcase')) == 1
assert [e.get('message') for e in xml.findall('.//error')] == ['exited with error code 1']
failed = re.findall(r'^---- (.+) stdout ----$', log, re.M)
assert len(failed) == 7
required = ['acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object',
            'acl::tests::existing_native_deny_does_not_require_write_dac',
            'acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write',
            'token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes']
counts = [log.splitlines().count('test ' + n + ' ... ok') for n in required]
assert counts == [1, 1, 1, 0]
assert not set(required) & set(failed)
interleaved = [line for line in log.splitlines() if required[3] in line and line.startswith('PROBE_OBSERVATION_ONLY')]
assert len(interleaved) == 1
result = {'schema': 'b11-native7-root-original-verification-v2',
          'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'recovery_note': 'The earlier unregistered root v1 receipt was lost with temporary files. This is a new verification of preserved originals, not reconstruction of the missing receipt.',
          'run': run['id'], 'job': jobs[0]['id'], 'head': run['head_sha'], 'actual_merge': actual['commit']['sha'],
          'tree': actual['tree_sha'], 'parents': [p['sha'] for p in actual['commit']['parents']],
          'archive': v['original_archive'], 'official_digest_match': True, 'all_16_members_original_crc_hash_bytes_verified': True,
          'full_job_log': dig(job), 'actual_source_leaves_verified': 77,
          'source_entry': entry, 'index_and_lock_receipts_reconstructed_from_full_bytes': False,
          'whole_result': {'pass': 147, 'fail': 7, 'ignored': 2, 'libtest_batches': summaries, 'failed_headers': failed, 'original_bazel_exit': 3, 'outer_bat_exit': 1},
          'counterfactual_terminal_original': terminal, 'required_intact_PASS_counts': dict(zip(required, counts)),
          'interleaved_raw_line_unchanged': interleaved[0],
          'scope': 'INVALID precondition, no negative and no source mutation. False restored flag means no mutation was attempted, not a restore failure. No PASS line reconstructed; B11 remains OPEN.'}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(OUT), **dig(OUT.read_bytes()), 'status': 'VERIFIED_NATIVE7_INVALID_WITHOUT_MUTATION'}))
