"""Current recipient trust source checks, not a Root/native qualification."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
DATA = AGENT + "root_historical_learning_trust_data.rs"
FILES = AGENT + "authority_host_historical_learning_trust.rs"


class HistoricalRecipientTrustSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_actual_activation_uses_the_shared_signed_genesis_codec(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertIn(DATA, rows["root_initial_learning_trust_activation"]["product_callers"])
        self.assertEqual(rows["root_historical_recipient_trust_activation"]["product_callers"], [FILES, AGENT + "authority_host_post_a_derive.rs", AGENT + "root_historical_learning_trust_client.rs"])
        self.assertEqual(rows["root_historical_recipient_trust_files"]["product_callers"], [AGENT + "authority_host_historical_read.rs"])
        self.assertEqual(rows["root_historical_recipient_trust_payload"]["product_callers"], [AGENT + "authority_host_historical_read.rs", AGENT + "authority_host_post_a_derive.rs"])
        self.check_markers(DATA, "fn activate_for_recipient(", (
            "self.signed.activate_pinned_genesis(now_seconds)?", "!initial.receipts.is_empty()",
            "activated.verifier().trust_digest() != initial.owners.evidence_trust_digest",
            "activated.verifier().objective_digest() != initial.request.envelope.objective_digest"))

    def test_freeze_evaluator_is_fixed_and_currently_authorized(self):
        self.check_markers(DATA, "fn activate_for_recipient(", (
            "signer.principal_id == self.freeze_evaluator.principal_id",
            "signer.controller_id == self.freeze_evaluator.controller_id",
            "matching.next().is_some()", "signer.original_signer()?",
            ".require_signer_binding(LearningEvidenceRoleV1::Evaluator, &signer, now_seconds)"))

    def test_pin_binds_new_initial_and_not_only_the_historical_trust(self):
        self.check_markers(DATA, "fn require_initial(", (
            "digest.is_zero() || digest.to_string() != *value", "!initial.receipts.is_empty()",
            "self.initial != initial.head_digest.to_string()",
            "self.trust != initial.owners.evidence_trust_digest.to_string()"))
        self.check_markers(DATA, "fn require_activation_pin(", (
            "pin.require_initial(initial)?", "activated.root_digest().to_string() != pin.root",
            "activated.distribution_digest().to_string() != pin.distribution",
            "self.freeze_evaluator_digest()?.to_string() != pin.freeze_evaluator"))

    def test_root_retains_original_files_and_validates_before_returning(self):
        self.check_markers(FILES, "fn open_original(", (
            "original_root()?", "MetadataFile::open_metadata(path)?", "expected.schema != 1",
            "&expected.target != target", "expected.initial != initial.head_digest.to_string()",
            "expected.signed_payload == path", "MetadataFile::open_metadata(&expected.signed_payload)?",
            "12 * 1024", "payload.activate_for_recipient(initial, now)?",
            "pin.learning_scope != expected.learning_scope", "held.revalidate(service, initial)?"))

    def test_original_files_and_clock_wrap_every_new_activation(self):
        for marker in ("self.metadata.require_metadata_unchanged()", "self.signed_file.require_metadata_unchanged()"):
            for occurrence in (0, 1):
                self.reject_removal(FILES, "fn revalidate(", marker, occurrence)
        self.check_markers(FILES, "fn revalidate(", (
            "initial != &self.initial", "self.pin.payload != self.signed_file.digest().to_string()",
            "HostAuthorityService::original_learning_unix_seconds(service)?",
            "self.payload.activate_for_recipient(initial, now)?"))

    def test_time_is_sampled_from_the_actual_root_service_only(self):
        self.check_markers(AGENT + "authority_host_learning_time.rs", "fn original_learning_unix_seconds(", (
            "original_root()?", "self\n            .clock\n            .refresh_projection()",
            ".observed_unix_ms", "/ 1_000"))

    def test_read_payload_is_mapped_to_the_actual_original_ledger(self):
        self.check_markers(FILES, "fn require_original_ledger(", (
            "ledger.validate_data()?", "ledger.target != self.expected.target",
            "ledger.trust.learning_scope != self.pin.learning_scope", "ledger.trust.objective != self.pin.objective"))
        for occurrence in (0, 1):
            self.reject_removal(FILES, "fn read_original_payload(", "self.revalidate(service, initial)?", occurrence)
        self.reject_removal(FILES, "fn read_original_payload(", "self.require_original_ledger(ledger)?")

    def test_root_enrollment_fixes_current_trust_before_profile_and_ack(self):
        self.check_markers(AGENT + "authority_host_historical_read.rs", "fn open_original(", (
            "service.with_learning_profile(", "RootHistoricalLearningTrustV1::open_original(",
            "&deployment.learning_trust_deployment", "&initial", "&deployment.target",
            "learning_trust: learning_trust.pin.clone()", "profile.binding = profile.digest()?",
            "RootHistoricalLearningTrustV1::revalidate(&learning_trust, service, &initial)?"))

    def test_both_read_operations_keep_whole_root_context_and_physical_refusal(self):
        path = AGENT + "authority_host_historical_read.rs"
        for occurrence in (0, 1, 2):
            self.reject_removal(path, "fn observe_complete_task(",
                                "RootHistoricalLearningTrustV1::revalidate(&self.learning_trust, service, &initial)?", occurrence)
        self.check_markers(path, "fn observe_complete_task(", (
            ".with_original_historical_task(service, end, |read|", "let (reply, initial) = service.with_learning_profile(",
            "RootOriginalHistoricalTaskReadV1::observe_original_task(",
            "RootHistoricalLearningTrustV1::require_original_ledger(&self.learning_trust, &ledger)?",
            "publication: RootOriginalHistoricalCompleteTaskObservationV1::publication_read_data(&observed)",
            "HistoricalReadOperationV1::LearningTrust", "reply.is_empty() || reply.len() > WIRE_BOUND"))

    def test_trust_reply_is_exact_profile_cut_pin_and_original_bound(self):
        self.check_markers(DATA, "fn require_original_trust_reply(", (
            "bytes.is_empty() || bytes.len() > WIRE_BOUND", "!(1..=MAX_READS).contains(&request_id)",
            "response.schema != 1", "response.purpose != TRUST_PURPOSE", "response.request_id != request_id",
            "response.profile != profile", "&response.pin != expected", "canonical_digest(&response.data_cut)?",
            "response.pin.require_initial(initial)?"))

    def test_operation_selection_cannot_reset_sequence_or_absolute_end(self):
        self.check_markers(AGENT + "authority_host_historical_read_runtime.rs", "fn serve_optional(", (
            "HistoricalReadOperationV1::from_purpose(&request.purpose)", "request.request_id != sequence",
            "!(1..=MAX_READS).contains(&sequence)", ".checked_add(1)", "let request_end = session_end",
            ".min(Instant::now() + Duration::from_millis(config.timeout_ms))", "operation,"))


if __name__ == "__main__":
    unittest.main()
