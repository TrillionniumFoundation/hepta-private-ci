import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from isolated_lock_repin_probe import inspect_lock_conflict, SOURCE_SHA

MANIFEST = ('[workspace.dependencies]\n'
            'matrix-sdk = { git = "https://github.com/matrix-org/matrix-rust-sdk", '
            'rev = "' + SOURCE_SHA + '", version = "0.19.1", '
            'default-features = false, features = ["e2e-encryption", "sqlite"] }\n').encode()
LOCK = b'version = 4\n\n[[package]]\nname = "async-trait"\nversion = "0.1.89"\n'
FAILURE = '''error: failed to select a version for `async-trait`.
    ... required by package `matrix-sdk v0.19.1 (https://github.com/matrix-org/matrix-rust-sdk?rev=b3c07ea6ba6e8e46e30811c0500b04505c4be9f9#b3c07ea6)`
versions that meet the requirements `^0.1.92` are: 0.1.92
  previously selected package `async-trait v0.1.89`
    ... which satisfies dependency `async-trait = "^0.1.13"` (locked to 0.1.89) of package `tonic v0.14.3`
'''

class IsolatedLockProbeTests(unittest.TestCase):
    def test_known_exact_conflict_can_be_diagnosed(self):
        r = inspect_lock_conflict(FAILURE, MANIFEST, LOCK)
        self.assertTrue(r['exact_obsolete_lock_conflict'])
        self.assertEqual(r['new_version'], '0.1.92')
        self.assertFalse(r['production_authorized'])
        self.assertFalse(r['security_advisories_resolved'])
        self.assertFalse(r['advisory_ignored'])

    def test_rejects_unrelated_failure(self):
        r = inspect_lock_conflict('error: SQLite links conflict', MANIFEST, LOCK)
        self.assertFalse(r['exact_obsolete_lock_conflict'])

    def test_rejects_incorrect_or_newer_old_lock(self):
        for version in ('0.1.88', '0.1.92', '0.1.95'):
            with self.subTest(version=version):
                self.assertFalse(inspect_lock_conflict(
                    FAILURE, MANIFEST, LOCK.replace(b'0.1.89', version.encode())
                )['exact_obsolete_lock_conflict'])

    def test_rejects_absent_lock_or_duplicate_version(self):
        for lock in [b'version=4\n', LOCK + LOCK.replace(b'version = 4',b'')]:
            self.assertFalse(inspect_lock_conflict(FAILURE, MANIFEST, lock)['exact_obsolete_lock_conflict'])

    def test_rejects_weakened_e2ee_or_sqlite(self):
        for stripped in [b'["sqlite"]', b'["e2e-encryption"]', b'[]']:
            m = MANIFEST.replace(b'["e2e-encryption", "sqlite"]', stripped)
            self.assertFalse(inspect_lock_conflict(FAILURE, m, LOCK)['exact_obsolete_lock_conflict'])

    def test_rejects_unpinned_commit_or_version(self):
        for m in [MANIFEST.replace(SOURCE_SHA.encode(), b'0'*40),
                  MANIFEST.replace(b'0.19.1', b'0.19.0')]:
            self.assertFalse(inspect_lock_conflict(FAILURE, m, LOCK)['exact_obsolete_lock_conflict'])

    def test_rejects_unsupported_or_mismatched_text(self):
        self.assertFalse(inspect_lock_conflict(FAILURE.replace('^0.1.92', '^0.1.90'), MANIFEST, LOCK)['exact_obsolete_lock_conflict'])
        self.assertFalse(inspect_lock_conflict(FAILURE.replace('tonic v0.14.3', 'other-pkg v1'), MANIFEST, LOCK)['exact_obsolete_lock_conflict'])
        self.assertFalse(inspect_lock_conflict('x' * 500001, MANIFEST, LOCK)['exact_obsolete_lock_conflict'])

    def test_cli_output_only_evidence_never_modifies_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            dir = Path(directory)
            for name, content in [('error.txt', FAILURE.encode()), ('Cargo.toml', MANIFEST), ('Cargo.lock', LOCK)]:
                (dir / name).write_bytes(content)
            path = dir / 'result.json'
            r = subprocess.run([sys.executable, str(Path(__file__).parent / 'isolated_lock_repin_probe.py'),
                                '--stderr', str(dir/'error.txt'), '--manifest', str(dir/'Cargo.toml'),
                                '--lock', str(dir/'Cargo.lock'), '--output', str(path)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(path.read_text())['exact_obsolete_lock_conflict'])
            self.assertEqual((dir / 'Cargo.lock').read_bytes(), LOCK)
            self.assertEqual((dir / 'Cargo.toml').read_bytes(), MANIFEST)


    def test_cli_cannot_overwrite_cargo_lock_or_manifest_through_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            manifest = stage / 'Cargo.toml'
            lock = stage / 'Cargo.lock'
            stderr = stage / 'stderr.log'
            manifest.write_bytes(MANIFEST)
            lock.write_bytes(LOCK)
            stderr.write_text(FAILURE)
            for original in (manifest, lock, stderr):
                path = stage / 'alias'
                if path.is_symlink():
                    path.unlink()
                path.symlink_to(original)
                r = subprocess.run([
                    sys.executable, str(Path(__file__).parent / 'isolated_lock_repin_probe.py'),
                    '--stderr', str(stderr), '--manifest', str(manifest),
                    '--lock', str(lock), '--output', str(path),
                ], capture_output=True, text=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('must not overwrite', r.stderr)
                self.assertEqual(manifest.read_bytes(), MANIFEST)
                self.assertEqual(lock.read_bytes(), LOCK)
                self.assertEqual(stderr.read_text(), FAILURE)


if __name__ == '__main__':
    unittest.main()
