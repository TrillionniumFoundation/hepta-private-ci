"""Actual Root-to-A trust and Ledger source guards, not execution receipts."""

import tomllib
import unittest

import test_initial_artifact_readview_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT


class InitialLearningTrustSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.InitialArtifactReadviewClosureTests.reject_removal

    def test_only_actual_root_files_and_the_original_lane_create_authorities(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        expected = {
            "root_initial_learning_trust_files": ["authority_host_initial_deployment.rs"],
            "root_initial_learning_trust_bind": ["authority_host_generation_initial_enrollment.rs"],
            "root_initial_learning_trust_payload": ["authority_host_initial_learning_trust_transport.rs"],
            "root_initial_learning_trust_activation": ["authority_host_initial_learning_trust_files.rs", "root_generation_initial_learning_trust.rs"],
            "root_initial_learning_trust_exchange": ["authority_host_generation_initial_transport.rs"],
            "root_initial_learning_trust_client": ["neuron_generation_current_initial_learning_trust.rs"],
            "root_initial_learning_trust_current": ["neuron_generation_update_live.rs"],
            "root_initial_learning_trust_live": ["circuit_feature_learning_trust.rs"],
            "root_initial_learning_trust_task": ["production_initial_q24.rs"],
            "root_initial_learning_trust_consume": ["production_initial_q24_ledger_files.rs"],
            "ordinary_initial_q24_original_ledger_files": ["production_initial_q24.rs"],
            "learning_original_durable_ledger_writer": ["production_initial_q24_ledger_files.rs"],
            "q24_task_original_profile_install": ["production_initial_q24.rs"],
        }
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                self.assertEqual(rows[identifier]["product_callers"], [AGENT + name for name in callers])

    def test_root_holds_actual_immutable_files_without_daemon_bootstrap(self):
        file = "authority_host_initial_learning_trust_files.rs"
        for marker in ("original_root()?", "MetadataFile::open_metadata(path)?",
                       "expected.schema != 1", "expected.mode !=", "expected.learning_scope == [0; 32]",
                       "paths[..index].contains(original)", "MetadataFile::open_metadata(&expected.root_key)?",
                       "MetadataFile::open_metadata(&expected.distribution)?", "MetadataFile::open_metadata(&expected.source_deployment)?",
                       "generator: expected.generator.clone()", "observer: expected.observer.clone()", "> 12 * 1024"):
            self.reject_removal(file, "fn open_original_learning_trust(", marker)
        for field in ("descriptor", "root", "distribution", "source"):
            self.reject_removal(file, "fn require_original_files(", f"self.{field}.require_metadata_unchanged()")

    def test_root_scope_maps_to_the_actual_source_and_entire_target(self):
        file = "authority_host_initial_learning_trust_files.rs"
        for marker in ("&self.expected.deployment != deployment", "require_actual_source(identity, deployment, &source)?",
                       "self.payload.activate_pinned_genesis(now_millis / 1_000)?",
                       "activated.verifier().objective_digest() != source.source.objective_digest",
                       "mapping: self.descriptor.digest()", "source_metadata: self.source.digest()",
                       "roles: self.payload.role_digest()?", "pin.require_target(&deployment.target)?"):
            self.reject_removal(file, "fn observe_original(", marker)
        self.reject_removal(file, "fn observe_original(", "self.require_original_files()?", 1)
        for marker in ("original.fence.owner_agent_id != identity.agent_id",
                       "identity.spawn_generation.checked_add(1) != Some(original.fence.generation)",
                       "scope.run_id != source.scope.run_id.as_str()", "scope.principal_digest != source.scope.principal_digest.into_array()",
                       "target.source_frontier() != source.source_frontier.into_array()", "crate::circuit_feature_task_digest_v1(&original.definition, source)"):
            self.reject_removal(file, "fn require_actual_source(", marker)

    def test_genesis_activation_keeps_real_crypto_and_independent_fixed_roles(self):
        file = "root_initial_learning_trust_data.rs"
        for marker in ("self.distribution.generation != 1", "self.distribution.signature.len() != 64",
                       "self.distribution.signers.len() > 64", "select(&signers, &self.generator)?",
                       "select(&signers, &self.observer)?", "activate_learning_trust(&root, signed, /*previous*/ None, now_seconds)",
                       ".require_signer_binding(role, signer, now_seconds)",
                       "verify_independent_roles(&generator.principal, &observer.principal, now_seconds)",
                       "generator.controller_id == observer.controller_id"):
            self.reject_removal(file, "fn activate_pinned_genesis(", marker)
        for marker in ("signer.controller_id.as_str() == selected.controller_id", "if matching.next().is_some()"):
            self.reject_removal(file, "fn select(", marker)

    def test_enrollment_and_every_selection_keep_the_same_trust_pin(self):
        for marker in ("files.bind_original(&self.identity, deployment, now)",
                       "learning_trust: learning_trust.as_ref().map(|original| original.pin.clone())", "learning_trust,"):
            self.reject_removal("authority_host_generation_initial_enrollment.rs", "fn enroll_generation_initial(", marker)
        for occurrence in (0, 1):
            self.reject_removal("authority_host_generation_initial.rs", "fn require_selection(",
                                "self.require_learning_trust(now)", occurrence)
        self.reject_removal("authority_host_generation_initial.rs", "fn require_learning_trust(",
                            "(Some(original), Some(pin)) if &original.pin == pin => original.revalidate(now_millis)")

    def test_root_exchange_preserves_context_current_final_use_and_absolute_end(self):
        file = "authority_host_initial_learning_trust_transport.rs"
        for marker in ("self.service.with_initial_publication_context(", "request.purpose != LEARNING_TRUST_PURPOSE",
                       "!matches!(&request.command, Command::ReadLearningTrust {})", "slot.profile.writer != proof",
                       "slot.require_selection(now)?", "before.is_none()", "Some(&slot.profile.prepared)",
                       "payload: original.read_original_payload(now)?", "raw.len() > 16 * 1024",
                       "slot.require_selection(after)?", "self.service.issuer.revocations()? != revocations",
                       "read_current(slot, current.as_ref())? != before", "self.slot.fence()?"):
            self.reject_removal(file, "fn exchange(", marker)
        for occurrence in (0, 1, 2):
            self.reject_removal(file, "fn exchange(", "Instant::now() >= self.end", occurrence)
        for occurrence in (0, 1):
            self.reject_removal(file, "fn exchange(", "require_observation(slot, before.as_ref(), &revocations)?", occurrence)

    def test_client_validates_same_session_before_and_after_actual_activation(self):
        file = "root_generation_initial_learning_trust.rs"
        for occurrence in (0, 1, 2):
            self.reject_removal(file, "fn read_original_learning_trust(",
                                "self.require_learning_trust_session(session, identity)?", occurrence)
        for marker in ("pin.require_target(&self.profile.deployment.target)?", "original_initial_record(",
                       "held.take().ok_or_else(uncertain)?", "&response.pin != pin", "response.payload.activate_pinned_genesis(",
                       "response.payload.require_activation_pin(&activated, pin)?", "self.observe_initial_current()? != before", "self.fence()"):
            self.reject_removal(file, "fn read_original_learning_trust(", marker)
        self.reject_removal(file, "fn require_learning_trust_session(", "self.connection.original_launch_binding().1 != identity")

    def test_published_task_read_keeps_both_actual_current_and_artifact_checks(self):
        for occurrence in (0, 1):
            self.reject_removal("neuron_generation_update_live.rs", "fn read_initial_learning_trust(",
                                "self.check_current(self.publication.target())", occurrence)
            self.reject_removal("circuit_feature_learning_trust.rs", "fn read_original_initial_learning_trust(",
                                "self.require_current()?", occurrence)
        self.reject_removal("neuron_generation_update_live.rs", "fn read_initial_learning_trust(",
                            "!matches!(&self.publication, RetainedPublication::Initial(_))")
        self.reject_removal("neuron_generation_current_initial_learning_trust.rs", "fn read_root_initial_learning_trust(",
                            ".original_initial_client()?")

    def test_first_a_requires_original_empty_files_before_initializing_any_store(self):
        file = "production_initial_q24_ledger_files.rs"
        for marker in ("original: OriginalRootInitialLearningTrustV1", "files: &mut OriginalFiles",
                       "original.into_ledger_authorities()", "generator.controller_id == observer.controller_id",
                       "data.configuration(generator, observer, observed_at)?", "original_key(&key_file, &config.generator.verifying_key)?",
                       "require_unwritten(file)?", "OriginalParent::open_original(path, file)?", "DurableLedger::create(",
                       "LedgerWitnessStore::create(", "signature_witness.current().map_err(invalid)?.is_some()",
                       "LedgerWriter::from_durable(", "&held[0].directory", "&held[1].directory", "parent.directory.sync_all()?"):
            self.reject_removal(file, "fn open(", marker)
        self.reject_removal(file, "fn open(", "parent.require_original()?", 1)

    def test_ledger_key_and_parent_are_actual_descriptors(self):
        file = "production_initial_q24_ledger_files.rs"
        for marker in ("flags & libc::O_ACCMODE != libc::O_RDONLY", "flags & libc::O_PATH != 0",
                       "before.len() != 32", "before.nlink() != 1", "bytes != comparison",
                       "stamp(file.metadata()?) != before", "key.verifying_key().to_bytes() != *verifying_key"):
            self.reject_removal(file, "fn original_key(", marker)
        for marker in ("directory.uid() != uid", "file.uid() != uid", "file.nlink() != 1",
                       "libc::AT_SYMLINK_NOFOLLOW", "entry.st_dev != file.dev()", "entry.st_ino != file.ino()"):
            self.reject_removal(file, "fn require_original(", marker)

    def test_main_revalidates_root_after_ledger_io_and_drops_extra_owners(self):
        file = "production_initial_q24.rs"
        function = "fn assemble_original_initial_q24("
        for occurrence in (0, 1):
            self.reject_removal(file, function, "published.read_original_initial_learning_trust(&root.session, &identity)?", occurrence)
        for marker in ("ledger_files::open(deployment, trust, &mut files)?", "self.root = root", "drop(files)",
                       "config.with_q24_learning_task_profile(profile, inputs)?", "drop(ledger)", "drop((source, cell))"):
            self.reject_removal(file, function, marker)
        self.reject_removal("production_initial_q24_load.rs", "fn open(", "files,\n        data,")


if __name__ == "__main__":
    unittest.main()
