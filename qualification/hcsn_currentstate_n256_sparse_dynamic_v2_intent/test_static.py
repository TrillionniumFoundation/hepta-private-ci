"""Static and authentic-schema tests; no NumPy or SciPy may be imported."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_sparse_dynamic_v2_intent import admission
from qualification.hcsn_currentstate_n256_sparse_dynamic_v2_intent import sparse_dynamic
from qualification.hcsn_currentstate_n256_sparse_dynamic_v2_intent.static_inspector import inspect


ROOT = Path(__file__).parent
PHASE = ROOT.parent / "hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json"
PHASE_SHA256 = "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"


class SparseDynamicIntentTest(unittest.TestCase):
    def test_source_is_fail_closed_and_sparse(self):
        report = inspect(
            ROOT / "sparse_dynamic.py",
            ROOT / "admission.py",
            ROOT / "REQUEST.json",
            PHASE,
        )
        self.assertEqual(
            report["status"], "PASS_SOURCE_ONLY_SIGNED_CONTENT_HOLD_NUMERICAL"
        )
        self.assertEqual(report["dynamic_runs"], 0)
        self.assertEqual(report["authentic_phase_packets"], 8)
        self.assertFalse(report["largegrid_qualification"])

    def test_authentic_signed_content_maps_without_numeric_imports(self):
        raw = PHASE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PHASE_SHA256)
        phase = json.loads(raw)
        self.assertEqual(phase["packet_count"], 8)
        alphas = tuple(
            sparse_dynamic._phase_packet_alpha(item) for item in phase["packets"]
        )
        self.assertEqual(len(alphas), 8)
        self.assertTrue(all(len(alpha) == 5 for alpha in alphas))
        self.assertTrue(all("signed_content" in item for item in phase["packets"]))
        self.assertTrue(all("content" not in item for item in phase["packets"]))
        self.assertNotIn("numpy", sys.modules)
        self.assertNotIn("scipy", sys.modules)

    def test_legacy_content_alias_rejects(self):
        item = json.loads(PHASE.read_text())["packets"][0]
        item["content"] = item.pop("signed_content")
        with self.assertRaisesRegex(ValueError, "field set"):
            sparse_dynamic._phase_packet_alpha(item)

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
