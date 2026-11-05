"""Verify the complete native8 archive and distinguish WSL launcher failure."""
from pathlib import Path
import collections
import datetime
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path('/workspace/scratch/07dd58cc9630')
P = ROOT / 'architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127545539398'
REC = ROOT / 'hepta-audit-fifth/recovery-2113'


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


api = json.loads((P / 'terminal-api-envelopes.json').read_text())
run = json.loads(api['run']['structuredContent']['content'])
jobs = json.loads(api['jobs']['structuredContent']['content'])['jobs']
artifacts = json.loads(api['artifacts']['structuredContent']['content'])['artifacts']
assert run['id'] == 42113095723 and run['run_attempt'] == 1
assert run['head_sha'] == '2338281bac08ff68b85dc2146c04a35598e6cbb4'
assert run['status'] == 'completed' and run['conclusion'] == 'failure'
assert len(jobs) == 1 and jobs[0]['id'] == 127545539398
job = jobs[0]
assert job['status'] == 'completed' and job['conclusion'] == 'failure'
assert len(artifacts) == 1 and artifacts[0]['id'] == 13454109636
archive = (P / 'artifact.zip').read_bytes()
assert artifacts[0]['size_in_bytes'] == len(archive) == 2049241
assert artifacts[0]['digest'] == 'sha256:' + digest(archive)['sha256']
verification = json.loads((P / 'artifact-verification.json').read_text())
assert verification['zip_bytes'] == len(archive)
assert verification['zip_sha256'] == digest(archive)['sha256']
with zipfile.ZipFile(P / 'artifact.zip') as z:
    assert z.testzip() is None
    members = [i for i in z.infolist() if not i.is_dir()]
    assert len(members) == len(verification['members']) == 21
    claimed = {e['path']: e for e in verification['members']}
    assert set(claimed) == {i.filename for i in members}
    for i in members:
        data = z.read(i.filename)
        assert data == (P / 'members' / i.filename).read_bytes()
        e = claimed[i.filename]
        assert e['crc32'] == f'{i.CRC:08x}'
        assert all(e[k] == v for k, v in digest(data).items())
job_log = (P / 'job.log').read_bytes()
assert api['log']['structuredContent']['content'].encode() == job_log
base = P / 'members/b11-token-mechanism-probe'
actual = json.loads((REC / 'trees/merge8fd.json').read_text())
publication = json.loads((REC / 'b11-seven-publication-root.json').read_text())
assert actual['sha'] == 'cb105f2d902326c3c2e187f49c76d5598e6646c3'
assert publication['merge_commit']['sha'] == '8fd0c14cd5853d21eb23571f67461f3fc386c01c'
parents = [e['sha'] for e in publication['merge_commit']['parents']]
assert parents == ['eed4d6bb61b789b19f60facc79f9e031765fa4c9', run['head_sha']]
assert (base / 'source-head-tree.txt').read_text().splitlines() == [publication['merge_commit']['sha'], actual['sha']]
leaves = {e['path']: e for e in actual['tree'] if e['type'] != 'tree'}
selected = []
for line in (base / 'source-leaves.txt').read_text().splitlines():
    mode, kind, rest = line.split(' ', 2)
    sha, path = rest.split('\t')
    assert [mode, kind, sha] == [leaves[path][k] for k in ['mode', 'type', 'sha']]
    selected.append(leaves[path])
