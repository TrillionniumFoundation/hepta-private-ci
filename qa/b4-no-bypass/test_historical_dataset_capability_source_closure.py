"""Historical Dataset uses actual receipt/current trust and never a writer."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
HISTORY = AGENT + "cell_q24_dataset_historical_ledger.rs"
MATERIALIZER = AGENT + "cell_q24_dataset_materializer.rs"
OPERATION = AGENT + "cell_q24_dataset_operation.rs"
PREPARED = AGENT + "cell_q24_prepared_operation.rs"
SOURCE = AGENT + "cell_q24_source_receipt_owner.rs"
SIGNATURE = AGENT + "cell_q24_source_signature.rs"
SOURCE_OPERATION = AGENT + "cell_q24_source_receipt_operation.rs"


class HistoricalDatasetCapabilitySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_current_trust_and_snapshot_have_only_actual_consumers(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["root_historical_current_trust_read"]["product_callers"], [HISTORY])
        self.assertEqual(rows["root_historical_current_trust_receipt"]["product_callers"], [HISTORY, OPERATION])
        self.assertEqual(rows["root_historical_ledger_snapshot_data"]["product_callers"],
                         [HISTORY, AGENT + "cell_q24_dataset_historical_preparation.rs"])
        self.assertEqual(rows["q24_dataset_pure_original_projection"]["product_callers"],
                         [HISTORY, AGENT + "cell_q24_dataset_historical_preparation.rs", MATERIALIZER,
                          AGENT + "authority_host_post_a_derive.rs"])

    def test_capture_checks_actual_task_and_trust_receipt_before_holding_view(self):
        self.check_markers(HISTORY, "fn capture_original(", (
            "OriginalHistoricalLearningTrustV1::require_original_receipt(&trust, &receipt)?",
            "tasks.len() != 1", "CellQ24DatasetTaskV1::require_historical_receipt(task, &receipt)?",
            "ledger.with_current(", "RootHistoricalLedgerReadDataV1::read_snapshot(data)"))

    def test_every_read_uses_current_authority_from_the_same_receipt(self):
        self.check_markers(HISTORY, "fn with_current<T>(", (
            "OriginalHistoricalLearningTrustV1::require_original_receipt(&self.trust, &self.receipt)?",
            "OriginalHistoricalLearningTrustV1::with_current_trust(&self.trust, action)"))

    def test_canonical_image_and_fixed_current_evaluator_govern_freeze(self):
        self.check_markers(HISTORY, "fn materialize_historical_in_operation(", (
            "operation.read_historical(", "RootHistoricalLedgerReadDataV1::read_snapshot(data)?",
            "current != self.frozen", "dataset_freeze_signing_payload_v2(&current, &plan)",
            "LearningEvidenceRoleV1::Evaluator", "&self.evidence", "&payload",
            "verified.principal() != &evaluator.principal", "verified.controller_id() != &evaluator.controller_id",
            "freeze_dataset_from_ledger(", "verified.principal().clone()", "!= self.receipt",
            "LedgerSnapshot::read_dataset_records(", "project_original_q24_dataset_v1("))

    def test_private_source_is_attached_only_after_full_materialization(self):
        self.check_markers(HISTORY, "fn from_original_historical_dataset(", (
            "tasks: ledger.tasks.clone()", "ledger: OriginalDatasetLedgerV1::Historical(ledger)",
            "source.materialize()?", "batch.source = Some(source)"))
        self.check_markers(MATERIALIZER, "fn materialize(", (
            "match &self.ledger", "OriginalDatasetLedgerV1::Live(ledger) => self.materialize_live(ledger)",
            "OriginalDatasetLedgerV1::Historical(ledger) => self.materialize_historical(ledger)"))

    def test_borrow_only_enters_through_actual_root_trust(self):
        self.check_markers(OPERATION, "fn with_original_ledger_operation<T, E>(", (
            "for<'read> FnOnce(&OriginalDatasetOperationV1<'read>)", "Self::Historical(ledger)",
            "OriginalHistoricalLearningTrustV1::require_original_receipt(",
            "&ledger.trust", "&ledger.receipt", "OriginalHistoricalLearningTrustV1::with_original_operation("))
        self.check_markers(OPERATION, "fn read_historical<T>(", (
            "DatasetOperationKind::Historical(read) = &self.kind", "return Err(",
            "OriginalHistoricalOperationV1::read_for(read, &ledger.trust, &ledger.receipt, action)"))

    def test_each_operation_checks_complete_batch_on_both_sides(self):
        for occurrence in (0, 1):
            self.reject_removal(OPERATION, "fn with_original_dataset_operation<T, E>(",
                                ".require_original_batch(self)", occurrence)
        self.check_markers(OPERATION, "fn require_original_batch(", (
            "match (&source.ledger, &self.kind)", "source.materialize_live(ledger)?",
            "source.materialize_historical_in_operation(ledger, self)?",
            "OriginalDatasetLedgerV1::Live(_), DatasetOperationKind::Historical(_)",
            "OriginalDatasetLedgerV1::Historical(_), DatasetOperationKind::Live",
            "observed.encoded != batch.encoded || observed.digest != batch.digest"))

    def test_borrowed_prepared_facts_keep_actual_owner_and_full_validation(self):
        self.check_markers(PREPARED, "fn with_original_prepared_operation<T, E>(", (
            "for<'read> FnOnce(&OriginalPreparedReadV1<'read>)",
            "CellQ24TrainingBatchV1::with_original_dataset_operation(", "prepared: self", "operation,"))
        self.check_markers(PREPARED, "fn require_prepared(", (
            "!std::ptr::eq(self.prepared, prepared)", "return Err(", "self.revalidate_source()"))
        self.check_markers(PREPARED, "fn revalidate_source(", (
            "OriginalDatasetOperationV1::require_original_batch(", "self.operation", "&self.prepared.batch",))
        for occurrence in (0, 1):
            self.reject_removal(PREPARED, "fn read_validated_facts(",
                                "self.revalidate_source()?", occurrence)

    def test_source_owners_borrow_the_same_prepared_identity(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["q24_original_source_receipt_signature"]["product_callers"], [SOURCE])
        self.assertIn(SOURCE, rows["q24_original_prepared_operation"]["product_callers"])
        self.assertEqual(rows["q24_original_prepared_operation_owner"]["product_callers"],
                         [AGENT + "cell_q24_learning_historical_operation.rs",
                          AGENT + "cell_q24_prepared_learning.rs", SOURCE_OPERATION, SOURCE])
        self.check_markers(SOURCE, "fn require_prepared(", (
            "self.config.stage != stage", "self.prepared.initial() != prepared.initial()",
            "self.prepared.scope() != prepared.scope()", "!std::ptr::eq(self.prepared.as_ref(), prepared)",
            "self.prepared.with_original_prepared_operation(",
            "validate_config(&self.prepared, &self.config, &self.key, read)? != self.saved",
            "validate_config(prepared, &self.config, &self.key, read)? != self.saved",
            "original_facts != retained_facts",
            "OriginalPreparedReadV1::require_prepared(read, &self.prepared)?",
            "OriginalPreparedReadV1::require_prepared(read, prepared)?"))

    def test_both_real_signers_are_checked_before_either_original_file_is_opened(self):
        self.check_markers(AGENT + "cell_q24_source_owner_files.rs", "fn open_original_source_files(", (
            "CellQ24PreparedLearningV1::with_original_prepared_operation(&prepared, |read|",
            "validate_config(&prepared, &experience, &self.experience.key, read)?",
            "validate_config(&prepared, &dataset, &self.dataset.key, read)?",
            ".open(Arc::clone(&prepared), experience, mode)?",
            "self.dataset.open(Arc::clone(&prepared), dataset, mode)?",
            "prepared.revalidate_source()?"))

    def test_training_material_is_compared_within_the_same_prepared_borrow(self):
        self.check_markers(AGENT + "cell_q24_prepared_learning.rs", "fn training_material(", (
            "self.with_original_prepared_operation(|read|",
            "OriginalPreparedReadV1::read_validated_facts(read)?",
            "scope != self.scope", "dataset.request != self.initial.request",
            "dataset.owners != self.initial.owners", "dataset.receipts.len() != 2",
            "dataset.receipts[0].observation != facts.experience",
            "dataset.receipts[1].observation != facts.dataset",
            "dataset.receipts[0].evidence_digest != facts.experience_evidence",
            "dataset.receipts[1].evidence_digest != facts.dataset_evidence",
            "CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(",
            "OriginalPreparedReadV1::require_prepared(read, self)?", "self.batch.clone()"))

    def test_source_signing_stays_after_actual_claim_and_between_complete_reads(self):
        self.check_markers(SOURCE, "fn attest_at(", (
            "self.original_observation(read)?", "self.journal.read(&self.saved)",
            "require_signer_binding(", "self.journal.commit_once(saved, ||",
            "sign_original_source_receipt(", "learning_owner_evidence::encode(&payload, &signed)",
            "self.authenticate_completed(prefix, &bytes, read)"))
        for occurrence in (0, 1):
            self.reject_removal(SOURCE, "fn attest_at(",
                                "OriginalPreparedReadV1::require_prepared(read, prepared)", occurrence)
        self.check_markers(SIGNATURE, "fn sign_original_source_receipt(", (
            "config.verifier.require_signer_binding(",
            ".checked_add(config.maximum_signature_lifetime_seconds)",
            ".min(config.signer.principal.expires_at)",
            "principal_id: config.signer.principal.principal_id.clone()",
            "trust_digest: config.verifier.trust_digest()", "scope_digest: config.verifier.scope_digest()",
            "objective_digest: config.verifier.objective_digest()",
            "key.sign(&signed.signing_bytes()).to_bytes()", "config.verifier.verify("))

    def test_dataset_still_reads_actual_experience_on_both_sides_of_work(self):
        self.check_markers(SOURCE, "fn with_original_experience(", (
            "Arc::clone(&self.prepared)", "prepared.with_original_prepared_operation(",
            "self.with_original_experience_in_operation(experience, read, operation)"))
        self.check_markers(SOURCE_OPERATION, "fn with_original_experience_in_operation(", (
            "experience.config.stage != OriginalCellQ24SourceStageV1::Experience",
            "!Arc::ptr_eq(&self.prepared, &experience.prepared)",
            "receipt.operation_id != initial.request.operation_id",
            "receipt.predecessor != initial.head_digest", "receipt.actor_id != initial.owners.experience",
            "facts.experience_evidence_digest()",
            "receipt.observed_unix_seconds != before.attestation.issued_at",
            "LearningEvidenceRoleV1::Observer", "operation(self, &before.snapshot, read)?"))
        for occurrence in (0, 1):
            self.reject_removal(SOURCE_OPERATION, "fn with_original_experience_in_operation(",
                                "experience.read_at(prepared.initial(), read)?", occurrence)
        self.check_markers(SOURCE, "fn authenticate_completed(", (
            "learning_owner_evidence::decode(bytes)?",
            "payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?",
            "verified.principal() != &self.config.signer.principal",
            "verified.controller_id() != &self.config.signer.controller_id",
            "self.journal.read(&self.saved)? != bytes"))

    def test_live_writer_identity_cannot_be_replaced_by_historical_bytes(self):
        self.check_markers(MATERIALIZER, "fn require_original_ledger_capability(", (
            "let OriginalDatasetLedgerV1::Live(original) = &source.ledger else",
            "!Arc::ptr_eq(original, ledger)", "source.require_batch(self)"))
        self.check_markers(MATERIALIZER, "fn from_original_dataset(", (
            "ledger: OriginalDatasetLedgerV1::Live(ledger)", "source.materialize()?", "batch.source = Some(source)"))


if __name__ == "__main__":
    unittest.main()
