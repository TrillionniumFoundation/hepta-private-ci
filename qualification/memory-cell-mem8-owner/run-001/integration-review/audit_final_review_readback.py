#!/usr/bin/env python3
"""Audit the complete immutable GitHub download of the final static review bundle."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

BASE = Path(__file__).resolve().parent
WORK = BASE.parent
COMMIT = '049459ac4c2b8c5626668a80d38e5aedafeb0286'
REPO_PATH = 'qualification/memory-cell-mem8-owner/run-001/integration-review/mem8-composition-ci-blocker-review-v2.tar.xz'
EXPECTED_SHA256 = 'e5988a03861667afeb195e9c09bd6f43f89ea87d562ed59f281e2bded6afa46d'
EXPECTED_BLOB = 'ddbdcb458f0336d6162d9a90b942a3589c134eef'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def main():
    receipt = json.loads((BASE / 'FINAL_REVIEW_ARCHIVE_READBACK.json').read_text())
    assert receipt['encoding'] == 'base64' and receipt['sha'] == EXPECTED_BLOB
    assert receipt['display_url'] == 'https://github.com/TrillionniumFoundation/hepta-private-ci/blob/' + COMMIT + '/' + REPO_PATH
    encoded = receipt['content'].encode('ascii')
    clean = bytes(c for c in encoded if c not in b' \t\r\n\v\f')
    data = base64.b64decode(clean, validate=True)
    assert len(data) == 392476 and sha(data) == EXPECTED_SHA256 and blob(data) == EXPECTED_BLOB
    original = WORK / 'mem8-final-review-bundle-20261111/mem8-composition-ci-blocker-review-v2.tar.xz'
    assert original.read_bytes() == data
    (BASE / 'FINAL_REVIEW_DOWNLOADED.tar.xz').write_bytes(data)
    out = BASE / 'readback/integration-review'
    out.mkdir(parents=True, exist_ok=True)
    members = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as archive:
        for item in archive.getmembers():
            path = PurePosixPath(item.name)
            assert item.isfile() and not path.is_absolute() and '..' not in path.parts
            assert str(path) == item.name and item.name not in members
            raw = archive.extractfile(item).read()
            assert len(raw) == item.size
            members[item.name] = raw
    assert len(members) == 157
    manifest = json.loads(members['MEMBER_MANIFEST.json'])
    rows = {row['path']: row for row in manifest['files']}
    assert len(rows) == len(manifest['files']) == 156
    assert set(members) == set(rows) | {'MEMBER_MANIFEST.json'}
    for name, raw in members.items():
        assert (WORK / 'mem8-final-review-bundle-20261111/payload' / name).read_bytes() == raw
        if name in rows:
            row = rows[name]
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256'] and blob(raw) == row['git_blob_sha']
        dest = out / name
        assert not dest.is_symlink() and out.resolve() in dest.resolve().parents
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    verifier = out / 'verify_review_bundle.py'
    assert sha(verifier.read_bytes()) == 'ba44883e0d373f93da9b51633f1b4f1c771366faf0506e68ae704886645cbe09'
    # The root read this exact pinned script and its root_verify_trees dependency.
    # Both only inspect retained files; no native/model/network operation occurs.
    result = subprocess.run([sys.executable, '-B', str(verifier), str(out)], capture_output=True, text=True, check=True)
    assert not result.stderr
    replay = json.loads(result.stdout)
    assert replay['status'] == 'PASS' and replay['members'] == 157
    audit = {
        'schema': 'hepta.mem8.root-final-review-readback.v1',
        'passed': True,
        'immutable_commit': COMMIT,
        'repository_path': REPO_PATH,
        'full_remote_binary_readback': True,
        'archive_bytes': len(data),
        'archive_sha256': sha(data),
        'archive_git_blob_sha': blob(data),
        'regular_unique_members': len(members),
        'all_members_match_original_local_bytes': True,
        'all_156_manifest_entries_recomputed': True,
        'decoded_only_ascii_whitespace_before_strict_base64': True,
        'offline_replay': replay,
        'new_native_or_model_executions': 0,
        'combined_head_ci_pass_claimed': False,
        'original_blockers_closed_by_this_review': [],
    }
    (BASE / 'ROOT_FINAL_REVIEW_READBACK_AUDIT.json').write_text(json.dumps(audit, indent=2, sort_keys=True) + '\n')
    print(json.dumps(audit, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
