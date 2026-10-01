from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2 import product_gate
import test_product_gate as fixtures


class ProductGateCliTests(unittest.TestCase):
    def test_real_repository_cli_executes_fenced_lifecycle_without_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repository"
            root.mkdir()
            def git(*args):
                return subprocess.run(
                    ["git", "-C", str(root), *args], check=True,
                    capture_output=True, text=True,
                ).stdout.strip()
            git("init", "-q")
            git("config", "user.name", "Product CLI test")
            git("config", "user.email", "product@example.invalid")
            git("remote", "add", "origin", "https://github.com/" + product_gate.EXPECTED_REPOSITORY + ".git")
            target = root / product_gate.CANONICAL_WORK_PACKAGE_PATH
            target.parent.mkdir(parents=True)
            target.write_text(fixtures.CANONICAL_REGISTRY, encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "product fixture")
            source = git("rev-parse", "HEAD")
            destination = Path(temporary) / "receipt.json"
            arguments = [
                "--repository", str(root), "--repository-full-name", product_gate.EXPECTED_REPOSITORY,
                "--repository-id", str(product_gate.EXPECTED_REPOSITORY_ID),
                "--workflow-ref", product_gate.EXPECTED_REPOSITORY + product_gate.EXPECTED_WORKFLOW_SUFFIX + "@refs/heads/main",
                "--job-name", product_gate.EXPECTED_JOB, "--run-id", "123", "--run-attempt", "1",
                "--source-sha", source, "--event-name", "push", "--lane", "source-head",
                "--pull-request-number", "0", "--output", str(destination),
            ]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(product_gate.main(arguments), 0)
            receipt = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(receipt["testedSha"], source)
            self.assertEqual(receipt["workerLifecycle"]["reopenedState"], "completed_observed")
            self.assertEqual(receipt["integrationReconciliation"]["reopenedTerminalState"], "terminal_merged")
            self.assertFalse(receipt["independentCompletionProved"])
            self.assertFalse(receipt["externalEffectAuthority"])
            self.assertFalse(receipt["mergeAuthority"])
            self.assertEqual(git("status", "--porcelain"), "")
            arguments[arguments.index("--repository-full-name") + 1] = "unrelated/repository"
            destination.unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(product_gate.main(arguments), 1)
            self.assertFalse(json.loads(output.getvalue())["authorityGranted"])
            self.assertFalse(destination.exists())
