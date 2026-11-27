"""Static tests only; importing this module cannot import NumPy or SciPy."""

import json
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_sparse_dynamic_intent import admission
from qualification.hcsn_currentstate_n256_sparse_dynamic_intent.static_inspector import inspect


ROOT = Path(__file__).parent


class SparseDynamicIntentTest(unittest.TestCase):
    def test_source_is_fail_closed_and_sparse(self):
        report = inspect(ROOT / "sparse_dynamic.py", ROOT / "admission.py", ROOT / "REQUEST.json")
        self.assertEqual(report["status"], "PASS_SOURCE_ONLY_HOLD_NUMERICAL")
        self.assertEqual(report["dynamic_runs"], 0)
        self.assertFalse(report["largegrid_qualification"])

    def test_missing_admission_rejects_before_numeric_import(self):
        with self.assertRaises(admission.NumericalAdmissionRequired):
            admission.require_admission(ROOT / "REQUEST.json", None)

    def test_unbound_admission_rejects_even_if_well_formed(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        payload = {
            "source_commit": "0" * 64,
            "source_tree_sha256": "1" * 64,
            "input_bundle_sha256": request["input_bundle_sha256"],
            "roster_identity": request["roster_identity"],
            "runtime_profile_sha256": "2" * 64,
            "host_snapshot_sha256": "3" * 64,
            "ancestor_cgroup_snapshot_sha256": "4" * 64,
            "allocation_sha256": "5" * 64,
            "concurrency": 1,
            "calendar_start_utc": "2030-01-01T00:00:00Z",
            "calendar_end_utc": "2030-01-01T01:00:00Z",
            "idempotency_key": request["reserved_idempotency_key"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "admission.json"
            path.write_text(json.dumps(payload))
            with self.assertRaises(admission.NumericalAdmissionRequired):
                admission.require_admission(ROOT / "REQUEST.json", path)


if __name__ == "__main__":
    unittest.main()
