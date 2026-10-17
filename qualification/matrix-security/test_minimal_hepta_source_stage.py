"""Adversarial, offline tests for the disposable minimal Matrix upgrade arm."""

import hashlib
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

from minimal_hepta_source_stage import prepare, rewrite_manifest
from staged_resolution_probe import SOURCE_SPEC, SQLITE_PATCH_SPEC


def fixture_manifest():
    return (
        '[workspace]\nmembers=[]\n'
        '[workspace.dependencies]\n' + SOURCE_SPEC + '\n'
        '[patch.crates-io]\n' + SQLITE_PATCH_SPEC + '\n'
    ).encode("utf-8")


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


class MinimalHeptaSourceStageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.stage = self.base / "detached-Hepta"
        self.stage.mkdir()
        (self.stage / "codex-rs").mkdir()
        (self.stage / "codex-rs/Cargo.toml").write_bytes(fixture_manifest())
        git(self.stage, "init", "-q")
        git(self.stage, "config", "user.email", "test@example.invalid")
        git(self.stage, "config", "user.name", "Offline Test")
        git(self.stage, "add", "codex-rs/Cargo.toml")
        git(self.stage, "commit", "-qm", "baseline")
        git(self.stage, "checkout", "--detach", "HEAD")
        self.sha = git(self.stage, "rev-parse", "HEAD")
        self.release = self.base / "audited-release"
        self.migration = self.base / "audited-patch"
        self.release.mkdir()
        self.migration.mkdir()
        self.candidate = self.base / "minimal-source"

    def build_source(self, release, migration, destination):
        self.assertEqual(release, self.release)
        self.assertEqual(migration, self.migration)
        path = destination / "crates/matrix-sdk"
        path.mkdir(parents=True)
        (path / "Cargo.toml").write_text(
            '[package]\nname="matrix-sdk"\nversion="0.19.1"\n'
            '[dependencies]\nanymap3 = {version="1.1.0"}\n'
        )
        return {
            "release_commit": "a" * 40,
            "migration_commit": "b" * 40,
            "applied_source_patch_sha256": "c" * 64,
            "anymap2_source_dependency_removed": True,
            "production_authorized": False,
        }

    def test_single_exact_workspace_rewrite_preserves_e2ee_and_sqlite(self):
        self.candidate.joinpath("crates/matrix-sdk").mkdir(parents=True)
        data = rewrite_manifest(fixture_manifest(), self.stage / "codex-rs", self.candidate)
        doc = tomllib.loads(data.decode())
        sdk = doc["workspace"]["dependencies"]["matrix-sdk"]
        self.assertEqual(sdk["features"], ["e2e-encryption", "sqlite"])
        self.assertFalse(sdk["default-features"])
        self.assertEqual(sdk["path"], "../../minimal-source/crates/matrix-sdk")
        self.assertNotIn("matrix-sdk-sqlite", doc["patch"]["crates-io"])
        self.assertNotIn(SOURCE_SPEC, data.decode())

    def test_unsupported_baseline_or_sneaky_feature_mutation_is_rejected(self):
        self.candidate.joinpath("crates/matrix-sdk").mkdir(parents=True)
        for original in (
            fixture_manifest().replace(b'"sqlite"', b'"sqlite", "unsafe-bypass"'),
            fixture_manifest().replace(b'matrix-sdk =', b'matrix-other =', 1),
            fixture_manifest() + (SOURCE_SPEC + "\n").encode(),
            fixture_manifest().replace(SQLITE_PATCH_SPEC.encode(), b""),
        ):
            with self.subTest(original=original[:80]):
                with self.assertRaises(ValueError):
                    rewrite_manifest(original, self.stage / "codex-rs", self.candidate)

    def test_source_must_be_a_separate_dir_with_complete_sdk(self):
        with self.assertRaises(ValueError):
            rewrite_manifest(fixture_manifest(), self.stage / "codex-rs", self.stage)
        with self.assertRaises(ValueError):
            rewrite_manifest(fixture_manifest(), self.stage / "codex-rs", self.candidate)

    def test_success_is_never_marked_production_authorized(self):
        result = prepare(
            self.stage, self.release, self.migration, self.candidate,
            self.sha, source_builder=self.build_source,
        )
        self.assertEqual(result["hepta_source_sha"], self.sha)
        self.assertEqual(result["sqlite_arm"], "genuine_upstream_0_19_sqlite")
        self.assertTrue(all(result[field] is False for field in (
            "cargo_resolution_verified", "hepta_matrix_compile_verified",
            "matrix_e2ee_verified", "sqlite_wal_recovery_verified",
            "cargo_deny_verified", "production_authorized", "production_source_modified",
        )))
        self.assertEqual(
            result["hepta_manifest_before_sha256"], hashlib.sha256(fixture_manifest()).hexdigest(),
        )
        self.assertEqual(git(self.stage, "diff", "--name-only"), "codex-rs/Cargo.toml")
        self.assertIn("../../minimal-source/crates/matrix-sdk", (
            self.stage / "codex-rs/Cargo.toml").read_text())

    def test_source_sha_dirty_worktree_or_occupied_destination_fail_before_clone(self):
        for sha in ("0" * 40, "not-a-commit"):
            with self.subTest(sha=sha):
                with self.assertRaises(ValueError):
                    prepare(self.stage, self.release, self.migration, self.candidate, sha,
                            source_builder=lambda *args: self.fail("untrusted source called"))
        (self.stage / "untracked").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "dirty"):
            prepare(self.stage, self.release, self.migration, self.candidate, self.sha,
                    source_builder=lambda *args: self.fail("untrusted source called"))
        (self.stage / "untracked").unlink()
        self.candidate.mkdir()
        with self.assertRaisesRegex(ValueError, "new patched SDK"):
            prepare(self.stage, self.release, self.migration, self.candidate, self.sha,
                    source_builder=lambda *args: self.fail("untrusted source called"))

    def test_wrong_source_review_status_or_sdk_version_rejected(self):
        def unapproved(release, migration, destination):
            result = self.build_source(release, migration, destination)
            result["anymap2_source_dependency_removed"] = False
            return result
        with self.assertRaisesRegex(ValueError, "unverified"):
            prepare(self.stage, self.release, self.migration, self.candidate, self.sha,
                    source_builder=unapproved)
        # Source identity checks also fail if a staged 0.19.0 SDK is supplied.
        import shutil
        shutil.rmtree(self.candidate)
        def obsolete(release, migration, destination):
            result = self.build_source(release, migration, destination)
            p = destination / "crates/matrix-sdk/Cargo.toml"
            p.write_text(p.read_text().replace('0.19.1', '0.19.0'))
            return result
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            prepare(self.stage, self.release, self.migration, self.candidate, self.sha,
                    source_builder=obsolete)


if __name__ == "__main__":
    unittest.main()
