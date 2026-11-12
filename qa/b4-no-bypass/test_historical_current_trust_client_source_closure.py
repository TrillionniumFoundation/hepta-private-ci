"""Current trust must come from the actual same-session bounded Root exchange."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
CLIENT = AGENT + "root_historical_task_read_client.rs"
TRUST = AGENT + "root_historical_learning_trust_client.rs"


class HistoricalCurrentTrustClientSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_current_capsule_has_no_unimplemented_product_caller(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["root_historical_current_trust_capsule"]["product_callers"], [])
        for key in ("root_historical_current_trust_read", "root_historical_current_trust_receipt"):
            self.assertEqual(rows[key]["product_callers"], [AGENT + "cell_q24_dataset_historical_ledger.rs"])
        self.assertEqual(rows["root_historical_fixed_client_exchange"]["product_callers"], [TRUST])
        self.assertEqual(rows["root_historical_recipient_trust_reply"]["product_callers"], [CLIENT])

    def test_capsule_uses_original_receipt_session_clock_cut_and_pin(self):
        for occurrence in (0, 1):
            self.reject_removal(TRUST, "fn activate_current_learning_trust(",
                                "OriginalHistoricalTaskReadReceiptV1::require_original_client(self, client, session)", occurrence)
        self.check_markers(TRUST, "fn activate_current_learning_trust(", (
            "let clock = session.clock()", "RootHistoricalTaskReadClientV1::exchange(",
            "HistoricalReadOperationV1::LearningTrust", "Reply::Task(_) => return Err(refused())",
            "response.data_cut != self.data.data_cut.to_string()",
            "OriginalHistoricalTaskReadReceiptV1::with_current_read(self, |_|",
            "clock.now_unix_ms()", "activate_for_recipient(&self.client.initial, now)?",
            "response.payload.require_activation_pin(", "receipt: Arc::clone(self)", "self.client.fence()"))

    def test_each_trust_operation_reactivates_before_and_after_the_callback(self):
        for marker in ("self.clock.now_unix_ms()", "self.require_same_activation(&activated, &evaluator)?"):
            for occurrence in (0, 1):
                self.reject_removal(TRUST, "fn with_current_trust<T>(", marker, occurrence)
        self.check_markers(TRUST, "fn with_current_trust<T>(", (
            "OriginalHistoricalTaskReadReceiptV1::with_current_read(&self.receipt, |data|",
            "activate_for_recipient(self.initial_snapshot(), now)?",
            "action(data, activated.verifier(), &evaluator, now)?",
            "activate_for_recipient(self.initial_snapshot(), after)?"))

    def test_current_authority_cannot_switch_receipt_or_signer(self):
        self.check_markers(TRUST, "fn require_original_receipt(", (
            "!Arc::ptr_eq(&self.receipt, receipt)", "self.receipt.client.fence()", "return Err(refused())"))
        self.check_markers(TRUST, "fn require_same_activation(", (
            "self.payload.require_activation_pin(", "&self.receipt.client.learning_trust",
            "activated.root_digest() != self.activated.root_digest()",
            "activated.distribution_digest() != self.activated.distribution_digest()",
            "activated.verifier().trust_digest() != self.activated.verifier().trust_digest()",
            "evaluator != &self.evaluator"))

    def test_one_lane_and_sequence_carry_both_strict_operations(self):
        for occurrence in (0, 1):
            self.reject_removal(CLIENT, "fn exchange(",
                                "self.connection\n                .require_original_session()", occurrence)
        self.check_markers(CLIENT, "fn exchange(", (
            "self.lane.try_lock()", "held.take().ok_or_else(refused)?", "let request_id = lane.sequence",
            "!(1..=MAX_READS).contains(&request_id)", "purpose: operation.purpose().into()",
            "lane.stream.exchange(&request)?", "require_complete_reply(&bytes, request_id, &self.profile)?",
            "require_original_trust_reply(", "&self.learning_trust", "&self.initial",
            "request_id.checked_add(1)", "*held = Some(lane)", "if result.is_err()"))

    def test_original_absolute_end_and_sealed_pin_reach_the_same_client(self):
        self.check_markers(AGENT + "root_historical_task_read_inputs.rs", "fn connect_original(", (
            "connection.original_end().min(launch_end)", "bundle.profile.require_original_context(",
            "OriginalPublicationStream::from_stream_until(",
            "RootHistoricalTaskReadClientV1::from_original_stream(", "bundle.profile.learning_trust"))
        self.reject_removal(CLIENT, "fn from_original_stream(", "learning_trust.require_initial(&initial)?")


if __name__ == "__main__":
    unittest.main()
