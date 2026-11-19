"""Original owner startup composition preserves real capability boundaries.

All positives here are source-closure evidence only. Native Root reads, original
journal state and the unchanged end-to-end deadline/read budget are separate gates.
"""
from dataclasses import replace
from pathlib import Path
import re
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component
import test_historical_task_read_source_closure as route

ROOT = component.ROOT
A = component.AGENT
PROOF = component.PROOF
EXPECTED = {
    "q24_original_historical_freeze_construction": {
        "symbol": "CellQ24DatasetFreezePreparationV1::materialize_original_historical_owner",
        "path": "codex-rs/hepta-agentd/src/cell_q24_freeze_operation.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/production_post_a_q24_owners.rs"
        ]
    },
    "q24_original_freeze_create_in_operation": {
        "symbol": "OriginalCellQ24DatasetFreezeOwnerV1::create_in_operation",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_freeze_owner.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/cell_q24_freeze_operation.rs"
        ]
    },
    "q24_original_freeze_recover_in_operation": {
        "symbol": "OriginalCellQ24DatasetFreezeOwnerV1::recover_in_operation",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_freeze_owner.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/cell_q24_freeze_operation.rs"
        ]
    },
    "q24_original_freeze_authorize_in_operation": {
        "symbol": "OriginalCellQ24DatasetFreezeOwnerV1::authorize_in_operation",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_freeze_owner.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/cell_q24_freeze_operation.rs"
        ]
    },
    "q24_original_historical_successor_registration": {
        "symbol": "OriginalCellQ24LearningStageOwnersV1::register_original_historical_successor",
        "path": "codex-rs/hepta-agentd/src/cell_q24_learning_successor.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/learning_iteration_successor.rs"
        ]
    },
    "root_historical_original_task_operation_read": {
        "symbol": "OriginalHistoricalOperationV1::read_original_task",
        "path": "codex-rs/hepta-agentd/src/root_historical_learning_operation.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_task.rs"
        ]
    },
    "q24_original_historical_task_capture_in_operation": {
        "symbol": "CellQ24DatasetTaskV1::capture_historical_in_operation",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_task.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_ledger.rs"
        ]
    },
    "q24_original_historical_task_ledger_in_operation": {
        "symbol": "HistoricalDatasetLedgerV1::capture_original_task_in_operation",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_ledger.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_preparation.rs"
        ]
    },
    "q24_original_dataset_borrow_historical": {
        "symbol": "OriginalDatasetOperationV1::borrow_original_historical",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_operation.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_preparation.rs"
        ]
    },
    "q24_original_historical_task_preparation": {
        "symbol": "CellQ24DatasetFreezePreparationV1::capture_original_historical_task",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_preparation.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/production_post_a_q24.rs"
        ]
    },
    "q24_original_historical_preparation_in_operation": {
        "symbol": "CellQ24DatasetFreezePreparationV1::capture_historical_in_operation",
        "path": "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_preparation.rs",
        "callers": []
    },
    "q24_historical_delivery_capture_in_operation": {
        "symbol": "RegisteredHistoricalLearningSourceV1::capture_original_historical_source_in_operation",
        "path": "codex-rs/hepta-agentd/src/learning_iteration_historical_source.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/production_post_a_q24.rs"
        ]
    },
    "q24_historical_delivery_install_in_operation": {
        "symbol": "LearningIterationRuntimeBootstrapV1::with_original_historical_source_in_operation",
        "path": "codex-rs/hepta-agentd/src/learning_iteration_historical_source.rs",
        "callers": [
            "codex-rs/hepta-agentd/src/production_post_a_q24.rs"
        ]
    }
}

class HistoricalStartupOperationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {item["path"] for item in EXPECTED.values()}
        paths.update(path for item in EXPECTED.values() for path in item["callers"])
        cls.sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_every_new_internal_entry_has_exact_actual_callers(self):
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.symbol, expected["symbol"])
                self.assertEqual(row.definition_path, expected["path"])
                self.assertEqual(row.product_callers, tuple(expected["callers"]))
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_unregistered_or_omitted_callers_cannot_borrow_original_authority(self):
        for identifier in EXPECTED:
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                method = row.symbol.rsplit("::", 1)[-1]
                sources = dict(self.sources)
                sources[A + "unregistered_startup_owner.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}")
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                if row.product_callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_original_freezer_open_and_sign_use_actual_borrow_and_journal(self):
        owner = A + "cell_q24_dataset_freeze_owner.rs"
        self.check_markers(owner, "fn create_in_operation(", (
            "read: &OriginalFreezePreparationReadV1<'_>",
            "OriginalFreezePreparationReadV1::original_signing_payload(read)?",
            "validate_config(preparation, &config, &key, read)?",
            "LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?"))
        self.check_markers(owner, "fn recover_in_operation(", (
            "read: &OriginalFreezePreparationReadV1<'_>",
            "validate_config(preparation, &config, &key, read)?",
            "LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?"))
        path = A + "cell_q24_freeze_operation.rs"
        function = "fn materialize_original_historical_owner<W: AnchorWitnessStore>("
        self.check_markers(path, function, (
            "OriginalDatasetLedgerV1::Historical(ledger) = &self.ledger else",
            ".with_original_ledger_operation(move |operation|",
            "preparation: &self", "operation,",
            "OriginalCellQ24DatasetFreezeOwnerV1::create_in_operation(",
            "OriginalCellQ24DatasetFreezeOwnerV1::recover_in_operation(",
            "OriginalCellQ24DatasetFreezeOwnerV1::authorize_in_operation(",
            "read.validate_original_authorization(&authorization)?",
            "drop(owner)", "result?",
            "CellQ24PreparedLearningV1::from_historical(self.config, ledger, frozen, operation)",
            ".map_err(Error::from)?"))
        for occurrence in (0, 1):
            self.reject_removal(path, function,
                                "OriginalFreezePreparationReadV1::revalidate_source(&read)?", occurrence)

    def test_new_ledger_constructs_task_from_same_root_operation_not_raw_input(self):
        self.check_markers(A + "cell_q24_dataset_historical_ledger.rs",
                           "fn capture_original_task_in_operation(", (
            "OriginalHistoricalLearningTrustV1::require_original_receipt(&trust, &receipt)?",
            "CellQ24DatasetTaskV1::capture_historical_in_operation(",
            "Arc::clone(&receipt)", "client,", "session,", "operation,",
            "OriginalHistoricalOperationV1::read_for(operation, &trust, &receipt,",
            "RootHistoricalLedgerReadDataV1::read_snapshot(data).map(|_| ())",
            "tasks: vec![task]"))
        self.check_markers(A + "cell_q24_dataset_operation.rs",
                           "fn borrow_original_historical(", (
            "read: &'read OriginalHistoricalOperationV1<'read>",
            "kind: DatasetOperationKind::Historical(read)"))

    def test_successor_registration_brackets_actual_slot_with_original_context(self):
        path = A + "cell_q24_learning_successor.rs"
        function = "fn register_original_historical_successor("
        self.check_markers(path, function, (
            "!std::ptr::eq(self, context.owners().as_ref())",
            "Arc::downgrade(slot)",
            "in_original_prepared_lane(move |owners, _runtime, read|",
            ".require_successor_session(context.session())",
            "owners.generation.is_some() || inner.successor.set(weak).is_err()"))
        for occurrence in (0, 1):
            self.reject_removal(path, function,
                                ".require_original_successor_operation(read)", occurrence)

    def test_source_capture_keeps_actual_completed_acceptance_and_exact_owner(self):
        path = A + "learning_iteration_historical_source.rs"
        self.check_markers(path, "fn capture_original_historical_source_in_operation(", (
            "receipt.require_original_client(client, session)?",
            "receipt.initial_snapshot().request.agent_id.as_str() != identity.agent_id.as_str()",
            "RootHistoricalTaskReadClientV1::retain_original_completed_acceptance(",
            "client, session, &identity",
            "terminal_acceptance: Mutex::new(Some(terminal_acceptance))",
            ".require_original_stage_operation(&source.identity, read)",
            "source.receipt.require_original_client(client, session)?"))

    def test_restore_only_reads_initialized_experience_and_dataset_in_same_operation(self):
        path = A + "cell_q24_learning_historical_operation.rs"
        self.check_markers(path, "fn run_stage(", (
            "let submit = matches!(mode, OriginalHistoricalRestoreModeV1::Submit)",
            "let mut current = self.restore(mode)?",
            "if submit && current.generation_prefix.is_none()",
            "LearningIterationCoordinatorV1::from_snapshot(",
            "current.snapshot.clone()", "stage @ (LearningIterationStageV1::Experience",
            "LearningIterationStageV1::Dataset)",
            "current = self.execute(current.snapshot, stage)?", "Ok(current)"))
        source = (ROOT / path).read_text()
        def check(text):
            body, _ = route.function(text, "fn run_stage(")
            prefix = body.split("OriginalHistoricalWorkV1::ConfirmRecovery(expected)", 1)[0]
            match = re.search(r"stage\s*@\s*\(([^)]*)\)", prefix)
            self.assertIsNotNone(match)
            self.assertEqual(re.findall(r"LearningIterationStageV1::([A-Za-z]+)", match.group(1)),
                             ["Experience", "Dataset"])
            self.assertNotIn(".await", prefix)
            self.assertNotIn(".block_on(", prefix)
            self.assertEqual(prefix.count("self.execute(current.snapshot, stage)?"), 1)
        check(source)
        for changed in (
            source.replace("stage @ (LearningIterationStageV1::Experience", "stage @ (LearningIterationStageV1::Training", 1),
            source.replace("| LearningIterationStageV1::Dataset)", "| LearningIterationStageV1::Dataset | LearningIterationStageV1::Training)", 1),
            source.replace("current = self.execute(current.snapshot, stage)?;", "current = self.execute(current.snapshot, stage).unwrap();", 1),
        ):
            self.assertNotEqual(changed, source)
            with self.assertRaises(AssertionError):
                check(changed)

    def test_new_construction_borrows_never_cross_an_async_or_detached_boundary(self):
        functions = {
            "cell_q24_freeze_operation.rs": ["fn materialize_original_historical_owner<W: AnchorWitnessStore>("],
            "cell_q24_dataset_historical_preparation.rs": ["fn capture_original_historical_task(", "fn capture_historical_in_operation("],
            "cell_q24_dataset_historical_task.rs": ["fn capture_historical_in_operation("],
            "cell_q24_dataset_historical_ledger.rs": ["fn capture_original_task_in_operation("],
            "root_historical_learning_operation.rs": ["fn read_original_task("],
            "learning_iteration_historical_source.rs": ["fn capture_original_historical_source_in_operation(", "fn with_original_historical_source_in_operation("],
        }
        for path, names in functions.items():
            source = (ROOT / (A + path)).read_text()
            for name in names:
                with self.subTest(path=path, function=name):
                    body, _ = route.function(source, name)
                    self.assertNotRegex(body, r"\.\s*await\b|\b(?:spawn|spawn_blocking|block_on|transmute)\s*\(")
                    self.assertNotIn("'static", body)

if __name__ == "__main__":
    unittest.main()
