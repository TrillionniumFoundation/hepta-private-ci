import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "apps/hepta-native/tools/prepare_current_source.py"
)
spec = importlib.util.spec_from_file_location("prepare_current_source", SOURCE)
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class CurrentSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "core.autocrlf", "false"], cwd=self.root, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "test"], cwd=self.root, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "-q", "-b", source.BRANCH],
            cwd=self.root,
            check=True,
        )
        self.app = self.root / "apps/hepta-native"
        self.app.mkdir(parents=True)
        (self.app / "source.rs").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "source"], cwd=self.root, check=True)
        self.patches = [
            patch.object(source, "ROOT", self.root),
            patch.object(source, "APP", self.app),
            patch.object(source, "INTEGRATION_ROOTS", ()),
            patch.object(source, "INTEGRATION_FILES", ()),
            patch.dict(
                os.environ,
                {"HEPTA_UI_NATIVE_WRITE_BRANCH": source.BRANCH},
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def commit_manifest(self):
        source.fingerprint(True)
        subprocess.run(
            ["git", "add", "apps/hepta-native/CURRENT_SOURCE.json"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(["git", "commit", "-qm", "manifest"], cwd=self.root, check=True)

    def verify_output(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            source.fingerprint(False)
        return output.getvalue().strip()

    def test_fingerprints_only_committed_sources(self):
        self.commit_manifest()
        before = self.verify_output()
        (self.app / "target").mkdir()
        (self.app / "target/cache").write_text("ignored", encoding="utf-8")
        after = self.verify_output()
        self.assertEqual(before, after)
        manifest = json.loads((self.app / "CURRENT_SOURCE.json").read_text())
        self.assertEqual(manifest["schema"], "hepta.ui.native.current-source.v3")
        self.assertNotIn("files", manifest)
        self.assertEqual(manifest["inventoryPolicy"], source.inventory_policy())

    def test_manifest_stays_exact_with_windows_default_newlines(self):
        subprocess.run(
            ["git", "config", "core.autocrlf", "true"], cwd=self.root, check=True
        )
        write_text = Path.write_text

        def windows_default(path, data, *args, **kwargs):
            kwargs.setdefault("newline", "\r\n")
            return write_text(path, data, *args, **kwargs)

        with patch.object(Path, "write_text", windows_default):
            self.commit_manifest()
        manifest = self.app / "CURRENT_SOURCE.json"
        self.assertNotIn(b"\r\n", manifest.read_bytes())
        self.assertEqual(manifest.read_bytes(), source.committed_blob(manifest))
        self.assertIn("verified 1 native source identities", self.verify_output())

    def test_json_equivalent_crlf_manifest_is_still_rejected(self):
        self.commit_manifest()
        manifest = self.app / "CURRENT_SOURCE.json"
        committed = source.committed_blob(manifest)
        manifest.write_bytes(committed.replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(RuntimeError, "differs from committed bytes"):
            self.verify_output()

    def test_new_committed_source_is_automatically_inventoried(self):
        self.commit_manifest()
        before = self.verify_output()
        (self.app / "new.rs").write_text("new", encoding="utf-8")
        subprocess.run(
            ["git", "add", "apps/hepta-native/new.rs"], cwd=self.root, check=True
        )
        subprocess.run(
            ["git", "commit", "-qm", "new source"], cwd=self.root, check=True
        )
        after = self.verify_output()
        self.assertNotEqual(before, after)
        self.assertIn("verified 2 native source identities", after)

    def test_new_committed_source_cannot_be_hidden_by_manifest_policy(self):
        self.commit_manifest()
        manifest_path = self.app / "CURRENT_SOURCE.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inventoryPolicy"]["trackedRoots"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "narrow policy"], cwd=self.root, check=True
        )
        with self.assertRaises(RuntimeError):
            source.fingerprint(False)

    def test_stale_canonical_branch_rejected(self):
        self.commit_manifest()
        manifest_path = self.app / "CURRENT_SOURCE.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["canonicalBranch"] = "work/ui-native-stale"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "stale metadata"], cwd=self.root, check=True
        )
        with self.assertRaises(RuntimeError):
            source.fingerprint(False)

    def test_nonpromoting_flags_are_required(self):
        self.commit_manifest()
        manifest_path = self.app / "CURRENT_SOURCE.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["productionQualified"] = True
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "false claim"], cwd=self.root, check=True
        )
        with self.assertRaises(RuntimeError):
            source.fingerprint(False)

    def test_wrong_current_branch_refused(self):
        subprocess.run(
            ["git", "checkout", "-qb", "work/ui-native-other"],
            cwd=self.root,
            check=True,
        )
        with self.assertRaises(RuntimeError):
            source.fingerprint(True)

    def test_metadata_only_commit_is_not_selected_as_source(self):
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self.commit_manifest()
        docs = self.root / "docs/modules/ui.native"
        docs.mkdir(parents=True)
        (docs / "metadata.json").write_text("{}", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "metadata only"], cwd=self.root, check=True
        )
        resolved = source.git(
            "log", "-1", "--format=%H", "--", *source.SOURCE_LOG_PATHS
        )
        self.assertEqual(resolved, source_commit)

    def test_sync_registry_keeps_standalone_app_out_of_cargo_bindings(self):
        docs = self.root / "docs/modules"
        docs.mkdir(parents=True)
        (docs / "CARGO_BINDINGS.json").write_text(
            json.dumps(
                {
                    "bindings": [
                        {"package": "hepta-native", "packagePath": "apps/hepta-native"}
                    ]
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(RuntimeError):
            source.sync_registry_metadata()

    def test_retired_navigation_is_rewritten(self):
        value = {
            "source": "apps/hepta-native/src/native.js",
            "tests": ["apps/hepta-native/test/shell-runtime.test.js"],
            "commands": ["node --test apps/hepta-native/test/native.test.js"],
            "exports": ["buildNativeIntent", "observeNativeOutcome"],
        }
        rewritten = source.rewrite_retired_navigation(value)
        self.assertEqual(rewritten["source"], "apps/hepta-native/src/runtime.rs")
        self.assertEqual(rewritten["tests"][0], "apps/hepta-native/tests/runtime.rs")
        self.assertEqual(
            rewritten["commands"][0],
            "cargo test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets",
        )
        self.assertEqual(
            rewritten["exports"],
            ["request_platform_capability", "reconcile_pending"],
        )


if __name__ == "__main__":
    unittest.main()
