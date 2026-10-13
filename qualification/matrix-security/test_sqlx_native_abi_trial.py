"""Adversarial, model-free checks for the scratch-only SQLx native ABI trial."""

import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from sqlx_native_abi_trial import CANDIDATE, EXPECTED_OLD, SCHEMA, stage, trial

MANIFEST = (
    b'[package]\nname = "sqlx-sqlite"\nversion = "0.9.0"\nedition = "2021"\n'
    b'\n[dependencies.libsqlite3-sys]\n'
    b'version = ">=0.30.1, <0.38.0"\n'
    b'default-features = false\nfeatures = ["bundled"]\n'
    b'\n[dependencies.serde]\nversion = "1.0"\n'
)


def fixture_archive(source=MANIFEST, *, extra=None, symlink=False):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, payload in [
            ("sqlx-sqlite-0.9.0/Cargo.toml", source),
            ("sqlx-sqlite-0.9.0/src/lib.rs", b"pub fn example() {}\n"),
            *(extra or []),
        ]:
            info = tarfile.TarInfo(name)
            if symlink and name.endswith("src/lib.rs"):
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                info.size = 0
                tar.addfile(info)
            else:
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def fixture_lock(archive, *, source="registry+https://github.com/rust-lang/crates.io-index",
                 sqlx="0.9.0", sqlite="0.37.0", checksum=None):
    check = checksum or hashlib.sha256(archive).hexdigest()
    return (
        'version = 4\n'
        '[[package]]\nname = "sqlx-sqlite"\nversion = "0.9.0"\n'
        f'source = "{source}"\nchecksum = "{check}"\n'
        f'[[package]]\nname = "sqlx"\nversion = "{sqlx}"\n'
        f'[[package]]\nname = "libsqlite3-sys"\nversion = "{sqlite}"\n'
    ).encode()


class SqlxNativeAbiTrialTests(unittest.TestCase):
    def test_one_exact_pinned_manifest_delta(self):
        original = fixture_archive()
        files, report = trial(original, fixture_lock(original))
        self.assertEqual(report["schema"], SCHEMA)
        self.assertFalse(report["production_authorized"])
        self.assertFalse(report["native_compile_verified"])
        self.assertFalse(report["cargo_deny_verified"])
        self.assertEqual(
            files["sqlx-sqlite-0.9.0/Cargo.toml"],
            MANIFEST.replace(EXPECTED_OLD.encode(), CANDIDATE.encode()),
        )
        self.assertEqual(
            files["sqlx-sqlite-0.9.0/src/lib.rs"],
            b"pub fn example() {}\n",
        )

    def test_stage_writes_only_disposable_new_directory_and_report(self):
        archive = fixture_archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scratch = root / "scratch"
            scratch.mkdir()
            repo = root / "repo"
            (repo / "codex-rs").mkdir(parents=True)
            lock = repo / "codex-rs/Cargo.lock"
            lock.write_bytes(fixture_lock(archive))
            archive_file = scratch / "source.crate"
            archive_file.write_bytes(archive)
            dest = scratch / "candidate"
            receipt = scratch / "evidence.json"
            path, observed = stage(archive_file, lock, dest, receipt, scratch)
            self.assertEqual(path, dest / "sqlx-sqlite-0.9.0")
            self.assertIn(CANDIDATE, (path / "Cargo.toml").read_text())
            self.assertTrue(receipt.is_file())
            self.assertFalse(observed["hepta_cargo_lock_changed"])
            with self.assertRaisesRegex(ValueError, "detached outputs"):
                stage(archive_file, lock, dest, scratch / "second.json", scratch)

    def test_archive_checksum_or_source_substitution_fails_closed(self):
        archive = fixture_archive()
        for bad in [
            fixture_lock(archive, checksum="0" * 64),
            fixture_lock(archive, source="path+file:///tmp/forged-sqlx"),
            fixture_lock(archive, sqlx="0.8.6"),
            fixture_lock(archive, sqlite="0.38.2"),
        ]:
            with self.subTest(bad=bad[:80]):
                with self.assertRaises(ValueError):
                    trial(archive, bad)
        with self.assertRaisesRegex(ValueError, "checksum/size"):
            trial(archive + b"forged", fixture_lock(archive))

    def test_refuses_unrecognized_manifest_or_unrelated_patch(self):
        for mutated in [
            MANIFEST.replace(b"sqlx-sqlite", b"impostor"),
            MANIFEST.replace(b"0.9.0", b"0.10.0"),
            MANIFEST.replace(EXPECTED_OLD.encode(), b">=0.30.1, <0.37.0"),
            MANIFEST.replace(b"default-features = false", b"default-features = true").replace(
                EXPECTED_OLD.encode(), CANDIDATE.encode()
            ),
        ]:
            archive = fixture_archive(mutated)
            with self.subTest(mutated=mutated[:70]):
                with self.assertRaises(ValueError):
                    trial(archive, fixture_lock(archive))

    def test_rejects_tar_path_escape_duplicate_and_symlink(self):
        bad_archives = [
            fixture_archive(extra=[("../escape", b"secret")]),
            fixture_archive(extra=[("sqlx-sqlite-0.9.0/../escape", b"secret")]),
            fixture_archive(extra=[("sqlx-sqlite-0.9.0/Cargo.toml", MANIFEST)]),
            fixture_archive(symlink=True),
        ]
        for b in bad_archives:
            with self.subTest(n=hashlib.sha256(b).hexdigest()[:8]):
                with self.assertRaises(ValueError):
                    trial(b, fixture_lock(b))

    def test_refuses_unknown_output_locations_and_oversized_archives(self):
        archive = fixture_archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scratch = root / "scratch"
            scratch.mkdir()
            repo = root / "repo"
            (repo / "codex-rs").mkdir(parents=True)
            lock = repo / "codex-rs/Cargo.lock"
            lock.write_bytes(fixture_lock(archive))
            source = scratch / "archive"
            source.write_bytes(archive)
            with self.assertRaises(ValueError):
                stage(source, lock, scratch / "out", scratch / "out" / "receipt.json", scratch)
            symlink = scratch / "source-link"
            symlink.symlink_to(source)
            with self.assertRaises(ValueError):
                stage(symlink, lock, scratch / "out", scratch / "receipt.json", scratch)
            with self.assertRaisesRegex(ValueError, "confined"):
                stage(source, lock, repo / "injection", scratch / "receipt.json", scratch)
            with self.assertRaisesRegex(ValueError, "confined"):
                stage(source, lock, scratch / "out", repo / "injection.json", scratch)
            with self.assertRaisesRegex(ValueError, "confined"):
                stage(source, lock, repo / "injection", repo / "injection.json", repo)


if __name__ == "__main__":
    unittest.main()
