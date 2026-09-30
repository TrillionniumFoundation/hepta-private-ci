import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class ReadinessManifestTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[3]
        self.script = Path(__file__).with_name("build_readiness_manifest.py")
        self.head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            text=True,
        ).strip()

    def base_command(self, output: Path) -> list[str]:
        return [
            "python3",
            str(self.script),
            "--candidate-role",
            "source-head",
            "--source-head-sha",
            self.head,
            "--workflow-sha",
            self.head,
            "--workflow-run-id",
            "12345",
            "--attempt-id",
            "2",
            "--qualified",
            "--output",
            str(output),
        ]

    def test_source_green_without_product_caller_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            subprocess.run(self.base_command(output), cwd=self.root, check=True)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema"], "hepta.secrets-heptabao-readiness.v3")
            self.assertTrue(receipt["identityClosed"])
            self.assertTrue(receipt["readinessDimensions"]["sourceQualified"])
            self.assertTrue(receipt["readinessDimensions"]["sourceImmutable"])
            self.assertFalse(receipt["readinessDimensions"]["productComposed"])
            self.assertIsNone(receipt["productCaller"])
            self.assertIsNone(receipt["productCallerManifestSha256"])
            self.assertFalse(receipt["productionQualified"])
            self.assertFalse(receipt["mergeReady"])
            self.assertEqual(receipt["candidateSha"], receipt["qualificationSha"])
            identity = receipt["qualificationIdentity"]
            self.assertEqual(identity["source_head_sha"], self.head)
            self.assertEqual(identity["workflow_sha"], self.head)
            self.assertEqual(identity["workflow_run_id"], "12345")
            self.assertEqual(identity["attempt_id"], "2")
            self.assertEqual(identity["source_tree_hash"], receipt["sourceTreeSha"])
            self.assertEqual(identity["cargo_lock_hash"], receipt["cargoLockHash"])

    def test_mismatched_source_head_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            command = self.base_command(output)
            index = command.index("--source-head-sha") + 1
            command[index] = "0" * 40
            result = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must bind sourceHeadSha to exact HEAD", result.stderr)
            self.assertFalse(output.exists())

    def test_incomplete_product_caller_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            directory_path = Path(directory)
            output = directory_path / "receipt.json"
            manifest = directory_path / "caller.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "hepta.secrets-heptabao-product-caller.v1",
                        "callerId": "invented-caller",
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                self.base_command(output)
                + ["--product-caller-manifest", str(manifest)],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("product caller manifest fields differ", result.stderr)
            self.assertFalse(output.exists())

    def test_legacy_arbitrary_caller_string_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            result = subprocess.run(
                self.base_command(output) + ["--product-caller", "invented-caller"],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unrecognized arguments", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
