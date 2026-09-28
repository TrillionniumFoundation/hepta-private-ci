import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import hepta_memory_retrieval_status as status


def git(root, *args, input_text=None):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_text,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class StatusManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Status fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        marker = self.root / "codex-rs/hepta-memory-retrieval/src/lib.rs"
        marker.parent.mkdir(parents=True)
        marker.write_text("// base\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")
        self.base = git(self.root, "rev-parse", "HEAD")

        mapping = {
            "module": "memory.retrieval",
            "productionImplementation": False,
            "claimBoundary": {claim: False for claim in status.CLAIMS},
        }
        path = self.root / status.MAP
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mapping))
        marker.write_text("// source\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "source")
        self.source = git(self.root, "rev-parse", "HEAD")
        self.main = self.base
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        self.synthetic = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input_text="synthetic\n",
        )
        self.checks = [
            {
                "id": index,
                "name": name,
                "head_sha": self.source,
                "status": "completed",
                "conclusion": "success",
                "app": {"slug": "github-actions"},
                "details_url": f"https://example.invalid/{index}",
            }
            for index, name in enumerate(status.REQUIRED_CHECKS, start=1)
        ]
        self.checks.extend(
            {
                "id": 100 + index,
                "name": name,
                "head_sha": self.source,
                "status": "completed",
                "conclusion": conclusion,
                "app": {"slug": "github-advanced-security"},
                "details_url": f"https://example.invalid/security/{index}",
            }
            for index, (name, conclusion) in enumerate(status.SECURITY_CHECKS.items())
        )

    def build(self):
        return status.build_manifest(
            self.root,
            self.source,
            self.base,
            self.main,
            self.synthetic,
            self.checks,
        )

    def test_manifest_binds_all_git_identities_and_stays_non_production(self):
        manifest = self.build()
        self.assertEqual(manifest["source_sha"], self.source)
        self.assertEqual(manifest["main_sha"], self.main)
        self.assertEqual(manifest["synthetic_base_sha"], self.base)
        self.assertEqual(manifest["synthetic_merge_sha"], self.synthetic)
        self.assertTrue(manifest["repository_checks_satisfied"])
        self.assertTrue(manifest["security_checks_satisfied"])
        self.assertFalse(manifest["external_gates_satisfied"])
        self.assertFalse(manifest["production_ready"])
        self.assertFalse(manifest["independent_acceptance"])
        self.assertEqual(manifest["activation_mode"], "compatibility")

    def test_latest_failed_check_wins(self):
        self.checks.append(
            {
                **self.checks[0],
                "id": 1000,
                "conclusion": "failure",
            }
        )
        manifest = self.build()
        self.assertFalse(manifest["repository_checks_satisfied"])
        self.assertFalse(manifest["production_ready"])

    def test_missing_check_is_explicit(self):
        self.checks = [row for row in self.checks if row["name"] != "CodeQL"]
        manifest = self.build()
        self.assertEqual(manifest["security_checks"]["CodeQL"]["status"], "not_observed")
        self.assertFalse(manifest["security_checks_satisfied"])

    def test_wrong_synthetic_parent_order_fails(self):
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        reversed_merge = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.source,
            "-p",
            self.base,
            input_text="reversed\n",
        )
        with self.assertRaises(status.StatusError):
            status.build_manifest(
                self.root,
                self.source,
                self.base,
                self.main,
                reversed_merge,
                self.checks,
            )

    def test_promoted_claim_is_refused(self):
        path = self.root / status.MAP
        mapping = json.loads(path.read_text())
        mapping["claimBoundary"]["activation"] = True
        path.write_text(json.dumps(mapping))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "bad claim")
        self.source = git(self.root, "rev-parse", "HEAD")
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        self.synthetic = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input_text="bad synthetic\n",
        )
        for row in self.checks:
            row["head_sha"] = self.source
        with self.assertRaises(status.StatusError):
            self.build()


if __name__ == "__main__":
    unittest.main()
