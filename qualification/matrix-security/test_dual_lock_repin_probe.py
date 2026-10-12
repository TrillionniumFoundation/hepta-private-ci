import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from dual_lock_repin_probe import inspect_pair, scratch_unlock_two, SOURCE_REV

MANIFEST = (f'[workspace.dependencies]\nmatrix-sdk = {{ git = "https://github.com/matrix-org/matrix-rust-sdk", '
            f'rev = "{SOURCE_REV}", version = "0.19.1", default-features = false, '
            'features = ["e2e-encryption", "sqlite"] }\n').encode()
LOCK = b'''version = 4

[[package]]
name = "async-trait"
version = "0.1.89"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "a" * 64

[[package]]
name = "bytes"
version = "1.11.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "b" * 64

[[package]]
name = "safe-dependency"
version = "3.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "c" * 64
'''.replace(b'"a" * 64', b'"' + b'a' * 64 + b'"').replace(b'"b" * 64', b'"' + b'b' * 64 + b'"').replace(b'"c" * 64', b'"' + b'c' * 64 + b'"')
ASYNC = f'''error: failed to select a version for `async-trait`.
... required by package `matrix-sdk v0.19.1 (?rev={SOURCE_REV})`
versions that meet the requirements `^0.1.92` are: 0.1.92
previously selected package `async-trait v0.1.89`
which satisfies dependency (locked to 0.1.89) of package `tonic v0.14.3`
'''
BYTES = f'''error: failed to select a version for `bytes`.
... required by package `matrix-sdk v0.19.1 (?rev={SOURCE_REV})`
versions that meet the requirements `^1.12.1` are: 1.12.1
previously selected package `bytes v1.11.1`
which satisfies dependency (locked to 1.11.1) of package `axum v0.8.8`
'''

class DualLockTests(unittest.TestCase):
    def test_exact_pair_accepted_but_no_security_claim(self):
        result = inspect_pair(ASYNC, BYTES, MANIFEST, LOCK)
        self.assertTrue(result["dual_conflict_exactly_verified"])
        for key in ("production_authorized", "cargo_deny_verified", "e2ee_verified", "cargo_resolution_verified"):
            self.assertFalse(result[key])

    def test_any_other_error_is_rejected(self):
        for wrong in ("" , "error: failed to select a version for `rusqlite`.",
                      ASYNC.replace("0.1.92", "0.1.91"),
                      ASYNC.replace("tonic v0.14.3", "evil v4")):
            with self.subTest(wrong=wrong):
                self.assertFalse(inspect_pair(wrong, BYTES, MANIFEST, LOCK)["dual_conflict_exactly_verified"])
        self.assertFalse(inspect_pair(ASYNC, BYTES.replace("^1.12.1", "^1.11.1"), MANIFEST, LOCK)["dual_conflict_exactly_verified"])

    def test_weak_feature_or_pin_fails(self):
        for manifest in (MANIFEST.replace(b'"sqlite"', b'"none"'),
                         MANIFEST.replace(SOURCE_REV.encode(), b'0'*40),
                         MANIFEST.replace(b'0.19.1', b'0.18.0')):
            self.assertFalse(inspect_pair(ASYNC, BYTES, manifest, LOCK)["dual_conflict_exactly_verified"])

    def test_lock_source_version_duplicate_and_missing_rejected(self):
        for sample in (LOCK.replace(b'0.1.89', b'0.1.91'),
                       LOCK.replace(b'1.11.1', b'1.12.1'),
                       LOCK.replace(b'crates.io-index', b'malicious-index'),
                       LOCK + LOCK.split(b'[[package]]')[1].join([b'\n[[package]]', b''])):
            self.assertFalse(inspect_pair(ASYNC, BYTES, MANIFEST, sample)["dual_conflict_exactly_verified"])

    def test_scratch_lock_only_drops_two_entries_and_keeps_others(self):
        result = scratch_unlock_two(LOCK)
        self.assertNotIn(b'name = "async-trait"', result)
        self.assertNotIn(b'name = "bytes"', result)
        self.assertIn(b'name = "safe-dependency"', result)
        self.assertEqual(result.count(b'[[package]]'), 1)

    def test_scratch_rejects_bad_lock(self):
        for sample in (LOCK.replace(b'0.1.89', b'0.1.92'), LOCK.replace(b'1.11.1', b'1.12.0'),
                       b'bad', LOCK + b'\n[[package]]\nname = "bytes"\nversion = "1.11.1"\n'):
            with self.assertRaises(ValueError):
                scratch_unlock_two(sample)

    def test_cli_never_modifies_inputs_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {"async": ASYNC.encode(), "bytes": BYTES.encode(), "Cargo.toml": MANIFEST, "Cargo.lock": LOCK}
            for name, content in files.items():
                (root / name).write_bytes(content)
            cmd = [sys.executable, str(Path(__file__).with_name("dual_lock_repin_probe.py")),
                   "--async-log", str(root / "async"), "--bytes-log", str(root / "bytes"),
                   "--manifest", str(root / "Cargo.toml"), "--lock", str(root / "Cargo.lock"),
                   "--report", str(root / "report.json"), "--scratch-lock", str(root / "scratch.lock")]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads((root / "report.json").read_text())["dual_conflict_exactly_verified"])
            for name, content in files.items():
                self.assertEqual((root / name).read_bytes(), content)
            repeat = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(repeat.returncode, 0)
            self.assertEqual((root / "Cargo.lock").read_bytes(), LOCK)
            cmd[-1] = str(root / "Cargo.lock")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)

if __name__ == "__main__":
    unittest.main()
