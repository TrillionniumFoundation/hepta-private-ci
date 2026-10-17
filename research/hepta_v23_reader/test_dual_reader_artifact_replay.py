"""Source-only V23 adversarial proof-boundary tests, not new model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import dual_reader_artifact_replay as v23

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "V23_ORIGINAL_SANITIZED_MEMBER_SNAPSHOT_20261016.json"
OBSERVED = ROOT / "V23_ORIGINAL_DUAL_READER_REPLAY_20261016.json"


class V23SanitizedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.report = v23.reconcile(self.payload)

    def test_original_source_only_reference_is_nongo(self):
        self.assertEqual(self.report["decision"], "HOLD_NO_GO")
        self.assertFalse(self.report["production_authorized"])
        self.assertFalse(self.report["semantic_answer_correctness_verified"])
        self.assertFalse(self.report["evidence_sufficiency_human_certified"])
        self.assertFalse(self.report["ndu_system2_or_cell_split_gain_verified"])

    def test_exact_original_output_matches_frozen_digests(self):
        self.assertEqual(self.report, json.loads(OBSERVED.read_text(encoding="utf-8")))
        self.assertEqual(self.report["original_sanitized_artifact_sha256"], v23.ARTIFACT_SHA256)
        self.assertEqual(self.report["exact_parent_commit"], v23.COMMIT_SHA)

    def test_actual_four_arm_no_capacity_win(self):
        arms = self.report["four_arm_descriptive_proxy"]
        self.assertEqual(set(arms), set(v23.ARMS))
        self.assertEqual(arms["annotated"]["135m_weak_literal_hits"], 5)
        self.assertEqual(arms["annotated"]["qwen_weak_literal_hits"], 4)
        self.assertEqual(arms["retrieved"]["qwen_minus_135m_weak_literal_hits"], 0)
        for row in arms.values():
            self.assertEqual(row["labeled_questions"], 22)
            self.assertEqual(row["publisher_answer_missing"], 8)
            self.assertEqual(row["qwen_strict_full_answer_matches"], 0)
            self.assertEqual(row["135m_strict_full_answer_matches"], 0)

    def test_actual_tokens_alias_once(self):
        self.assertEqual(self.report["qwen_physical_input_tokens_charged_once"], 12008)
        self.assertEqual(self.report["qwen_alias_inclusive_logical_input_tokens"], 13663)
        self.assertEqual(self.report["distinct_physical_requests_each_model"], 96)
        self.assertEqual(self.report["original_qwen_model_forwards"], 1970)
        self.assertEqual(self.report["original_135m_model_forwards"], 1777)

    def _tamper(self, member, field, value):
        data = copy.deepcopy(self.payload)
        data[member][field] = value
        with self.assertRaises(ValueError):
            v23.reconcile(data)

    def test_fake_go_denied(self):
        self._tamper("v19-qwen-sanitized.json", "decision", "GO")

    def test_fake_production_authority_denied(self):
        self._tamper("v19-qwen-sanitized.json", "production_authorized", True)

    def test_source_replaced_with_valid_sha_string_denied(self):
        self._tamper("v19-135m-sanitized.json", "original_corpus_sha256", "0"*64)

    def test_stolen_reference_model_digest_denied(self):
        self._tamper("v19-qwen-sanitized.json", "reference_material_sha256", "1"*64)

    def test_semantic_accuracy_fake_denied(self):
        self._tamper("v19-qwen-sanitized.json", "independent_semantic_review_verified", True)

    def test_fake_equal_token_budget_denied(self):
        self._tamper("v19-qwen-sanitized.json", "model_token_budget_matched_to_135m", True)

    def test_fake_ndu_gain_denied(self):
        self._tamper("v19-qwen-sanitized.json", "no_cell_learning_or_NDU_gain", False)

    def test_missing_eight_answers_cannot_be_scored_as_failures(self):
        d = copy.deepcopy(self.payload)
        d["v19-qwen-sanitized.json"]["scores"]["annotated"]["labeled"] = 30
        d["v19-qwen-sanitized.json"]["scores"]["annotated"]["missing_answer"] = 0
        with self.assertRaisesRegex(ValueError, "missing publisher"):
            v23.reconcile(d)

    def test_answer_citation_never_counts_as_entailed_evidence(self):
        self.assertFalse(self.report["citation_entailment_verified"])
        self.assertEqual(self.report["four_arm_descriptive_proxy"]["none"]["qwen_foreign_citation_cases"], 13)
        self.assertEqual(self.report["four_arm_descriptive_proxy"]["annotated"]["qwen_valid_syntactic_citations_not_entailment"], 25)

    def test_repeated_request_double_charging_denied(self):
        d = copy.deepcopy(self.payload)
        d["v20-reference-alias-reconciliation.json"]["unique_tokens_paid_once"] = 13663
        with self.assertRaisesRegex(ValueError, "shared Qwen"):
            v23.reconcile(d)

    def test_alias_mapping_changed_denied(self):
        d = copy.deepcopy(self.payload)
        d["v20-reference-alias-reconciliation.json"]["source_alias_mapping_sha256"] = "a"*64
        with self.assertRaisesRegex(ValueError, "shared Qwen"):
            v23.reconcile(d)

    def test_larger_than_total_cpu_denied(self):
        d = copy.deepcopy(self.payload)
        d["v19-qwen-sanitized.json"]["scores"]["annotated"]["model_cpu_ms"] = 10000000
        with self.assertRaisesRegex(ValueError, "CPU"):
            v23.reconcile(d)

    def test_fake_forward_count_denied(self):
        self._tamper("v19-qwen-sanitized.json", "reference_forward_count", 1)

    def test_missing_or_extra_member_denied(self):
        d = copy.deepcopy(self.payload)
        d.pop("source/qwen-token-preflight.json")
        with self.assertRaisesRegex(ValueError, "member universe"):
            v23.reconcile(d)
        d = copy.deepcopy(self.payload)
        d["private-original-answers.json"] = {"answers": []}
        with self.assertRaisesRegex(ValueError, "member universe"):
            v23.reconcile(d)

    def test_duplicate_or_nonfinite_json_denied(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            v23._json(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            v23._json(b'{"a":NaN}')

    def test_create_only_local_receipt_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "out.json"
            v23.write_once(output, self.report)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "must be new"):
                v23.write_once(output, self.report)
            self.assertEqual(json.loads(output.read_text()), self.report)

    def test_original_archive_sha_must_match(self):
        with tempfile.TemporaryDirectory() as folder:
            zpath = Path(folder) / "fake.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                for name, content in self.payload.items():
                    z.writestr(name, json.dumps(content))
            with self.assertRaisesRegex(ValueError, "artifact SHA"):
                v23.read_original_archive(zpath)

    def test_source_fixture_does_not_fake_live_model_or_human(self):
        self.assertTrue(self.report["per_case_paired_scores_not_available_in_sanitized_archive"])
        self.assertFalse(self.report["model_capacity_or_learning_superiority_verified"])
        self.assertFalse(self.report["independent_raw_answer_replay_from_sanitized_archive_possible"])

    def test_no_torch_transformers_or_network_dependency(self):
        import sys
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("transformers", sys.modules)
        self.assertNotIn("huggingface_hub", sys.modules)

    def test_extracted_member_checksum_denies_resigned_report(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name, content in self.payload.items():
                dst = base / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(json.dumps(content))
            with self.assertRaisesRegex(ValueError, "pinned original JSON member"):
                v23.read_extracted_members(base)

    def test_extracted_member_private_extra_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name, content in self.payload.items():
                dst = base / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(json.dumps(content))
            (base / "publisher-answer-private.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "member census"):
                v23.read_extracted_members(base)

    def test_extracted_member_source_identities_match_original_archive(self):
        # Source-only mock hashes prove the test checks bytes, not filenames.
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            import hashlib
            original = dict(v23.MEMBER_SHA256)
            try:
                for name, content in self.payload.items():
                    dst = base / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    raw = json.dumps(content).encode()
                    dst.write_bytes(raw)
                    v23.MEMBER_SHA256[name] = hashlib.sha256(raw).hexdigest()
                self.assertEqual(v23.reconcile(v23.read_extracted_members(base)), self.report)
            finally:
                v23.MEMBER_SHA256.clear()
                v23.MEMBER_SHA256.update(original)


if __name__ == "__main__":
    unittest.main()
