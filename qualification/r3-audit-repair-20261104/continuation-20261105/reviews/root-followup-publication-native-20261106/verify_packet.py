#!/usr/bin/env python3
"""Verify and optionally restore exact publication/native evidence, without CI."""
from pathlib import Path, PurePosixPath
from collections import Counter
import argparse
import base64
import hashlib
import io
import json
import re
import tomllib
import zipfile


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
            'sha256': hashlib.sha256(data).hexdigest()}


def api(obj):
    if 'raw' in obj:
        return api(obj['raw'])
    assert not obj.get('isError'), obj
    obj = obj.get('structuredContent', obj)
    if isinstance(obj.get('content'), str):
        return json.loads(obj['content'])
    return obj


def verify(root, extract=None):
    archive = json.loads((root / 'archive.json').read_text())
    manifest_bytes = (root / 'manifest.json').read_bytes()
    assert identity(manifest_bytes) == archive['payload_manifest']
    manifest = json.loads(manifest_bytes)
    encoded = []
    for part in archive['parts']:
        data = (root / part['path']).read_bytes()
        assert identity(data) == {k: part[k] for k in identity(data)}
        assert len(data) <= 400000
        encoded.append(data)
    data = base64.b64decode(b''.join(encoded), validate=True)
    assert identity(data) == archive['archive']
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        files = {n: z.read(n) for n in z.namelist()}
        assert len(files) == len(z.infolist())
    assert sorted(files) == sorted(x['path'] for x in manifest['files'])
    for row in manifest['files']:
        path = PurePosixPath(row['path'])
        assert not path.is_absolute() and '..' not in path.parts
        assert identity(files[row['path']]) == {k: row[k] for k in identity(b'')}
        assert not re.search(rb'https://[^\s"<>]*(?:blob\.core\.windows\.net|amazonaws\.com)[^\s"<>]*(?:[?&](?:sig|X-Amz-Signature)=)', files[row['path']], re.I)
    def read(name):
        return json.loads(files[name])
    def records(name):
        return {x['key']: x['value'] for x in read(name)['records']}

    base = '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
    publications = []
    shared = records('collector-v3-publication-originals.json')
    win = records('windows-format/publication-originals.json')
    pty = records('pty-discard-publication-originals.json')
    for rec, prefix, number, head, tree, parent, merge, ref_key, root_key, body_key in [
        (shared, 'b21.', 4902, '84cc73453eb926d6f2c5b0372c0287b0ab86ed53', '45858bc96c0edbc366ec77991646b15971129975', 'ebd31e2b3e38ff72cedaa7b57bee60c1c102da27', '285d5727d01e38a76a77441ab038e109dbab787c', 'refAfter', 'treeRootActual', 'bodyIntended'),
        (shared, 'b23.', 4910, '2ac89eaf91306d410ef5e9b548ee9fabd12b71b7', '9a6fd02aa18b2421f6aaec8a5db6ecf82b710c89', 'e63ed76c5d8ded046f97caffbdbe2883140e6032', '652ff4a8a9042d68983a29855bba3e9bfe1ae7b2', 'refAfter', 'treeRootActual', 'bodyIntended'),
        (win, '', 4913, '18bbef4f61c6086f145bdb6f7acbf82127741a14', 'd611fe969ecada41618b8feb19f688565b301063', '340fbc0629d27e3a2bda7c6971be25c60b3bf2bc', 'eefd44670b764a49892ecbfefe8c3c7009b12bd5', 'refAfter', 'rootActual', 'bodyIntended'),
        (pty, '', 4927, '8075eb367b6e97546af206b27bbf4a3a867497c8', 'c1249a173ac346d0f1230fe56451b97d4e13c601', base, 'b88f625afe17975db80b152283ef2e19cc50e41f', 'refActual', 'rootActual', 'body'),
    ]:
        commit = api(rec[prefix + 'commitActual'])
        pull = api(rec[prefix + 'prActual'])
        merged = api(rec[prefix + 'mergeActual'])
        tree_root = api(rec[prefix + root_key])
        ref = api(rec[prefix + ref_key])
        assert commit['sha'] == head and commit['tree']['sha'] == tree
        assert [p['sha'] for p in commit['parents']] == [parent]
        assert ref['object']['sha'] == head
        assert pull['number'] == number and pull['head']['sha'] == head and pull['base']['sha'] == base
        assert pull['body'] == rec[prefix + body_key] and pull['draft']
        assert pull['merge_commit_sha'] == merged['sha'] == merge
        assert [p['sha'] for p in merged['parents']] == [base, head]
        assert merged['tree']['sha'] == tree_root['sha'] == tree
        assert tree_root['truncated'] is False and len(tree_root['tree']) == 53
        if prefix:
            before = api(rec[prefix + 'before.pr'])
            assert pull['body'].endswith(before['body'])
        elif number == 4913:
            assert pull['body'].endswith(api(win['before.prraw'])['body'])
        publications.append({'pr': number, 'head': head, 'tree': tree, 'merge': merge, 'body_exact': True, 'actual_ref_and_commit_GET': True})
    assert pty['rootReplay']['exit_code'] == 0
    assert identity(pty['rootReplay']['output'].encode())['git_blob'] == '9f21221d4df81c24bd93dc6dd0b0c7e129b6b10b'
    assert identity(files['windows-format/postimage.rs'])['git_blob'] == '79182413b0e84d021a2fb1dbdb275b8f7592ee48'
    assert identity(files['windows-setup-causes/repo-checks-127703396530.original.log'])['git_blob'] == '5be21956ff8436f9f8177f358ffbe57d22b0aef7'

    certificate = read('b23-closure-root-replay/ROOT_ACCEPTANCE.json')
    scope = read('b23-closure-root-replay/scope.stdout.original.json')
    assert certificate['decision'] == 'CLOSED_SCOPED'
    assert certificate['unchanged_original_exit_zh'] == scope['unchanged_original_exit_zh']
    assert identity(files['b23-closure-root-replay/independent-review.original.json']) == certificate['independent_review']
    for row in certificate['root_actual_offline_executions']:
        assert row['exit_code'] == 0 and row['matches_frozen_stdout']
        assert identity(files['b23-closure-root-replay/' + row['name'] + '.stdout.original.json']) == row['stdout']
        assert identity(files['b23-closure-root-replay/' + row['name'] + '.stderr.original.txt']) == row['stderr']
    for row in certificate['custody_now_actual']:
        assert identity(files['custody/' + row['archive_registry']]) == {k: row[k] for k in identity(b'')}
    assert scope['native']['job_overall'] == 'failure' and scope['native']['original_bazel_exit'] == 0
    assert scope['original_ci_acceptance']['target_results_cached'] is True
    assert scope['cross_source_and_execution_binding']['main_and_diag_log_bytes_equal'] is False

    official = api(read('cargo-deny-native/official-artifact-metadata.tool-return.original.json'))['artifacts']
    art = next(x for x in official if x['id'] == 13478122141)
    cargo_zip = files['cargo-deny-native/artifact-13478122141.original.zip']
    assert len(cargo_zip) == art['size_in_bytes'] == 735485
    assert identity(cargo_zip)['sha256'] == art['digest'].removeprefix('sha256:')
    assert art['workflow_run']['id'] == 42162085830
    assert art['workflow_run']['head_sha'] == '476653f8fe5874849e864ab3fd49c792913450ab'
    with zipfile.ZipFile(io.BytesIO(cargo_zip)) as z:
        assert z.testzip() is None and len(z.infolist()) == 11
        cargo = {n: z.read(n) for n in z.namelist()}
    receipt = json.loads(cargo['evidence-receipt.json'])
    assert receipt['original_command_exit_code'] == 1 and receipt['safe_for_upload']
    assert receipt['original_payloads_rewritten'] is False
    for row in receipt['files']:
        assert len(cargo[row['name']]) == row['bytes']
    assert cargo['command-exit-code.txt'] == b'1\n'
    assert cargo['console-copy-exit-code.txt'] == cargo['after-capture-exit-code.txt'] == b'0\n'
    for phase in ['before', 'after']:
        s = json.loads(cargo['source-' + phase + '.json'])
        assert s['head'] == '825779c5bba92a228f8d3cf6add429592acdc4a7'
        assert s['tree'] == '06c4e2f80884b169e31d8a5edf04438486a9ee81'
        assert s['clean'] and s['git_exit_codes'] == [0, 0, 0]
    text = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', cargo['cargo-deny.log']).decode()
    errors = re.findall(r'^error\[[^\]]+\]:[^\r\n]+', text, re.M)
    assert errors == ['error[unmaintained]: `pin-utils` is unmaintained']
    assert 'RUSTSEC-2026-0441' in text and 'advisories FAILED, bans ok, licenses ok, sources ok' in text
    lock_bytes = files['cargo-deny-native/source-lock.txt']
    assert identity(lock_bytes)['git_blob'] == '71fc8fa78b5afa076835b29790a5e6b0bd772558'
    lock = tomllib.loads(lock_bytes.decode())
    reverse = sorted((p['name'], p['version']) for p in lock['package'] if any(d.split(' ')[0] == 'pin-utils' for d in p.get('dependencies', [])))
    assert reverse == [('aws-smithy-http', '0.64.1'), ('aws-smithy-runtime', '1.16.0'), ('aws-smithy-types', '1.8.1'), ('loom', '0.7.2')]

    cut = read('new-fixes-ci-cut-originals.json')
    cuts = []
    for key, declared in cut['summary'].items():
        jobs = []
        for row in cut['records']:
            if row['key'] != key:
                continue
            parsed = api(row['raw'])
            assert parsed == row['parsed']
            if 'jobs' in parsed:
                assert parsed['total_count'] == len(parsed['jobs'])
                jobs += parsed['jobs']
            else:
                assert parsed['total_count'] == len(parsed['workflow_runs']) == declared['runs']
                assert all(r['head_sha'] == declared['head'] for r in parsed['workflow_runs'])
        assert len(jobs) == len({j['id'] for j in jobs}) == declared['jobs']
        counts = Counter(j['conclusion'] if j['status'] == 'completed' else j['status'] for j in jobs)
        assert dict(counts) == declared['job_counts']
        cuts.append({'source': key, **declared})
    latest = read('final-seven-heads-ci-cut-originals.json')
    latest_cuts = []
    for key, head in latest['headScopes']:
        run_records = [x for x in latest['runRecords'] if x['key'] == key]
        assert len(run_records) == 1 and run_records[0]['result']['status'] == 'fulfilled'
        run_page = api(run_records[0]['result']['value'])
        assert run_page['total_count'] == len(run_page['workflow_runs'])
        assert all(x['head_sha'] == head for x in run_page['workflow_runs'])
        run_ids = {x['id'] for x in run_page['workflow_runs']}
        job_records = [x for x in latest['jobRecords'] if x['key'] == key]
        assert len(job_records) == len(run_ids) and {x['run'] for x in job_records} == run_ids
        all_jobs = []
        for row in job_records:
            assert row['result']['status'] == 'fulfilled'
            page = api(row['result']['value'])
            assert page['total_count'] == len(page['jobs'])
            assert all(j['run_id'] == row['run'] for j in page['jobs'])
            all_jobs += page['jobs']
        declared = latest['summary'][key]
        assert len(all_jobs) == len({j['id'] for j in all_jobs}) == declared['jobs']
        counts = Counter(j['conclusion'] if j['status'] == 'completed' else j['status'] for j in all_jobs)
        assert dict(counts) == declared['counts']
        if key == 'main':
            assert declared['jobs'] == 93 and dict(counts) == {'success': 68, 'failure': 9, 'cancelled': 10, 'skipped': 6}
            assert next(j for j in all_jobs if j['id'] == 127704207208)['conclusion'] == 'success'
            assert next(j for j in all_jobs if j['id'] == 127712699481)['conclusion'] == 'failure'
        if key == 'arg0':
            for job_id in [127717742578, 127717742170]:
                assert next(j for j in all_jobs if j['id'] == job_id)['conclusion'] == 'success'
        latest_cuts.append({'source': key, 'head': head, 'runs': len(run_ids), 'jobs': len(all_jobs), 'counts': dict(counts)})
    arg0_log = files['arg0-clippy/GNU-clippy-127717742578.original.log']
    assert identity(arg0_log)['git_blob'] == 'fdbb2e5c5f07308daa29af4d211d00d1e1be05b3'
    assert b'HEAD is now at 65e1ec7 Merge 3c9e2bba4e7e84616509d6320a9ae013a274532c into 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed' in arg0_log
    assert b'Build completed successfully, 26119 total actions' in arg0_log
    assert b'Run ./.github/actions/check-clean-worktree' in arg0_log
    if extract is not None:
        extract.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            out = extract / name
            out.parent.mkdir(parents=True, exist_ok=True)
            assert not out.exists() or out.read_bytes() == data
            out.write_bytes(data)
    return {'schema': 'root-followup-offline-verification-v1', 'result': 'PASS_EVIDENCE_ONLY',
        'archive': archive['archive'], 'original_payload_members': len(files), 'publications': publications,
        'B23': {'decision': 'CLOSED_SCOPED', 'original_exit_unchanged': True, 'custody_actual': True, 'original_collector_failure_preserved': True},
        'cargo_native': {'run': 42162085830, 'job': 127715564317, 'artifact': art['id'], 'members': 11,
            'original_log': identity(cargo['cargo-deny.log']), 'original_command_exit': 1, 'errors': errors,
            'reverse_dependencies': reverse, 'old_main_job_cause': 'UNKNOWN; not retroactively assigned'},
        'bounded_CI_cuts': cuts,
        'latest_CI_window': {'before': latest['before'], 'after': latest['afterJobs'], 'atomic': False, 'heads': latest_cuts},
        'arg0_original_GNU_clippy': {'job': 127717742578, 'API_conclusion': 'success', 'actual_checkout': '65e1ec7164063b139db291562dd6093c3008b403', 'full_log': identity(arg0_log), 'fresh_uncached_execution_claimed': False},
        'qualification': {'offline_verification_only': True, 'new_native_execution': False,
            'new_heads_inherit_prior_passes': False, 'all_blockers_closed': False}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--extract', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.extract), ensure_ascii=False, indent=2))
