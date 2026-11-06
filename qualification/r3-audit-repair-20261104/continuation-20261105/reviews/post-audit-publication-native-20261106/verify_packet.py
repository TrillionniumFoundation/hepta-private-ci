#!/usr/bin/env python3
"""Restore exact evidence; verify actual audit publication, metadata and native scope."""
from pathlib import Path, PurePosixPath
import base64
import collections
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
C1 = 'fc10fbef82ec8e1a7db511c06d865c147200f1fc'
TREE = '3cbdfada435378fb080f1e5f9359e4f34d70f74c'
PARENT = '46fd74d98c1cef42e1439920f9ca83361481b3d8'


def identity(raw):
    return {'bytes': len(raw), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(), 'sha256': hashlib.sha256(raw).hexdigest()}


def unwrap(raw):
    if set(raw) == {'raw', 'parsed'}:
        parsed = unwrap(raw['raw'])
        assert parsed == raw['parsed']
        return parsed
    payload = raw.get('structuredContent') or json.loads(next(x['text'] for x in raw['content'] if x['type'] == 'text'))
    return json.loads(payload['content']) if isinstance(payload.get('content'), str) else payload


def tree_hash(entries):
    data = b''
    for item in sorted(entries, key=lambda x: (x['path'] + ('/' if x['type'] == 'tree' else '')).encode()):
        mode = '40000' if item['type'] == 'tree' else item['mode']
        data += mode.encode() + b' ' + item['path'].encode() + b'\0' + bytes.fromhex(item['sha'])
    return hashlib.sha1(b'tree ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def verify_tree(snapshot):
    assert snapshot['truncated'] is False
    paths = {x['path']: x for x in snapshot['tree']}
    assert len(paths) == len(snapshot['tree'])
    directories = {path: x['sha'] for path, x in paths.items() if x['type'] == 'tree'}
    directories[''] = snapshot['sha']
    groups = collections.defaultdict(list)
    for path, item in paths.items():
        parent, _, name = path.rpartition('/')
        groups[parent].append({**item, 'path': name})
    for directory, expected in directories.items():
        assert tree_hash(groups[directory]) == expected, directory
    return paths, len(paths) - len(directories) + 1, len(directories) - 1


archive = json.loads((ROOT / 'archive.json').read_bytes())
manifest_bytes = (ROOT / 'manifest.json').read_bytes()
assert identity(manifest_bytes) == archive['payload_manifest']
manifest = json.loads(manifest_bytes)
parts = []
for row in archive['parts']:
    raw = (ROOT / row['path']).read_bytes()
    assert identity(raw) == {k: row[k] for k in identity(raw)}
    parts.append(raw)
raw_zip = base64.b64decode(b''.join(parts), validate=True)
assert identity(raw_zip) == archive['archive']
z = zipfile.ZipFile(io.BytesIO(raw_zip))
expected = {x['path']: x for x in manifest['files']}
assert len(expected) == len(manifest['files']) == len(z.namelist())
assert set(z.namelist()) == set(expected) and z.testzip() is None
with tempfile.TemporaryDirectory(prefix='post-audit-evidence-') as tmp:
    temp = Path(tmp)
    for item in z.infolist():
        rel = PurePosixPath(item.filename)
        assert not rel.is_absolute() and '..' not in rel.parts and not item.is_dir()
        assert (item.external_attr >> 16) == 0o100644
        raw = z.read(item)
        assert identity(raw) == {k: expected[item.filename][k] for k in identity(raw)}
        path = temp / item.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def read(name):
        return json.loads((temp / name).read_bytes())

    actual = unwrap(read('publication/commit-C1.actual.json'))
    assert actual['sha'] == C1 and actual['tree']['sha'] == TREE
    assert [x['sha'] for x in actual['parents']] == [PARENT]
    before_ref = unwrap(read('publication/precommit-ref.actual.json'))
    after_ref = unwrap(read('publication/ref-C1.after.json'))
    assert before_ref['object']['sha'] == PARENT and after_ref['object']['sha'] == C1
    assert before_ref['ref'] == after_ref['ref'] == 'refs/heads/audit/r3-evidence-20261105'
    actual_root = unwrap(read('publication/precommit-root.actual.json'))
    assert actual_root['sha'] == TREE and tree_hash(actual_root['tree']) == TREE
    tree, leaves, directories = verify_tree(read('publication/final-audit-intended-full-tree.json'))
    assert leaves == 14670 and directories == 2276
    for path in (temp / 'documents').iterdir():
        assert tree[PREFIX + path.name]['sha'] == identity(path.read_bytes())['git_blob']
    old = read('old/continuation-blocker-progress-v7.json')
    current = read('documents/continuation-blocker-progress-v8.json')
    before = {x['id']: x for x in old['items']}
    after = {x['id']: x for x in current['items']}
    assert set(before) == set(after) == {f'B{n:02}' for n in range(1, 24)}
    for key in before:
        assert before[key]['original_exit_condition_zh'] == after[key]['original_exit_condition_zh']
        if key != 'B23':
            assert before[key]['status'] == after[key]['status']
            assert before[key]['closure_class'] == after[key]['closure_class']
    assert before['B23']['closure_class'] == 'OPEN' and after['B23']['closure_class'] == 'CLOSED_SCOPED'
    counts = dict(collections.Counter(x['closure_class'] for x in after.values()))
    assert counts == current['counts'] == {'CLOSED_SCOPED': 16, 'OPEN': 6, 'SCIENTIFIC_HOLD': 1}
    assert current['all_blockers_closed'] is False and current['whole_candidate_qualified'] is False
    metadata = []
    for number in (4797, 4884):
        old_pr = unwrap(read(f'publication/metadata-pr-{number}.before.original.json'))
        pre = unwrap(read(f'publication/metadata-pr-{number}.pre-update.original.json'))
        new_pr = unwrap(read(f'publication/metadata-pr-{number}.after.original.json'))
        intended = (temp / f'publication/metadata-pr-{number}.intended.md').read_text()
        assert pre['body'] == old_pr['body'] and new_pr['body'] == intended
        assert intended.endswith(old_pr['body']) and C1 in intended
        for field in ('head', 'base'):
            assert old_pr[field]['sha'] == pre[field]['sha'] == new_pr[field]['sha']
        assert old_pr['merge_commit_sha'] == new_pr['merge_commit_sha']
        assert new_pr['draft'] is True and new_pr['state'] == 'open'
        metadata.append({'PR': number, 'head': new_pr['head']['sha'], 'base': new_pr['base']['sha'],
                         'merge': new_pr['merge_commit_sha'], 'new_body_bytes': len(intended.encode()),
                         'prior_full_body_preserved_as_suffix': True})
    cuts = []
    for label, run_id, head in [
        ('b21collector', 42164663819, '84cc73453eb926d6f2c5b0372c0287b0ab86ed53'),
        ('b23collector', 42164668625, '2ac89eaf91306d410ef5e9b548ee9fabd12b71b7'),
        ('windowsfmt', 42166252146, '18bbef4f61c6086f145bdb6f7acbf82127741a14'),
        ('pty', 42167168039, '8075eb367b6e97546af206b27bbf4a3a867497c8')]:
        run = unwrap(read(f'post-C1-ci-cut/{label}.run.original.json'))
        jobs = unwrap(read(f'post-C1-ci-cut/{label}.jobs.original.json'))
        assert run['id'] == run_id and run['head_sha'] == head and run['event'] == 'pull_request'
        assert jobs['total_count'] == len(jobs['jobs']) == len({x['id'] for x in jobs['jobs']})
        assert all(x['run_id'] == run_id and x['head_sha'] == head and x['run_attempt'] == run['run_attempt'] for x in jobs['jobs'])
        cuts.append({'scope': label, 'run': run_id, 'head': head, 'jobs': len(jobs['jobs']),
                     'counts': dict(collections.Counter(x['conclusion'] or x['status'] for x in jobs['jobs']))})
    assert sum(x['jobs'] for x in cuts) == 73
    windows_jobs = unwrap(read('post-C1-ci-cut/windowsfmt.jobs.original.json'))['jobs']
    fmt, = [x for x in windows_jobs if x['id'] == 127731162050]
    assert fmt['conclusion'] == 'success' and fmt['status'] == 'completed'
    assert all(x['conclusion'] in ('success', 'skipped') for x in fmt['steps'])
    fmt_log = (temp / 'windows-format/job-127731162050.original.log').read_bytes()
    assert b'eefd44670b764a49892ecbfefe8c3c7009b12bd5' in fmt_log and b'Run just fmt-check' in fmt_log
    fmt_pub = read('windows-format/publication-originals.json')
    fmt_records = {x['key']: x['value'] for x in fmt_pub['records']}
    fmt_commit = unwrap(fmt_records['commitActual'])
    fmt_ref = unwrap(fmt_records['refAfter'])
    fmt_pr = unwrap(fmt_records['prActual.raw'])
    fmt_merge = unwrap(fmt_records['mergeActual.raw'])
    fmt_root = unwrap(fmt_records['rootActual.raw'])
    assert fmt_pr == fmt_records['prActual'] and fmt_merge == fmt_records['mergeActual']
    assert fmt_root == fmt_records['rootActual'] and tree_hash(fmt_root['tree']) == fmt_pub['tree']
    assert fmt_commit['sha'] == fmt_ref['object']['sha'] == fmt_pr['head']['sha'] == fmt['head_sha'] == fmt_pub['source_after']
    assert [x['sha'] for x in fmt_commit['parents']] == ['340fbc0629d27e3a2bda7c6971be25c60b3bf2bc']
    assert fmt_commit['tree']['sha'] == fmt_merge['tree']['sha'] == fmt_pub['tree'] == 'd611fe969ecada41618b8feb19f688565b301063'
    assert fmt_merge['sha'] == fmt_pr['merge_commit_sha'] == fmt_pub['merge'] == 'eefd44670b764a49892ecbfefe8c3c7009b12bd5'
    assert [x['sha'] for x in fmt_merge['parents']] == ['67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed', fmt['head_sha']]
    state = read('windows-state-rejected/registry.actual.json')
    assert identity((temp / 'windows-state-rejected/registry.actual.json').read_bytes())['git_blob'] == '4404e9d44ee8b1e070a6106f2fba1779991bb7db'
    assert state['decision'] == 'REJECT_PUBLICATION' and state['qualification']['no_blocker_closure'] is True
    state_replay = read('windows-state-root-replay/restore.stdout.json')
    assert state_replay['all_bytes_equal'] is True and state_replay['members'] == 117
    assert state_replay['static_replay']['stdout']['git_blob'] == '00ace6952c8c6c9688688797d9dd064a1d87684c'
    b23 = temp / 'b23-collector-v3-native'
    proc = subprocess.run([sys.executable, str(b23 / 'verify_native.py')], cwd=b23, capture_output=True, timeout=60)
    assert proc.returncode == 0 and proc.stderr == b'' and proc.stdout == (b23 / 'verification.stdout.json').read_bytes()
    native = json.loads(proc.stdout)
    independent = read('b23-v3-independent/REVIEW.json')
    assert identity((temp / 'b23-v3-independent/REVIEW.json').read_bytes())['git_blob'] == 'fdc684cee0eec8d6387020e666bb915e4fad6e83'
    assert independent['decision'] == 'ACCEPT_NEW_RUN_AND_COLLECTOR_WITH_STATED_SCOPE' and independent['blocking_findings'] == []
    assert independent['new_blockers_closed'] == []
    root_review = read('root-followup-independent/REVIEW.json')
    assert identity((temp / 'root-followup-independent/REVIEW.json').read_bytes())['git_blob'] == '4423b3169ab036951dfbf9736d435e68fc41458a'
    assert root_review['decision'] == 'ACCEPT_PACKET_WITH_ITS_EXPLICIT_SCOPES'
    result = {'schema': 'hepta-post-audit-publication-native-verification-v1',
        'archive': archive['archive'], 'exact_members': len(expected),
        'actual_audit_commit': C1, 'actual_audit_parent': PARENT, 'actual_audit_tree': TREE,
        'full_tree_leaves': leaves, 'full_tree_nonroot_directories': directories,
        'all_23_original_exit_strings_unchanged': True, 'C1_only_transition': 'B23 OPEN -> CLOSED_SCOPED',
        'counts': counts, 'metadata_updates': metadata,
        'bounded_followup_CI_window': read('post-C1-ci-cut/cut-receipt.json')['before'] | {'end': read('post-C1-ci-cut/cut-receipt.json')['after']},
        'bounded_followup_runs': cuts,
        'windows_format_original_job': {'job': fmt['id'], 'source': fmt['head_sha'], 'conclusion': fmt['conclusion'], 'log': identity(fmt_log), 'earlier_340_two_test_pass_not_transferred': True},
        'B23_new_native_and_collector': {'run': native['actual_run']['run'], 'job': native['actual_run']['job'], 'collector_complete': True, 'original_exit': 0, 'product_tests': native['product_tests'], 'compact': native['compact'], 'isolated_replay_stdout': identity(proc.stdout)},
        'windows_state_design': 'REJECT_PUBLICATION; original EOF single event and independent ACL error preserved; no native execution or blocker closure',
        'all_blockers_closed': False, 'whole_candidate_qualified': False,
        'limits': ['This packet appends actual publication and a bounded four-run observation; it does not replace the complete 46-run/214-job observation in C1.', 'B23 collector success does not rewrite the prior failed collector or close another blocker.', 'A rejected state-lock design is evidence of a design constraint, not a product repair.']}
    print(json.dumps(result, ensure_ascii=False, indent=2))
