"""The original freeze journal uses the current Root-selected Evaluator key."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
HISTORY = AGENT + "cell_q24_dataset_historical_freezer.rs"
OWNER = AGENT + "cell_q24_dataset_freeze_owner.rs"
OPERATION = AGENT + "cell_q24_freeze_operation.rs"


class HistoricalFreezerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_only_actual_original_owner_requests_current_admission(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["q24_original_freeze_phase_clock"]["product_callers"], [OWNER])
        self.assertEqual(rows["q24_historical_freeze_key_admission"]["product_callers"], [OPERATION])
        for key in ("q24_original_freeze_operation", "q24_original_freeze_operation_owner",
                    "q24_original_freeze_operation_payload", "q24_original_freeze_operation_authorization",
                    "q24_original_freeze_operation_key"):
            self.assertEqual(rows[key]["product_callers"], [OWNER])
        self.assertEqual(rows["q24_historical_freeze_signing_config"]["product_callers"], [AGENT + "production_post_a_q24_owners.rs"])

    def test_config_clones_only_the_current_root_selected_authorities(self):
        self.check_markers(HISTORY, "fn original_historical_freeze_config(", (
            "OriginalDatasetLedgerV1::Historical(ledger) = &self.ledger else", "self.with_historical_cut(",
            "!(1..=86_400).contains(&maximum_signature_lifetime_seconds)",
            "signer: evaluator.clone()", "verifier: verifier.clone()"))

    def test_key_role_and_full_current_trust_are_checked_before_shared_identity(self):
        self.check_markers(HISTORY, "fn validate_historical_freezer(", (
            "CellQ24DatasetFreezePreparationV1::with_historical_cut_in_operation(", "config.signer != *evaluator",
            "config.verifier.trust_digest() != verifier.trust_digest()",
            "config.verifier.scope_digest() != verifier.scope_digest()",
            "key.verifying_key().to_bytes() != evaluator.verifying_key",
            "!(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)",
            "verifier.require_signer_binding(", "config.verifier.require_signer_binding(",
            "dataset_freeze_signing_payload_v2(snapshot, &self.plan()?)?",
            "crate::original_q24_dataset_preparation_identity_v1(", "ledger.initial_snapshot().head_digest",
            "self.config.baseline.effective_weights_digest()", "self.config.head", "self.config.rule",
            "crate::original_q24_dataset_freeze_execution_key_v1(", "&self.config.request.operation_id"))

    def test_the_existing_once_only_journal_is_used_after_historical_admission(self):
        self.check_markers(OWNER, "fn validate_config(", (
            "matches!(&preparation.ledger, OriginalDatasetLedgerV1::Historical(_))",
            "OriginalFreezePreparationReadV1::original_freezer_key(",
            "let identity = preparation.identity()?", "original_writer()"))
        self.check_markers(OWNER, "fn authorize_in_operation(", (
            "preparation.observed_unix_seconds()?", "self.journal.commit_once(",
            "preparation\n                        .observed_unix_seconds()",
            "observed >= preparation.config.request.envelope.expiry_unix_seconds",
            "sign_original(config, key, saved.binding_digest, &payload, observed)?"))
        self.check_markers(OWNER, "fn authenticate(", (
            "self.config.verifier.verify(", "preparation.observed_unix_seconds()?",
            "OriginalFreezePreparationReadV1::validate_original_authorization(read, &signed)?", "self.journal.read(&self.saved)? != bytes"))

    def test_real_root_operation_encloses_success_and_error_with_full_postcheck(self):
        self.check_markers(OPERATION, "fn with_original_freeze_operation<T, E>(", (
            "for<'read> FnOnce(&OriginalFreezePreparationReadV1<'read>)",
            "OriginalDatasetLedgerV1::with_original_ledger_operation(&self.ledger,",
            "preparation: self", "operation,", "action(&read).map_err(FreezeOperationError::Work)",
            "Err(FreezeOperationError::Work(error)) => Ok(Err(error))",
            "Err(FreezeOperationError::Source(error)) => Err(error)"))
        for occurrence in (0, 1):
            self.reject_removal(OPERATION, "fn with_original_freeze_operation<T, E>(",
                                "read.revalidate_source()", occurrence)
        self.check_markers(OPERATION, "fn require_original_preparation(", (
            "!std::ptr::eq(self.preparation, preparation)", "return Err(", "self.revalidate_source()"))

    def test_all_original_owner_entries_borrow_an_actual_preparation(self):
        for function in ("fn create(", "fn recover(", "fn authorize_or_readback(", "fn readback("):
            self.reject_removal(OWNER, function,
                                "CellQ24DatasetFreezePreparationV1::with_original_freeze_operation(")
        self.reject_removal(OWNER, "fn validate_config(",
                            "OriginalFreezePreparationReadV1::require_original_preparation(read, preparation)?")

    def test_live_owner_and_historical_canonical_checks_are_both_retained(self):
        self.check_markers(OPERATION, "fn original_signing_payload(", (
            "OriginalDatasetLedgerV1::Live(_) => self.preparation.signing_payload()",
            "OriginalDatasetLedgerV1::Historical(ledger)",
            "CellQ24DatasetFreezePreparationV1::with_historical_cut_in_operation(",
            "self.preparation", "ledger", "self.operation", "dataset_freeze_signing_payload_v2(",
            "&self.preparation.plan()?"))
        self.check_markers(OPERATION, "fn validate_original_authorization(", (
            "OriginalDatasetLedgerV1::Live(_)", "self.preparation.validate_authorization(authorization)",
            "OriginalDatasetLedgerV1::Historical(ledger)",
            "CellQ24DatasetFreezePreparationV1::validate_authorization_historical_in_operation(",
            "self.preparation", "ledger", "authorization", "self.operation"))

    def test_current_clock_still_uses_actual_original_root_lifetime_and_deadline(self):
        path = AGENT + "root_historical_learning_trust_client.rs"
        for occurrence in (0, 1):
            self.reject_removal(path, "fn original_unix_seconds(",
                                "RootHistoricalTaskReadConnectionV1::require_original_session(\n                &self.receipt.client.connection,\n            )", occurrence)
        self.check_markers(path, "fn original_unix_seconds(", (
            "self.receipt.client.fenced.load(Ordering::Acquire)", "self.clock.now_unix_ms()",
            "if result.is_err()", "self.receipt.client.fence()"))
        self.check_markers(HISTORY, "fn observed_unix_seconds(", (
            "match &self.ledger", "OriginalDatasetLedgerV1::Live(_) => now()",
            "OriginalDatasetLedgerV1::Historical(ledger)",
            "HistoricalDatasetLedgerV1::original_unix_seconds(ledger)?"))


if __name__ == "__main__":
    unittest.main()
