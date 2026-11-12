"""Original Root preparation and physical material fail closed before effects.

These mutations validate the actual guarded production bodies. They are source
closure evidence only, not a completed Artifact, C, or cold recovery proof.
"""

from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT, AGENT, PROOF = component.ROOT, component.AGENT, component.PROOF
ROUTE = AGENT + "root_publication_preparation.rs"
MATERIAL = AGENT + "production_post_a_material.rs"
LATE = AGENT + "production_post_a_late_input.rs"
CODEC = AGENT + "authority_host_publication_bootstrap.rs"


class PostAPhysicalPreparationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_explicit_versions_reject_downgrade_and_missing_preparation(self):
        self.check_markers(CODEC, "fn encode_original_publication_bootstrap(", (
            "PublicationVersion::from_purpose(&route.purpose)?",
            "(PublicationVersion::LegacyV1, None) => serde_json::to_vec(route)",
            "(PublicationVersion::DurableV2, Some(prepared))", "schema: 2,", "return Err("))
        self.check_markers(CODEC, "fn decode_original_publication_bootstrap(", (
            "== PublicationVersion::LegacyV1", "Ok((route, None))", "value.schema == 2",
            "== PublicationVersion::DurableV2", "Ok((value.route, Some(value.prepared)))", "_ => Err("))

    def test_route_is_from_the_actual_sealed_offer_and_same_learning_cut(self):
        self.check_markers(ROUTE, "fn retain_original_preparation(", (
            "RootGenerationPublicationHandoffV1::read_original_route(&mut self, &connection, end)?",
            "PublicationVersion::from_purpose(&bundle.purpose)? != PublicationVersion::DurableV2",
            "bundle.initial != prepared.initial().head_digest.to_string()",
            "bundle.scope != prepared.scope().binding().to_string()",
            "bundle.learning_operation != prepared.initial().request.operation_id.as_str()",
            "data: data.ok_or_else(", "OriginalPreparedPublicationRoute::require_current(&route)?"))

    def test_same_root_pidfd_and_session_failure_permanently_fence_the_route(self):
        self.check_markers(ROUTE, "fn require_current(", (
            "self.fenced.load(Ordering::Acquire)",
            "RootGenerationPublicationHandoffV1::require_original_root(&self.handoff)?",
            "self.connection.require_original_publication_session()?",
            "if result.is_err()", "self.fenced.store(true, Ordering::Release)"))
        for occurrence in (0, 1):
            self.reject_removal(ROUTE, "fn require_current(", "publication_remaining(self.end)?", occurrence)
        self.check_markers(ROUTE, "fn into_original_connection(", (
            "Self::require_current(&self)?", "Ok((self.handoff, self.connection, self.end))"))

    def test_callbacks_recheck_even_failed_results_and_fence_unwinds(self):
        for path, name, check, callback, fence in (
            (ROUTE, "fn with_original_data<T>(", "Self::require_current(self)?",
             "let result = action(&self.data)", "self.route.fenced.store(true, Ordering::Release)"),
            (LATE, "fn with_original_bytes<T>(", "Self::require_unchanged(self)?",
             "let result = read(&self.bytes)", "self.value.fenced.store(true, Ordering::Release)"),
        ):
            for occurrence in (0, 1):
                self.reject_removal(path, name, check, occurrence)
            self.check_markers(path, name, ("armed: true,", callback, "if result.is_ok()", "fence.armed = false"))
            self.check_markers(path, "fn drop(", ("if self.armed", fence))

    def test_root_fixed_full_pin_and_explicit_material_mode_choose_the_writer(self):
        self.check_markers(MATERIAL, "fn open_from_original_root(", (
            "OriginalPreparedPublicationRoute::with_original_data(route, |fixed|", "let expected = &fixed.material",
            "path: expected.path.clone()", "Mode::Reserve => MaterialMode::Create", "Mode::Recover => MaterialMode::Recover",
            "device: expected.device", "inode: expected.inode", "uid: expected.uid", "gid: expected.gid", "mode: expected.mode"))
        self.check_markers(MATERIAL, "fn open_original(", (
            "files.write(&self.path)?", "file.try_lock()",
            "actual_owner.0 == 0 || (pin.uid, pin.gid) != actual_owner || pin != self.expected",
            "MaterialMode::Create => length != 0", "MaterialMode::Recover => !(1..=65_536).contains(&length)"))

    def test_material_recovery_never_rewrites_and_actual_writer_closes_before_readback(self):
        self.check_markers(MATERIAL, "fn commit_original_material(", (
            "RootGenerationPublicationDeploymentV1::encode_original_material(", "target, selection,",
            "self.file.metadata()?.len() != 0", "self.file.write_all_at(&bytes,", "self.file.sync_all()?",
            "MaterialMode::Recover => {}", "require_exact_bytes(&self.file, &bytes)?", "drop(self.file)",
            "OriginalMaterialReadback::require_unchanged(&observed)?"))
        for occurrence in range(3):
            self.reject_removal(MATERIAL, "fn commit_original_material(", "self.require_original()?", occurrence)

    def test_material_file_and_path_custody_are_both_checked(self):
        self.check_markers(MATERIAL, "fn read(", (
            "!metadata.is_file() || metadata.nlink() != 1 || metadata.mode() != 0o100600",
            "device: metadata.dev()", "inode: metadata.ino()", "uid: metadata.uid()", "gid: metadata.gid()", "mode: metadata.mode()"))
        self.check_markers(MATERIAL, "fn require_file(", (
            "Self::read(&file.metadata()?)? != *self", "Self::read(&std::fs::symlink_metadata(path)?)? != *self"))
        for occurrence in (0, 1):
            self.reject_removal(MATERIAL, "fn require_file(", "parent.canonicalize()? != parent", occurrence)

    def test_material_readback_rechecks_physical_bytes_and_retains_failure(self):
        self.check_markers(MATERIAL, "fn require_exact_bytes(", (
            "expected.is_empty() || expected.len() > 65_536", "original.0 != expected.len() as u64", "for _ in 0..2",
            "stamp(&file.metadata()?) != original", "file.read_exact_at(&mut bytes,",
            "bytes != expected || stamp(&file.metadata()?) != original"))
        self.check_markers(MATERIAL, "fn require_unchanged(", (
            "self.fenced.load(Ordering::Acquire)", "require_exact_bytes(&self.file, &self.bytes)?",
            "if result.is_err()", "self.fenced.store(true, Ordering::Release)"))

    def test_late_data_waits_only_for_the_original_empty_file_or_producer_lock(self):
        self.check_markers(LATE, "fn wait_original_value(", (
            "cancelled.is_cancelled()", "identity(&locked.metadata()?)? != self.identity", "locked.try_lock_shared()",
            "Err(TryLockError::WouldBlock) => false", "Err(error) => return Err(", "physical.len() > 1_048_576",
            "physical.len() != 0", "locked.read_exact_at(&mut bytes,", "value.require_unchanged()?",
            "drop(locked)", "post_a_remaining(self.end)?.min(std::time::Duration::from_millis(5))"))
        for occurrence in (0, 1):
            self.reject_removal(LATE, "fn wait_original_value(", "self.require_original()?", occurrence)

    def test_late_value_rechecks_full_physical_cut_and_keeps_first_failure(self):
        self.check_markers(LATE, "fn require_physical_value(", (
            "self.original.require_original()?", "identity(&self.locked.metadata()?)? != self.original.identity",
            "for _ in 0..2", "stamp(&self.locked.metadata()?) != self.stamp", "self.locked.read_exact_at(&mut bytes,",
            "bytes != self.bytes || stamp(&self.locked.metadata()?) != self.stamp", "self.original.require_original()"))
        self.check_markers(LATE, "fn require_unchanged(", (
            "self.fenced.load(Ordering::Acquire)", "let result = self.require_physical_value()", "if result.is_err()",
            "self.fenced.store(true, Ordering::Release)"))
        self.check_markers(LATE, "fn stamp(", (
            "metadata.len()", "metadata.mtime()", "metadata.mtime_nsec()", "metadata.ctime()", "metadata.ctime_nsec()"))

    def test_feature_fact_is_borrowed_from_actual_double_root_read(self):
        self.check_markers(AGENT + "root_historical_task_read_client.rs", "fn with_current_feature_read<T>(", (
            "OriginalHistoricalTaskReadReceiptV1::with_current_read(self, |ledger|",
            "RootHistoricalTaskPublicationDataV1::validate_against(", "&self.data.publication, ledger,",
            "action(&ledger.target, source, decision)"))
        self.check_markers(AGENT + "circuit_feature_current_publication.rs", "fn read_original_historical_completion(", (
            "OriginalHistoricalTaskReadReceiptV1::with_current_feature_read(", "manifest.digest()", "!= binding.manifest_digest()",
            "manifest.bundle_digest != source.bundle_digest().into_array()", "receipt.checkpoint_after != source.checkpoint_digest()",
            "source.input().scope.agent_id.as_str() != binding.scope().agent_id", "source.input().scope.cell_id.as_str() != binding.scope().cell_id",
            "source.input().scope.run_id.as_str() != binding.scope().run_id", "!= binding.scope().principal_digest",
            "source.require_decision(&receipt)", "require_publication_predecessor(binding)"))

    def test_route_cannot_be_serialized_or_reconstructed_and_data_files_cannot_initialize(self):
        for path, injected in ((ROUTE, "fn bad() { let route = serde_json::from_slice::<Deserialize>(bytes); }"),
                               (ROUTE, "fn bad() { let route = pub data: PreparedPublicationData; }"),
                               (MATERIAL, "fn bad() { OpenOptions::new().create(true); }"),
                               (LATE, "fn bad() { file.set_len(0); }")):
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                source = (ROOT / path).read_text()
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                target.write_text(source + "\n" + injected)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
