"""Small source-only controls for the fail-closed binding publisher."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent import (
    admission as oracle_admission,
)
from qualification.hcsn_currentstate_n256_oracle_binding_publisher_intent import (
    publisher,
    static_inspector,
)


ROOT = Path(__file__).parent
REPO = ROOT.parents[1]
ORACLE_ROOT = REPO / "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent"
CANDIDATE_ROOT = REPO / "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent"


def _paths():
    return {
        "oracle_request_path": ORACLE_ROOT / "REQUEST.json",
        "oracle_adapter_path": ORACLE_ROOT / "adapter.py",
        "candidate_source_path": CANDIDATE_ROOT / "sparse_dynamic.py",
        "candidate_request_path": CANDIDATE_ROOT / "REQUEST.json",
        "legacy_oracle_source_path": REPO / "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py",
        "t0_builder_source_path": REPO / "qualification/hcsn_currentstate_n256_t0_capsule_v1/builder.py",
    }


class OracleBindingPublisherIntentTest(unittest.TestCase):
    def test_missing_original_rejects_before_candidate_admission(self):
        with mock.patch.object(
            oracle_admission.candidate_admission, "require_admission"
        ) as candidate_gate:
            with self.assertRaises(publisher.BindingOriginalRequired):
                publisher.build_binding_record(
                    created_at_utc="2026-11-15T11:30:00Z",
                    provider_admission_path=None,
                    execution_freeze_path=None,
                    candidate_binding_path=None,
                    **_paths(),
                )
            candidate_gate.assert_not_called()

    def test_synthetic_record_is_accepted_by_parent_validator(self):
        admitted = SimpleNamespace(
            source_binding_sha256="a" * 64,
            provider_admission_sha256="b" * 64,
            execution_freeze_sha256="c" * 64,
            execution_key="synthetic-never-executed",
        )
        provider = {
            "external_reviewer_identity_sha256": "d" * 64,
            "external_reviewer_custody_sha256": "e" * 64,
            "external_review_artifact_sha256": "f" * 64,
        }
        freeze = {"execution_not_before_utc": "2026-11-15T12:00:00Z"}
        candidate = {"created_at_utc": "2026-11-15T11:00:00Z"}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name, value in (("provider", provider), ("freeze", freeze), ("candidate", candidate)):
                (folder / f"{name}.json").write_text(json.dumps(value))
            with mock.patch.object(
                oracle_admission.candidate_admission,
                "require_admission",
                return_value=admitted,
            ):
                binding = publisher.build_binding_record(
                    created_at_utc="2026-11-15T11:30:00Z",
                    provider_admission_path=folder / "provider.json",
                    execution_freeze_path=folder / "freeze.json",
                    candidate_binding_path=folder / "candidate.json",
                    **_paths(),
                )
                (folder / "oracle.json").write_text(json.dumps(binding))
                result = oracle_admission.require_admission(
                    _paths()["oracle_request_path"],
                    _paths()["oracle_adapter_path"],
                    _paths()["candidate_source_path"],
                    _paths()["candidate_request_path"],
                    _paths()["legacy_oracle_source_path"],
                    _paths()["t0_builder_source_path"],
                    folder / "provider.json",
                    folder / "freeze.json",
                    folder / "candidate.json",
                    folder / "oracle.json",
                )
                self.assertIs(result, admitted)
        self.assertEqual(set(binding), oracle_admission.FIELDS)
        self.assertTrue(binding["historical_negative_and_unknown_preserved"])
        self.assertFalse(binding["largegrid_qualification"])
        self.assertFalse(binding["production_adoption"])

    def test_bad_reviewer_hash_and_time_window_are_rejected(self):
        admitted = SimpleNamespace(
            source_binding_sha256="a" * 64,
            provider_admission_sha256="b" * 64,
            execution_freeze_sha256="c" * 64,
            execution_key="synthetic-never-executed",
        )
        provider = {
            "external_reviewer_identity_sha256": "not-a-hash",
            "external_reviewer_custody_sha256": "e" * 64,
            "external_review_artifact_sha256": "f" * 64,
        }
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "provider.json").write_text(json.dumps(provider))
            (folder / "freeze.json").write_text(
                json.dumps({"execution_not_before_utc": "2026-11-15T12:00:00Z"})
            )
            (folder / "candidate.json").write_text(
                json.dumps({"created_at_utc": "2026-11-15T11:00:00Z"})
            )
            arguments = {
                "provider_admission_path": folder / "provider.json",
                "execution_freeze_path": folder / "freeze.json",
                "candidate_binding_path": folder / "candidate.json",
                **_paths(),
            }
            with mock.patch.object(
                oracle_admission.candidate_admission,
                "require_admission",
                return_value=admitted,
            ):
                with self.assertRaisesRegex(ValueError, "external_reviewer_identity"):
                    publisher.build_binding_record(
                        created_at_utc="2026-11-15T11:30:00Z", **arguments
                    )
                provider["external_reviewer_identity_sha256"] = "d" * 64
                (folder / "provider.json").write_text(json.dumps(provider))
                with self.assertRaisesRegex(ValueError, "preexecution interval"):
                    publisher.build_binding_record(
                        created_at_utc="2026-11-15T12:00:01Z", **arguments
                    )

    def test_request_keeps_every_external_original_null(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertTrue(
            all(value is None for value in request["required_external_originals"].values())
        )
        self.assertIsNone(request["execution_key"])
        self.assertIsNone(request["oracle_binding_output_sha256"])
        self.assertFalse(request["numerical_execution_allowed"])
        self.assertTrue(request["historical_negative_and_unknown_preserved"])
        self.assertFalse(request["all_closed"])

    def test_static_inspector_reports_zero_execution(self):
        report = static_inspector.inspect(ROOT / "publisher.py", ROOT / "REQUEST.json")
        self.assertEqual(report["status"], "PASS_ORACLE_BINDING_PUBLISHER_SOURCE_HOLD")
        self.assertEqual(report["external_originals_present"], 0)
        self.assertEqual(report["binding_originals_published"], 0)
        self.assertEqual(report["dynamic_runs"], 0)
        self.assertEqual(report["optimizer_steps"], 0)


if __name__ == "__main__":
    unittest.main()
