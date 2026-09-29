from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("runtime_agentd_current_status.py")
SPEC = importlib.util.spec_from_file_location("runtime_agentd_current_status", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RuntimeAgentdCurrentStatusTests(unittest.TestCase):
    def test_exact_verifier_result_is_accepted(self) -> None:
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "engineering.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "source_sha": sha,
                        "run_id": "77",
                        "attempt": "3",
                        "engineering_result": "success",
                        "production_activation": False,
                    }
                ),
                encoding="utf-8",
            )
            observed = MODULE._engineering_result(path, sha, "77", 3)
            self.assertTrue(observed["passed"])
            self.assertEqual(observed["reason"], "exact_candidate_passed")

    def test_wrong_attempt_or_activation_is_rejected(self) -> None:
        sha = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "engineering.json"
            path.write_text(
                json.dumps(
                    {
                        "source_sha": sha,
                        "run_id": "9",
                        "attempt": "2",
                        "engineering_result": "success",
                        "production_activation": True,
                    }
                ),
                encoding="utf-8",
            )
            observed = MODULE._engineering_result(path, sha, "9", 2)
            self.assertFalse(observed["passed"])

    def test_pull_request_requires_successful_prospective_merge(self) -> None:
        passed = MODULE._prospective_merge_result("pull_request", "success")
        failed = MODULE._prospective_merge_result("pull_request", "failure")
        self.assertTrue(passed["required"])
        self.assertTrue(passed["passed"])
        self.assertFalse(failed["passed"])

    def test_push_does_not_manufacture_merge_evidence(self) -> None:
        observed = MODULE._prospective_merge_result("push", "skipped")
        self.assertFalse(observed["required"])
        self.assertTrue(observed["passed"])
        self.assertEqual(observed["reason"], "not_required_for_event")

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"run_id":"1","run_id":"2"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE._load_json(path)


if __name__ == "__main__":
    unittest.main()
