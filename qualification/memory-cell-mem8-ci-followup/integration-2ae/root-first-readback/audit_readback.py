#!/usr/bin/env python3
"""Verify full immutable downloads and replay the retained subset audits offline."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

BASE = Path(__file__).resolve().parent
WORK = BASE.parent

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def main():
    publication = json.loads((BASE / 'STAGED_PUBLICATION.json').read_text())
    assert publication['commit'] == 'eae8aefe6faaa8fd827471d285d68ff7e4238fb1'
    archives = []
    paths = {}
    for package in publication['packages']:
        name = package['name']
        receipt = json.loads((BASE / ('READBACK_' + name + '.json')).read_text())
        assert receipt['encoding'] == 'base64' and receipt['sha'] == package['git_blob']
        assert receipt['display_url'] == 'https://github.com/TrillionniumFoundation/hepta-private-ci/blob/' + publication['commit'] + '/' + package['path']
        encoded = receipt['content'].encode('ascii')
        raw = base64.b64decode(bytes(c for c in encoded if c not in b' \t\r\n\v\f'), validate=True)
        assert len(raw) == package['bytes'] and sha(raw) == package['sha256']
        assert git_blob(raw) == package['git_blob']
        assert raw == (WORK / 'mem-integrated-ci-watch-2ae' / package['archive_name']).read_bytes()
        (BASE / package['archive_name']).write_bytes(raw)
        out = BASE / 'readback' / name
        out.mkdir(parents=True, exist_ok=True)
        members = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as archive:
            for entry in archive.getmembers():
                p = PurePosixPath(entry.name)
                assert entry.isfile() and not p.is_absolute() and '..' not in p.parts
                assert str(p) == entry.name and entry.name not in members
                content = archive.extractfile(entry).read()
                assert len(content) == entry.size
                members[entry.name] = content
        assert len(members) == package['members']
        manifest = json.loads(members['FILE_MANIFEST.json'])
        assert manifest['manifest_excludes_itself'] is True
        rows = {r['path']: r for r in manifest['files']}
        assert len(rows) == len(manifest['files']) == len(members) - 1
        assert set(rows) == set(members) - {'FILE_MANIFEST.json'}
        for path, content in members.items():
            if path in rows:
                assert len(content) == rows[path]['bytes'] and sha(content) == rows[path]['sha256']
            destination = out / path
            assert not destination.is_symlink() and out.resolve() in destination.resolve().parents
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        paths[name] = out
        archives.append({'name': name, 'archive_bytes': len(raw), 'archive_sha256': sha(raw),
                         'archive_git_blob': git_blob(raw), 'members': len(members),
                         'full_remote_bytes_match_original': True, 'all_member_hashes_recomputed': True})
    # Retained verifiers were read by root before execution; they inspect only
    # these files and write deterministic audit JSON. No driver is executed.
    cleanup = paths['cleanup-readback']
    shutil.copyfile(BASE / 'mem8-superseded-component-ci-cleanup-v1-v2.tar.xz',
                    cleanup / 'mem8-superseded-component-ci-cleanup-v1-v2.tar.xz')
    outputs = {}
    for name, folder, script, report in [
        ('cleanup', cleanup, 'verify_cleanup.py', 'CLEANUP_INDEPENDENT_AUDIT.json'),
        ('windows_private', paths['windows-private'], 'verify_windows_private.py', 'WINDOWS_PRIVATE_INDEPENDENT_AUDIT.json'),
    ]:
        expected_report = (folder / report).read_bytes()
        verified_script = WORK / 'mem-integrated-ci-watch-2ae' / (('private-state/' if name == 'windows_private' else '') + script)
        assert (folder / script).read_bytes() == verified_script.read_bytes()
        result = subprocess.run([sys.executable, '-B', str(folder / script)], capture_output=True, text=True, check=True)
        assert not result.stderr and (folder / report).read_bytes() == expected_report
        outputs[name] = json.loads(result.stdout)
    assert outputs['cleanup']['independent_final_runs_cancelled'] == 11
    assert outputs['cleanup']['standard_cancel_http_202'] == 11
    assert outputs['cleanup']['force_cancel_http_202'] == 5
    assert outputs['cleanup']['integration_run_ids_cancelled'] == []
    assert outputs['windows_private']['regular_native_unique_cases'] == 34
    assert outputs['windows_private']['signed_credit']['passed'] == 1
    assert outputs['windows_private']['signed_credit']['retries'] == 0
    audit = {'schema': 'mem8.ci-followup-v10.root-readback.v1', 'passed': True,
             'immutable_commit': publication['commit'], 'archives': archives,
             'offline_replays': outputs, 'new_native_or_model_executions': 0,
             'integration_required_ci_pass_claimed': False,
             'original_2ae_caller_and_clippy_failures_still_open': True,
             'cancelled_old_runs_counted_as_pass': False,
             'source_result_transfer_to_a_repair_head': False}
    (BASE / 'ROOT_READBACK_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps(audit, indent=2))

if __name__ == '__main__':
    main()
