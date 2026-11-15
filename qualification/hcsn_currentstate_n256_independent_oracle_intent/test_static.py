"""Static-only tests; importing this module cannot import NumPy or SciPy."""

import json
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_independent_oracle_intent import admission
from qualification.hcsn_currentstate_n256_independent_oracle_intent.static_inspector import inspect

ROOT = Path(__file__).parent


class IndependentOracleIntentTest(unittest.TestCase):
    def test_source_is_independent_sparse_and_fail_closed(self):
        report = inspect(ROOT / "independent_oracle.py", ROOT / "admission.py", ROOT / "REQUEST.json")
        self.assertEqual(report["status"], "PASS_SOURCE_ONLY_HOLD_NUMERICAL")
        self.assertEqual(report["candidate_imports"], 0)
        self.assertEqual(report["oracle_calls"], 0)
        self.assertFalse(report["oracle_numerical_qualification"])

    def test_missing_admission_rejects_before_numeric_import(self):
        with self.assertRaises(admission.NumericalAdmissionRequired):
            admission.require_admission(ROOT / "REQUEST.json", None)

    def test_unbound_admission_rejects_even_if_well_formed(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        payload = {
            "source_commit": "0" * 64,
            "oracle_source_sha256": "1" * 64,
            "candidate_source_sha256": request["candidate_source_sha256"],
            "input_bundle_sha256": request["input_bundle_sha256"],
            "roster_identity": request["roster_identity"],
            "runtime_profile_sha256": "2" * 64,
            "host_snapshot_sha256": "3" * 64,
            "ancestor_cgroup_snapshot_sha256": "4" * 64,
            "allocation_sha256": "5" * 64,
            "calendar_sha256": "6" * 64,
            "concurrency": 1,
            "idempotency_key": request["reserved_idempotency_key"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "admission.json"
            path.write_text(json.dumps(payload))
            with self.assertRaises(admission.NumericalAdmissionRequired):
                admission.require_admission(ROOT / "REQUEST.json", path)


if __name__ == "__main__":
    unittest.main()
