"""Historical dispatch cannot turn absence, cancellation or raw data into work."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
SOURCE = AGENT + "learning_iteration_historical_source.rs"
JOURNAL = AGENT + "learning_owner_journal_historical_delivery.rs"


class HistoricalLearningDeliverySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_new_source_is_only_same_actual_receipt_prepared_owner_and_recipient(self):
        self.check_markers(SOURCE, "fn capture_original_historical_source(", (
            "receipt.require_original_client(client, session)?",
            "receipt.initial_snapshot().request.agent_id.as_str() != identity.agent_id.as_str()",
            "source.require_current_historical_source(&source.identity)?",
            "source.receipt.require_original_client(client, session)?"))
        self.check_markers(SOURCE, "fn require_prepared_historical_source(", (
            "!std::ptr::eq(self.prepared.as_ref(), prepared)",
            "self.require_current_historical_source(&self.identity)"))
        self.check_markers(SOURCE, "fn require_current_historical_source(", (
            "identity != &self.identity || Instant::now() >= self.end",
            "require_original_historical_source(&self.receipt)"))
        self.reject_removal(SOURCE, "fn require_current_historical_source(",
                            "Instant::now() >= self.end", 1)

    def test_dataset_capsule_cannot_be_replaced_by_live_or_another_root_receipt(self):
        self.check_markers(AGENT + "cell_q24_dataset_historical_ledger.rs",
                           "fn require_original_historical_dataset_receipt(", (
            "OriginalDatasetLedgerV1::Historical(ledger) = &source.ledger",
            "!Arc::ptr_eq(&ledger.receipt, receipt)",
            "OriginalHistoricalLearningTrustV1::require_original_receipt(&ledger.trust, receipt)?"))
        self.check_markers(AGENT + "cell_q24_prepared_learning.rs",
                           "fn require_original_historical_source(", (
            "require_original_historical_dataset_receipt(receipt)?",
            "receipt.initial_snapshot() != &self.initial", "self.revalidate_source()"))

    def test_original_root_assembly_and_new_journal_binding_are_mandatory(self):
        self.check_markers(SOURCE, "fn with_original_historical_source(", (
            "self.require_identity(identity)?", "source.require_prepared_historical_source(prepared)?",
            "self.retained_source.is_some()", "self.historical_source.is_some()",
            "self.historical_delivery.is_some()", "!self.enforce_circuit_admission",
            "CircuitLearningSourceV1::OriginalQ24", "self.scope.as_ref() != Some(prepared.scope())",
            "self.owners != prepared.initial().owners",
            "registry.requests.as_slice() != std::slice::from_ref(source.request())",
            "crate::neuron_generation_process_identity_digest_v1(identity)?",
            "prepared.initial().head_digest.as_array()", "prepared.scope().binding().as_array()"))
        for occurrence in (0, 1):
            self.reject_removal(SOURCE, "fn with_original_historical_source(",
                                "source.require_current_historical_source(identity)?", occurrence)

    def test_queue_reservation_and_witnessed_claim_precede_actual_async_dispatch(self):
        self.check_markers(SOURCE, "fn run(", (
            "require_ready(&state).is_ok() && state.automation_admission_ready()?",
            "handle.reserve()", "self.journal.read(&self.key)",
            "commit_original_historical_delivery(&self.key",
            "timeout_at(source.end.into(), reservation.submit(source.request().clone()))"))
        for occurrence in (0, 1):
            self.reject_removal(SOURCE, "fn run(",
                                "source.require_current_historical_source(state.identity())", occurrence)
        self.check_markers(JOURNAL, "fn commit_original_historical_delivery<F>(", (
            "self.journal.claim(key)", "ProductEvaluationExecutionStateV1::Pending",
            "return Err(Error::Pending)", "self.anchor_append(before)?",
            "let bytes = dispatch().await?", "self.journal.complete(key, &bytes).is_err()",
            "self.read(key)?", "saved != bytes"))

    def test_existing_pending_or_complete_uses_only_actual_root_readback(self):
        for occurrence in (0, 1):
            self.reject_removal(SOURCE, "fn run(",
                                "self.readback(reservation, &cancellation).await?", occurrence)
        self.check_markers(SOURCE, "fn run(", (
            "saved.as_slice() != snapshot.head_digest.as_array()", "Err(JournalError::Pending)",
            "ProductEvaluationExecutionStoreErrorV1::Missing", "*observed_snapshot = Some(result)"))
        self.check_markers(SOURCE, "fn readback(", (
            "cancellation.cancelled()",
            "tokio::time::timeout_at(self.source.end.into(), reservation.readback(self.source.request().clone()))",
            "require_complete(&self.source, &result)?"))
        self.check_markers(SOURCE, "fn require_complete(", (
            "snapshot.request != *source.request()", "snapshot.owners != source.prepared.initial().owners",
            "validate_snapshot(snapshot)", "completed.next_stage().is_some()"))

    def test_waiting_c_preserves_original_source_and_current_owner_checks(self):
        path = AGENT + "learning_iteration_successor.rs"
        self.check_markers(path, "fn prepare_original_successor_context(", (
            "match (&self.retained_source, &self.historical_source)",
            "(Some(retained), None) if retained.request() == &prepared.initial().request",
            "(None, Some(historical)) if historical.request() == &prepared.initial().request",
            "RegisteredHistoricalLearningSourceV1::require_prepared_historical_source(\n                    historical, prepared,\n                )?",
            "session.identity() != identity", "self.scope.as_ref() != Some(prepared.scope())",
            "self.owners != prepared.initial().owners", "context.require_current_successor_context().await?"))
        self.check_markers(path, "fn require_current_successor_context(", (
            "retained.observe_retained_learning(&self.identity).await?",
            "RegisteredHistoricalLearningSourceV1::require_current_historical_source(\n                    source,\n                    &self.identity,\n                )?",
            "owners\n            .require_current()\n            .await"))
        for occurrence in (0, 1):
            self.reject_removal(path, "fn require_current_successor_context(",
                                "self.session.require_current_successor_session()", occurrence)

    def test_closed_new_inventory_does_not_claim_an_unwired_main(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        selected = {name: row for name, row in rows.items() if name.startswith("q24_historical_delivery_")}
        self.assertEqual(len(selected), 7)
        for name in selected:
            self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])
        for name in ("q24_historical_delivery_capture", "q24_historical_delivery_install"):
            self.assertEqual(rows[name]["product_callers"], [])
        self.assertEqual(rows["q24_historical_delivery_async_claim"]["product_callers"], [SOURCE])


if __name__ == "__main__":
    unittest.main()
