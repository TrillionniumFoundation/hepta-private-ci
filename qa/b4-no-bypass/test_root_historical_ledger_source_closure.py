"""Root four-file custody/cold refusal source checks, not native admission proof."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT


class RootHistoricalLedgerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_actual_capture_callers_are_fixed_and_history_is_not_yet_admitted(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        expected = {
            "root_original_ledger_metadata": ["authority_host_historical_source_deployment.rs", "authority_host_historical_ledger_history.rs"],
            "root_original_ledger_custody": ["authority_host_historical_ledger_session.rs", "authority_host_historical_ledger_history.rs"],
            "root_original_ledger_install": ["authority_host_historical_source_deployment.rs"],
            "root_original_ledger_runtime_registration": ["authority_host_generation_initial_runtime.rs"],
            "root_original_ledger_baseline": ["authority_host_historical_ledger_session.rs"],
            "root_original_ledger_runtime_take": ["authority_host_historical_source_session.rs"],
            "root_original_source_data_context": ["authority_host_historical_source_pin.rs"],
            "root_original_ledger_capture_context": ["authority_host_historical_source_data.rs"],
            "root_original_ledger_capture": ["authority_host_historical_source_pin.rs"],
            "root_original_ledger_physical_open": ["authority_host_historical_ledger_pin.rs", "authority_host_historical_ledger_history.rs"],
            "root_original_ledger_historical_context": [],
            "root_original_ledger_historical_observation": [],
            "root_original_ledger_historical_cut": [],
        }
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                self.assertEqual(rows[identifier]["product_callers"], [AGENT + name for name in callers])

    def test_root_metadata_retains_only_existing_distinct_public_inputs(self):
        self.check_markers(AGENT + "authority_host_initial_ledger_files.rs", "fn open_original(", (
            "original_root()?", "MetadataFile::open_metadata(path)?", "data.schema != 1",
            "paths[..index].contains(path)", "*path == &data.ledger.generator_key",
            "RootInitialLearningTrustFilesV1::open_original_learning_trust(", "held.require_original_files()?"))
        for index in range(4):
            self.reject_removal(AGENT + "authority_host_initial_ledger_files.rs", "fn open_original(",
                                f"OriginalFile::open_original(paths[{index}])?")

    def test_custody_checks_four_inodes_private_original_owner_and_metadata(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn retain_original_ledger(", (
            "original_root()?", "uid == 0 || gid == 0", "FilePin::readonly(descriptor, uid, gid)?",
            "(previous.device, previous.inode) == (pin.device, pin.inode)", "held.require_original_files()?"))
        self.check_markers(AGENT + "authority_host_initial_ledger_files.rs", "fn require_original_files(", (
            "self.metadata.require_metadata_unchanged()?", "self.trust.require_original_files()?",
            "file.require_original_file()?", "self.metadata.require_metadata_unchanged()"))

    def test_empty_baseline_is_physically_locked_twice_before_any_initialization(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn require_empty_baseline(", (
            "self.open_original_descriptors()?", "file.try_lock_shared()", "for _ in 0..2",
            "file.metadata()?.len() != 0"))
        for occurrence in (0, 1):
            self.reject_removal(AGENT + "authority_host_historical_ledger_registration.rs",
                                "fn register_original_initial_ledger(", "files.require_empty_baseline()?", occurrence)

    def test_four_locks_and_independent_signature_reader_survive_the_context(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn open_original_terminal(", (
            "ReadOnlyLedgerViewV1::observe_closed(", "ReadOnlyLedgerViewV1::open_at_retained_cut(",
            "signatures.try_lock_shared()", "signature_witness\n            .try_lock_shared()",
            "FilePin::readonly(&self.files[2], self.uid, self.gid)?",
            "signature_files: [signatures, signature_witness]"))

    def test_signature_cut_requires_actual_witness_and_two_completed_envelopes(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn open_original_terminal(", (
            "observe_original_file_anchor_v1(",
            "anchor.sequence != 5 || expected_signatures.is_some_and(|expected| expected != anchor)",
            "context.signature_binding()", "sequence: anchor.sequence - 1", "history_digest: anchor.checkpoint_digest"))
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn observe_original_terminal(", (
            "context.execution_keys()", "ProductEvaluationExecutionStateV1::Completed(bytes)",
            "self.signatures.readback(key)", ".verify_original_terminal(", "&envelopes[0]", "&envelopes[1]"))

    def test_all_physical_images_and_frontiers_are_rechecked(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn signature_images(", (
            "anchor != Some(self.anchor)", "image(&self.signature_files[0], 32 * 1024 * 1024)? != before[0]",
            "image(&self.signature_files[1], 1024 * 1024)? != before[1]"))
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn require_unchanged(", (
            "self.ledger.observe().map_err(io::Error::other)?.cut != expected.cut",
            "self.anchor != expected.signature_anchor", "self.signature_images()? != expected.signature_images"))

    def test_baseline_arm_contains_the_entire_original_root_context(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_registration.rs", "fn register_original_initial_ledger(", (
            "RootDataRefusalV1::create_fresh(", "RootDataKind::HistoricalLedger",
            "self.with_initial_publication_context(", "slot.mode != RootGenerationInitialModeV1::Reserve",
            "files.deployment.initial != slot.profile.deployment", "slot.profile.writer != proof",
            "Some(&trust.pin) != slot.profile.learning_trust.as_ref()", "registered_identity: serde_json::to_string(",
            "registered_at: now / 1_000", "HostAuthorityFrontierStore::initialize("))
        for occurrence in (0, 1):
            self.reject_removal(AGENT + "authority_host_historical_ledger_registration.rs",
                                "fn register_original_initial_ledger(", "Instant::now() >= end", occurrence)

    def test_capture_ready_requires_post_context_physical_record_and_deadline(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_pin.rs", "fn with_original_ledger_capture<T>(", (
            "original.refusal.inspect(||", "original.baseline.phase != LedgerPhase::Enrolled",
            "let result = action(Some(&mut pending))?", "let (captured, observation, mut held)",
            "held.require_unchanged(&observation)?", "!= captured"))
        self.reject_removal(AGENT + "authority_host_historical_ledger_pin.rs", "fn with_original_ledger_capture<T>(",
                            "Instant::now() >= original.end", 1)

    def test_capture_requires_same_original_source_publisher_and_real_signed_facts(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_pin.rs", "fn observe_and_retain_original_ledger(", (
            "retained.expected.pin.initial_profile != baseline.initial_profile",
            "retained.expected.pin.publisher != baseline.publisher",
            "retained.expected.pin.publisher_epoch != baseline.publisher_epoch",
            "retained.expected.pin.target != baseline.target", "source.original_identity() != identity",
            "(ledger.device, ledger.inode) == (source.device, source.inode)",
            "generator != original.config.generator || observer != original.config.observer",
            "held.observe_original_terminal(", ".compare_and_set(&original.owner, baseline, &next)",
            "held.require_unchanged(&observed)?"))

    def test_complete_cut_binds_real_cell_and_every_original_file(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_pin.rs", "fn from_original(", (
            "source_pin: source_pin.to_string()", "publication.publication_digest()",
            "crate::circuit_cell_output::encode_receipt(cell)", "&cell.representation.drive_q24",
            "&cell.representation.prediction_q24", "observed.cut.ledger_digest", "observed.cut.witness_digest",
            "observed.signature_images[0].1", "observed.signature_images[1].1",
            "observed.facts.decision.chain_digest", "observed.facts.outcome.chain_digest"))

    def test_cold_arm_precedes_primary_and_all_four_file_opening(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn with_retained_original_ledger<T>(", (
            "RootDataRefusalV1::open_existing(", "refusal.inspect(||",
            "HostAuthorityFrontierStore::open(root, owner.clone())", "record.registered_at == 0",
            "!matches!(record.phase, LedgerPhase::Captured { .. })", "registration.identity()?",
            "RootHistoricalLedgerDeploymentV1::open_original(deployment_path)?",
            "OriginalLedgerFiles::retain_original_ledger(", "files.file_pins() != &record.files",
            "files.deployment.metadata_digest().to_string() != record.metadata",
            "let result = action(&mut pending)?", "held.require_unchanged(&observed)?", "trust.revalidate("))
        self.reject_removal(AGENT + "authority_host_historical_ledger_history.rs", "fn with_retained_original_ledger<T>(",
                            "Instant::now() >= end", 1)

    def test_caught_error_or_second_read_never_completes_the_cold_attempt(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn observe_original_terminal(", (
            "std::mem::replace(&mut self.state, HistoryState::Verifying)", "HistoryState::Unobserved",
            "Instant::now() >= self.end", "self.state = HistoryState::Complete"))
        self.reject_removal(AGENT + "authority_host_historical_ledger_history.rs", "fn with_retained_original_ledger<T>(",
                            "let HistoryState::Complete")

    def test_cold_identity_target_source_and_original_roles_are_exact(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn observe_original_terminal(", (
            "original.pin.writer != record.writer", "original.pin.target != record.target",
            "original.pin.publisher != record.publisher", "original.pin.publisher_epoch != record.publisher_epoch",
            "source.original_identity() != &self.identity", "original.pin.source_configuration != source.binding_digest().to_string()",
            "original.pin.source_sequence != source.journal_anchor().sequence",
            "require_target(&record.target, definition, source.original_source())?", "trust.pin != record.trust",
            ".configuration(generator, observer, record.registered_at)", "OriginalLedgerReadModeV1::Retained",
            "CapturedLedgerCut::from_original(", "!= **cut", "held.require_unchanged(&observed)?"))

    def test_runtime_custody_requires_pre_a_cell_and_consumes_once(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_session.rs", "fn install_initial_source_ledger(", (
            "initial.phase.load(Ordering::Acquire) != PREPARED", "source.phase.load(Ordering::Acquire) != PREPARED",
            "inputs.initial != initial.deployment", "cell_retention::OriginalCellCustody::Held(_)",
            "self.service.with_initial_publication_context(", "!matches!(&*held, OriginalLedgerCustody::Absent)"))
        self.check_markers(AGENT + "authority_host_historical_ledger_session.rs", "fn take_original_source_ledger(", (
            "std::mem::replace(&mut *held, OriginalLedgerCustody::Absent)",
            "OriginalLedgerCustody::Registered(original) => Ok(Some(original))", "OriginalLedgerCustody::Held(_)", "self.close()"))

    def test_actual_registration_precedes_ack_and_nested_context_keeps_cell(self):
        self.reject_removal(AGENT + "authority_host_generation_initial_runtime.rs", "fn serve_optional(",
                            ".and_then(|()| source.register_original_source_ledger(context))")
        self.check_markers(AGENT + "authority_host_historical_source_data.rs", "fn with_original_capture<T>(", (
            "original.ledger.is_some() && original.cell.is_none()",
            "RegisteredOriginalCellCaptureV1::with_original_cell_capture(",
            "RegisteredOriginalLedgerCaptureV1::with_original_ledger_capture(", "|ledger| action(cell, ledger)"))


if __name__ == "__main__":
    unittest.main()
