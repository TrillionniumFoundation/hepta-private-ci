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
from qualification.hcsn_currentstate_n256_execution_admission_bridge.test_admission_bridge import (
    _records,
)


ROOT = Path(__file__).parent
PHASE = ROOT.parent / "hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json"
PHASE_SHA256 = "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"


def _seal(record):
    payload = dict(record)
    payload.pop("binding_sha256", None)
    record["binding_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record


def _binding(provider_admission, freeze):
    return _seal(
        {
            "schema": admission.BINDING_SCHEMA,
            "candidate_source_sha256": hashlib.sha256(
                Path(sparse_dynamic.__file__).read_bytes()
            ).hexdigest(),
            "candidate_admission_sha256": hashlib.sha256(
                Path(admission.__file__).read_bytes()
            ).hexdigest(),
            "candidate_request_sha256": hashlib.sha256(
                (ROOT / "REQUEST.json").read_bytes()
            ).hexdigest(),
            "provider_admission_sha256": provider_admission["admission_sha256"],
            "execution_freeze_sha256": freeze["freeze_sha256"],
            "execution_key": provider_admission["execution_key"],
            "input_bundle_sha256": sparse_dynamic.INPUT_BUNDLE_SHA256,
            "roster_identity": json.loads((ROOT / "REQUEST.json").read_text())[
                "roster_identity"
            ],
            "operator_roster_sha256": provider_admission[
                "operator_roster_sha256"
            ],
            "segment_roster_sha256": provider_admission["segment_roster_sha256"],
            "external_reviewer_identity_sha256": provider_admission[
                "external_reviewer_identity_sha256"
            ],
            "external_reviewer_custody_sha256": provider_admission[
                "external_reviewer_custody_sha256"
            ],
            "external_review_artifact_sha256": provider_admission[
                "external_review_artifact_sha256"
            ],
            "created_at_utc": "2026-11-15T01:05:00Z",
            "historical_negative_and_unknown_preserved": True,
            "largegrid_qualification": False,
            "production_adoption": False,
        }
    )


class SparseDynamicIntentTest(unittest.TestCase):
    def test_source_is_fail_closed_and_sparse(self):
        report = inspect(
            ROOT / "sparse_dynamic.py",
            ROOT / "admission.py",
            ROOT / "REQUEST.json",
            PHASE,
        )
        self.assertEqual(
            report["status"], "PASS_SOURCE_ONLY_ADMISSION_BRIDGE_HOLD_NUMERICAL"
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
            admission.require_admission(
                ROOT / "REQUEST.json", sparse_dynamic.__file__, None, None, None
            )

    def test_complete_synthetic_preexecution_bundle_cross_binds_source(self):
        provider_admission, freeze, _manifest = _records()
        binding = _binding(provider_admission, freeze)
        with tempfile.TemporaryDirectory() as temporary:
            paths = []
            for name, record in (
                ("admission", provider_admission),
                ("freeze", freeze),
                ("binding", binding),
            ):
                path = Path(temporary) / f"{name}.json"
                path.write_text(json.dumps(record))
                paths.append(path)
            result = admission.require_admission(
                ROOT / "REQUEST.json", sparse_dynamic.__file__, *paths
            )
            self.assertEqual(result.execution_key, provider_admission["execution_key"])
            self.assertNotIn("numpy", sys.modules)
            self.assertNotIn("scipy", sys.modules)

    def test_current_source_and_execution_key_mismatches_reject(self):
        provider_admission, freeze, _manifest = _records()
        binding = _binding(provider_admission, freeze)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sparse_dynamic.py"
            source.write_bytes(Path(sparse_dynamic.__file__).read_bytes() + b"\n")
            records = []
            for name, record in (
                ("admission", provider_admission),
                ("freeze", freeze),
                ("binding", binding),
            ):
                path = Path(temporary) / f"{name}.json"
                path.write_text(json.dumps(record))
                records.append(path)
            with self.assertRaisesRegex(ValueError, "source is not byte-bound"):
                admission.require_admission(
                    ROOT / "REQUEST.json", source, *records
                )
            binding["execution_key"] = "different-key"
            _seal(binding)
            records[2].write_text(json.dumps(binding))
            with self.assertRaisesRegex(ValueError, "execution_key"):
                admission.require_admission(
                    ROOT / "REQUEST.json", sparse_dynamic.__file__, *records
                )


if __name__ == "__main__":
    unittest.main()
