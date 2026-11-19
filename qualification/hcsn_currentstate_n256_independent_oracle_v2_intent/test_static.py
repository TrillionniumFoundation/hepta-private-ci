"""Source-only controls for the authentic independent-oracle v2 bridge."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent import (
    adapter,
    admission,
    static_inspector,
)


ROOT = Path(__file__).parent
REPO = ROOT.parents[1]


class IndependentOracleV2IntentTest(unittest.TestCase):
    def test_source_is_independent_signed_content_and_fail_closed(self):
        report = static_inspector.inspect(
            ROOT / "adapter.py", ROOT / "admission.py", ROOT / "REQUEST.json"
        )
        self.assertEqual(report["status"], "PASS_ORACLE_V2_SIGNED_CONTENT_SOURCE_HOLD")
        self.assertEqual(report["dynamic_runs"], 0)
        self.assertFalse(report["oracle_numerical_qualification"])

    def test_authentic_originals_parse_without_numeric_imports(self):
        before = {name for name in sys.modules if name == "numpy" or name.startswith("scipy")}
        result = adapter.load_authentic_input(REPO)
        after = {name for name in sys.modules if name == "numpy" or name.startswith("scipy")}
        self.assertEqual(after, before)
        self.assertEqual(len(result.nodes_payload), 257 * 8)
        self.assertEqual(len(result.active_payload), 257 * 8)
        self.assertEqual(len(result.signed_content_payload), 257 * 4 * 8)
        self.assertEqual(len(result.phase_packets), 8)

    def test_legacy_content_alias_is_rejected(self):
        phase_path = REPO / adapter.RELATIVE["phase"]
        phase = json.loads(phase_path.read_text())
        changed = copy.deepcopy(phase)
        changed["packets"][0]["content"] = changed["packets"][0].pop("signed_content")
        with self.assertRaisesRegex(ValueError, "field set"):
            adapter._validate_phase(changed)

    def test_missing_oracle_binding_rejects_before_candidate_admission(self):
        with self.assertRaises(admission.NumericalAdmissionRequired):
            admission.require_admission(
                ROOT / "REQUEST.json",
                ROOT / "adapter.py",
                REPO / "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py",
                REPO / "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/REQUEST.json",
                REPO / "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py",
                REPO / "qualification/hcsn_currentstate_n256_t0_capsule_v1/builder.py",
                None,
                None,
                None,
                None,
            )

    def test_source_request_retains_all_external_unknowns(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertTrue(request["historical_negative_and_unknown_preserved"])
        self.assertTrue(all(value is None for value in request["required_external_freeze"].values()))
        self.assertFalse(request["largegrid_qualification"])
        self.assertFalse(request["production_adoption"])
        self.assertFalse(request["all_closed"])

    def test_complete_synthetic_cross_binding_and_source_mutation_control(self):
        request_path = ROOT / "REQUEST.json"
        adapter_path = ROOT / "adapter.py"
        candidate_source = (
            REPO
            / "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py"
        )
        candidate_request = (
            REPO / "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/REQUEST.json"
        )
        legacy_oracle = (
            REPO
            / "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py"
        )
        t0_builder = REPO / "qualification/hcsn_currentstate_n256_t0_capsule_v1/builder.py"
        request = json.loads(request_path.read_text())
        digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
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
        candidate_binding = {"created_at_utc": "2026-11-15T11:00:00Z"}
        binding = {
            "schema": admission.SCHEMA,
            "oracle_adapter_source_sha256": digest(adapter_path),
            "oracle_admission_source_sha256": digest(admission.__file__),
            "oracle_request_sha256": digest(request_path),
            "legacy_oracle_source_sha256": digest(legacy_oracle),
            "candidate_source_sha256": digest(candidate_source),
            "candidate_admission_sha256": digest(admission.candidate_admission.__file__),
            "candidate_request_sha256": digest(candidate_request),
            "candidate_source_binding_sha256": admitted.source_binding_sha256,
            "provider_admission_sha256": admitted.provider_admission_sha256,
            "execution_freeze_sha256": admitted.execution_freeze_sha256,
            "execution_key": admitted.execution_key,
            "input_bundle_sha256": request["input_bundle_sha256"],
            "phase_original_sha256": request["phase_original_sha256"],
            "state_original_sha256": request["state_original_sha256"],
            "npz_b64_original_sha256": request["npz_b64_original_sha256"],
            "t0_builder_source_sha256": digest(t0_builder),
            **provider,
            "created_at_utc": "2026-11-15T11:30:00Z",
            "historical_negative_and_unknown_preserved": True,
            "largegrid_qualification": False,
            "production_adoption": False,
        }

        def seal(value):
            result = dict(value)
            result["binding_sha256"] = hashlib.sha256(admission._canonical(value)).hexdigest()
            return result

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            records = {
                "provider.json": provider,
                "freeze.json": freeze,
                "candidate.json": candidate_binding,
                "oracle.json": seal(binding),
            }
            for name, value in records.items():
                (folder / name).write_text(json.dumps(value))
            with mock.patch.object(
                admission.candidate_admission, "require_admission", return_value=admitted
            ):
                result = admission.require_admission(
                    request_path,
                    adapter_path,
                    candidate_source,
                    candidate_request,
                    legacy_oracle,
                    t0_builder,
                    folder / "provider.json",
                    folder / "freeze.json",
                    folder / "candidate.json",
                    folder / "oracle.json",
                )
                self.assertIs(result, admitted)
                changed = dict(binding)
                changed["candidate_source_sha256"] = "0" * 64
                (folder / "oracle.json").write_text(json.dumps(seal(changed)))
                with self.assertRaisesRegex(ValueError, "candidate_source_sha256"):
                    admission.require_admission(
                        request_path,
                        adapter_path,
                        candidate_source,
                        candidate_request,
                        legacy_oracle,
                        t0_builder,
                        folder / "provider.json",
                        folder / "freeze.json",
                        folder / "candidate.json",
                        folder / "oracle.json",
                    )


if __name__ == "__main__":
    unittest.main()
