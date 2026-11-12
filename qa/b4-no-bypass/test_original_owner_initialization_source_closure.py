"""Original initialization shares one real Prepared operation, not cached success."""

from dataclasses import replace
from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
PROOF = component.PROOF
AGENT = component.AGENT
SOURCE = AGENT + "cell_q24_source_receipt_owner.rs"
CONSTRUCTION = AGENT + "cell_q24_source_receipt_construction.rs"
FILES = AGENT + "cell_q24_source_owner_files.rs"
INPUTS = AGENT + "cell_q24_learning_owner_inputs.rs"
INITIAL = AGENT + "cell_q24_learning_owner_initialization.rs"
AGGREGATE = AGENT + "cell_q24_learning_stage_owners.rs"
NATIVE = AGENT + "cell_composed_q24_training_owner.rs"
NATIVE_NEW = AGENT + "cell_composed_q24_training_construction.rs"
STAGE = AGENT + "cell_q24_training_stage.rs"
STAGE_NEW = AGENT + "cell_q24_training_stage_construction.rs"
PREPARED = AGENT + "cell_q24_prepared_learning.rs"
MATERIAL = AGENT + "cell_q24_prepared_training_material.rs"
CALLERS = {
    "q24_source_construct_in_operation": (SOURCE, FILES),
    "q24_source_files_in_operation": (INPUTS,),
    "q24_source_experience_attest_operation": (INITIAL, SOURCE),
    "q24_source_dataset_attest_operation": (INITIAL,),
    "q24_prepared_training_material_operation": (PREPARED, INPUTS),
    "q24_native_training_create_source": (NATIVE, INPUTS),
    "q24_native_training_recover_source": (NATIVE, INPUTS),
    "q24_training_stage_initialize_operation": (INITIAL,),
    "q24_learning_initialize_operation": (AGGREGATE,),
    "q24_training_files_in_operation": (),
    "learning_original_source_prepared_handoff": (INPUTS,),
    "learning_original_training_require_original_pair": (INPUTS,),
    "learning_original_q24_source_inputs": (INITIAL,),
    "learning_original_q24_training_inputs": (INITIAL,),
}


class OriginalOwnerInitializationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_new_operations_have_exact_real_callers_and_reject_extra_issuers(self):
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        paths = {path for name in CALLERS for path in
                 (rows[name].definition_path, *rows[name].product_callers)}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for name, callers in CALLERS.items():
            with self.subTest(boundary=name):
                row = rows[name]
                self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, sources, ())
                for path in callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=tuple(
                            p for p in callers if p != path)), sources, ())
                extra = dict(sources)
                method = row.symbol.rsplit("::", 1)[-1]
                extra[AGENT + "unregistered_initialization_owner.rs"] = (
                    f"fn unexpected(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                    if row.receiver_type else f"fn unexpected() {{ {row.symbol}(); }}")
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_no_generic_constructor_or_attester_gains_product_authority(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        for name in ("learning_original_source_create", "learning_original_source_recover",
                     "learning_original_source_attest_experience", "learning_original_source_attest_dataset",
                     "learning_original_source_files_create", "learning_original_source_files_recover",
                     "cell_q24_original_native_create", "cell_q24_original_native_recover",
                     "learning_original_training_stage_constructor"):
            self.assertEqual(rows[name]["product_callers"], [])
            self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])

    def test_aggregate_keeps_real_factory_postcheck_even_when_initialization_fails(self):
        self.check_markers(AGGREGATE, "fn from_original_owners(", (
            "factory\n            .require_learning_scope", "factory\n            .require_local_policy",
            "local\n            .require_context", "let original_verifier = verifier.clone()",
            "tokio::task::spawn_blocking(move ||",
            "initialization::initialize_original_owners(for_open, sources, verifier, files, mode)",
            "map_err(|_| Error::CommitUncertain)", "} = opened??", "training: Arc::new(training)"))
        for occurrence in (0, 1):
            self.reject_removal(AGGREGATE, "fn from_original_owners(",
                                "factory.require_current().await", occurrence)

    def test_one_prepared_operation_encloses_actual_signers_dataset_and_trainer(self):
        self.check_markers(INITIAL, "fn initialize_original_owners(", (
            "let original = Arc::clone(&prepared)", ".with_original_prepared_operation(move |read|",
            "sources.open_original_source_pair_in_operation(", "OriginalCellQ24LearningOpenV1::Create",
            ".attest_experience_in_operation(read)", ".attest_dataset_in_operation(&mut experience, read)",
            "OriginalCellQ24LearningOpenV1::Recover", ".read_dataset_in_operation(&mut experience, read)",
            "completed.snapshot().clone()", "files.open_original_training_pair_in_operation(",
            "OriginalCellQ24TrainingStageV1::from_original_owners_in_operation(", "Ok(OriginalInitialOwnersV1"))
        for occurrence in (0, 1):
            self.reject_removal(INITIAL, "fn initialize_original_owners(",
                                "OriginalPreparedReadV1::require_prepared(read, &prepared)", occurrence)
        source = (ROOT / INITIAL).read_text()
        start = source.index("struct OriginalInitialOwnersV1")
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        self.assertNotIn("OriginalPreparedReadV1", source[start:end + 1])

    def test_source_construction_requires_original_mode_key_and_postcheck(self):
        self.check_markers(CONSTRUCTION, "fn open_original_source_in_operation(", (
            "validate_config(&prepared, &config, &key, read)?", "let journal = match mode",
            "OriginalCellQ24LearningOpenV1::Create", "LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?",
            "OriginalCellQ24LearningOpenV1::Recover", "LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?",
            "OriginalPreparedReadV1::require_prepared(read, &prepared)?", "Ok(Self"))
        self.check_markers(CONSTRUCTION, "fn attest_experience_in_operation(", (
            "self.config.stage != OriginalCellQ24SourceStageV1::Experience", "return Err(",
            "Arc::clone(&self.prepared)", "self.attest_at(prepared.initial(), read)"))
        self.check_markers(CONSTRUCTION, "fn attest_dataset_in_operation(", (
            "self.with_original_experience_in_operation(experience, read, Self::attest_at)",))

    def test_trainer_recovery_keeps_original_witness_and_durable_binding(self):
        self.check_markers(NATIVE_NEW, "fn create_with_source(", (
            "job_key(&plan, &batch, rule, source)?", "if witness.current()?.is_some()",
            "LockedFileProductEvaluationExecutionStoreV1::create(file, key.binding_digest)?",
            ".compare_and_swap(None, anchor(journal.anchor()))", "map_err(|_| Error::CommitUncertain)?"))
        self.check_markers(NATIVE_NEW, "fn recover_with_source(", (
            "job_key(&plan, &batch, rule, source)?", "witness\n            .current()?",
            "minimum\n            .sequence\n            .checked_sub(1)",
            "LockedFileProductEvaluationExecutionStoreV1::recover(", "checkpoint_digest",
            "witness\n                .compare_and_swap(Some(minimum), current)", "Ok(Self"))
        self.check_markers(NATIVE_NEW, "fn job_key(", (
            "plan.validate_fit_input_with_source(batch, rule, source)?",
            "plan.prefix.request.operation_id.clone()", "plan.prefix.head_digest.as_array()",
            "plan.scope.binding().as_array()", "plan.baseline.effective_weights_digest().as_array()",
            "batch.digest().as_array()", "optimizer.as_array()"))

    def test_stage_cannot_publish_before_both_original_owners_are_rechecked(self):
        self.check_markers(STAGE_NEW, "fn require_original_pair_with_source(", (
            "&receipts.config.dataset != dataset || &receipts.config.scope != scope",
            "super::super::validate_config(&receipts.config, &receipts.key)?",
            "training.require_original_dataset_source(source)?",
            "training.require_dataset_scope_with_source(dataset, scope, source)?"))
        self.check_markers(STAGE_NEW, "fn from_original_owners_in_operation(", (
            "Self::require_original_pair_with_source(&training, &receipts, dataset, scope, read)?",
            "let mut owners = Owners { training, receipts }", "let result = owners.require_original_initial_receipts(read);",
            "&owners.training", "&owners.receipts", "result?;", "dataset: dataset.clone()",
            "owners: Arc::new(Mutex::new(owners))", "lane: Arc::new(Semaphore::new(/*permits*/ 1))"))
        self.check_markers(STAGE_NEW, "fn require_original_initial_receipts(", (
            "super::super::validate_config(&self.receipts.config, &self.receipts.key)?",
            "match self.receipts.journal.read(&self.receipts.saved)",
            ".read_original_completion_with_source(source)", "ProductEvaluationExecutionStoreErrorV1::Missing",
            "Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into())"))

    def test_wrappers_and_new_modules_cannot_hide_validation_in_dead_branches(self):
        paths = (SOURCE, FILES, NATIVE, NATIVE_NEW, INITIAL, STAGE_NEW, MATERIAL, CONSTRUCTION)
        rows = [row for row in self.manifest["protected_file"] if row["path"] in paths]
        PROOF._verify_protected_files(ROOT, {"protected_file": rows})
        for path, function, marker in (
            (CONSTRUCTION, "fn open_original_source_in_operation(", "let saved = validate_config(&prepared, &config, &key, read)?;"),
            (FILES, "fn open_original_source_files_in_operation(", "validate_config(&prepared, &dataset, &self.dataset.key, read)?;"),
            (STAGE_NEW, "fn from_original_owners_in_operation(", "result?;"),
        ):
            source = (ROOT / path).read_text()
            start = source.index(function)
            offset = source.index(marker, start)
            changed = source[:offset] + "if false { " + marker + " }" + source[offset + len(marker):]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_text(changed)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {"protected_file": [r for r in rows if r["path"] == path]})


if __name__ == "__main__":
    unittest.main()
