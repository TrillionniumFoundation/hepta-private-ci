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


class TrainingSourceOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

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


if __name__ == "__main__":
    unittest.main()
