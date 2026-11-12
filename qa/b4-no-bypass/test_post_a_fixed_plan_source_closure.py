"""A fixed Root post-A policy is neither a peer batch nor a registration grant."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
FILE = component.AGENT + "authority_host_post_a_learning.rs"


class PostAFixedPlanSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_original_recipient_target_trust_and_policy_are_fixed(self):
        self.check_markers(FILE, "fn retain_original_plan(", (
            "original_root()?", "MetadataFile::open_metadata(path)?", "data.schema != 1",
            "data.purpose !=", "data.initial != initial.head_digest.to_string()",
            "!initial.receipts.is_empty()", "data.target != actual_target.to_string()",
            "!(1..=86_400).contains(&data.maximum_signature_lifetime_seconds)",
            "!(1..=256).contains(&data.epochs)",
            "!(1..=(1 << 24)).contains(&data.learning_rate_q24)",
            "mapping.is_zero() || mapping.to_string() != data.learning_trust_mapping"))

    def test_explicit_mode_and_actual_baseline_define_the_policy(self):
        self.check_markers(FILE, "fn retain_original_plan(", (
            "match data.mode.as_str()", "match data.head.as_str()",
            "baseline_bundle: initial\n                .request\n                .selected_bundle\n                .digest()",
            "PostABaselineFiles::retain_original_baseline(data.baseline)?",
            "PostAFreezeFiles::retain_original_freeze(",
            "initial.request.envelope.objective_digest",
            "MetadataFile::open_metadata(&data.model_reservation)?",
            "StableId::new(data.snapshot_id)", "held.require_original_metadata()?"))
        self.reject_removal(FILE, "fn retain_original_plan(", "peer_uid", 1)
        self.reject_removal(FILE, "fn retain_original_plan(", "peer_gid", 1)

    def test_metadata_and_explicit_recovery_never_use_missing_state_defaults(self):
        self.check_markers(FILE, "fn require_original_metadata(", (
            "original_root()?", "self.metadata.require_metadata_unchanged()?",
            "self.reservation_metadata.require_metadata_unchanged()"))
        self.check_markers(FILE, "fn original_mode(", (
            "if self.register", "OriginalDerivedLearningMode::Register",
            "OriginalDerivedLearningMode::Reopen"))


if __name__ == "__main__":
    unittest.main()
