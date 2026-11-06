#!/usr/bin/env python3
"""Verify preserved GitHub Windows artifacts and replay parsers only; no native tests."""
import argparse
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile
sys.dont_write_bytecode = True

HEAD = '340fbc0629d27e3a2bda7c6971be25c60b3bf2bc'
BASE = '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
MERGE = 'ff2b873c8b907e1e86b1a728c2c18552edfbd0ed'
TREE = '78b817fec87e593e0a0f6357d84f895b8574bde5'
RUN = 42158689226
SPECS = [('shard4', 127703396792, 13477083714, 43), ('shard2', 127703396875, 13477309997, 93)]


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest()}


def read_json(path):
    return json.loads(path.read_bytes())


def response(raw):
    assert not raw.get('isError', False)
    return raw['structuredContent']


def api(raw):
    data = response(raw)
    return json.loads(data['content']) if isinstance(data.get('content'), str) else data


def verify(root):
    publication = read_json(root / 'authority/publication-originals.json')
    records = publication['records']
    actual_commits = {}
    for key in ['commitActual', 'mergeActual']:
        item = records[key]
        assert api(item['raw']) == item['response']
        actual_commits[key] = item['response']
    head, merge = actual_commits['commitActual'], actual_commits['mergeActual']
    assert head['sha'] == HEAD and merge['sha'] == MERGE
    assert head['tree']['sha'] == merge['tree']['sha'] == TREE
    assert [p['sha'] for p in head['parents']] == [BASE]
    assert [p['sha'] for p in merge['parents']] == [BASE, HEAD]
    source_postimages = []
    for sha in ['37aa38dde9e83ee5f3ce8f267f11afd76fee3400', '505be9299f9580877449740fd235e988f8c93b7b']:
        item = records['postimage.' + sha]
        def bodies(value):
            out = []
            if isinstance(value, dict):
                for key, val in value.items():
                    if key == 'content' and isinstance(val, str):
                        if identity(val.encode())['git_blob'] == sha:
                            out.append(val)
                    elif isinstance(val, (dict, list)):
                        out.extend(bodies(val))
            elif isinstance(value, list):
                for val in value:
                    out.extend(bodies(val))
            return out
        matches = bodies(item)
        assert matches and len(set(matches)) == 1
        source_postimages.append(identity(matches[0].encode()))
    lib = (root / 'authority/lib.rs').read_bytes()
    assert identity(lib)['git_blob'] == '11778af7beb645b36401807cf3e31a0dd4deddc0'
    assert response(read_json(root / 'authority/lib.rs.GET.original.json'))['content'].encode() == lib
    assert b'#[cfg(target_os = "windows")]\nmod setup_error;' in lib

    cut = read_json(root / 'original/windows-six-API-records.extracted.json')
    assert cut['parent_identity']['git_blob'] == 'c10b5e771f406cc987b8589f3d8cc5ed07aa4c48'
    assert len(cut['records']) == 6
    all_jobs = []
    runs = None
    for item in cut['records']:
        assert item['key'] == 'windows'
        data = api(item['raw'])
        assert data == item['parsed']
        if item['kind'] == 'runs':
            assert runs is None
            runs = data['workflow_runs']
            assert data['total_count'] == len(runs) == 5
            assert len({r['id'] for r in runs}) == 5
            assert all(r['head_sha'] == HEAD for r in runs)
        else:
            assert item['kind'] == 'jobs'
            assert data['total_count'] == len(data['jobs'])
            assert all(j['run_id'] == item['run'] and j['head_sha'] == HEAD for j in data['jobs'])
            all_jobs.extend(data['jobs'])
    assert RUN in {r['id'] for r in runs}
    assert len({j['id'] for j in all_jobs}) == len(all_jobs)
    capture = read_json(root / 'original/job-log-capture.json')
    jobs = []
    archives = []
    manifest_results = []
    for label, job_id, artifact_id, count in SPECS:
        job = next(j for j in all_jobs if j['id'] == job_id)
        assert job['run_id'] == RUN and job['status'] == 'completed' and job['conclusion'] == 'failure'
        assert any(s['name'] == 'bazel test shard' and s['conclusion'] == 'failure' for s in job['steps'])
        assert any(s['name'] == 'Upload Bazel execution logs' and s['conclusion'] == 'success' for s in job['steps'])
        declared = next(c for c in capture['jobs'] if c['job'] == job_id)
        raw_file = root / f'original/job-{job_id}.tool-response.original.json'
        log_file = root / f'original/job-{job_id}.decoded.original.log'
        raw_bytes, log_bytes = raw_file.read_bytes(), log_file.read_bytes()
        assert identity(raw_bytes) == declared['body_identity']
        assert identity(log_bytes) == declared['decoded_identity']
        assert response(json.loads(raw_bytes))['content'].encode() == log_bytes
        assert log_bytes.count(b'\r') == declared['CR']
        log = log_bytes.decode()
        assert f'refs/pull/4913/merge ({MERGE})' in log
        assert f'HEAD is now at ff2b873 Merge {HEAD} into {BASE}' in log
        metadata = response(read_json(root / f'original/artifacts-{label}.GET.original.json'))['artifacts']
        assert len(metadata) == 1
        artifact = metadata[0]
        assert artifact['id'] == artifact_id and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == HEAD
        declared_members = read_json(root / f'artifacts/{label}-members.json')
        zip_path = root / f'artifacts/windows-{label}-{artifact_id}.original.zip'
        zip_bytes = zip_path.read_bytes()
        zip_identity = identity(zip_bytes)
        assert zip_identity['bytes'] == artifact['size_in_bytes'] == declared_members['zip_bytes']
        assert 'sha256:' + zip_identity['sha256'] == artifact['digest']
        assert zip_identity['sha256'] == declared_members['zip_sha256']
        unpacked = root / f'artifacts/windows-{label}-original'
        member_records = []
        with zipfile.ZipFile(zip_path) as archive:
            assert archive.testzip() is None
            infos = archive.infolist()
            assert len(infos) == len({i.filename for i in infos}) == count
            expected = {e['path']: e for e in declared_members['members']}
            assert set(expected) == {i.filename for i in infos}
            for info in infos:
                path = PurePosixPath(info.filename)
                assert not path.is_absolute() and '..' not in path.parts and '\\' not in info.filename and ':' not in info.filename
                assert not info.is_dir() and (info.external_attr >> 16) & 0o170000 != 0o120000
                data = archive.read(info)
                actual = identity(data)
                row = expected[info.filename]
                assert actual == {k: row[k] for k in actual}
                assert row['crc32'] == f'{info.CRC:08x}'
                destination = unpacked / path
                if destination.exists():
                    assert destination.read_bytes() == data
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                member_records.append({'path': info.filename, **actual, 'crc32': row['crc32']})
            assert {str(p.relative_to(unpacked)) for p in unpacked.rglob('*') if p.is_file()} == set(expected)
        for manifest_path in sorted(unpacked.glob('*-test-logs/*/manifest.json')):
            manifest = read_json(manifest_path)
            assert manifest['complete_for_selected_targets'] is True and manifest['errors'] == []
            assert manifest['source'] == {'commit': MERGE, 'tracked_worktree_dirty': False, 'tree': TREE}
            assert len({e['archive_relative_path'] for e in manifest['files']}) == len(manifest['files'])
            for item in manifest['files']:
                file = manifest_path.parent / item['archive_relative_path']
                current = identity(file.read_bytes())
                assert current['bytes'] == item['bytes'] and current['sha256'] == item['sha256']
            manifest_results.append({'path': str(manifest_path.relative_to(root)), 'source': manifest['source'], 'targets': manifest['selected_targets'], 'file_count': len(manifest['files']), 'full_original_bytes_hash_equal': True})
        archives.append({'artifact': artifact_id, 'name': artifact['name'], 'zip': zip_identity, 'official_API_digest_equal': True, 'members': member_records, 'CRC_passed': True})
        jobs.append({'job': job_id, 'name': job['name'], 'status': job['status'], 'conclusion': job['conclusion'], 'started_at': job['started_at'], 'completed_at': job['completed_at'], 'original_log': identity(log_bytes), 'CR_preserved': declared['CR'], 'tool_response': identity(raw_bytes), 'actual_checkout_marker': MERGE})
    assert len(manifest_results) == 4
    replay_results = []
    for script, frozen in [('decode_native_compacts.py', 'decode-01.stdout.json'), ('bind_test_logs_v2.py', 'binding-05.stdout.json')]:
        expected = (root / frozen).read_bytes()
        run = subprocess.run([sys.executable, str(root / script)], cwd=root, capture_output=True, timeout=150)
        assert run.returncode == 0 and run.stderr == b''
        assert run.stdout == expected
        replay_results.append({'script': script, 'exit': 0, 'stderr_bytes': 0, 'stdout': identity(run.stdout), 'frozen_stdout_equal': True})
    outputs = read_json(root / 'analysis-output-index.json')
    for item in outputs['files']:
        assert identity((root / item['path']).read_bytes()) == item['identity']
    bindings = read_json(root / 'actual-test-runner-bindings.v2.json')['bindings']
    assert len(bindings) == 20
    core = [b for b in bindings if b['target'] == '//codex-rs/core:core-all-test']
    library = [b for b in bindings if b['target'] == '//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests']
    assert len(core) == 19 and len(library) == 1
    lib_run = library[0]
    assert lib_run['compact_file_digest_equals_this_attempt'] is True
    library_log = (root / lib_run['log']).read_text()
    new_cases = []
    for name in ['typed_setup_report_preserves_code_and_message_through_context', 'untyped_setup_report_preserves_context_chain_and_os_error']:
        full = 'setup_error::tests::' + name
        line = 'test ' + full + ' ... ok'
        assert library_log.count(line) == 1
        new_cases.append({'name': full, 'original_raw_occurrences_ok': 1, 'native_target': lib_run['target'], 'actual_tw_sequence': lib_run['actual_tw_sequence'], 'local': True, 'cached': False, 'actual_budget_ms': 300000, 'cfg': 'target_os = windows module; cfg(test) cases', 'source_head': HEAD, 'source_merge': MERGE})
    assert sum(b['passed'] for b in lib_run['libtest_batches']) == 141
    assert sum(b['failed'] for b in lib_run['libtest_batches']) == 13
    assert sum(b['ignored'] for b in lib_run['libtest_batches']) == 2
    assert library_log.count('PoisonError { .. }') == 6
    core7 = [b for b in core if '/shard_7_of_16/' in b['log']]
    assert len(core7) == 3
    assert [sum(x['failed'] for x in b['libtest_batches']) for b in core7] == [4, 3, 4]
    eof = []
    access = []
    for binding in core7:
        lines = (root / binding['log']).read_text().splitlines()
        for number, line in enumerate(lines, 1):
            if 'EOF while parsing a value at line 1 column 0' in line:
                assert 'parse deny-read ACL state' in line and 'deny_read_acl_state.json' in line
                eof.append({'path': binding['log'], 'line_number': number, 'line': line})
            if 'helper_unknown_error: apply deny-read ACLs:' in line and 'SetSecurityInfo failed' in line:
                access.append({'path': binding['log'], 'line_number': number, 'line': line})
    assert len(eof) == 2 and len({e['path'] for e in eof}) == 1
    assert 'test_attempts/attempt_2.log' in eof[0]['path']
    assert access
    core1 = [b for b in core if '/shard_1_of_16/' in b['log']]
    assert [b['original_test_exit'] for b in core1] == [1, 0]
    assert 'Error: agent thread limit reached' in (root / core1[0]['log']).read_text()
    primary = (root / 'primary/CompactSpawnLogContext.java').read_bytes()
    assert identity(primary)['git_blob'] == '62f3884f2c6c94f605a1748d4b1d5da431ea56d8'
    assert response(read_json(root / 'primary/CompactSpawnLogContext.java.GET.original.json'))['content'].encode() == primary
    assert b'input instanceof ParamFileActionInput ? null : input.getExecPathString()' in primary
    assert b'int id = entryMap.getOrDefault(key, 0);\n      if (id != 0) {\n        return id;' in primary
    assert sum(b['compact_file_digest_equals_this_attempt'] for b in bindings) == 17
    return {'schema': 'windows-setup-causes-native-qualification-v2', 'result': 'OFFLINE_ORIGINAL_EVIDENCE_VERIFIED', 'source_head': HEAD, 'source_merge': MERGE, 'source_tree': TREE, 'source_actual_postimages': source_postimages, 'source_cfg_gate': identity(lib), 'API_cut_records': 6, 'API_run_count': len(runs), 'API_job_count': len(all_jobs), 'API_original_parent': cut['parent_identity'], 'jobs': jobs, 'archives': archives, 'manifest_bindings': manifest_results, 'replays': replay_results, 'verified_generated_projections': len(outputs['files']), 'native_case_qualification': new_cases, 'library_batches': lib_run['libtest_batches'], 'library_total': {'passed': 141, 'failed': 13, 'ignored': 2, 'poison_errors_in_original': 6}, 'core_actual_attempts': 19, 'core_failed_attempts': sum(bool(x['original_test_exit']) for x in core), 'core_shard7': [{k: b[k] for k in ['actual_tw_sequence', 'attempt_ordinal_from_same_target_and_output_path', 'log', 'libtest_batches', 'failure_headers']} for b in core7], 'core_shard1': [{k: b[k] for k in ['actual_tw_sequence', 'log', 'libtest_batches', 'failure_headers']} for b in core1], 'EOF_original_lines': eof, 'ACL_error5_original_lines': access, 'compact_scope': {'record_counts': [89912, 87267], 'tw_executions': 20, 'xml_generator_spawns': 20, 'all_tw_local_noncached': True, 'fresh_first_or_single_attempt_digest_matches': 17, 'retry_digest_reuse_records': 3, 'retry_association': 'Original retention attempt path/order; XML exact duration/exit and full transcript; no new digest claim for repeated compact file path IDs.', 'primary': identity(primary)}, 'limits': ['Only two new case passes are qualified; whole Windows library and Core targets fail.', 'Six lock-poison test failures are retained; not described as six independent product mechanisms.', 'EOF appears in one attempt, twice as log and returned error. No writer/PID/timing observation proves its unique cause.', 'SetSecurityInfo error 5 is a distinct observed failure class and is not explained by EOF.', 'Old 340/ff2 native qualification does not transfer to later formatting commit 18bb or another source.', 'Other targets in the complete artifact are preserved without extending this narrow qualification; cached PTY receipt is not native acceptance.', 'No native product execution, dispatch, rerun, cancellation, timeout or test assertion changes were performed by this verifier.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve()), ensure_ascii=False, indent=2))
