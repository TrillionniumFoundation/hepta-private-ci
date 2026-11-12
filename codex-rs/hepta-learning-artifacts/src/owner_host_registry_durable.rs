//! Physical, bounded evidence from the original artifact writer. No operation
//! in this module creates a file, resumes a transaction, or signs a HEAD.

use std::fs::File;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ArtifactOwnerHostError;
use super::ArtifactOwnerPublicationCheckpointV1;
use super::LearningArtifactOwnerHost;
use super::MAX_SMALL_RECORD_BYTES;
use super::SignedArtifactWriterLeaseV1;
use super::SignedCurrentArtifactHeadV1;
use super::checkpoint_from_snapshot;
use super::decode_checkpoint;
use super::ordered_phases;
use super::read_small_record;
use crate::ArtifactEvent;
use crate::ArtifactManifest;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationIntentV1;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationTransactionSnapshotV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::ArtifactRegistrySnapshot;
use crate::DatasetWithdrawalRegistry;
use crate::OriginalArtifactPreparationErrorV1 as Error;
use crate::OriginalArtifactPublicationContextV1;
use crate::RegistryHeadRequirementV1;
use crate::RegistrySnapshotReceipt;
use crate::read_candidate_payload;
use crate::read_registry_head_witness;
use crate::read_registry_snapshot;
use crate::validate_artifact_publication_v3;

/// Original complete files and current owner state, never a signing or resume
/// capability. The only constructor is the original writer's physical read.
#[derive(Debug)]
pub struct OriginalArtifactRegistryDurableV1 {
    checkpoint: ArtifactOwnerPublicationCheckpointV1,
    registry: ArtifactRegistrySnapshot,
    registry_receipt: RegistrySnapshotReceipt,
    current: Option<SignedCurrentArtifactHeadV1>,
    writer_lease: SignedArtifactWriterLeaseV1,
    trust_digest: Digest32,
    observed_unix_millis: u64,
}

impl OriginalArtifactRegistryDurableV1 {
    pub fn checkpoint(&self) -> &ArtifactOwnerPublicationCheckpointV1 { &self.checkpoint }
    pub fn registry_snapshot(&self) -> &ArtifactRegistrySnapshot { &self.registry }
    pub fn registry_receipt(&self) -> RegistrySnapshotReceipt {
        self.registry_receipt
    }
    pub fn current_head(&self) -> Option<&SignedCurrentArtifactHeadV1> { self.current.as_ref() }
    pub fn writer_lease(&self) -> &SignedArtifactWriterLeaseV1 { &self.writer_lease }
    pub fn trust_digest(&self) -> Digest32 { self.trust_digest }
    pub fn observed_unix_millis(&self) -> u64 { self.observed_unix_millis }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }

    pub(crate) fn same_original_read(&self, other: &Self) -> bool {
        self.checkpoint == other.checkpoint && self.registry == other.registry
            && self.current == other.current && self.writer_lease == other.writer_lease
            && self.trust_digest == other.trust_digest
    }
}

impl LearningArtifactOwnerHost {
    // The original recovery API and the new readback share precisely the same
    // bounded five-phase decoder. This helper itself has no recovery effects.
    pub(crate) fn read_original_publication_checkpoint(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
        Ok(self.read_original_publication_checkpoints(operation_id)?.pop())
    }

