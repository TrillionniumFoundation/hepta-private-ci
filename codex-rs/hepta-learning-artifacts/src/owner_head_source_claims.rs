//! Structurally checked source claims. Their type intentionally does not assert
//! provenance: decoding bytes is never equivalent to holding an original
//! writer or to reading a process-pinned source. The typed agentd source client
//! establishes that separate boundary before its private native HEAD owner.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::ArtifactHeadSigningConfigV1;
use super::Error;
use super::super::ArtifactOwnerPublicationCheckpointV1;
use super::super::ArtifactOwnerVerifierV1;
use super::super::SignedCurrentArtifactHeadV1;
use super::super::registry_durable::original_registration_event;
use crate::ArtifactPublicationIntentV1;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationTransactionSnapshotV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::ArtifactRegistrySnapshot;
use crate::RegistryHeadRequirementV1;
use crate::RegistrySnapshotReceipt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UntrustedArtifactRegistryDurableV1 {
    pub(super) checkpoint: ArtifactOwnerPublicationCheckpointV1,
    pub(super) registry: ArtifactRegistrySnapshot,
    pub(super) receipt: RegistrySnapshotReceipt,
    pub(super) current: Option<SignedCurrentArtifactHeadV1>,
    pub(super) writer_lease_digest: Digest32,
    pub(super) trust_digest: Digest32,
    pub(super) observed_at: u64,
}

impl UntrustedArtifactRegistryDurableV1 {
    pub fn decode(bytes: &[u8], config: &ArtifactHeadSigningConfigV1) -> Result<Self, Error> {
        super::codec::decode_source(bytes, config)
    }

