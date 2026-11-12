"""The ordinary post-A entry consumes only actual original Root resources."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
MAIN = AGENT + "production_post_a_q24.rs"
HANDOFF = AGENT + "production_post_a_q24_handoff.rs"


class PostAMainSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_main_calls_the_real_profile_assembly_before_runtime(self):
        self.check_markers(AGENT + "main.rs", "fn main(", (
            "startup.receive().await?", "launch.assemble_original_initial_q24(config).await?",
            "codex_hepta_agentd::AgentdProductionLaunch::assemble_original_post_a_q24(", "launch.run(config, arg0_paths).await?"))
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["ordinary_post_a_q24_assembly"]["product_callers"], [AGENT + "main.rs"])
        for key in ("production_original_q24_assemble", "q24_successor_launch_prepare",
                    "q24_historical_delivery_capture", "q24_historical_delivery_install"):
            self.assertIn(MAIN, rows[key]["product_callers"])

    def test_profile_requires_original_handoffs_and_authbus_before_fd_ownership(self):
        self.check_markers(AGENT + "production_post_a_q24_cli.rs", "fn validate(", (
            "profile != Profile::PostAQ24", "deployment.is_some()", "deployment.is_none()",
            "historical_learning_model_publication\n            .iter()\n            .any(Option::is_none)",
            "incompatible.iter().any(Option::is_some)",
            "found.next().is_none_or(|pair| pair[1].is_empty()) || found.next().is_some()"))
        self.check_markers(AGENT + "production_launcher_inputs.rs", "fn parse(", (
            "initial_q24::validate(", "post_a_q24::validate(",
            "&[\n            historical_handoff,\n            learning_handoff,\n            q24_model_handoff,\n            publication_handoff,\n        ]",
            "numbers.iter().copied().collect::<BTreeSet<_>>().len() != numbers.len()",
            "let handoff = UnixDatagram::from(take_descriptor(handoff)?)"))

    def test_three_original_datagrams_are_deferred_in_both_actual_startups(self):
        self.check_markers(HANDOFF, "fn defer_for_original_profile(", (
            "!matches!(primary, PrimaryInputs::PostAQ24 { .. })", "return Ok(None)",
            "let learning = learning\n            .take()", "let model = model\n            .take()"))
        for path, function in ((AGENT + "production_launcher.rs", "fn from_process_environment("),
                               (AGENT + "production_launcher_late_writer.rs", "fn receive_original_late_writer(")):
            self.check_markers(path, function, (
                "post_a_q24::PendingHandoffs::defer_for_original_profile(",
                "&mut learning_handoff", "&mut q24_model_handoff", "&mut publication_handoff", "let learning = learning_handoff"))

    def test_original_root_task_current_trust_and_freezer_precede_late_install(self):
        self.check_markers(MAIN, "fn assemble_original_post_a_q24(", (
            "PrimaryInputs::PostAQ24 { deployment }", "config.require_original_initial_q24_configuration()?",
            "self.q24_model.is_some()", "self.initial_publication.is_some()", "self.publication.is_some()",
            "self.original_source_capture.is_some()", "self.original_run_start_retention.is_some()",
            "OriginalFiles::new()?", "self.take_original_historical_read()?",
            "RootHistoricalTaskReadClientV1::observe_original_task(",
            "OriginalHistoricalTaskReadReceiptV1::activate_current_learning_trust(",
            "CellQ24DatasetTaskV1::capture_historical(",
            "CellQ24DatasetFreezePreparationV1::capture_historical(",
            "owners::SigningFilesData::freeze_original(",
            "OriginalHistoricalTaskReadReceiptV1::install_original_post_a_learning(",
            "OriginalPostAFrozenLearningAckV1::require_prepared_scope(&ack, prepared.scope())?"))
        for occurrence in range(3):
            self.reject_removal(MAIN, "fn assemble_original_post_a_q24(",
                                "self.require_original_post_a_context(&identity)?", occurrence)

    def test_late_handoffs_keep_exact_scope_and_absolute_end_on_both_sides(self):
        for occurrence in (0, 1, 2):
            self.reject_removal(HANDOFF, "fn receive_original_after_ack(",
                                "OriginalPostAFrozenLearningAckV1::require_prepared_scope(ack, prepared.scope())?", occurrence)
        self.check_markers(HANDOFF, "fn receive_original_after_ack(", (
            "crate::receive_root_learning_handoff(", "crate::RootLearningHandoffV1::connect_until(",
            "learning.require_prepared_q24(prepared)?", "crate::receive_root_q24_model_factory_handoff(",
            "crate::RootQ24ModelFactoryHandoffV1::connect_until("))
        for occurrence in range(5):
            self.reject_removal(HANDOFF, "fn receive_original_after_ack(",
                                "post_a_remaining(end)?.min(Duration::from_millis(500))", occurrence)

    def test_real_learning_and_waiting_c_are_bound_to_the_same_registered_history(self):
        self.check_markers(MAIN, "fn assemble_original_post_a_q24(", (
            "config.with_root_learning_inputs(learning)?", "self.q24_model = Some(model)",
            "OriginalHistoricalLearningTrustV1::original_stage_authorities(&trust)?",
            "owners::JournalData::open(", "owners::StageFilesData::into_original_inputs(",
            "RegisteredHistoricalLearningSourceV1::capture_original_historical_source(",
            "self.assemble_q24_learning(config, inputs).await?", "take_learning_iteration_bootstrap()",
            "delivery.open_witness()?", "crate::LearningIterationRuntimeBootstrapV1::with_original_historical_source(",
            "config.with_learning_iteration_bootstrap(bootstrap)?",
            "prepare_original_q24_successor(config, data.queue_capacity)",
            "OriginalPostAContinuationV1::from_original_inputs(",
            "crate::LearningIterationRuntimeBootstrapV1::with_original_post_a_continuation("))
        self.check_markers(AGENT + "production_launcher.rs", "fn run(", (
            "self.post_a_handoffs.is_some()",
            "initial_q24::writer::attach(config, self.root, self.session_end).await?",
            "let result = crate::run(config, arg0_paths).await",
            "drop((attachment, desktop_attachment, initial_attachment))"))

    def test_current_offer_is_retained_without_connecting_before_real_b(self):
        self.check_markers(HANDOFF, "fn receive_original_after_ack(", (
            "crate::receive_root_generation_publication_handoff(", "self.publication,",
            "Ok((learning, model, publication))"))
        self.check_markers(MAIN, "fn assemble_original_post_a_q24(", (
            "self.publication = Some(publication)",
            "crate::RootGenerationPublicationHandoffV1::retain_original_preparation(",
            "self.take_generation_publication_handoff()?",
            "self.take_generation_publication_connection()?,\n            &prepared,\n            self.session_end,"))
        self.check_markers(AGENT + "root_generation_publication_inputs.rs", "fn connect_until(", (
            "timeout.min(publication_remaining(end)?)",
            "OriginalPublicationStream::from_stream_until(", "timeout,\n            end,"))

    def test_current_recipient_identity_and_writer_lease_surround_each_context(self):
        for occurrence in (0, 1):
            self.reject_removal(MAIN, "fn require_original_post_a_context(",
                                "post_a_remaining(self.session_end)?", occurrence)
        self.check_markers(MAIN, "fn require_original_post_a_context(", (
            "self.root.bootstrap.registered_identity.identity()? != *identity",
            "verify_sender_process_binding(", "&self.root.session.authority()", "&identity.agent_id",
            "&self.root.bootstrap.writer.local_lease_id", "self.root.bootstrap.writer.local_lease_generation",
            "identity.spawn_generation"))


if __name__ == "__main__":
    unittest.main()
