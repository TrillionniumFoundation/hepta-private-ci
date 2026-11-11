"""Fail-closed fixture tests for exported C2 native observation binding."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from c2_durable import append_receipt
from c2_native_replay import inspect_exported_observations, WAIT4_SCOPE

OWNER = "hcsn-owner-new-start"
NAMES = ["hcsn-s101-lr0.001", "hcsn-s101-lr0.003", "hcsn-s211-lr0.001",
         "hcsn-s211-lr0.003", "hcsn-s307-lr0.001", "hcsn-s307-lr0.003"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NativeObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = {}

    def add(self, name, *, status="completed", job=None):
        job = job or f"job-{name}"
        directory = self.root / "artifacts" / name
        directory.mkdir(parents=True)
        (directory / "result.json").write_text('{"schema":"synthetic-test-only"}\n')
        resource = {"schema": "hcsn-c2-resource-v1", "native_job_id": job,
                    "child_cpu_scope": WAIT4_SCOPE,
                    "child_cpu_seconds": 3.25, "child_user_cpu_seconds": 3.0,
                    "child_system_cpu_seconds": 0.25,
                    "whole_process_wall_seconds": 9.0,
                    "attempt_wrapper_wall_seconds": 9.1,
                    "child_peak_rss_bytes": 8192}
        (directory / "resource.json").write_text(json.dumps(resource))
        append_receipt(self.root / "receipts", owner_start_id=OWNER,
                       attempt_id=name, event_type="terminal", payload={
                           "status": status, "native_job_id": job,
                           "result_sha256": digest(directory / "result.json"),
                           "resource_sha256": digest(directory / "resource.json")})
        self.native[job] = {"job_id": job, "status_authoritative": True,
                            "terminal_publication_confirmed": True,
                            "output_complete": True, "output_durable": True,
                            "log_truncated": {"stdout": False, "stderr": False},
                            "state": "succeeded" if status == "completed" else "failed",
                            "exit_code": 0 if status == "completed" else 1}

    def audit(self):
        return inspect_exported_observations(
            self.root / "receipts", owner_start_id=OWNER,
            expected_attempts=NAMES, native_observations=self.native,
            artifacts_root=self.root / "artifacts")

    def test_missing_roster_keeps_full_denominator(self):
        self.add(NAMES[0])
        report = self.audit()
        self.assertEqual((report["expected_count"], report["producer_terminal_count"],
                          report["structurally_matched_count"]), (6, 1, 1))
        self.assertEqual(len(report["missing"]), 5)
        self.assertEqual(report["scientific_admission"], "HOLD_NO_GO")

    def test_six_matching_copies_not_live_attestation_or_science(self):
        for name in NAMES:
            self.add(name)
        report = self.audit()
        self.assertEqual(report["structurally_successful_count"], 6)
        self.assertFalse(report["independent_live_native_status_verified"])
        self.assertTrue(report["native_observations_are_untrusted_copies"])
        self.assertEqual(report["scientific_admission"], "HOLD_NO_GO")

    def test_native_unknown_and_false_terminal_rejected(self):
        self.add(NAMES[0])
        job = "job-" + NAMES[0]
        self.native[job]["terminal_publication_confirmed"] = False
        self.assertEqual(self.audit()["structurally_matched_count"], 0)
        self.native[job]["terminal_publication_confirmed"] = True
        self.native[job]["status_authoritative"] = False
        self.assertEqual(self.audit()["structurally_matched_count"], 0)

    def test_exit_zero_mismatch_rejected(self):
        self.add(NAMES[0])
        self.native["job-"+NAMES[0]]["exit_code"] = 1
        self.assertIn(NAMES[0], self.audit()["rejected"])

    def test_resource_hash_change_rejected(self):
        self.add(NAMES[0])
        path = self.root / "artifacts" / NAMES[0] / "resource.json"
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertIn(NAMES[0], self.audit()["rejected"])

    def test_non_wait4_child_cost_rejected_even_if_rehashed(self):
        self.add(NAMES[0])
        path = self.root / "artifacts" / NAMES[0] / "resource.json"
        payload = json.loads(path.read_text())
        payload["child_cpu_scope"] = "RUSAGE_CHILDREN aggregate"
        path.write_text(json.dumps(payload))
        self.assertIn(NAMES[0], self.audit()["rejected"])

    def test_undurable_output_rejected(self):
        self.add(NAMES[0])
        self.native["job-"+NAMES[0]]["output_durable"] = False
        self.assertIn(NAMES[0], self.audit()["rejected"])

    def test_failed_terminal_not_scientific_success(self):
        self.add(NAMES[0], status="failed")
        out = self.audit()
        self.assertEqual(out["structurally_matched_count"], 1)
        self.assertEqual(out["structurally_successful_count"], 0)
        self.assertEqual(out["scientific_admission"], "HOLD_NO_GO")

    def test_missing_native_status_rejected(self):
        self.add(NAMES[0])
        self.native.clear()
        self.assertIn(NAMES[0], self.audit()["rejected"])

    def test_duplicate_native_job_rejected(self):
        self.add(NAMES[0], job="one-job")
        self.add(NAMES[1], job="one-job")
        self.assertIn(NAMES[1], self.audit()["rejected"])


    def _rebound_resource(self, suffix: str):
        name = NAMES[0]
        self.add(name)
        directory = self.root / "artifacts" / name
        resource = directory / "resource.json"
        original = resource.read_text()
        assert original.endswith("}")
        resource.write_text(original[:-1] + suffix + "}")
        rebound = self.root / "rebinding-receipts"
        append_receipt(rebound, owner_start_id=OWNER, attempt_id=name,
                       event_type="terminal", payload={
                           "status": "completed", "native_job_id": "job-" + name,
                           "result_sha256": digest(directory / "result.json"),
                           "resource_sha256": digest(resource)})
        return inspect_exported_observations(
            rebound, owner_start_id=OWNER, expected_attempts=NAMES,
            native_observations=self.native,
            artifacts_root=self.root / "artifacts")

    def test_rebound_duplicate_resource_json_key_rejected(self):
        # Hash matches the malicious resource bytes: checksum alone is insufficient.
        out = self._rebound_resource(', "child_cpu_seconds":3.25')
        self.assertIn(NAMES[0], out["rejected"])

    def test_rebound_nonfinite_extra_resource_field_rejected(self):
        # Python json.loads accepts NaN by default even if the six metered fields fit.
        out = self._rebound_resource(', "debug":NaN')
        self.assertIn(NAMES[0], out["rejected"])

    def test_rebound_overflow_exponent_resource_field_rejected(self):
        out = self._rebound_resource(', "debug":1e400')
        self.assertIn(NAMES[0], out["rejected"])

    def test_rebound_oversized_resource_field_rejected(self):
        out = self._rebound_resource(', "padding":"' + "A" * (1 << 20) + '"')
        self.assertIn(NAMES[0], out["rejected"])


if __name__ == "__main__":
    unittest.main()