    pub fn checkpoint(&self) -> &ArtifactOwnerPublicationCheckpointV1 { &self.checkpoint }
    pub fn current_head(&self) -> Option<&SignedCurrentArtifactHeadV1> { self.current.as_ref() }
    pub fn observed_unix_millis(&self) -> u64 { self.observed_at }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }

    pub fn registry_receipt(&self) -> RegistrySnapshotReceipt { self.receipt }

    /// Full stable subject for original claim persistence, excluding the
    /// observation clock and legitimate RegistryDurable -> HEAD -> ACK progress.
    pub fn subject_binding(&self, config: &ArtifactHeadSigningConfigV1) -> Result<Digest32, Error> {
        let receipt = self.checkpoint.registry_receipt.ok_or(Error::CheckpointMismatch)?;
        let mut bytes = b"hepta.original-artifact-head-subject.v1".to_vec();
        bytes.extend_from_slice(config.binding()?.as_array());
        for digest in [
            self.checkpoint.intent_digest, self.checkpoint.admission_digest,
            self.checkpoint.withdrawal_scope_digest, self.checkpoint.withdrawal_head_digest,
            self.checkpoint.expected_registry_predecessor_head, self.writer_lease_digest,
            self.trust_digest, receipt.binding, receipt.head_digest, receipt.file_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&(receipt.records as u64).to_be_bytes());
        bytes.extend_from_slice(&(receipt.encoded_bytes as u64).to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn same_original_observation(&self, other: &Self) -> bool {
        self.checkpoint == other.checkpoint && self.registry == other.registry
            && self.current == other.current && self.writer_lease_digest == other.writer_lease_digest
            && self.trust_digest == other.trust_digest
    }

    pub fn require_unsigned_phase(&self) -> Result<(), Error> {
        if self.checkpoint.phase != ArtifactPublicationPhaseV1::RegistryDurable
            || self.checkpoint.witness_receipt.is_some() || self.checkpoint.acknowledged_at.is_some()
            || self.current.as_ref().is_some_and(|head| head.witness.head_digest == self.registry_receipt().head_digest)
        {
            return Err(Error::CheckpointMismatch);
        }
        Ok(())
    }

    /// Pure final-clock authentication of already decoded full original values.
    /// Live withdrawal, lease-file and CURRENT observation remain the original
    /// source's responsibility; a caller-created value cannot establish them.
    pub fn authenticate_current(&self, config: &ArtifactHeadSigningConfigV1, now: u64) -> Result<(), Error> {
        config.authenticate_current(now)?;
        let verifier = ArtifactOwnerVerifierV1::new(config.trust.clone())?;
        let context = &config.publication;
        let checkpoint = &self.checkpoint;
        let receipt = checkpoint.registry_receipt.ok_or(Error::CheckpointMismatch)?;
        if self.observed_at > now || self.observed_at < context.admission.admitted_at
            || self.trust_digest != verifier.trust_digest()
            || self.writer_lease_digest != config.writer_lease_digest()
            || checkpoint.operation_id != context.operation_id
            || checkpoint.original_writer_lease_digest != self.writer_lease_digest
            || checkpoint.admission_digest != context.admission.admission_digest
            || checkpoint.withdrawal_scope_digest != context.admission.withdrawal_scope_digest
            || checkpoint.withdrawal_head_digest != context.admission.withdrawal_head_digest
            || checkpoint.expected_registry_predecessor_head != context.expected_registry_predecessor_head
            || checkpoint.authority.grants_any() || receipt != self.receipt || receipt.binding != config.storage_binding
            || receipt.head_digest != self.registry.head_digest
            || matches!(checkpoint.phase, ArtifactPublicationPhaseV1::Prepared | ArtifactPublicationPhaseV1::PayloadDurable)
        {
            return Err(Error::CheckpointMismatch);
        }
        let transaction = ArtifactPublicationTransactionV1::from_snapshot(ArtifactPublicationTransactionSnapshotV1 {
            intent: ArtifactPublicationIntentV1 {
                operation_id: context.operation_id.clone(),
                admission: context.admission.clone(),
                expected_registry_predecessor_head: context.expected_registry_predecessor_head,
                intent_digest: checkpoint.intent_digest,
            },
            phase: checkpoint.phase, registry_receipt: checkpoint.registry_receipt,
            witness_receipt: checkpoint.witness_receipt, acknowledged_at: checkpoint.acknowledged_at,
            state_digest: checkpoint.state_digest,
        })?;
        let registry = ArtifactRegistry::from_snapshot(self.registry.clone())?;
        let canonical = crate::storage::encode_snapshot(&registry, receipt.binding)?;
        if canonical.len() != receipt.encoded_bytes || registry.records().len() != receipt.records
            || Digest32::of_bytes(&canonical) != receipt.file_digest
        {
            return Err(Error::CheckpointMismatch);
        }
        let mut parent = self.registry.clone();
        let last = parent.records.pop().ok_or(Error::CheckpointMismatch)?;
        if last.predecessor_chain_digest != context.expected_registry_predecessor_head
            || last.event != original_registration_event(&transaction)?
        {
            return Err(Error::CheckpointMismatch);
        }
        parent.head_digest = context.expected_registry_predecessor_head;
        ArtifactRegistry::from_snapshot(parent)?;
        match &self.current {
            Some(current) => {
                if current.binding != config.storage_binding
                    || ![context.expected_registry_predecessor_head, receipt.head_digest].contains(&current.witness.head_digest)
                    || current.witness.head_digest == receipt.head_digest
                        && current.witness.predecessor_head_digest != context.expected_registry_predecessor_head
                {
                    return Err(Error::CurrentHeadConflict);
                }
                verifier.verify_signed_head(current, &RegistryHeadRequirementV1 {
                    registry_id: config.trust.registry_id.clone(),
                    minimum_generation: config.trust.minimum_registry_generation,
                    expected_predecessor_head_digest: current.witness.predecessor_head_digest,
                    minimum_authority_epoch: config.trust.minimum_authority_epoch,
                    now,
                }, /*require_current_signer*/ true)?;
            }
            None if context.expected_registry_predecessor_head == config.trust.genesis_predecessor_head_digest => {}
            None => return Err(Error::CurrentHeadConflict),
        }
        if matches!(checkpoint.phase, ArtifactPublicationPhaseV1::WitnessDurable | ArtifactPublicationPhaseV1::Acknowledged) {
            let head = self.current.as_ref().ok_or(Error::CurrentHeadConflict)?;
            if head.witness.head_digest != receipt.head_digest { return Err(Error::CurrentHeadConflict); }
            let witness = checkpoint.witness_receipt.ok_or(Error::CheckpointMismatch)?;
            let encoded = crate::storage::encode_head_witness(&head.witness, head.binding)?;
            let validated = crate::validate_registry_head_witness(&head.witness, &RegistryHeadRequirementV1 {
                registry_id: config.trust.registry_id.clone(), minimum_generation: head.witness.generation,
                expected_predecessor_head_digest: context.expected_registry_predecessor_head,
                minimum_authority_epoch: config.trust.minimum_authority_epoch, now,
            }).map_err(|_| Error::CurrentHeadContext)?;
            if witness.binding != head.binding || witness.witness_digest != validated.witness_digest
                || witness.file_digest != Digest32::of_bytes(&encoded) || witness.encoded_bytes != encoded.len()
            {
                return Err(Error::CheckpointMismatch);
            }
        }
        Ok(())
    }
}
