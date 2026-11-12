"""Root independently derives its scope; raw bytes cannot supply that authority."""

from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT = route.ROOT
PROOF = route.PROOF
FILE = route.A + "authority_host_post_a_derive.rs"
DERIVE = "fn with_original_derived_profile<T>("


class PostADeriveSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject(self, function, marker, occurrence=0):
        source = (ROOT / FILE).read_text()
        code, _ = route.function(source, function)
        matches = list(re.finditer(route.token_pattern(marker), code))
        self.assertGreater(len(matches), occurrence)
        full = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = full.index(function)
        match = matches[occurrence]
        left, right = start + match.start(), start + match.end()
        rows = [r for r in self.manifest["protected_file"] if r["path"] == FILE]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / FILE
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:left] + "/* " + source[left:right] + " */" + source[right:])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def check(self, markers, function=DERIVE):
        for marker in markers:
            with self.subTest(marker=marker):
                self.reject(function, marker)

    def test_same_original_task_recipient_and_actual_baseline_are_mandatory(self):
        self.check(("initial != &self.initial || trust.pin.mapping != self.learning_trust_mapping",
                    "RootOriginalHistoricalCompleteTaskObservationV1::ledger_read_data(observed)?",
                    "RootOriginalHistoricalCompleteTaskObservationV1::publication_read_data(observed)",
                    "RootHistoricalTaskPublicationDataV1::validate_against(&publication_data, &ledger)",
                    "self.require_original_task(&publication)?", "!= self.target",
                    "baseline.components() != &initial.request.selected_bundle.components",
                    "baseline.input_width() != usize::from(self.plan.projection.input_width)",
                    "usize::from(index) >= baseline.output_width()"))

    def test_actual_completion_has_fixed_identity_payload_evaluator_and_ttl(self):
        self.check(("ledger.read_snapshot()?", "dataset_freeze_signing_payload_v2(&snapshot, &plan)",
                    "current_trust.activate_for_recipient(initial, now)?",
                    "current_trust.require_activation_pin(initial, &activated, &trust.pin)?",
                    "original_q24_dataset_preparation_identity_v1(",
                    "original_q24_dataset_freeze_execution_key_v1(",
                    "PostAFreezeFiles::with_original_completion(&self.freeze, &key, end, |saved|",
                    "learning_owner_evidence::decode(saved)", "saved_payload != payload",
                    "signed.evidence_id.as_str()", "signed.expires_at != expected_expiry",
                    "signed.issued_at >= initial.request.envelope.expiry_unix_seconds",
                    ".verify(LearningEvidenceRoleV1::Evaluator, &signed, &payload, now)",
                    "verified.principal() != &evaluator.principal",
                    "verified.controller_id() != &evaluator.controller_id"))

    def test_scope_uses_original_records_and_shared_full_batch_algorithm(self):
        self.check(("freeze_dataset_from_ledger(&snapshot, plan, verified.principal().clone(), now)",
                    "LedgerSnapshot::read_dataset_records(&snapshot, &receipt, now)",
                    "project_original_q24_dataset_v1(", "&[(publication, cell)]",
                    "batch.rows() > initial.request.budget.maximum_dataset_rows",
                    "batch.encoded().len() as u64 > initial.request.budget.maximum_dataset_bytes",
                    "> initial.request.budget.maximum_training_steps", "self.plan.rule.digest(&batch)",
                    "HostAuthorityLearningProfileV1::new_scoped_v2(", "LearningUpdateScopeV2::Cell",
                    "profile.require_binding(identity, proof)? != *initial", "let result = action(profile)?"))

    def test_original_data_and_deadline_are_rechecked_after_the_root_action(self):
        self.check(("RootHistoricalLearningTrustV1::revalidate(trust, service, initial)?",
                    "after.components() != baseline.components()",
                    "after.effective_weights_digest() != baseline.effective_weights_digest()"))
        for occurrence in (0, 1):
            self.reject(DERIVE, "PostABaselineFiles::read_model(&self.baseline)?", occurrence)
        for occurrence in (0, 1, 2):
            self.reject(DERIVE, "self.require_original_metadata()?", occurrence)
            self.reject(DERIVE, "require_end(end)?", occurrence)

    def test_scope_cannot_substitute_another_task_model_or_principal(self):
        self.check(("input.scope.agent_id != request.agent_id", "input.scope.cell_id != request.cell_id",
                    "input.scope.run_id != request.source_run_id",
                    "input.scope.principal_digest.to_string() != request.principal_id.as_str()",
                    "input.objective_digest != request.envelope.objective_digest",
                    "publication.history_digest().as_str() != request.completed_task_receipt.to_string()",
                    "publication.bundle_digest() != self.plan.projection.baseline_bundle"),
                   "fn require_original_task(")


if __name__ == "__main__":
    unittest.main()
