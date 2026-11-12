"""Exact data identities move together; all actual signer checks remain outside."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
PURE = AGENT + "cell_q24_dataset_identity.rs"
CAPTURE = AGENT + "cell_q24_dataset_preparation.rs"
OWNER = AGENT + "cell_q24_dataset_freeze_owner.rs"


class FreezeIdentitySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_only_actual_owner_consumers_are_listed(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["q24_dataset_pure_preparation_identity"]["product_callers"], [AGENT + "cell_q24_dataset_historical_preparation.rs", AGENT + "cell_q24_dataset_preparation.rs", AGENT + "authority_host_post_a_derive.rs"])
        self.assertEqual(rows["q24_dataset_pure_freeze_execution_key"]["product_callers"], [AGENT + "cell_q24_dataset_freeze_owner.rs", AGENT + "authority_host_post_a_derive.rs"])

    def test_full_preparation_data_and_order_remain_bound(self):
        self.check_markers(PURE, "fn original_q24_dataset_preparation_identity_v1(", (
            "CellQ24PrivateHeadV1::Drive { index } => (1_u8, index)",
            "CellQ24PrivateHeadV1::Prediction { index } => (2_u8, index)",
            "initial_head.as_array()", "ledger_binding.as_array()",
            "Digest32::of_bytes(canonical_payload).as_array()", "effective_weights.as_array()",
            "&[tag]", "&index.to_le_bytes()", "&rule.epochs.to_le_bytes()",
            "&rule.learning_rate_q24.to_le_bytes()"))

    def test_actual_preparation_still_checks_original_source_before_hashing(self):
        self.check_markers(CAPTURE, "fn identity(", (
            "self.revalidate_source()?", "LearningIterationCoordinatorV1::new(",
            "dataset_freeze_signing_payload_v2(", "crate::original_q24_dataset_preparation_identity_v1(",
            "initial.snapshot().head_digest", "ledger.binding_digest()", "&payload",
            "self.config.baseline.effective_weights_digest()", "self.config.head", "self.config.rule"))

    def test_freeze_namespace_keeps_key_principal_trust_and_ttl(self):
        self.check_markers(PURE, "fn original_q24_dataset_freeze_execution_key_v1(", (
            "plan_id: operation_id.clone()", "preparation_identity.as_array()", "trust_digest.as_array()",
            "signer.principal.principal_id.as_str().as_bytes()", "&signer.verifying_key",
            "&maximum_signature_lifetime_seconds.to_be_bytes()"))

    def test_actual_freezer_keeps_current_role_and_key_checks(self):
        self.check_markers(OWNER, "fn validate_config(", (
            "preparation.identity()?", "ledger.verifier()",
            "config.verifier.trust_digest() != original.trust_digest()",
            "config.verifier.scope_digest() != original.scope_digest()",
            "config.verifier.objective_digest()",
            "key.verifying_key().to_bytes() != config.signer.verifying_key",
            "!(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)", "original.require_signer_binding(",
            "config.verifier.require_signer_binding(", "crate::original_q24_dataset_freeze_execution_key_v1(",
            "&preparation.config.request.operation_id", "original.trust_digest(),",
            "&config.signer,\n        config.maximum_signature_lifetime_seconds,"))


if __name__ == "__main__":
    unittest.main()
