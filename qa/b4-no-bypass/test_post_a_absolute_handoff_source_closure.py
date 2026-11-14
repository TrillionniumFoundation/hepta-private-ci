"""Late learning/model consumption cannot renew the already selected end."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT


class PostAAbsoluteHandoffSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_original_absolute_stream_keeps_actual_peer_and_all_lifetime_checks(self):
        self.check_markers(AGENT + "root_observation_stream.rs", "fn from_stream_for_uid_until(", (
            "peer.pid == 0", "peer.process_start_ticks == 0", "timeout.is_zero()",
            "timeout > Duration::from_millis(500)", "remaining.is_zero()",
            "remaining > Duration::from_secs(300)", "root_pidfd.as_raw_fd()",
            "start != Some(peer.process_start_ticks)", "check_lifetime(&root_pidfd)?",
            "actual.uid() != uid", "actual.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(peer.pid)",
            "check_lifetime(root.get_ref())?", "Instant::now() >= end", "end,"))

    def test_checkpoint_until_constructor_preserves_full_empty_initial_and_scope(self):
        self.check_markers(AGENT + "learning_iteration_checkpoint_transport.rs", "fn from_original_stream_until(", (
            "LearningIterationCoordinatorV1::new(", "expected.snapshot() != &initial",
            "if let Some(scope) = &scope", "scope.validate_snapshot(&initial)",
            "RootObservationStream::from_stream_until(", "end)", "next_request_id: 1"))

    def test_learning_consumer_moves_every_original_check_before_fixed_end_client(self):
        self.check_markers(AGENT + "root_production_learning_inputs.rs", "fn connect_until(", (
            "timeout.is_zero()", "remaining(end)? > Duration::from_secs(300)",
            "validate_binding(&bundle, &production.bootstrap, expected, self.root_pid)?",
            "let scope = bundle.frozen_scope(&initial)?", "validate_lane_paths(",
            "AgentdLearningCheckpointClientV1::from_original_stream_until(", "end,", "scope.clone()",
            "client\n            .restore(&initial.request)\n            .await", "remaining(end)?"))

    def test_model_consumer_keeps_actual_files_context_peer_and_exact_end(self):
        self.check_markers(AGENT + "root_production_q24_model_inputs.rs", "fn connect_until(", (
            "remaining(end)? > Duration::from_secs(300)", "bundle.root != original.root",
            "learning.q24_model_scope(identity)?", "LiveFactoryProfile::require_context(",
            "bundle.profile.require_files(", "validate_lane_paths(", "UnixStream::connect(",
            "RootObservationStream::from_stream_until(", "AgentdRootQ24ModelFactoryV1::from_original_handoff("))


if __name__ == "__main__":
    unittest.main()
