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
                                ".require_batch(self)", occurrence)
        self.check_markers(OPERATION, "fn require_batch(", (
            "match (&source.ledger, &self.kind)", "source.materialize_live(ledger)?",
            "source.materialize_historical_in_operation(ledger, self)?",
            "OriginalDatasetLedgerV1::Live(_), DatasetOperationKind::Historical(_)",
            "OriginalDatasetLedgerV1::Historical(_), DatasetOperationKind::Live",
            "observed.encoded != batch.encoded || observed.digest != batch.digest"))

    def test_borrowed_prepared_facts_keep_actual_owner_and_full_validation(self):
        self.check_markers(PREPARED, "fn with_original_prepared_operation<T, E>(", (
            "for<'read> FnOnce(&OriginalPreparedReadV1<'read>)",
            "self.batch.with_original_dataset_operation(", "prepared: self", "operation,"))
        self.check_markers(PREPARED, "fn require_prepared(", (
            "!std::ptr::eq(self.prepared, prepared)", "return Err(", "self.revalidate_source()"))
        self.check_markers(PREPARED, "fn revalidate_source(", (
            "self.operation.require_batch(&self.prepared.batch)?",))
        for occurrence in (0, 1):
            self.reject_removal(PREPARED, "fn read_validated_facts(",
                                "self.revalidate_source()?", occurrence)

    def test_live_writer_identity_cannot_be_replaced_by_historical_bytes(self):
        self.check_markers(MATERIALIZER, "fn require_original_ledger_capability(", (
            "let OriginalDatasetLedgerV1::Live(original) = &source.ledger else",
            "!Arc::ptr_eq(original, ledger)", "source.require_batch(self)"))
        self.check_markers(MATERIALIZER, "fn from_original_dataset(", (
            "ledger: OriginalDatasetLedgerV1::Live(ledger)", "source.materialize()?", "batch.source = Some(source)"))


if __name__ == "__main__":
    unittest.main()
