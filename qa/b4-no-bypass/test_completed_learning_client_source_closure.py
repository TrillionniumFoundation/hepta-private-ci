"""Completed history comes only from the original bounded Root exchanges."""

from dataclasses import replace
import tomllib
import unittest

import test_q24_completed_history_control_source_closure as control

ROOT = control.ROOT
PROOF = control.PROOF
AGENT = control.AGENT
CAP = AGENT + "root_completed_learning_history.rs"
PROTOCOL = AGENT + "root_completed_learning_protocol.rs"
CLIENT = AGENT + "root_historical_task_read_client.rs"


class CompletedLearningClientSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    rejects = control.OriginalCompletedHistoryControlSourceTests.rejects

    def test_all_actual_client_and_wire_protections_are_live(self):
        rows = [row for row in self.manifest["protected_file"]
                if row["path"] in (CAP, PROTOCOL, CLIENT,
                                   AGENT + "root_historical_learning_trust_client.rs",
                                   AGENT + "root_post_a_learning_client.rs")]
        self.assertTrue({CAP, PROTOCOL, CLIENT}.issubset({row["path"] for row in rows}))
        PROOF._verify_protected_files(ROOT, {"protected_file": rows})

    def test_actual_private_construction_and_no_unregistered_product_consumer(self):
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        expected = {
            "root_completed_accept_original": (),
            "root_completed_retain_acceptance": (
                AGENT + "learning_iteration_historical_source.rs",),
            "root_completed_accept_capsule": (
                AGENT + "learning_iteration_terminal_acceptance.rs",),
            "root_completed_acceptance_construct": (),
            "root_completed_read_original": (AGENT + "production_post_a_q24.rs",),
            "root_completed_history_current": (
                AGENT + "config_q24_completed_history.rs", AGENT + "state_q24_completed_history.rs"),
            "root_completed_history_construct": (),
            "root_completed_accept_reply": (CLIENT,),
            "root_completed_history_reply": (CLIENT,),
        }
        paths = {CAP, PROTOCOL, CLIENT,
                 AGENT + "learning_iteration_historical_source.rs",
                 AGENT + "learning_iteration_terminal_acceptance.rs",
                 AGENT + "production_post_a_q24.rs",
                 AGENT + "config_q24_completed_history.rs", AGENT + "state_q24_completed_history.rs"}
        index = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }
        for identifier, callers in expected.items():
            with self.subTest(identifier=identifier):
                row = rows[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, index, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), index, ())
                injected = dict(index)
                expression = ("OriginalCompletedLearningHistoryV1 { client, data_cut, data }"
                              if identifier == "root_completed_history_construct"
                              else "OriginalCompletedLearningAcceptanceV1 { client, identity }"
                              if identifier == "root_completed_acceptance_construct"
                              else row.symbol + "()")
                injected[AGENT + "unregistered_completed_client.rs"] = "fn bypass(){ " + expression + "; }"
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, injected, ())

    def test_first_acceptance_is_once_and_rechecks_even_error(self):
        function = "fn accept_original_completed_learning("
        for marker in (
            "let mut fence = FenceReadOnDrop", "armed: true",
            "RootHistoricalTaskReadClientV1::accept_completed_once(self, identity)",
            "let identity_after = self.require_completed_identity(identity);",
            "let session_after =", "identity_after?;", "session_after?;", "let response = result?;",
        ):
            with self.subTest(marker=marker):
                self.rejects(CAP, function, marker)
        for occurrence in (0, 1):
            self.rejects(CAP, function,
                         "RootHistoricalTaskReadClientV1::require_same_original_session(self, session)", occurrence)

    def test_retained_capsule_requires_the_actual_session_and_private_recipient(self):
        function = "fn retain_original_completed_acceptance("
        for marker in ("let mut fence = FenceReadOnDrop", "armed: true",
                       "self.completed_attempted.load(Ordering::Acquire)",
                       "client: Arc::clone(self)", "identity: identity.clone()"):
            self.rejects(CAP, function, marker)
        for marker in ("RootHistoricalTaskReadClientV1::require_same_original_session(self, session)",
                       "self.require_completed_identity(identity)?"):
            for occurrence in (0, 1):
                self.rejects(CAP, function, marker, occurrence)
        for marker in ("let mut fence = FenceReadOnDrop", "client: &self.client", "armed: true",
                       "RootHistoricalTaskReadClientV1::accept_completed_once(",
                       "&self.identity"):
            self.rejects(CAP, "fn accept(", marker)

    def test_both_acceptance_routes_share_one_physical_attempt_and_error_postcheck(self):
        for marker in ("self.require_completed_identity(identity)?;",
                       "self.completed_attempted.swap(true, Ordering::AcqRel)",
                       "RootHistoricalTaskReadClientV1::exchange(",
                       "HistoricalReadOperationV1::AcceptCompletedLearning",
                       "response.initial != self.initial.head_digest.to_string()",
                       "let after = self.require_completed_identity(identity);", "after?;", "Ok(result?)"):
            self.rejects(CAP, "fn accept_completed_once(", marker)

    def test_capture_cannot_retry_or_replace_the_required_finalized_read(self):
        function = "fn read_original_completed_history("
        for marker in (
            "self.completed_attempted.swap(true, Ordering::AcqRel)",
            "HistoricalReadOperationV1::CaptureCompletedHistory",
            "CompletedHistoryModeV1::ReadFinalized => None",
            "HistoricalReadOperationV1::ReadCompletedHistory",
            "captured.data_cut != response.data_cut", "captured.completion != response.completion",
            "let identity_after = self.require_completed_identity(identity);",
            "let session_after =", "identity_after?;", "session_after?;", "let response = result?;",
            "client: Arc::clone(self)", "data_cut: response.data_cut", "data: response.completion",
        ):
            with self.subTest(marker=marker):
                self.rejects(CAP, function, marker)

    def test_current_query_must_reobserve_the_whole_same_root_cut(self):
        for marker in (
            "let mut fence = FenceReadOnDrop", "armed: true",
            "HistoricalReadOperationV1::ReadCompletedHistory",
            "observed.data_cut != self.data_cut || observed.completion != self.data",
            "self.client.require_completed_identity(identity)?;",
        ):
            with self.subTest(marker=marker):
                self.rejects(CAP, "fn require_original_current(", marker)

    def test_identity_uses_actual_original_connection_before_and_after(self):
        function = "fn require_completed_identity("
        for marker in (
            "RootHistoricalTaskReadConnectionV1::original_binding(&self.connection)",
            "self.fenced.load(Ordering::Acquire) || original != identity",
        ):
            self.rejects(CAP, function, marker)
        for occurrence in (0, 1):
            self.rejects(CAP, function,
                         "RootHistoricalTaskReadConnectionV1::require_original_session(&self.connection)", occurrence)

    def test_raw_reply_never_skips_current_identity_and_original_initial(self):
        for marker in (
            "self.require_completed_identity(identity)?;",
            "RootHistoricalTaskReadClientV1::exchange(self, operation)?",
            "response.completion.initial != self.initial.head_digest.to_string()",
            "crate::neuron_generation_process_identity_digest_v1(identity)?",
            "let after = self.require_completed_identity(identity);", "after?;", "let response = result?;",
        ):
            with self.subTest(marker=marker):
                self.rejects(CAP, "fn read_completed_response(", marker)

    def test_original_exchange_is_still_the_only_bounded_lane(self):
        for marker in (
            "self.lane.try_lock()", "held.take().ok_or_else(refused)?",
            "!(1..=MAX_READS).contains(&request_id)", "lane.stream.exchange(&request)?",
            "require_completed_acceptance_reply(", "require_completed_history_reply(",
            "request_id.checked_add(1)", "*held = Some(lane)", "held.take()",
        ):
            with self.subTest(marker=marker):
                self.rejects(CLIENT, "fn exchange(", marker)

    def test_every_acceptance_binding_and_digest_is_mandatory(self):
        for marker in (
            "bytes.is_empty()", "bytes.len() > WIRE_BOUND", "!(1..=MAX_READS).contains(&request_id)",
            "response.schema != 1", "response.purpose != ACCEPT_COMPLETED_PURPOSE",
            "response.request_id != request_id", "response.profile != profile",
            "&response.data_cut,", "&response.initial,", "&response.frozen_scope,",
            "&response.terminal_head,", "&response.acceptance,", "canonical_digest(digest)?;",
        ):
            with self.subTest(marker=marker):
                self.rejects(PROTOCOL, "fn require_completed_acceptance_reply(", marker)

    def test_history_phase_bounds_profile_and_whole_completion_are_mandatory(self):
        for marker in (
            "HistoricalReadOperationV1::CaptureCompletedHistory => CAPTURE_COMPLETED_PURPOSE",
            "HistoricalReadOperationV1::ReadCompletedHistory => READ_COMPLETED_PURPOSE",
            "bytes.is_empty()", "bytes.len() > WIRE_BOUND", "!(1..=MAX_READS).contains(&request_id)",
            "response.schema != 1", "response.purpose != purpose", "response.request_id != request_id",
            "response.profile != profile", "response.completion.root_profile != profile",
            "canonical_digest(profile)?;", "canonical_digest(&response.data_cut)?;",
            "response\n        .completion\n        .validate_data()",
        ):
            with self.subTest(marker=marker):
                self.rejects(PROTOCOL, "fn require_completed_history_reply(", marker)


if __name__ == "__main__":
    unittest.main()
