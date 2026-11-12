"""Guard the real ordinary first-A route; this is not execution qualification."""

import tomllib
import unittest

import test_initial_artifact_readview_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT


class OrdinaryInitialQ24SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.InitialArtifactReadviewClosureTests.reject_removal

    def test_main_calls_the_actual_assembly_before_running(self):
        self.reject_removal("main.rs", "fn main(",
                            "launch.assemble_original_initial_q24(config).await?")
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["ordinary_initial_q24_assembly"]["product_callers"],
                         [AGENT + "main.rs"])
        for identifier in ("root_initial_artifact_authorities",
                           "root_initial_original_connection_until",
                           "root_initial_executable_feature_prepare",
                           "root_initial_actual_feature_publish"):
            self.assertEqual(rows[identifier]["product_callers"],
                             [AGENT + "production_initial_q24.rs"])

    def test_actual_root_session_and_grant_surround_initial_effects(self):
        function = "fn assemble_original_initial_q24("
        for occurrence in range(6):
            self.reject_removal("production_initial_q24.rs", function,
                                "self.require_original_initial_q24_session(config.identity())?",
                                occurrence)
        for marker in (".connect_until(", "self.session_end,",
                       ".open_original_artifact_authorities(&self.root, artifacts)?",
                       "clock::require_source_deadline(&target.source)?",
                       "original.prepare_feature(authorities, selected, target)?",
                       ".request_grant(prepared.final_use_binding())",
                       "prepared.publish(&signed)", "uncertain_after_prepare"):
            self.reject_removal("production_initial_q24.rs", function, marker)

    def test_capture_selects_actual_current_and_releases_external_owners(self):
        for marker in ("self.retain_original_initial_source_capture(&published)?",
                       "config.with_q24_circuit_task_profile(", "published_task: published",
                       "drop((source, cell))"):
            self.reject_removal("production_initial_q24.rs",
                                "fn assemble_original_initial_q24(", marker)

    def test_sealed_data_cannot_replace_actual_model_or_root_target(self):
        for marker in ("validate_sealed(&file, size)?", "data.clock != super::clock::DOMAIN",
                       "crate::neuron_generation_process_identity_digest_v1(identity)?",
                       "initial.mode != RootGenerationInitialModeV1::Reserve",
                       "identity.spawn_generation.checked_add(1) != Some(source.fence.generation)",
                       "LoadedCellQ24ModelV1::open_files(", "components: model.components().clone()",
                       "crate::circuit_feature_initial_root::require_feature("):
            self.reject_removal("production_initial_q24_deployment.rs", "fn read(", marker)
        self.reject_removal("production_initial_q24_deployment.rs", "fn read(",
                            "validate_sealed(&file, size)?", 1)

    def test_file_custody_and_alias_rejection_precede_owner_initialization(self):
        for marker in ("physical.nlink() != 1", "named.nlink() != 1",
                       "(physical.dev(), physical.ino()) != (named.dev(), named.ino())",
                       "access != Access::Read || physical.uid() != 0",
                       "*previous != Access::Read || access != Access::Read"):
            self.reject_removal("production_initial_q24_files.rs", "fn open(", marker)
        for marker in ("require_unwritten(&target.journal)?",
                       "target.witness.metadata()?.len() == 0", "require_unwritten(journal)?",
                       "source_witness.current().map_err(invalid)?.is_some()",
                       "cell_witness.current().map_err(invalid)?.is_some()"):
            self.reject_removal("production_initial_q24_load.rs", "fn open(", marker)

    def test_writer_uses_the_original_checkpoint_without_a_fake_target(self):
        for marker in ("config.require_unconfigured_production_hosts()?",
                       "original.bootstrap.registered_identity.identity()? != *config.identity()",
                       ".verify_sender_process_binding(",
                       "AgentdProductionWriterHost::open_with_protected_recovery(",
                       "original.checkpoint", "_checkpoint: checkpoint",
                       "_device: original.device", "_notes: original.notes"):
            self.reject_removal("production_initial_q24_writer.rs", "fn attach(", marker)
        self.reject_removal("production_initial_q24_writer.rs", "fn attach(", "require_current()?", 1)

    def test_profile_rejects_competing_authority_inputs_and_unreadable_time(self):
        for marker in ("self.authbus_trust_file.is_none()", "self.authbus_checkpoint_file.is_none()",
                       "self.objective_profile_file.is_none()", "self.plasticity_bootstrap.is_some()",
                       "self.neuron_generation_bootstrap.is_some()", "self.root_learning_inputs.is_some()"):
            self.reject_removal("config_initial_q24.rs",
                                "fn require_original_initial_q24_configuration(", marker)
        self.reject_removal("production_initial_q24_clock.rs", "fn sample(", ".unwrap_or(u64::MAX)")
        self.reject_removal("production_initial_q24_clock.rs", "fn require_source_deadline(",
                            "observed >= source.deadline_micros")


if __name__ == "__main__":
    unittest.main()
