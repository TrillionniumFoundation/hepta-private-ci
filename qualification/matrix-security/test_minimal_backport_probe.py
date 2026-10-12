import subprocess
import tempfile
import unittest
from pathlib import Path

from minimal_backport_probe import CHANGESET, probe


class MinimalBackportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.release = base / "release"
        self.patch = base / "upstream-patch"
        self.release.mkdir()
        self._git(self.release, "init", "-q")
        sdk = self.release / "crates/matrix-sdk"
        (sdk / "src/event_handler").mkdir(parents=True)
        (sdk / "Cargo.toml").write_text(
            '[package]\nname="matrix-sdk"\nversion="0.19.1"\n'
            '[dependencies]\nanymap2={version="0.13.0",default-features=false}\n'
        )
        (sdk / "src/event_handler/mod.rs").write_text(
            "use anymap2::CloneAny;\n// Stable adjacent context\ntype AnyMap = anymap2::Map<dyn CloneAny>;\n"
        )
        (self.release / "Cargo.lock").write_text("[[package]]\nname=\"anymap2\"\nversion=\"0.13.0\"\n")
        self._commit(self.release, "release")
        self.release_sha = self._sha(self.release)
        subprocess.run(["git", "clone", "-q", str(self.release), str(self.patch)], check=True)
        (self.patch / "Cargo.lock").write_text("[[package]]\nname=\"anymap3\"\nversion=\"1.1.0\"\n")
        (self.patch / "crates/matrix-sdk/Cargo.toml").write_text(
            '[package]\nname="matrix-sdk"\nversion="0.19.1"\n'
            '[dependencies]\nanymap3={version="1.1.0",default-features=false}\n'
        )
        (self.patch / "crates/matrix-sdk/src/event_handler/mod.rs").write_text(
            "use anymap3::CloneAny;\n// Stable adjacent context\ntype AnyMap = anymap3::Map<dyn CloneAny>;\n"
        )
        self._commit(self.patch, "upstream anymap3 migration")
        self.patch_sha = self._sha(self.patch)

    def _git(self, path, *args):
        subprocess.run(["git", "-C", str(path), *args], check=True,
                       capture_output=True)

    def _sha(self, path):
        return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()

    def _commit(self, path, msg):
        self._git(path, "add", ".")
        self._git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                  "commit", "-qm", msg)

    def _probe(self):
        return probe(self.release, self.patch,
                     release_sha=self.release_sha, migration_sha=self.patch_sha)

    def test_upstream_source_diff_applies_to_published_release_without_mutation(self):
        report = self._probe()
        self.assertTrue(report["source_patch_applies_clean"])
        self.assertEqual(set(report["upstream_commit_changed_files"]), CHANGESET)
        self.assertEqual(len(report["source_patch_sha256"]), 64)
        self.assertFalse(report["production_authorized"])
        self.assertFalse(report["cargo_deny_verified"])
        self.assertIn("anymap2", (self.release / "crates/matrix-sdk/Cargo.toml").read_text())

    def test_reject_unexpected_extra_file_in_upstream_commit(self):
        (self.patch / "unexpected-trust-root.toml").write_text("bypass=true\n")
        self._commit(self.patch, "extra unreviewed source")
        self.patch_sha = self._sha(self.patch)
        with self.assertRaisesRegex(ValueError, "unexpected files"):
            self._probe()

    def test_exact_commit_mismatch_fails_before_any_source_read(self):
        with self.assertRaisesRegex(ValueError, "not the expected"):
            probe(self.release, self.patch,
                  release_sha="a" * 40, migration_sha=self.patch_sha)
        with self.assertRaisesRegex(ValueError, "not the expected"):
            probe(self.release, self.patch,
                  release_sha=self.release_sha, migration_sha="b" * 40)

    def test_dirty_candidate_checkout_rejected(self):
        (self.patch / "Cargo.lock").write_text("unexpected change")
        with self.assertRaisesRegex(ValueError, "dirty"):
            self._probe()

    def test_release_shape_drift_rejected(self):
        path = self.release / "crates/matrix-sdk/Cargo.toml"
        path.write_text(path.read_text().replace('version="0.19.1"', 'version="0.20.0"'))
        self._commit(self.release, "unauthorized release shape")
        self.release_sha = self._sha(self.release)
        with self.assertRaisesRegex(ValueError, "not exactly 0.19.1"):
            self._probe()

    def test_patch_conflict_is_not_a_success_and_release_stays_clean(self):
        path = self.release / "crates/matrix-sdk/src/event_handler/mod.rs"
        path.write_text("use anymap2::CloneAny;\ntype OtherMap = anymap2::Map<dyn CloneAny>;\n")
        self._commit(self.release, "alternate event-handler API")
        self.release_sha = self._sha(self.release)
        with self.assertRaisesRegex(ValueError, "incompatible with exact upstream AnyMap"):
            self._probe()
        self.assertEqual(path.read_text(), "use anymap2::CloneAny;\ntype OtherMap = anymap2::Map<dyn CloneAny>;\n")

    def test_later_upstream_context_drift_is_not_imported(self):
        manifest = self.release / "crates/matrix-sdk/Cargo.toml"
        manifest.write_text(manifest.read_text().replace(
            'anymap2={version="0.13.0",default-features=false}\n',
            'anymap2={version="0.13.0",default-features=false}\n'
            'unrelated_new_dependency="1.0"\n',
        ))
        self._commit(self.release, "only different dependency context")
        self.release_sha = self._sha(self.release)
        report = self._probe()
        self.assertTrue(report["source_patch_applies_clean"])
        self.assertFalse(report["upstream_raw_patch_applies_clean"])
        self.assertFalse(report["production_authorized"])
        self.assertIn('unrelated_new_dependency', manifest.read_text())

    def test_reject_nested_or_same_checkout_paths(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            probe(self.release, self.release, release_sha=self.release_sha,
                  migration_sha=self.release_sha)


if __name__ == "__main__":
    unittest.main()
