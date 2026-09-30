"""Synthetic readiness control-flow tests, never native execution evidence."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_readiness_manifest as readiness
from test_receipt_validation import receipt


class ReadinessManifestTest(unittest.TestCase):
    def setUp(self):
        self.root = readiness.ROOT
        self.head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()
        self.tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=self.root, text=True).strip()

    def base_command(self, output):
        return ["build_readiness_manifest.py", "--candidate-role", "source-head",
                "--source-head-sha", self.head, "--workflow-sha", self.head,
                "--workflow-run-id", "12345", "--attempt-id", "2", "--qualified",
                "--output", str(output)]

    def invoke(self, command, *, native=True, change=None, dirty="", parents=None):
        with tempfile.TemporaryDirectory() as directory:
            native_path = Path(directory) / "receipt.json"
            value = receipt()
            value.update(head=self.head, expectedSha=self.head, tree=self.tree, candidateRole="source-head",
                         passed=True, identityClean=True, workflowSha=self.head, workflowRunId="12345", workflowAttempt="2")
            if change:
                value.update(change)
            for row in value["checks"]:
                path = Path(directory) / (row["check"] + ".log")
                path.write_text("test result: ok. 3 passed; 0 failed; 0 ignored;\n")
                row["logSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            native_path.write_text(json.dumps(value))
            if native:
                command = command + ["--native-receipt", str(native_path)]
            original_run = readiness.run
            def synthetic_run(*args):
                if args == ("rustc", "--version", "--verbose"):
                    return receipt()["rustToolchain"]
                if args == ("git", "status", "--porcelain=v1", "--untracked-files=all"):
                    return dirty
                if parents is not None and args[:4] == ("git", "show", "-s", "--format=%P"):
                    return parents
                return original_run(*args)
            with patch("sys.argv", command), patch.object(readiness, "run", side_effect=synthetic_run), contextlib.redirect_stderr(io.StringIO()), patch.dict(os.environ, {"GITHUB_RUN_ID":"12345", "GITHUB_RUN_ATTEMPT":"2", "GITHUB_WORKFLOW_SHA":self.head}):
                readiness.main()

    def test_source_green_without_product_caller_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            self.invoke(self.base_command(output))
            value = json.loads(output.read_text())
            self.assertTrue(value["identityClosed"])
            self.assertTrue(value["readinessDimensions"]["sourceQualified"])
            self.assertTrue(value["nativeReceiptSha256"])
            self.assertFalse(value["readinessDimensions"]["productComposed"])
            self.assertIsNone(value["productCaller"])
            self.assertFalse(value["productionQualified"])
            self.assertFalse(value["mergeReady"])
            self.assertEqual(value["qualificationIdentity"]["source_tree_hash"], self.tree)

    def test_qualified_flag_without_retained_native_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            with self.assertRaisesRegex(SystemExit, "requires --native-receipt"):
                self.invoke(self.base_command(output), native=False)
            self.assertFalse(output.exists())

    def test_other_candidate_role_tree_run_attempt_or_toolchain_cannot_qualify(self):
        cases = [({"head":"0"*40,"expectedSha":"0"*40}, "exact current"),
                 ({"tree":"0"*40}, "exact current"),
                 ({"candidateRole":"synthetic-merge"}, "did not pass"),
                 ({"workflowRunId":"old-run"}, "execution identity"),
                 ({"workflowAttempt":"old-attempt"}, "execution identity"),
                 ({"workflowSha":"0"*40}, "execution identity"),
                 ({"rustToolchain":"rustc different"}, "toolchain")]
        for change, message in cases:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "receipt.json"
                with self.assertRaisesRegex((SystemExit, ValueError), message):
                    self.invoke(self.base_command(output), change=change)
                self.assertFalse(output.exists())

    def test_dirty_current_tree_cannot_receive_qualified_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            with self.assertRaisesRegex(SystemExit, "pristine"):
                self.invoke(self.base_command(output), dirty="?? invented.rs")
            self.assertFalse(output.exists())

    def test_cli_cannot_relabel_an_old_run_as_current_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            command = self.base_command(output)
            command[command.index("--workflow-run-id") + 1] = "old-run"
            with self.assertRaisesRegex(SystemExit, "current execution environment"):
                self.invoke(command, change={"workflowRunId":"old-run"})
            self.assertFalse(output.exists())

    def test_synthetic_readiness_rejects_wrong_base_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            command = self.base_command(output)
            command[command.index("--candidate-role") + 1] = "synthetic-merge"
            command += ["--base-sha", "b" * 40, "--deterministic-merge-sha", self.head]
            with self.assertRaisesRegex(SystemExit, "base and source parents"):
                self.invoke(command, change={"candidateRole":"synthetic-merge"}, parents="c" * 40 + " " + self.head)
            self.assertFalse(output.exists())

    def test_qualified_target_cannot_differ_from_executed_host(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            with self.assertRaisesRegex(SystemExit, "Rust host target"):
                self.invoke(self.base_command(output) + ["--target-triple", "invented-target"])
            self.assertFalse(output.exists())

    def test_mismatched_source_head_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            command = self.base_command(output)
            command[command.index("--source-head-sha") + 1] = "0" * 40
            with self.assertRaisesRegex(SystemExit, "must bind sourceHeadSha to exact HEAD"):
                self.invoke(command)
            self.assertFalse(output.exists())

    def test_incomplete_product_caller_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            manifest = Path(directory) / "caller.json"
            manifest.write_text(json.dumps({"schema":"hepta.secrets-heptabao-product-caller.v1", "callerId":"invented"}))
            with self.assertRaisesRegex(SystemExit, "fields differ"):
                readiness.load_product_caller(str(manifest))

    def test_registered_caller_is_source_bound_without_runtime_composition(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            self.invoke(self.base_command(output) + ["--product-caller-manifest", "docs/modules/secrets.heptabao/PRODUCT_CALLER_MANIFEST_V1.json"])
            value = json.loads(output.read_text())
            self.assertTrue(value["productCallerSourceBound"])
            self.assertFalse(value["readinessDimensions"]["productComposed"])

    def test_source_traversal_and_foreign_package_are_rejected(self):
        canonical = self.root / "docs/modules/secrets.heptabao/PRODUCT_CALLER_MANIFEST_V1.json"
        for field, changed, message in [("sourcePath", "../../outside.rs", "without traversal"),
                                        ("binaryPackage", "invented", "Cargo package")]:
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                manifest = Path(directory) / "caller.json"
                value = json.loads(canonical.read_text())
                value[field] = changed
                manifest.write_text(json.dumps(value))
                with self.assertRaisesRegex(SystemExit, message):
                    readiness.load_product_caller(str(manifest))

    def test_comment_only_constructor_cannot_manufacture_caller_evidence(self):
        canonical = self.root / "docs/modules/secrets.heptabao/PRODUCT_CALLER_MANIFEST_V1.json"
        source = self.root / "codex-rs/hepta-bao-adapter/src/product_bootstrap.rs"
        original_read = Path.read_text
        def synthetic_read(path, *args, **kwargs):
            if path == source:
                return '// pub fn compose_hepta_secrets_runtime() { SqliteBaoProductRuntimeV1::new(); } hepta-secrets-runtime'
            return original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", synthetic_read):
            with self.assertRaisesRegex(SystemExit, "non-test source"):
                readiness.load_product_caller(str(canonical))

    def test_unreachable_constructor_cannot_manufacture_library_binding(self):
        canonical = self.root / "docs/modules/secrets.heptabao/PRODUCT_CALLER_MANIFEST_V1.json"
        library = self.root / "codex-rs/hepta-bao-adapter/src/lib.rs"
        original_read = Path.read_text
        for fake, message in (
            ("// mod product_bootstrap; pub use product_bootstrap::compose_hepta_secrets_runtime;", "not compiled"),
            ("mod product_bootstrap; // pub use product_bootstrap::compose_hepta_secrets_runtime;", "not publicly exported"),
        ):
            def synthetic_read(path, *args, **kwargs):
                return fake if path == library else original_read(path, *args, **kwargs)
            with patch.object(Path, "read_text", synthetic_read):
                with self.assertRaisesRegex(SystemExit, message):
                    readiness.load_product_caller(str(canonical))

    def test_legacy_arbitrary_caller_string_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            with self.assertRaises(SystemExit):
                self.invoke(self.base_command(output) + ["--product-caller", "invented-caller"])
            self.assertFalse(output.exists())

    def test_ignored_document_cannot_change_same_candidate_hashes(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory(dir=self.root / "docs/modules/secrets.heptabao") as ignored:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            command = self.base_command(first)
            command.remove("--qualified")
            self.invoke(command, native=False)
            (Path(ignored) / ".DS_Store").write_bytes(b"uncommitted ignored metadata")
            command[command.index("--output") + 1] = str(second)
            self.invoke(command, native=False)
            before = json.loads(first.read_text())
            after = json.loads(second.read_text())
            for field in ("documentationSha256", "testSetSha256", "schemaSha256", "migrationSha256", "implementationMapSha256", "qualificationProfileSha256"):
                self.assertEqual(before[field], after[field])


if __name__ == "__main__":
    unittest.main()
