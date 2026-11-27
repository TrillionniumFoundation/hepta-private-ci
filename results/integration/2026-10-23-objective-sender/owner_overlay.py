#!/usr/bin/env python3
"""Apply/verify a recorded candidate overlay over the exact original workspace."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path('/dev/shm/organ-3d6a75235bcb-hepta3398/source')
BASELINE = json.loads((ROOT / 'validation/base-blob-manifest.json').read_text())
BASE_BLOBS = {entry['path']: entry for entry in BASELINE['blobs']}

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def changes():
    rows = []
    for path in sorted((ROOT / 'change').rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(ROOT / 'change').as_posix()
        original = ROOT / 'base' / name
        data = path.read_bytes()
        if original.exists() and original.read_bytes() == data:
            continue
        base = BASE_BLOBS.get(name)
        if base:
            assert original.is_file() and blob(original.read_bytes()) == base['sha'], name
        else:
            assert not original.exists(), name
        rows.append({
            'path': name,
            'preimage_git_blob': base['sha'] if base else None,
            'preimage_sha256': digest(original.read_bytes()) if base else None,
            'candidate_git_blob': blob(data),
            'candidate_sha256': digest(data),
            'mode': base['mode'] if base else '100644',
            'bytes': len(data),
        })
    return rows

def actual_bytes(path, mode):
    return os.readlink(path).encode() if mode == '120000' else path.read_bytes()

def verify(rows):
    candidates = {entry['path']: entry for entry in rows}
    for name, entry in BASE_BLOBS.items():
        path = SOURCE / name
        expected = candidates.get(name, {}).get('candidate_git_blob', entry['sha'])
        assert blob(actual_bytes(path, entry['mode'])) == expected, ('source mismatch', name)
        if entry['mode'] != '120000':
            assert bool(path.stat().st_mode & 0o111) == (entry['mode'] == '100755'), ('source mode mismatch', name)
    for name, entry in candidates.items():
        assert digest((SOURCE / name).read_bytes()) == entry['candidate_sha256'], name
    known = set(BASE_BLOBS) | set(candidates)
    generated = []
    generated_path = 'codex-rs/target/nextest/local/junit.xml'
    if (SOURCE / generated_path).is_file():
        data = (SOURCE / generated_path).read_bytes()
        generated.append({'path': generated_path, 'sha256': digest(data), 'bytes': len(data)})
        known.add(generated_path)
    metadata = []
    git_file = SOURCE / '.git'
    if git_file.is_file():
        data = git_file.read_bytes()
        expected_pointer = f"gitdir: {ROOT / 'validation/format-baseline.git'}\n".encode()
        assert data == expected_pointer, 'unexpected validation Git metadata pointer'
        metadata.append({'path': '.git', 'sha256': digest(data), 'bytes': len(data), 'purpose': 'external exact-base validation Git metadata'})
        known.add('.git')
    extras = [p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob('*') if (p.is_file() or p.is_symlink()) and p.relative_to(SOURCE).as_posix() not in known]
    assert not extras, ('unrecorded source files', extras)
    return {'original_blob_count': len(BASE_BLOBS), 'candidate_paths': len(rows), 'unrecorded_differences': [], 'generated_test_artifacts': generated, 'local_validation_metadata': metadata}

def main():
    mode = sys.argv[1]
    rows = changes()
    identity_path = ROOT / 'validation/overlay-identity.json'
    if mode == 'apply':
        previous = json.loads(identity_path.read_text())['changes'] if identity_path.exists() else []
        verify(previous)
        for row in rows:
            path = SOURCE / row['path']
            data = (ROOT / 'change' / row['path']).read_bytes()
            if path.is_file() and path.read_bytes() == data:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o755 if row['mode'] == '100755' else 0o644)
        result = verify(rows)
        identity_path.write_text(json.dumps({'base_head': BASELINE['head'], 'base_tree': BASELINE['tree'], 'candidate_is_uncommitted_overlay': True, 'changes': rows, 'verification': result}, indent=2) + '\n')
    elif mode == 'verify':
        assert rows == json.loads(identity_path.read_text())['changes'], 'candidate changed since apply'
        result = verify(rows)
    elif mode == 'restore':
        previous = json.loads(identity_path.read_text())['changes']
        verify(previous)
        for row in previous:
            path = SOURCE / row['path']
            if row['preimage_git_blob'] is None:
                path.unlink()
            else:
                path.write_bytes((ROOT / 'base' / row['path']).read_bytes())
                path.chmod(0o755 if row['mode'] == '100755' else 0o644)
        git_file = SOURCE / '.git'
        if git_file.is_file():
            assert git_file.read_text() == f"gitdir: {ROOT / 'validation/format-baseline.git'}\n"
            git_file.unlink()
        result = verify([])
        identity_path.rename(ROOT / 'validation/last-restored-overlay-identity.json')
    else:
        raise ValueError(mode)
    print(json.dumps({'operation': mode, **result}))

if __name__ == '__main__':
    main()
