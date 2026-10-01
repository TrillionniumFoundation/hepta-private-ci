//! Full admission sidecars bound to original immutable registration checkpoints.

use super::*;

use crate::ArtifactAdmissionSnapshotReceiptV3;
use crate::admission_snapshot_receipt_v3;
use crate::read_artifact_admission_snapshot_bound;
use crate::validate_admission_registry_projection_v3;
use crate::write_artifact_admission_snapshot_beneath;

/// Decode one bounded canonical head. Signature authentication remains the
/// caller's separate trust-bound verification step.
pub fn read_signed_current_artifact_head_v1(
    file: File,
) -> Result<SignedCurrentArtifactHeadV1, ArtifactOwnerHostError> {
    let encoded_bytes = file.metadata()?.len();
    let bytes = crate::storage::read_bounded(
        file,
        MAX_SMALL_RECORD_BYTES,
        encoded_bytes,
        crate::ArtifactStorageError::Corrupt,
    )?;
    decode_signed_head(&bytes)
}

impl LearningArtifactOwnerHost {
    pub(super) fn validate_candidate_lineage(
        &self,
        registry: &ArtifactRegistry,
        candidate: &WithdrawalBoundArtifactAdmissionV3,
        withdrawals: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<(), ArtifactOwnerHostError> {
        let manifest = &candidate.validated_manifest.manifest;
        if registry.records().is_empty() {
            return if manifest.predecessor_ids.is_empty() {
                Ok(())
            } else {
                Err(ArtifactOwnerHostError::FullAdmissionRejected)
            };
        }
        let current = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let binding = self.current_registry_receipt(&current)?.binding;
        let admissions = self.load_admissions_for_registry(registry, binding)?;
        let eligible = crate::admission_closure::eligible_admission_closure(
            registry,
            &admissions,
            withdrawals,
            now,
        )
        .map_err(|_| ArtifactOwnerHostError::FullAdmissionRejected)?;
        for parent in &manifest.predecessor_ids {
            let admission = admissions
                .iter()
                .find(|admission| &admission.validated_manifest.manifest.artifact_id == parent)
                .ok_or(ArtifactOwnerHostError::FullAdmissionRejected)?;
            let predecessor = &admission.validated_manifest.manifest;
            if !eligible.contains(parent)
                || manifest.generation <= predecessor.generation
                || manifest.kind != predecessor.kind
                || manifest.objective_class_digest != predecessor.objective_class_digest
                || candidate.admitted_at < admission.admitted_at
            {
                return Err(ArtifactOwnerHostError::FullAdmissionRejected);
            }
        }
        Ok(())
    }

    pub fn current_registry_view_with_withdrawals(
        &self,
        withdrawals: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let view = self.current_registry_view(now)?;
        let admissions =
            self.load_admissions_for_registry(view.registry(), view.receipt().binding)?;
        view.with_admission_closure(admissions, withdrawals, now)
            .map_err(|_| ArtifactOwnerHostError::FullAdmissionRejected)
    }
    /// Load every full admission behind this immutable compatibility registry.
    /// Missing legacy sidecars fail closed until an exact authenticated backfill.
    pub fn load_admissions_for_registry(
        &self,
        registry: &ArtifactRegistry,
        binding: Digest32,
    ) -> Result<Vec<WithdrawalBoundArtifactAdmissionV3>, ArtifactOwnerHostError> {
        let checkpoints = recovery::verified_checkpoints(self)?;
        let mut admissions = Vec::new();
        for record in registry.records() {
            let ArtifactEvent::Register { event_id, manifest } = &record.event else {
                continue;
            };
            let intent = registration_intent_digest(event_id)?;
            let checkpoint = checkpoints
                .iter()
                .find(|checkpoint| {
                    checkpoint.intent_digest == intent
                        && checkpoint.expected_registry_predecessor_head
                            == record.predecessor_chain_digest
                })
                .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
            if checkpoint.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest {
                return Err(ArtifactOwnerHostError::WriterLeaseContext);
            }
            let path = self
                .root
                .join(admission_relative_path(manifest.support_digest));
            let metadata = fs::symlink_metadata(&path)?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(ArtifactOwnerHostError::PathBoundary);
            }
            let (admission, _) = read_artifact_admission_snapshot_bound(
                File::open(path)?,
                binding,
                checkpoint.withdrawal_scope_digest,
                manifest.support_digest,
                checkpoint.admission_digest,
            )?;
            if admission.withdrawal_head_digest != checkpoint.withdrawal_head_digest {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            validate_admission_registry_projection_v3(manifest, &admission)?;
            admissions.push(admission);
        }
        Ok(admissions)
    }

    /// Backfill only the original exact admission behind a historical owner
    /// registration. This creates immutable bytes and grants no new state.
    pub fn backfill_artifact_admission(
        &self,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        registry: &ArtifactRegistry,
        binding: Digest32,
        now: u64,
    ) -> Result<ArtifactAdmissionSnapshotReceiptV3, ArtifactOwnerHostError> {
        let writer = self.require_current_writer(now)?;
        if admission.validated_manifest.manifest.producer_id != writer.producer_id {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        let recovered = self.recover_registry_by_head(registry.snapshot().head_digest)?;
        if recovered.records() != registry.records() {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let artifact = &admission.validated_manifest.manifest.artifact_id;
        let (intent, predecessor) = registry
            .records()
            .iter()
            .find_map(|record| match &record.event {
                ArtifactEvent::Register { event_id, manifest }
                    if &manifest.artifact_id == artifact =>
                {
                    Some((
                        registration_intent_digest(event_id),
                        record.predecessor_chain_digest,
                    ))
                }
                ArtifactEvent::Register { .. }
                | ArtifactEvent::Quarantine(_)
                | ArtifactEvent::Revoke(_) => None,
            })
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        let intent = intent?;
        let checkpoint = recovery::verified_checkpoints(self)?
            .into_iter()
            .find(|checkpoint| {
                checkpoint.intent_digest == intent
                    && checkpoint.expected_registry_predecessor_head == predecessor
            })
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        if checkpoint.registry_receipt.map(|receipt| receipt.binding) != Some(binding)
            || phase_code(checkpoint.phase)
                < phase_code(ArtifactPublicationPhaseV1::RegistryDurable)
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        self.persist_artifact_admission(admission, registry, binding)
    }

    pub(super) fn persist_artifact_admission(
        &self,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        registry: &ArtifactRegistry,
        binding: Digest32,
    ) -> Result<ArtifactAdmissionSnapshotReceiptV3, ArtifactOwnerHostError> {
        let artifact = &admission.validated_manifest.manifest.artifact_id;
        let (record, event_id, manifest) = registry
            .records()
            .iter()
            .find_map(|record| match &record.event {
                ArtifactEvent::Register { event_id, manifest }
                    if &manifest.artifact_id == artifact =>
                {
                    Some((record, event_id, manifest))
                }
                ArtifactEvent::Register { .. }
                | ArtifactEvent::Revoke(_)
                | ArtifactEvent::Quarantine(_) => None,
            })
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        validate_admission_registry_projection_v3(manifest, admission)?;
        let intent = registration_intent_digest(event_id)?;
        let checkpoint = recovery::verified_checkpoints(self)?
            .into_iter()
            .find(|checkpoint| {
                checkpoint.intent_digest == intent
                    && checkpoint.expected_registry_predecessor_head
                        == record.predecessor_chain_digest
            })
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        if checkpoint.admission_digest != admission.admission_digest
            || checkpoint.withdrawal_scope_digest != admission.withdrawal_scope_digest
            || checkpoint.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest
            || checkpoint.withdrawal_head_digest != admission.withdrawal_head_digest
            || checkpoint
                .registry_receipt
                .is_some_and(|receipt| receipt.binding != binding)
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let expected = admission_snapshot_receipt_v3(admission, binding)?;
        let relative = admission_relative_path(manifest.support_digest);
        match write_artifact_admission_snapshot_beneath(&self.root, &relative, admission, binding) {
            Ok(receipt) if receipt == expected => {}
            Ok(_) => return Err(ArtifactOwnerHostError::InternalInvariant),
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                let (reopened, receipt) = read_artifact_admission_snapshot_bound(
                    File::open(self.root.join(&relative))?,
                    binding,
                    admission.withdrawal_scope_digest,
                    manifest.support_digest,
                    admission.admission_digest,
                )?;
                if reopened != *admission || receipt != expected {
                    return Err(ArtifactOwnerHostError::IdentityConflict);
                }
            }
            Err(error) => return Err(error.into()),
        }
        recovery::synchronize_artifact_path(&self.root.join(relative))?;
        Ok(expected)
    }
}

fn admission_relative_path(manifest_digest: Digest32) -> PathBuf {
    PathBuf::from("admissions").join(format!("{manifest_digest}.admission"))
}

fn registration_intent_digest(event_id: &StableId) -> Result<Digest32, ArtifactOwnerHostError> {
    let digest = event_id
        .as_str()
        .strip_prefix("artifact-publication:")
        .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
    parse_digest(digest)
}
