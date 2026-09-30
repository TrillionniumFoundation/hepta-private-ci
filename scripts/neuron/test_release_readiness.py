import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import release_readiness


SOURCE = "a" * 40
BASE = "b" * 40


def module_manifest():
    return {
        "schema": release_readiness.MODULE_SCHEMA,
        "module": "neuron.runtime",
        "sourceSha": SOURCE,
        "baseSha": BASE,
        "qualificationReady": True,
        "workflowContext": {"runId": "101", "runAttempt": "2"},
        "workflowOutcomes": {"qualification": "success", "download": "success"},
        "productionActivation": False,
        "release": False,
        "gates": [{"id": "linux-stable-source-head", "result": "success"}],
        "blockers": [],
        "claimBoundary": {
            "sourceQualification": True,
            "productionActivation": False,
            "release": False,
        },
    }


def baseline():
    runner = {
        "name": "GitHub Actions 1",
        "group": "GitHub Actions",
        "labels": ["ubuntu-24.04"],
    }
    return {
        "schema": release_readiness.BASELINE_SCHEMA,
        "sourceSha": SOURCE,
        "baseSha": BASE,
        "pullRequest": {"number": 1240, "headSha": SOURCE, "baseSha": BASE},
        "workflow": "blocking-ci",
        "checkName": "CI required",
        "status": "completed",
        "conclusion": "success",
        "runId": 202,
        "runAttempt": 1,
        "jobId": 303,
        "htmlUrl": "https://example.invalid/run/202/job/303",
        "runner": runner,
        "runnerFingerprintSha256": release_readiness.sha256_bytes(
            release_readiness.canonical_bytes(runner)
        ),
    }


class ReleaseReadinessTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, value: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(value))
        return path

    def args(self, root: Path, module: dict, repo: dict, allow=False):
        return SimpleNamespace(
            spec=root / "spec.json",
            module_manifest=self.write_json(root, "module.json", module),
            baseline=self.write_json(root, "baseline.json", repo),
            source_sha=SOURCE,
            base_sha=BASE,
            generated_at="2026-09-30T00:00:00+00:00",
            output=root / "final.json",
            allow_incomplete=allow,
        )

    @mock.patch.object(
        release_readiness,
        "source_bindings",
        return_value={
            "specSha256": "1" * 64,
            "cargoLockSha256": "2" * 64,
            "documentationSha256": "3" * 64,
            "implementationMapSha256": "4" * 64,
            "moduleWorkflowSha256": "5" * 64,
            "repositoryBaselineDefinitionSha256": "6" * 64,
            "finalizerSha256": "7" * 64,
        },
    )
    def test_same_candidate_success_is_ready_but_never_activates(self, _bindings):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory), module_manifest(), baseline())
            result = release_readiness.finalize(args)
            self.assertTrue(result["qualificationReady"])
            self.assertFalse(result["productionActivation"])
            self.assertFalse(result["release"])
            self.assertEqual(result["blockers"], [])
            self.assertTrue(result["claimBoundary"]["moduleSourceQualification"])
            self.assertTrue(result["claimBoundary"]["repositoryBaselineQualified"])

    @mock.patch.object(release_readiness, "source_bindings", return_value={})
    def test_mixed_source_sha_fails_closed(self, _bindings):
        with tempfile.TemporaryDirectory() as directory:
            value = baseline()
            value["sourceSha"] = "c" * 40
            args = self.args(Path(directory), module_manifest(), value, allow=True)
            result = release_readiness.finalize(args)
            self.assertFalse(result["qualificationReady"])
            self.assertIn(
                "repository baseline source SHA differs from candidate",
                result["blockers"],
            )

    @mock.patch.object(release_readiness, "source_bindings", return_value={})
    def test_mixed_pull_request_base_fails_closed(self, _bindings):
        with tempfile.TemporaryDirectory() as directory:
            value = baseline()
            value["pullRequest"]["baseSha"] = "c" * 40
            args = self.args(Path(directory), module_manifest(), value, allow=True)
            result = release_readiness.finalize(args)
            self.assertFalse(result["qualificationReady"])
            self.assertIn(
                "repository baseline pull request base differs from candidate",
                result["blockers"],
            )

    @mock.patch.object(release_readiness, "source_bindings", return_value={})
    def test_failed_required_job_fails_closed(self, _bindings):
        with tempfile.TemporaryDirectory() as directory:
            value = baseline()
            value["conclusion"] = "failure"
            args = self.args(Path(directory), module_manifest(), value)
            with self.assertRaises(release_readiness.ReleaseReadinessError):
                release_readiness.finalize(args)
            persisted = json.loads(args.output.read_text())
            self.assertFalse(persisted["qualificationReady"])
            self.assertFalse(persisted["productionActivation"])

    @mock.patch.object(release_readiness, "source_bindings", return_value={})
    def test_activation_claim_is_rejected(self, _bindings):
        with tempfile.TemporaryDirectory() as directory:
            value = module_manifest()
            value["productionActivation"] = True
            args = self.args(Path(directory), value, baseline(), allow=True)
            result = release_readiness.finalize(args)
            self.assertFalse(result["qualificationReady"])
            self.assertIn(
                "module manifest attempted production activation", result["blockers"]
            )
            self.assertFalse(result["productionActivation"])

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema":"a","schema":"b"}')
            with self.assertRaises(release_readiness.ReleaseReadinessError):
                release_readiness.read_json(path)


if __name__ == "__main__":
    unittest.main()
