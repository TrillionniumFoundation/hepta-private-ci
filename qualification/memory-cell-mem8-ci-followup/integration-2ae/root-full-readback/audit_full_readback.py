#!/usr/bin/env python3
"""Replay reviewed, file-only readers against complete immutable Git downloads."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
REPO = 'https://github.com/TrillionniumFoundation/hepta-private-ci/blob/'
HEAD = '2ae5215beaf8d7b7df111a090b82134beae2683d'
TREE = '12159640adcf073b51f3837e75575e11f5c20233'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def safe_path(name):
    path = PurePosixPath(name)
    assert not path.is_absolute() and '..' not in path.parts and str(path) == name
    return path


def decode_readback(name, entry, commit):
    receipt = json.loads((HERE / ('READBACK_FULL_' + name + '.json')).read_text())
    assert receipt['encoding'] == 'base64' and receipt['sha'] == entry['sha']
    assert receipt['display_url'] == REPO + commit + '/' + entry['path']
    encoded = receipt['content'].encode('ascii')
    raw = base64.b64decode(bytes(c for c in encoded if c not in b' \t\r\n\v\f'), validate=True)
    assert git_blob(raw) == entry['sha']
    return raw


def unpack(raw, destination, manifest_name, rows_key, count):
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as archive:
        for entry in archive.getmembers():
            path = safe_path(entry.name)
            assert entry.isfile() and entry.name not in files
            content = archive.extractfile(entry).read()
            assert len(content) == entry.size
            files[str(path)] = content
    assert len(files) == count
    manifest = json.loads(files[manifest_name])
    rows = {row['path']: row for row in manifest[rows_key]}
    assert len(rows) == len(manifest[rows_key]) == count - 1
    assert set(rows) == set(files) - {manifest_name}
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if name in rows:
            assert len(content) == rows[name]['bytes'] and sha(content) == rows[name]['sha256']
        path = destination / name
        assert destination.resolve() in path.resolve().parents and not path.is_symlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


def main():
    publication = json.loads((HERE / 'FULL_STAGED_PUBLICATION.json').read_text())
    assert publication['commit'] == 'f94aec4112bf9f9aa76cb9a99c312a468b0cba06'
    entries = {PurePosixPath(row['path']).name: row for row in publication['entries']}
    original = WORK / 'mem-integrated-2ae-ci-evidence/complete-checkpoint'
    metadata = json.loads((original / 'ARCHIVE.json').read_text())
    chunks = []
    part_results = []
    offset = 0
    for part in metadata['parts']:
        assert part['offset'] == offset
        raw = decode_readback(part['path'], entries[part['path']], publication['commit'])
        assert len(raw) == part['bytes'] and sha(raw) == part['sha256']
        assert git_blob(raw) == part['git_blob']
        assert raw == (original / part['path']).read_bytes()
        offset += len(raw)
        chunks.append(raw)
        part_results.append({**part, 'full_remote_readback': True})
    assembled = b''.join(chunks)
    assert len(assembled) == metadata['bytes'] == 1521116
    assert sha(assembled) == metadata['sha256'] == '95e0a3f8366123c95d5b5a01ecffeff5ea6cbd9df693b08a4d6adc0fade57311'
    assert git_blob(assembled) == metadata['git_blob']
    assert assembled == (original / metadata['archive_file']).read_bytes()
    out = HERE / 'full-readback/mem-architecture'
    files = unpack(assembled, out, 'MEMBER_MANIFEST.json', 'members', 261)
    assert sha(files['MEMBER_MANIFEST.json']) == metadata['member_manifest_sha256']
    assert files['MEMBER_MANIFEST.json'] == (original / 'MEMBER_MANIFEST.json').read_bytes()
    index = json.loads(files['CHECKPOINT_INDEX.json'])
    assert index['source_sha'] == HEAD and index['source_tree'] == TREE

    # Verify original ZIP files and every file extracted by the first reader.
    zip_results = []
    for name, raw in files.items():
        if not name.endswith('.zip'):
            continue
        parent = str(PurePosixPath(name).parent)
        artifact = json.loads(files[parent + '/ARTIFACT_METADATA.json'])
        assert len(raw) == artifact['size_in_bytes']
        assert 'sha256:' + sha(raw) == artifact['digest']
        assert artifact['workflow_run']['head_sha'] == HEAD
        observed = set()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            assert archive.testzip() is None
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                safe_path(entry.filename)
                assert entry.filename not in observed
                observed.add(entry.filename)
                content = archive.read(entry)
                assert len(content) == entry.file_size
                assert content == files[parent + '/artifact/' + entry.filename]
        zip_results.append({'file': name, 'bytes': len(raw), 'sha256': sha(raw),
                            'original_members_verified': len(observed), 'crc': 'passed'})
    assert len(zip_results) == 5

    # These four scripts were read in full by root. They parse files and write
    # deterministic reports only. The downloader and all archived drivers are
    # retained as bytes and are never executed.
    replay = HERE / 'full-readback/offline-replay'
    data = replay / 'evidence'
    reference = replay / 'mem-final-composition-readonly'
    scripts = [
        ('audit_mem_python_artifacts.py', 'MEM_PYTHON_ARTIFACT_AUDIT.json'),
        ('native-owner/audit_native_artifact.py', 'native-owner/ARTIFACT_AUDIT.json'),
        ('architecture-source-head/audit_architecture_artifact.py', 'architecture-source-head/ARTIFACT_AUDIT.json'),
        ('architecture-base-merge/audit_base_merge_artifact.py', 'architecture-base-merge/ARTIFACT_AUDIT.json'),
    ]
    omitted = {report for _, report in scripts}
    for name, content in files.items():
        if name in omitted:
            continue
        dest = data / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        if name.startswith('reference/'):
            dest = reference / name[len('reference/'):]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
    replays = {}
    for script, report in scripts:
        assert files[script] == (WORK / 'mem-integrated-2ae-ci-evidence' / script).read_bytes()
        assert not (data / report).exists(), 'preserve previous replay rather than overwrite it'
        proc = subprocess.run([sys.executable, '-B', str(data / script)],
                              capture_output=True, text=True, check=True)
        assert not proc.stderr
        actual = json.loads((data / report).read_text())
        expected = json.loads(files[report])
        path_only_difference = None
        if report.startswith('native-owner/'):
            path_only_difference = {'original': expected.pop('source_plan_file'),
                                    'replayed': actual.pop('source_plan_file')}
            assert actual['source_plan_sha256'] == sha(files['reference/GIT_TREE_PLAN.json'])
        assert actual == expected, report
        replays[script] = {'report_sha256': sha((data / report).read_bytes()),
                           'all_report_fields_match_except_explicit_local_path': True,
                           'path_only_difference': path_only_difference,
                           'stdout': json.loads(proc.stdout)}

    failure_name = 'mem8-integrated-blocking-2ae-original-failures-v1.tar.xz'
    raw = decode_readback(failure_name, entries[failure_name], publication['commit'])
    assert len(raw) == 143988 and sha(raw) == '79617d8154e0055d34c38cb0f9d9f46fb4ae1f15d777ad61b20631884d599cd1'
    assert raw == (WORK / 'mem-integrated-ci-watch-2ae' / failure_name).read_bytes()
    failed = unpack(raw, HERE / 'full-readback/blocking-original', 'FILE_MANIFEST.json', 'files', 25)
    failure_reports = []
    for directory, job, marker in [
        ('build-test-failure', 130374692127, 'FAIL_HEPTA_CALLER_PROOF'),
        ('bazel-clippy-failure', 130374692388, 'await_holding_invalid_type'),
    ]:
        summary = json.loads(failed[directory + '/ORIGINAL_FAILURE_SUMMARY.json'])
        assert summary['job_id'] == job and summary['run_head'] == HEAD
        assert summary['actual_tree'] == TREE
        log = failed[directory + '/job-' + str(job) + '-decoded.log']
        prefix = 'full_' if directory == 'build-test-failure' else ''
        assert len(log) == summary[prefix + 'decoded_log_bytes']
        assert sha(log) == summary[prefix + 'decoded_log_sha256']
        assert marker in log.decode()
        failure_reports.append({'job_id': job, 'bytes': len(log), 'sha256': sha(log),
                                'original_failure_retained': True})

    report = {
        'schema': 'mem8.ci-followup-v10.complete-root-readback.v1', 'passed': True,
        'immutable_commit': publication['commit'], 'source_sha': HEAD, 'source_tree': TREE,
        'parts': part_results, 'assembled_archive_bytes': len(assembled),
        'assembled_archive_sha256': sha(assembled), 'archive_members': 261,
        'manifest_entries_verified': 260, 'original_zip_archives': zip_results,
        'offline_reader_replays': replays, 'execution_counts': index['runs'],
        'original_failure_archive_members': 25, 'original_failures': failure_reports,
        'previous_root_readback': 'eae8aefe6faaa8fd827471d285d68ff7e4238fb1',
        'previous_root_readback_members': 422,
        'native_or_model_executions_in_this_audit': 0,
        'ignored_provider_tests_executed_by_this_audit': 0,
        'whole_integrated_ci_pass_claimed': False,
        'source_result_transfer_to_any_repair_head': False,
        'prepublication_metadata_left_immutable': True,
    }
    (HERE / 'ROOT_FULL_READBACK_AUDIT.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
