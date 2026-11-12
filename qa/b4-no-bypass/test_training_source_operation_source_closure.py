"""Original native compute shares checks through two sealed source readers."""

from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
PROOF = component.PROOF
AGENT = component.AGENT
READ = AGENT + "cell_q24_training_source_read.rs"
PREPARED = AGENT + "cell_q24_prepared_operation.rs"
TRAINING = AGENT + "cell_composed_q24_training.rs"
FIT = AGENT + "cell_q24_training_fit.rs"
OPERATION = AGENT + "cell_q24_training_stage_operation.rs"
OWNER = AGENT + "cell_composed_q24_training_owner.rs"
STAGE = AGENT + "cell_q24_training_stage.rs"
CHECKPOINT = AGENT + "learning_iteration_q24_checkpoint.rs"


class TrainingSourceOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_scoped_checkpoint_shares_the_actual_client_and_concrete_owners(self):
        self.check_markers(CHECKPOINT, "fn with_original_q24_checkpoint(", (
            "self.initial != *prepared.initial()", "self.scope.as_ref() != Some(prepared.scope())",
            "let client = Arc::new(self)", "client: Arc::clone(&client)",
            "owners: Arc::clone(&owners)", "checkpoint: Checkpoint::RootClient(client)",
            "stages: owners"))
        self.check_markers(CHECKPOINT, "fn require_original_owners(", (
            "!Arc::ptr_eq(&self.owners, owners)", "self.client.initial != *prepared.initial()",
            "self.client.scope.as_ref() != Some(prepared.scope())"))

    def test_checkpoint_operations_still_call_the_original_transport(self):
        self.check_markers(CHECKPOINT, "fn restore_original(", (
            "self.require_original_owners(&self.owners)?", "self.client.restore(request).await"))
        self.check_markers(CHECKPOINT, "fn checkpoint_original(", (
            "self.require_original_owners(&self.owners)?", ".checkpoint(previous, snapshot)",
            "map_err(checkpoint_error)"))

    def test_source_read_implementations_cannot_be_replaced_with_success(self):
        source = (ROOT / READ).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == READ]
        markers = (
            "pub(crate) trait OriginalQ24DatasetReadV1: private::Sealed",
            "impl private::Sealed for OriginalQ24OwnerReadV1 {}",
            "batch.revalidate_source()", "batch.require_original_dataset_provenance()",
            "impl private::Sealed for super::OriginalPreparedReadV1<'_>",
            "super::OriginalPreparedReadV1::require_training_batch(self, batch)",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / READ
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            for marker in markers:
                with self.subTest(marker=marker):
                    target.write_text(source.replace(marker, "/* removed source check */"))
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source.replace("batch.revalidate_source()", "Ok(())"))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_prepared_read_requires_the_actual_same_dataset_arc(self):
        self.check_markers(PREPARED, "fn require_training_batch(", (
            "let original =", "self.prepared", "let candidate = batch",
            "!Arc::ptr_eq(original, candidate)", "return Err(",
            "OriginalDatasetOperationV1::require_original_batch(", "self.operation,", "batch,"))

    def test_existing_public_compute_keeps_original_owner_reads(self):
        self.check_markers(TRAINING, "fn fit(", (
            "self.fit_with_original_source(batch, rule, cancellation, &OriginalQ24OwnerReadV1)",))
        self.check_markers(TRAINING, "fn validate_fit_input(", (
            "self.validate_fit_input_with_source(batch, rule, &OriginalQ24OwnerReadV1)",))

    def test_full_preflight_still_checks_source_before_baseline_and_rule(self):
        self.check_markers(TRAINING, "fn validate_fit_input_with_source(", (
            "OriginalQ24DatasetReadV1::require_current_batch(source, batch)?",
            "source.require_baseline(", "let optimizer = rule.digest(batch)?"))

    def test_actual_fit_keeps_bounded_work_and_both_terminal_source_checks(self):
        self.check_markers(FIT, "fn fit_with_original_source(", (
            "self.validate_fit_input_with_source(&batch, rule, source)?", "checked_sub(now)",
            "remaining.min(Duration::from_millis(budget.maximum_training_milliseconds))",
            "cancellation.load(Ordering::Acquire)", "started.elapsed() >= limit",
            "if heads == plan.baseline.heads", "CellQ24TrainingOutcomeV1::NoUpdate",
            "plan.rebuild_candidate(", "CellQ24TrainingOutcomeV1::Candidate"))
        for occurrence in (0, 1):
            self.reject_removal(FIT, "fn fit_with_original_source(",
                                "OriginalQ24DatasetReadV1::require_current_batch(source, &batch)?",
                                occurrence)

    def test_new_reader_and_compute_boundaries_are_in_the_inventory(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        identifiers = (
            "q24_dataset_source_current_read", "q24_dataset_source_provenance_read",
            "q24_prepared_training_batch_read", "q24_native_training_fit_source_read",
            "q24_native_training_input_source_read",
        )
        for identifier in identifiers:
            self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
            self.assertIn(identifier, rows)
        self.assertEqual(rows["q24_prepared_training_batch_read"]["product_callers"], [READ])

    def test_borrowed_training_uses_the_original_lane_and_owner_through_postchecks(self):
        self.check_markers(OPERATION, "fn with_original_training_operation<T>(", (
            "for<'owners, 'read> FnOnce(", "self.require_dataset(dataset)",
            ".try_acquire_owned()", ".try_lock()",
            "validate_config(&owners.receipts.config, &owners.receipts.key)",
            "let result = work(&mut OriginalQ24TrainingOperationV1", "owners: &mut owners"))
        for occurrence in (0, 1):
            self.reject_removal(OPERATION, "fn with_original_training_operation<T>(",
                                "CellQ24TrainingOwnerV1::require_dataset_scope_with_source(", occurrence)
            self.reject_removal(OPERATION, "fn with_original_training_operation<T>(",
                                "CellQ24TrainingOwnerV1::require_original_dataset_source(", occurrence)

    def test_training_evidence_comes_from_actual_completed_owners_and_exact_cut(self):
        self.check_markers(OPERATION, "fn read_original_training_evidence(", (
            ".read_original_completion_with_source(self.source)",
            "LearningIterationCoordinatorV1::from_snapshot(", "self.dataset.clone()",
            "cut.record(", "completed.receipt.clone()", "completed.receipt.observed_unix_seconds",
            "snapshot: cut.snapshot().clone()", "source: self.source"))
        self.check_markers(STAGE, "fn read_original_completion_with_source(", (
            "OriginalCellQ24TrainingReceiptOwnerV1::readback_with_source(",
            "CellQ24TrainingOwnerV1::readback_with_source(training, source)?", "Ok(OriginalCellQ24TrainingCompletionV1"))

    def test_original_claim_witness_and_canonical_terminal_bytes_still_enclose_fit(self):
        self.check_markers(OWNER, "fn fit_or_readback_with_source(", (
            "match self.journal.claim(&self.key)?", "self.anchor_append(before)?",
            "self.plan.fit_with_original_source(", "self.batch.clone(),", "source,",
            "encode(&outcome, self.key.binding_digest)?", "self.decode(&payload)?",
            "self.journal.complete(&self.key, &payload)?", "self.readback_with_source(source)"))
        for occurrence in (0, 1):
            self.reject_removal(OWNER, "fn fit_or_readback_with_source(",
                                "self.require_current_with_source(source)?", occurrence)


if __name__ == "__main__":
    unittest.main()