assert len(selected) == len({e['path'] for e in selected}) == 78
assert any(e['path'].endswith('/read_acl_mutex_tests.rs') for e in selected)
assert (base / 'source-status-before.txt').read_text().strip() == ''
assert (base / 'source-status-after.txt').read_text().strip() == ''
assert (base / 'original-bazel-exit-code.txt').read_text().strip() == '3'
assert (base / 'console-copy-exit-code.txt').read_text().strip() == '0'
logs = list((P / 'members/bazel-execution-logs/failed-test-logs').glob('invocation-*/targets/0000/test.log'))
assert len(logs) == 1
log = logs[0].read_text()
batch = re.findall(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([0-9.]+)s$', log, re.M)
assert len(batch) == 2
assert [sum(int(s[i]) for s in batch) for i in [1, 2, 3]] == [147, 7, 2]
assert all(sum(int(s[i]) for i in range(1, 6)) == 156 for s in batch)
failed = re.findall(r'^---- (.+) stdout ----$', log, re.M)
assert len(failed) == len(set(failed)) == 7
xml = ET.parse(logs[0].with_suffix('.xml')).getroot()
assert len(xml.findall('.//testcase')) == 1
assert [e.get('message') for e in xml.findall('.//error')] == ['exited with error code 1']
stdout = xml.find('.//system-out').text
assert len(log) == len(stdout)
differences = collections.Counter((ord(a), ord(b)) for a, b in zip(log, stdout) if a != b)
assert differences == {(27, 63): 78}  # XML serializer replaces literal ESC; originals remain separate.
cf = base / 'acl-identity-counterfactual'
terminal = json.loads((cf / 'counterfactual-terminal.json').read_text())
assert terminal['status'] == 'INVALID_OR_NOT_RUN'
for key in ['physical_counterfactual_qualified', 'physical_oracle_reached', 'source_mutated',
            'source_mutation_attempted', 'restored_exact_original_bytes']:
    assert terminal[key] is False
assert terminal['restore_error'] is None and terminal['positive_scopes'] == []
assert not (cf / 'negative-command.json').exists() and not (cf / 'positive-source.original').exists()
assert sorted(p.name for p in cf.iterdir() if p.is_dir()) == ['positive-01']
entry_raw = (cf / 'source-entry.json').read_bytes()
assert entry_raw == (cf / 'positive-01/source-before.json').read_bytes() == (cf / 'positive-01/source-after.json').read_bytes()
entry = json.loads(entry_raw)
assert entry['head'] == publication['merge_commit']['sha'] and entry['head_tree'] == actual['sha']
assert entry['status'] == []
assert entry['source_canonical_git_blob'] == leaves['codex-rs/windows-sandbox-rs/src/acl_deny.rs']['sha']
command = json.loads((cf / 'positive-01/command.json').read_text())
cmd_exit = json.loads((cf / 'positive-01/command-terminal.json').read_text())
assert command['source'] == entry and command['argv'][0] == 'bash'
assert command['case'] == 'acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object'
assert cmd_exit['exit_code'] == 1
raw_console = (cf / 'positive-01/console.log').read_bytes()
assert len(raw_console) == 504
decoded_console = raw_console.decode('utf-16-le')
assert decoded_console.startswith('Windows Subsystem for Linux has no installed distributions.')
assert 'test result:' not in decoded_console and 'Bazel' not in decoded_console
steps = {e['name']: e for e in job['steps']}
assert steps['Run the original outer Windows sandbox unit target']['conclusion'] == 'failure'
assert steps['Check the ACL identity counterfactual and restore its source']['conclusion'] == 'failure'
assert steps['Run the original setup helper target after exact restoration']['conclusion'] == 'skipped'
assert steps['Check for a clean worktree']['conclusion'] == 'success'
result = {'schema': 'hepta-b11-native8-root-original-verification-v1',
          'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'run': run['id'], 'job': job['id'], 'attempt': 1, 'source_head': run['head_sha'],
          'actual_checkout': publication['merge_commit']['sha'], 'actual_tree': actual['sha'], 'parents': parents,
          'archive': digest(archive), 'official_digest_equal': True, 'all_21_members_crc_and_original_bytes': True,
          'complete_job_log': digest(job_log), 'original_API_envelopes': digest((P / 'terminal-api-envelopes.json').read_bytes()),
          'actual_source_leaves': selected, 'whole': {'pass': 147, 'fail': 7, 'ignored': 2, 'batches': batch,
             'failed_headers': failed, 'original_bazel_exit': 3, 'outer_bat_exit': 1,
             'xml_system_out_difference': 'Exactly 78 literal ESC characters become question marks; every other character agrees. Raw log and XML are both retained unchanged.'},
          'counterfactual_terminal_original': terminal, 'positive_01_command_original': command,
          'positive_01_command_terminal_original': cmd_exit, 'positive_01_console': digest(raw_console),
          'console_encoding': 'UTF-16LE', 'console_decoded_for_reading_only': decoded_console,
          'source_entry_and_before_after_byte_equal': True, 'original_source_guard': entry,
          'full_ordinary_index_or_lock_bytes_reconstructed_here': False,
          'helper_step': steps['Run the original setup helper target after exact restoration'],
          'decision': 'INVALID launcher precondition: bare bash resolved to WSL before any exact positive Bazel/test; no negative execution, no source mutation, no restoration failure. Whole original failure is unchanged; setup helper was correctly skipped. B11 remains OPEN.'}
out = REC / 'b11-native8-root-original-verification-v1.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(out), **digest(out.read_bytes()), 'status': 'VERIFIED_NATIVE8_WSL_LAUNCH_FAILURE_WITHOUT_MUTATION'}))
