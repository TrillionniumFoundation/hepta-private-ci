"""Static controls only; no N256 numerical dependency is imported."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_joint_admission import admission
from qualification.hcsn_currentstate_n256_joint_admission.inspector import inspect


ROOT = Path(__file__).parent
QUALIFICATION = ROOT.parent


def fixture(request):
    return {
        "candidate_source_sha256": request["candidate_source_sha256"],
        "oracle_source_sha256": request["oracle_source_sha256"],
        "serializer_source_sha256": request["serializer_source_sha256"],
        "input_bundle_sha256": request["input_bundle_sha256"],
        "roster_identity": request["roster_identity"],
        "resource_snapshot_source_freeze_sha256": request[
            "resource_snapshot_source_freeze_sha256"
        ],
        "runtime_profile_sha256": "1" * 64,
        "host_snapshot_sha256": "2" * 64,
        "ancestor_cgroup_snapshot_sha256": "3" * 64,
        "allocation_sha256": "4" * 64,
        "calendar_sha256": "5" * 64,
        "candidate_admission_sha256": "6" * 64,
        "oracle_admission_sha256": "7" * 64,
        "serializer_admission_sha256": "8" * 64,
        "concurrency": 1,
        "calendar_start_utc": "2030-01-01T00:00:00Z",
        "calendar_end_utc": "2030-01-01T01:00:00Z",
        "candidate_idempotency_key": request["candidate_reserved_idempotency_key"],
        "oracle_idempotency_key": request["oracle_reserved_idempotency_key"],
        "serializer_idempotency_key": request["serializer_reserved_idempotency_key"],
    }


class JointAdmissionTest(unittest.TestCase):
    def test_current_sources_are_bound_but_admission_is_red(self):
        report = inspect(ROOT, QUALIFICATION)
        self.assertEqual(report["status"], "RED_JOINT_ADMISSION_HOLD")
        self.assertEqual(report["new_idempotency_keys"], 0)
        self.assertEqual(report["n256_dynamic_runs"], 0)
        self.assertFalse(report["largegrid_qualification"])

    def test_missing_joint_admission_rejects(self):
        with self.assertRaises(admission.JointAdmissionRequired):
            admission.require_joint_admission(ROOT / "REQUEST.json", None)

    def test_unbound_well_formed_record_still_rejects(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            record_path = Path(temporary) / "admission.json"
            record_path.write_text(json.dumps(fixture(request)))
            with self.assertRaises(admission.JointAdmissionRequired):
                admission.require_joint_admission(ROOT / "REQUEST.json", record_path)

    def test_bound_record_with_source_mismatch_rejects(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        record = fixture(request)
        record["serializer_source_sha256"] = "9" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "admission.json"
            request_path = root / "request.json"
            record_path.write_text(json.dumps(record))
            request["joint_admission_sha256"] = hashlib.sha256(
                record_path.read_bytes()
            ).hexdigest()
            request_path.write_text(json.dumps(request))
            with self.assertRaisesRegex(ValueError, "serializer_source_sha256 mismatch"):
                admission.require_joint_admission(request_path, record_path)

    def test_calendar_and_existing_keys_are_jointly_required(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        record = fixture(request)
        record["calendar_end_utc"] = record["calendar_start_utc"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "admission.json"
            request_path = root / "request.json"
            record_path.write_text(json.dumps(record))
            request["joint_admission_sha256"] = hashlib.sha256(
                record_path.read_bytes()
            ).hexdigest()
            request_path.write_text(json.dumps(request))
            with self.assertRaisesRegex(ValueError, "calendar end must follow start"):
                admission.require_joint_admission(request_path, record_path)


if __name__ == "__main__":
    unittest.main()
