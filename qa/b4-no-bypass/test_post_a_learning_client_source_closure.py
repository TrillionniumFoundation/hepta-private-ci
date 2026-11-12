"""Late installation keeps the actual original historical session and budget."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
CLIENT = AGENT + "root_post_a_learning_client.rs"
PROTOCOL = AGENT + "root_post_a_learning_protocol.rs"


class PostALearningClientSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_install_has_only_the_actual_post_a_product_callers(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["root_post_a_learning_install_original"]["product_callers"],
                         [AGENT + "production_post_a_q24.rs"])
        self.assertEqual(rows["root_post_a_learning_scope_ack"]["product_callers"],
                         [AGENT + "production_post_a_q24.rs", AGENT + "production_post_a_q24_handoff.rs"])
        self.assertIn(CLIENT, rows["root_historical_fixed_client_exchange"]["product_callers"])

    def test_exact_session_and_complete_cut_surround_only_the_fixed_install(self):
        for marker in ("OriginalHistoricalTaskReadReceiptV1::require_original_client(self, client, session)",
                       "self.client.observe()? != self.data"):
            for occurrence in (0, 1):
                self.reject_removal(CLIENT, "fn install_original_post_a_learning(", marker, occurrence)
        self.check_markers(CLIENT, "fn install_original_post_a_learning(", (
            "RootHistoricalTaskReadClientV1::exchange(", "HistoricalReadOperationV1::PostAFrozenLearning",
            "Reply::Task(_) | Reply::LearningTrust(_) => return Err(refused())",
            "response.data_cut != self.data.data_cut.to_string()", "receipt: Arc::clone(self)",
            "&response.frozen_scope", "if result.is_err()", "self.client.fence()"))

    def test_root_ack_must_match_actual_prepared_scope_with_live_connection(self):
        for occurrence in (0, 1):
            self.reject_removal(CLIENT, "fn require_prepared_scope(",
                                "self.receipt\n                .client\n                .connection\n                .require_original_session()", occurrence)
        self.check_markers(CLIENT, "fn require_prepared_scope(", (
            "validate_snapshot(self.receipt.initial_snapshot())",
            "self.receipt.client.fenced.load(Ordering::Acquire)",
            "scope.binding() != self.frozen_scope", "if result.is_err()", "self.receipt.client.fence()"))

    def test_wire_keeps_original_bounds_and_every_response_binding(self):
        self.check_markers(PROTOCOL, "fn require_post_a_learning_reply(", (
            "bytes.is_empty()", "bytes.len() > WIRE_BOUND", "!(1..=MAX_READS).contains(&request_id)",
            "response.schema != 1", "response.purpose != POST_A_PURPOSE",
            "response.request_id != request_id", "response.profile != profile", "canonical_digest(profile)?",
            "canonical_digest(&response.data_cut)?", "canonical_digest(&response.frozen_scope)?"))


if __name__ == "__main__":
    unittest.main()
