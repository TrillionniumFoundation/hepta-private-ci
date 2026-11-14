"""Artifact publication keeps the actual Decision, signer and withdrawal cut."""

from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT, A, PROOF = component.ROOT, component.AGENT, component.PROOF
ART = A + 'production_post_a_artifacts.rs'
REQ = A + 'production_post_a_artifact_request.rs'


class PostAArtifactsSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_owner_requires_original_trainer_lease_and_existing_root_current(self):
        self.check_markers(ART, 'fn publish_and_select_original(', (
            'writer_lease.producer_id != snapshot.owners.trainer', 'route.with_original_data(|fixed|',
            'withdrawal_floor(inputs, files)?', 'LearningArtifactOwnerService::open(',
            'root: inputs.artifact_root.clone()', 'trust: inputs.owner_trust.original_owner_trust()?',
            'required_current_head: Some(inputs.retained_current.original_current()?)',
            'storage_binding: Digest32::from_array(inputs.storage_binding)',
            'Decision::new(snapshot.clone())', 'decision.require_root_publication()'))

    def test_adopt_retained_and_recovery_keep_their_original_owner_operations(self):
        self.check_markers(ART, 'fn publish_and_select_original(', (
            'if decision.adopts()', 'OriginalCellQ24ArtifactPublicationDriverV1::for_qualified_adoption(',
            'Mode::Reserve', 'self.head.wait_original_value(cancelled).await?', 'candidate_manifest()',
            'request::original_request(', 'OriginalCellQ24ArtifactPublicationDriverV1::publish_candidate(',
            'Mode::Recover', 'OriginalCellQ24ArtifactPublicationDriverV1::recover_published(driver)',
            'OriginalCellQ24RetainedArtifactForRootV1::from_original_result(', 'match (published, retained)',
            'OriginalCellQ24PublishedArtifactForRootV1::accept_selection(published, input)',
            'OriginalCellQ24RetainedArtifactForRootV1::accept_selection(retained, input)', '_ => return Err('))

    def test_independent_selection_reopens_and_rechecks_the_actual_selected_files(self):
        self.check_markers(ART, 'fn publish_and_select_original(', (
            'inputs.selector_trust.original_selector(&trust)?', 'libc::geteuid()',
            'LearningArtifactReadViewV1::open_original(',
            '.with_original_withdrawal_floor(Digest32::from_array(inputs.storage_binding), floor)',
            'registry_snapshot: files.read(&paths.0)?', 'payload: files.read(&paths.1)?', '!= paths'))
        for occurrence in (0, 1):
            self.reject_removal(ART, 'fn publish_and_select_original(',
                                'LearningArtifactReadViewV1::locate_selected_original_files(', occurrence)

    def test_artifact_full_payload_and_lineage_are_from_the_checkpointed_decision(self):
        self.check_markers(REQ, 'fn original_request(', (
            'decision.require_root_publication()', 'if !decision.adopts()',
            'validate_manifest(bundle, manifest)', 'serde_json::to_vec(manifest)?',
            'lineage.source_bundle', 'lineage.dataset', 'lineage.update_rule', 'lineage.evaluation_profile',
            'LearningIterationObservationV1::Training', 'LearningIterationObservationV1::Evaluation',
            'LearningIterationObservationV1::Proposal', 'LearningIterationObservationV1::LocalDecisionV2',
            'receipt.evidence_digest', 'provenance_mode: ProvenanceModeV1::DatasetDerived',
            'source_dataset_digests: vec![lineage.dataset]', 'predecessor_ids: vec![', 'rollback_predecessor: Some(',
            'bytes_digest: Digest32::of_bytes(&payload)', 'encoded_size_bytes: payload.len() as u64',
            'compatibility_digest: Digest32::from_array(manifest.digest()',
            'producer_id: decision.snapshot.owners.trainer.clone()'))

    def test_signature_window_and_withdrawal_head_cannot_be_renewed_locally(self):
        self.check_markers(REQ, 'fn original_request(', (
            'created_at: signed_current_head.witness.issued_at',
            'expires_at: signed_current_head.witness.expires_at',
            'let signed_at = signed_current_head.witness.issued_at',
            'admit_manifest_at_withdrawal_head_v3(', 'owner.withdrawal_registry()',
            'owner.withdrawal_registry().head_digest()', 'original,\n        signed_at,',
            'validate_artifact_publication_v3(&admission, owner.withdrawal_registry(), now)',
            'operation_id: decision.artifact_operation.clone()',
            'signed_current_head,', 'expected_registry_predecessor_head: owner.registry().snapshot().head_digest'))
        self.check_markers(A + 'production_post_a_artifact_data.rs', 'fn original_signed_lease(', (
            'signer_id: StableId::new(&self.signer_id)',
            'signing_key_digest: Digest32::from_array(self.signing_key_digest)',
            'authority_epoch: self.authority_epoch', 'lease_generation: self.lease_generation',
            'issued_at: self.issued_at', 'expires_at: self.expires_at', '.signature', '.try_into()'))

    def test_original_signed_inputs_remain_held_and_reobserved(self):
        self.check_markers(ART, 'fn require_original(', (
            'post_a_remaining(self.end)?', 'self.lease.require_unchanged()?',
            'head.require_unchanged()?', 'self.selection.require_unchanged()?'))
        self.check_markers(ART, 'fn withdrawal_floor(', (
            'read_dataset_withdrawal_snapshot(', 'files.read(&inputs.withdrawal_file)?',
            'binding: Digest32::from_array(data.binding)', 'scope_digest: Digest32::from_array(data.scope)',
            'head_digest: Digest32::from_array(data.head)', 'file_digest: Digest32::from_array(data.file_digest)',
            'records: data.records', 'encoded_bytes: data.encoded_bytes'))

    def test_missing_current_local_signatures_and_fresh_timestamps_are_forbidden(self):
        for path, injected in ((ART, 'fn bypass() { let required_current_head: None; }'),
                               (ART, 'fn bypass() { key.sign(bytes); }'),
                               (REQ, 'fn bypass() { let now = SystemTime::now(); }')):
            rows = [row for row in self.manifest['protected_file'] if row['path'] == path]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                source = (ROOT / path).read_text()
                target.write_text(source)
                PROOF._verify_protected_files(root, {'protected_file': rows})
                target.write_text(source + '\n' + injected)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {'protected_file': rows})


if __name__ == '__main__':
    unittest.main()