    fn read_original_publication_checkpoints(
        &self,
        operation_id: &StableId,
    ) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
        let mut observed = Vec::new();
        let mut missing_seen = false;
        let mut invariant = None;
        for phase in ordered_phases() {
            let path = self.checkpoint_path(operation_id, phase);
            if !path.exists() { missing_seen = true; continue; }
            if missing_seen { return Err(ArtifactOwnerHostError::CheckpointGap); }
            let checkpoint = decode_checkpoint(&read_small_record(&path, MAX_SMALL_RECORD_BYTES)?)?;
            if checkpoint.operation_id != *operation_id || checkpoint.phase != phase {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            let key = (checkpoint.intent_digest, checkpoint.admission_digest,
                checkpoint.withdrawal_scope_digest, checkpoint.expected_registry_predecessor_head);
            if invariant.is_some_and(|value| value != key) {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            invariant = Some(key);
            observed.push(checkpoint);
        }
        Ok(observed)
    }

    pub(crate) fn read_original_registry_predecessor(
        &self, expected: Digest32, binding: Digest32, at: u64,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        self.require_current_writer(at)?;
        let (current, registry) = self.read_preparation_current(binding, at)?;
        if registry.snapshot().head_digest != expected
            || current.is_none() && expected != self.verifier.trust.genesis_predecessor_head_digest
        {
            return Err(ArtifactOwnerHostError::RegistryPredecessorMismatch);
        }
        Ok(registry)
    }

    pub(crate) fn read_original_registry_durable(
        &self,
        context: &OriginalArtifactPublicationContextV1,
        withdrawals: &DatasetWithdrawalRegistry,
        binding: Digest32,
        clock: &impl Fn() -> Result<u64, Error>,
    ) -> Result<OriginalArtifactRegistryDurableV1, Error> {
        let started = clock()?;
        let writer = self.require_current_writer(started)?;
        let withdrawals_before = withdrawals.snapshot();
        validate_artifact_publication_v3(&context.admission, withdrawals, started)
            .map_err(ArtifactPublicationError::from)?;
        let before_records = self.read_original_publication_checkpoints(&context.operation_id)?;
        let before = before_records.last().cloned().ok_or(Error::NoCheckpoint)?;
        // Authenticate the complete original intent and phase/state digest,
        // including pending records, without invoking resume/recovery.
        for checkpoint in &before_records {
            if checkpoint.admission_digest != context.admission.admission_digest
                || checkpoint.withdrawal_scope_digest != context.admission.withdrawal_scope_digest
                || checkpoint.withdrawal_head_digest != context.admission.withdrawal_head_digest
                || checkpoint.expected_registry_predecessor_head != context.expected_registry_predecessor_head
                || checkpoint.original_writer_lease_digest != writer.lease_digest
                || checkpoint.authority.grants_any()
                || context.admission.validated_manifest.manifest.producer_id != writer.producer_id
            { return Err(Error::Context); }
            ArtifactPublicationTransactionV1::from_snapshot(ArtifactPublicationTransactionSnapshotV1 {
            intent: ArtifactPublicationIntentV1 {
                operation_id: context.operation_id.clone(), admission: context.admission.clone(),
                expected_registry_predecessor_head: context.expected_registry_predecessor_head,
                intent_digest: checkpoint.intent_digest,
            },
            phase: checkpoint.phase, registry_receipt: checkpoint.registry_receipt,
            witness_receipt: checkpoint.witness_receipt, acknowledged_at: checkpoint.acknowledged_at,
            state_digest: checkpoint.state_digest,
        })?;
        }
        if matches!(before.phase, ArtifactPublicationPhaseV1::Prepared | ArtifactPublicationPhaseV1::PayloadDurable) {
            return Err(Error::Pending(before.phase));
        }
        let receipt = before.registry_receipt.ok_or(Error::Context)?;
        if receipt.binding != binding { return Err(Error::Context); }
        let (current_before, current_registry_before) = self.read_preparation_current(binding, started)?;
        let registry = read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))
            .map_err(ArtifactOwnerHostError::from)?, receipt).map_err(ArtifactOwnerHostError::from)?;
        let mut predecessor_snapshot = registry.snapshot();
        let last = predecessor_snapshot.records.pop().ok_or(Error::Context)?;
        if last.predecessor_chain_digest != context.expected_registry_predecessor_head {
            return Err(Error::Context);
        }
        predecessor_snapshot.head_digest = context.expected_registry_predecessor_head;
        let predecessor = ArtifactRegistry::from_snapshot(predecessor_snapshot)
            .map_err(ArtifactOwnerHostError::from)?;
        let mut transaction = ArtifactPublicationTransactionV1::begin(
            context.operation_id.clone(), context.admission.clone(), withdrawals, &predecessor,
            context.expected_registry_predecessor_head, started,
        )?;
        if last.event != original_registration_event(&transaction)? { return Err(Error::Context); }
        let manifest = &context.admission.validated_manifest.manifest;
        let path = self.root.join("payloads").join(format!("{}-{}.bin", manifest.artifact_id, manifest.bytes_digest));
        let payload = read_candidate_payload(File::open(&path).map_err(ArtifactOwnerHostError::from)?,
            &registry, &manifest.artifact_id).map_err(ArtifactOwnerHostError::from)?;
        transaction.record_payload_durable(Digest32::of_bytes(&payload), payload.len() as u64)?;
        transaction.record_registry_durable(&registry, receipt, withdrawals, started)?;
        let current_head = current_before.as_ref().map(|value| value.witness.head_digest);
        let current_is_parent = current_registry_before.snapshot().head_digest == context.expected_registry_predecessor_head
            && (current_before.is_some() || context.expected_registry_predecessor_head == self.verifier.trust.genesis_predecessor_head_digest);
        if !current_is_parent && current_head != Some(receipt.head_digest) { return Err(Error::Context); }
        if matches!(before.phase, ArtifactPublicationPhaseV1::WitnessDurable | ArtifactPublicationPhaseV1::Acknowledged) {
            let signed = current_before.as_ref().ok_or(Error::Context)?;
            if signed.witness.head_digest != receipt.head_digest { return Err(Error::Context); }
            let requirement = self.preparation_head_requirement(signed, started);
            let witness_receipt = before.witness_receipt.ok_or(Error::Context)?;
            let witness_path = self.root.join("witnesses").join(format!("{}-{}.witness", signed.witness.generation.get(), witness_receipt.witness_digest));
            let actual = read_registry_head_witness(File::open(witness_path).map_err(ArtifactOwnerHostError::from)?,
                witness_receipt, &requirement).map_err(ArtifactOwnerHostError::from)?;
            if actual != signed.witness { return Err(Error::Context); }
            transaction.record_witness_durable(&actual, &requirement, witness_receipt, withdrawals, started)?;
            if let Some(acknowledged_at) = before.acknowledged_at {
                transaction.acknowledge(withdrawals, acknowledged_at)?;
            }
        }
        if checkpoint_from_snapshot(&transaction.snapshot(), writer.lease_digest) != before {
            return Err(Error::Context);
        }
        // Read the complete immutable data again. Valid signatures or a cached
        // registry never substitute for these physical reads.
        let registry_after = read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))
            .map_err(ArtifactOwnerHostError::from)?, receipt).map_err(ArtifactOwnerHostError::from)?;
        let payload_after = read_candidate_payload(File::open(path).map_err(ArtifactOwnerHostError::from)?,
            &registry_after, &manifest.artifact_id).map_err(ArtifactOwnerHostError::from)?;
        let (current_after, current_registry_after) = self.read_preparation_current(binding, started)?;
        let after_records = self.read_original_publication_checkpoints(&context.operation_id)?;
        let after = after_records.last().cloned().ok_or(Error::NoCheckpoint)?;
        if before_records != after_records || registry.snapshot() != registry_after.snapshot() || payload != payload_after
            || current_before != current_after || current_registry_before.snapshot() != current_registry_after.snapshot()
            || withdrawals_before != withdrawals.snapshot()
        { return Err(Error::ChangedDuringRead); }
        let fresh = clock()?;
        if fresh < started { return Err(Error::Clock); }
        let writer_after = self.require_current_writer(fresh)?;
        if writer_after.lease_digest != writer.lease_digest { return Err(Error::ChangedDuringRead); }
        validate_artifact_publication_v3(&context.admission, withdrawals, fresh).map_err(ArtifactPublicationError::from)?;
        if let Some(signed) = &current_after {
            self.verifier.verify_signed_head(signed, &self.preparation_head_requirement(signed, fresh), /*require_current_signer*/ true)?;
        }
        // No file, witness or peer I/O occurs after the fresh complete original
        // writer/head/withdrawal validation. This is a point-in-time proof.
        Ok(OriginalArtifactRegistryDurableV1 {
            checkpoint: after, registry: registry_after.snapshot(), registry_receipt: receipt, current: current_after,
            writer_lease: self.lease.clone(), trust_digest: self.verifier.trust_digest(),
            observed_unix_millis: fresh,
        })
    }

    fn preparation_head_requirement(&self, signed: &SignedCurrentArtifactHeadV1, now: u64) -> RegistryHeadRequirementV1 {
        RegistryHeadRequirementV1 { registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: signed.witness.generation,
            expected_predecessor_head_digest: signed.witness.predecessor_head_digest,
            minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch, now }
    }

    fn read_preparation_current(&self, binding: Digest32, now: u64)
        -> Result<(Option<SignedCurrentArtifactHeadV1>, ArtifactRegistry), ArtifactOwnerHostError>
    {
        let Some(head) = self.discover_current_head(now)? else { return Ok((None, ArtifactRegistry::new())); };
        let current = self.current_registry_view_bounded(now)?;
        if current.receipt().binding != binding || current.receipt().head_digest != head.signed.witness.head_digest
            || current.witness_digest() != head.witness_digest || current.trust_digest() != head.trust_digest
        { return Err(ArtifactOwnerHostError::CurrentHeadConflict); }
        Ok((Some(head.signed), current.registry().clone()))
    }
}

pub(super) fn original_registration_event(transaction: &ArtifactPublicationTransactionV1) -> Result<ArtifactEvent, ArtifactOwnerHostError> {
    let admission = &transaction.intent().admission;
    let v2 = &admission.validated_manifest.manifest;
    let event_id = StableId::new(format!("artifact-publication:{}", transaction.intent().intent_digest))
        .map_err(|_| ArtifactOwnerHostError::InternalInvariant)?;
    let predecessor_id = if v2.predecessor_ids.len() == 1 { v2.predecessor_ids.first().cloned() } else { None };
    Ok(ArtifactEvent::Register { event_id, manifest: ArtifactManifest {
        artifact_id: v2.artifact_id.clone(), kind: v2.kind, generation: v2.generation, predecessor_id,
        content_digest: v2.bytes_digest, objective_digest: v2.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest, producer_id: v2.producer_id.clone(),
        compatibility_digest: v2.compatibility_digest, encoded_size_bytes: v2.encoded_size_bytes,
    } })
}
