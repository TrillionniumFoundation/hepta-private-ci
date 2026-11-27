#!/usr/bin/env python3
"""Validate the complete immutable source-exclusion download and replay metadata audit."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

BASE = Path(__file__).resolve().parent
WORKSPACE = BASE.parent
EXPECTED_COMMIT = '067e51225df5bdfa6fd9a2b5e5ab3ad2fbbc0312'
EXPECTED_BYTES = 68968
EXPECTED_SHA256 = '5d2780a32a4ae1b42925ce3b484c7b616e003a84679ae996b9862da427ad00b1'
EXPECTED_BLOB = '97bd07d1ec0efb027cc7737a47911ad128bd4c3c'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def require(ok, message):
    if not ok:
        raise ValueError(message)

def main():
    response = json.loads((BASE / 'SOURCE_ARCHIVE_READBACK.json').read_text())
    require(response['encoding'] == 'base64', 'encoding')
    encoded = response['content']
    require(set(encoded) <= set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r\t '), 'unexpected encoding characters')
    raw = base64.b64decode(''.join(encoded.split()), validate=True)
    require(len(raw) == EXPECTED_BYTES, 'archive length')
    require(sha(raw) == EXPECTED_SHA256, 'archive SHA256')
    require(blob(raw) == response['sha'] == EXPECTED_BLOB, 'archive Git blob')
    require(EXPECTED_COMMIT in response['display_url'], 'immutable download ref')
    require(raw == (WORKSPACE / 'mem-source-exclusion-20261111/source-exclusion-24files.tar.xz').read_bytes(), 'download differs from original archive')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as archive:
        for entry in archive:
            path = PurePosixPath(entry.name)
            require(entry.isfile() and not path.is_absolute() and '..' not in path.parts, 'unsafe member')
            require(entry.name not in files, 'duplicate member')
            require(entry.uid == entry.gid == entry.mtime == 0 and entry.mode == 0o644, 'archive properties')
            files[entry.name] = archive.extractfile(entry).read()
    require(len(files) == 25, 'member count')
    manifest = json.loads(files['MEMBER_MANIFEST.json'])
    require(manifest['original_file_count'] == len(manifest['files']) == 24, 'manifest count')
    require(set(files) == {x['path'] for x in manifest['files']} | {'MEMBER_MANIFEST.json'}, 'member roster')
    original = WORKSPACE / 'mem-source-exclusion-20261111'
    for row in manifest['files']:
        content = files[row['path']]
        require(len(content) == row['bytes'] and sha(content) == row['sha256'] and blob(content) == row['git_blob'], 'member hash: ' + row['path'])
        require(content == (original / row['path']).read_bytes(), 'original member: ' + row['path'])
    destination = BASE / 'readback/source-exclusion'
    for name, content in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    command = [sys.executable, str(destination / 'audit_source_exclusions.py'), '--root', str(destination), '--mem6-archive', str(WORKSPACE / 'mem6-github-full-copy/mem6-cas-001.tar.xz'), '--mem5-zip', str(original / 'inputs/mem5-audit-core-5fa0d0e.zip')]
    run = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    (BASE / 'SOURCE_OFFLINE_REPLAY.stdout.json').write_text(run.stdout)
    (BASE / 'SOURCE_OFFLINE_REPLAY.stderr.txt').write_text(run.stderr)
    require(run.returncode == 0 and run.stderr == '', 'offline replay failed: ' + run.stderr)
    replay = json.loads(run.stdout)
    require(replay['status'] == 'PASS' and replay['known_exclusion_count'] == 69 and replay['not_in_known_union_upper_bound'] == 16, 'replay result')
    require(replay['global_exposure_status'] == 'UNKNOWN' and replay['verified_unseen_capacity'] is None, 'unknown certification')
    result = {'schema': 'hepta.mem8.source-exclusion.root-readback.v1', 'immutable_commit': EXPECTED_COMMIT, 'archive': {'bytes': len(raw), 'sha256': sha(raw), 'git_blob': blob(raw)}, 'full_download': True, 'safe_regular_members': len(files), 'all_24_original_member_bytes_and_hashes_match': True, 'offline_replay_command': command, 'offline_replay_exit_code': run.returncode, 'offline_replay': replay, 'new_host_jobs': 0, 'new_model_calls': 0, 'new_actor_episodes': 0, 'passed': True}
    (BASE / 'ROOT_SOURCE_READBACK_AUDIT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
