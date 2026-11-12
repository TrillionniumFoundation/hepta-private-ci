"""Shared preparation checks preserve live reads and native-batch provenance."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
CONFIG = AGENT + "cell_q24_learning_preparation.rs"
PREPARED = AGENT + "cell_q24_prepared_learning.rs"


class PreparationSharedChecksSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_live_capture_keeps_validation_before_and_after_original_read(self):
        self.check_markers(CONFIG, "fn require_configuration(", (
            "require_configuration_profile(config, tasks.len())?", "task.read_current().cloned()",
            "require_configuration_data(config, &publications)"))

    def test_shared_profile_keeps_initial_baseline_head_and_projection(self):
        self.check_markers(CONFIG, "fn require_configuration_profile(", (
            "LearningIterationCoordinatorV1::new(", "!(1..=256).contains(&count)",
            "config.baseline.components() != &config.request.selected_bundle.components",
            "config.projection.baseline_bundle != bundle",
            "usize::from(config.projection.input_width) != config.baseline.input_width()",
            "usize::from(index) >= config.baseline.output_width()"))

    def test_shared_publication_keeps_full_source_and_completion_binding(self):
        self.check_markers(CONFIG, "fn require_configuration_data(", (
            "require_configuration_profile(config, publications.len())?",
            "input.scope.agent_id != config.request.agent_id", "input.scope.cell_id != config.request.cell_id",
            "input.scope.principal_digest.to_string() != config.request.principal_id.as_str()",
            "input.objective_digest != config.request.envelope.objective_digest",
            "publication.original_record().snapshot.run_id != input.scope.run_id",
            "publication.original_record().snapshot.objective_digest != input.objective_digest",
            "publication.bundle_digest() != bundle", "input.scope.run_id == config.request.source_run_id",
            "source.is_some()", "publication.history_digest().as_str()",
            "config.request.completed_task_receipt.to_string()", "source.ok_or("))

    def test_live_materialization_does_not_skip_its_original_owners(self):
        self.check_markers(PREPARED, "fn from_original(", (
            "require_configuration(", "frozen.receipt.snapshot.snapshot_id != config.snapshot_id",
            "frozen.receipt.snapshot.objective_digest != config.request.envelope.objective_digest",
            "CellQ24TrainingBatchV1::from_original_dataset(",
            "Self::finish_original(config, frozen, batch, publication)"))

    def test_scope_uses_actual_native_batch_provenance_rule_and_postcheck(self):
        self.check_markers(PREPARED, "fn finish_original(", (
            "batch.require_original_dataset_provenance()?", "batch.rows() > config.request.budget.maximum_dataset_rows",
            "batch.encoded().len() as u64 > config.request.budget.maximum_dataset_bytes",
            "config.request.budget.maximum_training_steps", "config.rule.digest(&batch)?",
            "FrozenLearningScopeV2::freeze(", "LearningIterationCoordinatorV1::new(",
            "publication\n            .history_digest()", "publication.publication_digest()", "prepared.revalidate_source()?"))


if __name__ == "__main__":
    unittest.main()
