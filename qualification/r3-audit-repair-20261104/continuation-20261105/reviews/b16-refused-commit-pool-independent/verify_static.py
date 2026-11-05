#!/usr/bin/env python3
"""Verify candidate bytes and isolated patch roundtrips; run no product code."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

WORK = Path('/workspace/scratch/07dd58cc9630')
SOURCE = WORK / 'architecture-audit/b16-refused-commit-pool-20261105'
OUT = Path(__file__).resolve().parent


def identity(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()}


manifest = json.loads((SOURCE / 'manifest.json').read_bytes())
assert identity(SOURCE / 'manifest.json')['blob'] == '28a0ccb97b740c6d18561c9bf2d63616db881189'
verified = []
for row in manifest['files'].values():
    value = identity(WORK / row['path'])
    assert (value['bytes'], value['sha256'], value['blob']) == (row['bytes'], row['sha256'], row['git_blob'])
    verified.append(value)
commands = []


def run(directory, argv):
    result = subprocess.run(argv, cwd=directory, capture_output=True, text=True)
    commands.append({'argv': argv, 'exit_code': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr})
    assert result.returncode == 0


with tempfile.TemporaryDirectory(prefix='patch-only-', dir=OUT) as temporary:
    root = Path(temporary)
    run(root, ['git', 'init', '--quiet'])
    file = root / 'codex-rs/state/src/sqlite.rs'
    file.parent.mkdir(parents=True)
    file.write_bytes((SOURCE / 'preimage-sqlite.rs').read_bytes())
    for patch, expected in [
        ('controls-only.patch', 'baseline-with-controls-sqlite.rs'),
        ('production-only.patch', 'postimage-sqlite.rs'),
        ('negative-restore-production.patch', 'baseline-with-controls-sqlite.rs'),
        ('production-only.patch', 'postimage-sqlite.rs'),
    ]:
        run(root, ['git', 'apply', '--check', str(SOURCE / patch)])
        run(root, ['git', 'apply', str(SOURCE / patch)])
        assert file.read_bytes() == (SOURCE / expected).read_bytes()
        assert (file.parent / 'sqlite_refused_commit_pool_tests.rs').read_bytes() == (SOURCE / 'sqlite_refused_commit_pool_tests.rs').read_bytes()
    run(root, ['git', 'apply', '--reverse', '--check', str(SOURCE / 'full.patch')])
    run(root, ['git', 'apply', '--reverse', str(SOURCE / 'full.patch')])
    assert file.read_bytes() == (SOURCE / 'preimage-sqlite.rs').read_bytes()
    assert not (file.parent / 'sqlite_refused_commit_pool_tests.rs').exists()
    run(root, ['git', 'apply', '--check', str(SOURCE / 'full.patch')])
    run(root, ['git', 'apply', str(SOURCE / 'full.patch')])
    assert file.read_bytes() == (SOURCE / 'postimage-sqlite.rs').read_bytes()

primary_root = WORK / 'architecture-audit/pr4855-refused-commit-20261105/source/actual-registry'
primary = [identity(primary_root / name) for name in [
    'sqlx-sqlite/src/connection/worker.rs', 'sqlx-core/src/connection.rs', 'sqlx-core/src/pool/inner.rs']]
tests = (SOURCE / 'sqlite_refused_commit_pool_tests.rs').read_text().splitlines()
assert tests[115].strip() == 'observation.expect("read transaction must remain available after a refused commit");'
receipt = {'schema': 'hepta-independent-patch-only-verification-v1',
    'candidate_manifest_blob': '28a0ccb97b740c6d18561c9bf2d63616db881189',
    'verified_manifest_files': verified, 'commands': commands,
    'controls_production_negative_restore_full_roundtrip_exact': True,
    'same_two_test_bodies_across_all_stages': True, 'unique_negative_panic_line': 116,
    'primary_source_identities': primary, 'product_commands_executed': False,
    'cargo_or_native_execution': False, 'shared_source_or_refs_modified': False}
(OUT / 'static-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'commands': len(commands), 'all_exit_zero': True, 'receipt': identity(OUT / 'static-verification.json')}))
