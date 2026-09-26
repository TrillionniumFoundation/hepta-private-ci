from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hepta-supervisor-acceptance-bundle.py"
LANES = {
    "linux-source-head": ("linux", 256, "source"),
    "linux-merge-candidate": ("linux", 8, "merge"),
    "darwin-source-head": ("darwin", 64, "source"),
    "darwin-merge-candidate": ("darwin", 8, "merge"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SupervisorAcceptanceBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        self.source_tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
        ).strip()
        self.base_commit = "2" * 40
        self.merge_commit = "3" * 40
        self.merge_tree = "4" * 40

    def make_fixture(self, root: Path) -> tuple[list[str], list[str], Path]:
        artifacts_root = root / "artifacts"
        artifacts_root.mkdir()
        artifacts: dict[str, Path] = {}
        for name in (
            "hepta-supervisord",
            "hepta-supervisor-release-controller",
            "hepta-authority-signer",
        ):
            path = artifacts_root / name
            path.write_bytes(f"fixture:{name}".encode())
            path.chmod(0o700)
            artifacts[name] = path
        supervisord_digest = sha256(artifacts["hepta-supervisord"])

        lane_arguments: list[str] = []
        for label, (platform, instances, identity) in LANES.items():
            lane = root / label
            lane.mkdir()
            commit = self.source_commit if identity == "source" else self.merge_commit
            tree = self.source_tree if identity == "source" else self.merge_tree
            parents = [self.base_commit] if identity == "source" else [self.base_commit, self.source_commit]
            result = {
                "schema_version": 1,
                "status": "passed",
                "source_commit": commit,
                "source_tree": tree,
                "source_still_clean": True,
                "host_platform": platform,
                "host_instances": instances,
                "parents": parents,
                "deployment_qualified": False,
                "independent_acceptance": False,
                "checks": [
                    {
                        "name": "fixture",
                        "status": "passed",
                        "exit_code": 0,
                        "elapsed_seconds": 1.0,
                    }
                ],
            }
            policy = {
                "schema_version": 1,
                "status": "passed",
                "source_commit": commit,
                "platform": platform,
                "instances": instances,
                "deployment_qualified": False,
                "independent_acceptance": False,
                "unmeasured_faults": ["hardware power loss"],
            }
            physical = {
                "schema_version": 1,
                "status": "passed",
                "source_commit": commit,
                "instances": instances,
                "deployment_qualified": False,
                "independent_acceptance": False,
                "supervisord_sha256": supervisord_digest,
            }
            (lane / "result.json").write_text(json.dumps(result), encoding="utf-8")
            (lane / "physical-host-policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            (lane / "physical-host.json").write_text(
                json.dumps(physical), encoding="utf-8"
            )
            lane_arguments.extend(["--lane", f"{label}={lane}"])

        artifact_arguments: list[str] = []
        for name, path in artifacts.items():
            artifact_arguments.extend(["--artifact", f"{name}={path}"])
        return lane_arguments, artifact_arguments, artifacts["hepta-supervisord"]

    def run_bundle(
        self,
        root: Path,
        lane_arguments: list[str],
        artifact_arguments: list[str],
    ) -> subprocess.CompletedProcess[str]:
        output = root / "bundle.json"
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--source-commit",
                self.source_commit,
                "--source-tree",
                self.source_tree,
                "--base-commit",
                self.base_commit,
                "--merge-commit",
                self.merge_commit,
                "--merge-tree",
                self.merge_tree,
                *lane_arguments,
                *artifact_arguments,
                "--out",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_prepares_digest_bound_packet_without_acceptance_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lanes, artifacts, _ = self.make_fixture(root)
            completed = self.run_bundle(root, lanes, artifacts)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            bundle = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(bundle["status"], "prepared_for_external_review")
            self.assertFalse(bundle["authority"]["independent_acceptance"])
            self.assertFalse(bundle["authority"]["release_authority"])
            self.assertTrue((root / "bundle.json.sha256").is_file())

    def test_requires_all_four_exact_candidate_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lanes, artifacts, _ = self.make_fixture(root)
            del lanes[0:2]
            completed = self.run_bundle(root, lanes, artifacts)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("exact four", completed.stderr)

    def test_rejects_frozen_binary_that_does_not_match_host_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lanes, artifacts, supervisord = self.make_fixture(root)
            supervisord.write_bytes(b"different frozen binary")
            completed = self.run_bundle(root, lanes, artifacts)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("does not match", completed.stderr)

    def test_rejects_repository_self_asserted_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lanes, artifacts, _ = self.make_fixture(root)
            policy_path = root / "linux-source-head" / "physical-host-policy.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["independent_acceptance"] = True
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            completed = self.run_bundle(root, lanes, artifacts)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("self-asserted", completed.stderr)


if __name__ == "__main__":
    unittest.main()
