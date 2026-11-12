"""Historical preparation has current trust and no implicit old writer."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
HISTORY = AGENT + "cell_q24_dataset_historical_preparation.rs"
CAPTURE = AGENT + "cell_q24_dataset_preparation.rs"
MATERIALIZER = AGENT + "cell_q24_dataset_materializer.rs"


class HistoricalPreparationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_view_and_batch_have_actual_preparation_consumers(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        for key in ("q24_original_historical_dataset_ledger", "q24_original_historical_dataset_read"):
            self.assertEqual(rows[key]["product_callers"], [HISTORY])
        self.assertEqual(rows["q24_original_historical_dataset_batch"]["product_callers"],
                         [AGENT + "cell_q24_prepared_learning.rs"])
        self.assertEqual(rows["q24_original_historical_preparation"]["product_callers"],
                         [AGENT + "production_post_a_q24.rs"])

    def test_capture_uses_original_current_cut_and_deadline(self):
        self.check_markers(HISTORY, "fn capture_historical(", (
            "HistoricalDatasetLedgerV1::capture_original(receipt, trust, vec![task])?",
            "HistoricalDatasetLedgerV1::with_current(", "require_historical_configuration(&config, &ledger)",
            "observed_at >= config.request.envelope.expiry_unix_seconds",
            "RootHistoricalLedgerReadDataV1::read_snapshot(data)?", "data.ledger_cut()?.frontier",
            "ledger: OriginalDatasetLedgerV1::Historical(ledger)", "preparation.signing_payload()?"))

    def test_snapshot_and_whole_current_initial_are_rechecked_each_time(self):
        self.check_markers(HISTORY, "fn with_historical_cut<T>(", (
            "HistoricalDatasetLedgerV1::with_current(", "require_historical_configuration(&self.config, ledger)",
            "RootHistoricalLedgerReadDataV1::read_snapshot(data)?", "data.ledger_cut()?",
            "current != self.snapshot || cut.frontier != self.frontier",
            "action(&current, cut.binding, verifier, evaluator, observed_at)"))
        self.check_markers(HISTORY, "fn require_historical_configuration(", (
            "LearningIterationCoordinatorV1::new(", "initial.snapshot() != ledger.initial_snapshot()",
            "ledger\n        .original_task_data()", "require_configuration_data(config, &publications)"))

    def test_identity_and_payload_are_shared_and_computed_inside_current_read(self):
        self.check_markers(HISTORY, "fn identity_historical(", (
            "self.with_historical_cut(", "dataset_freeze_signing_payload_v2(snapshot, &self.plan()?)?",
            "crate::original_q24_dataset_preparation_identity_v1(", "ledger.initial_snapshot().head_digest",
            "&payload", "self.config.baseline.effective_weights_digest()",
            "self.config.head", "self.config.rule"))
        self.reject_removal(HISTORY, "fn identity_historical(", "binding,", 1)
        self.check_markers(HISTORY, "fn signing_payload_historical(", (
            "self.with_historical_cut(", "dataset_freeze_signing_payload_v2(snapshot, &self.plan()?)?"))

    def test_current_fixed_evaluator_and_canonical_projection_validate_freeze(self):
        self.check_markers(HISTORY, "fn validate_authorization_historical(", (
            "self.with_historical_cut(", "dataset_freeze_signing_payload_v2(snapshot, &plan)?",
            "verifier.verify(", "LearningEvidenceRoleV1::Evaluator", "authorization,", "&payload",
            "verified.principal() != &evaluator.principal", "verified.controller_id() != &evaluator.controller_id",
            "freeze_dataset_from_ledger(", "LedgerSnapshot::read_dataset_records(",
            "crate::project_original_q24_dataset_v1(", "&ledger.original_task_data()",
            "Ok(CellQ24FrozenDatasetV1", "authorization: authorization.clone()"))

    def test_historical_preparation_reuses_the_original_scope_algorithm(self):
        self.check_markers(HISTORY, "fn materialize_historical(", (
            "let OriginalDatasetLedgerV1::Historical(ledger) = &self.ledger else",
            "self.validate_authorization_historical(ledger, &authorization)?",
            "CellQ24PreparedLearningV1::from_historical(self.config, ledger, frozen)"))
        self.check_markers(AGENT + "cell_q24_prepared_learning.rs", "fn from_historical(", (
            "historical_preparation::require_historical_configuration(&config, &ledger)?",
            "frozen.receipt.snapshot.snapshot_id != config.snapshot_id",
            "CellQ24TrainingBatchV1::from_original_historical_dataset(",
            "Self::finish_original(config, frozen, batch, publication)"))

    def test_historical_variants_cannot_return_live_writer(self):
        for function in ("fn original_writer(", "fn into_original_writer("):
            self.check_markers(MATERIALIZER, function, (
                "match self", "Self::Live(ledger) => Ok(ledger)", "Self::Historical(_)", "Err(Error::Binding("))
        self.check_markers(CAPTURE, "fn identity(", (
            "OriginalDatasetLedgerV1::Historical(ledger) = &self.ledger", "return self.identity_historical(ledger)",
            "self.revalidate_source()?", "original_writer()?"))
        self.check_markers(CAPTURE, "fn materialize(", (
            "self.with_historical_cut(", "observed_at >= self.config.request.envelope.expiry_unix_seconds",
            "return self.materialize_historical(authorization)", "self.ledger.into_original_writer()?"))


if __name__ == "__main__":
    unittest.main()
