//! Read-only observation of one already started artifact publication.
//!
//! This Unix-millisecond product profile matches the version host's original
//! authority clock. It does not resume a transaction, grant writer permission,
//! select an artifact or authorize FinalUse. Each result is one current read;
//! callers must retain the original operation/intent and read again after loss.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ArtifactOwnerHostError;
use super::ArtifactOwnerPublicationCheckpointV1;
use super::LearningArtifactOwnerHost;
use super::MAX_HEAD_RECORDS;
use super::MAX_SMALL_RECORD_BYTES;
use super::VerifiedCurrentArtifactHeadV1;
use super::decode_checkpoint;
use super::phase_code;
use super::read_small_record;
use crate::ArtifactPublicationPhaseV1;
use crate::RegistryHeadRequirementV1;
use crate::RegistrySnapshotReceipt;
use crate::VerifiedCurrentRegistryViewV1;
use crate::read_registry_snapshot;

// Existing heads and individual records keep their original bounds. Also
// bound the transaction scan used by the existing CURRENT snapshot lookup.
const MAX_READBACK_TRANSACTION_RECORDS: usize = MAX_HEAD_RECORDS;

/// Actual checkpoint and authenticated CURRENT, not a publication capability.
/// An acknowledged historical operation may differ from the latest CURRENT.
/// Its old phase is never promoted into selection or adoption authority.
#[derive(Debug)]
pub struct OriginalArtifactPublicationReadbackV1 {
    checkpoint: ArtifactOwnerPublicationCheckpointV1,
    current: VerifiedCurrentRegistryViewV1,
    observed_unix_millis: u64,
}

impl OriginalArtifactPublicationReadbackV1 {
    pub fn checkpoint(&self) -> &ArtifactOwnerPublicationCheckpointV1 {
        &self.checkpoint
    }

    pub fn current(&self) -> &VerifiedCurrentRegistryViewV1 {
        &self.current
    }

    pub fn observed_unix_millis(&self) -> u64 {
        self.observed_unix_millis
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Debug)]
pub enum OriginalArtifactPublicationReadbackErrorV1 {
    Owner(ArtifactOwnerHostError),
    InvalidExpectation,
    ChangedDuringRead,
    Clock,
}

impl fmt::Display for OriginalArtifactPublicationReadbackErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OriginalArtifactPublicationReadbackErrorV1 {}

impl From<ArtifactOwnerHostError> for OriginalArtifactPublicationReadbackErrorV1 {
    fn from(error: ArtifactOwnerHostError) -> Self {
        Self::Owner(error)
    }
}

impl LearningArtifactOwnerHost {
    /// The existing named service is the only product caller. The host and its
    /// writer fence, trust and required CURRENT floor stay in original custody.
    pub(crate) fn read_original_publication_current(
        &self,
        operation_id: &StableId,
        expected_intent_digest: Digest32,
    ) -> Result<OriginalArtifactPublicationReadbackV1, OriginalArtifactPublicationReadbackErrorV1>
    {
        let started = now_unix_millis()?;
        if expected_intent_digest.is_zero() {
            return Err(OriginalArtifactPublicationReadbackErrorV1::InvalidExpectation);
        }
        let before = self
            .recover_publication(operation_id)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        if before.checkpoint.operation_id != *operation_id
            || before.checkpoint.intent_digest != expected_intent_digest
            || before.checkpoint.authority.grants_any()
            || before.authority.grants_any()
        {
            return Err(OriginalArtifactPublicationReadbackErrorV1::InvalidExpectation);
        }
        let head_before = self
            .discover_current_head(started)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let current_before = self.current_registry_view_bounded(started)?;
        let current_after = self.current_registry_view_bounded(started)?;
        let head_after = self
            .discover_current_head(started)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let after = self
            .recover_publication(operation_id)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        if before != after
            || head_before != head_after
            || current_before.receipt() != current_after.receipt()
            || current_before.witness_digest() != current_after.witness_digest()
            || current_before.trust_digest() != current_after.trust_digest()
            || current_after.receipt().head_digest != head_after.signed.witness.head_digest
            || current_after.receipt().binding != head_after.signed.binding
            || current_after.witness_digest() != head_after.witness_digest
            || current_after.trust_digest() != head_after.trust_digest
        {
            return Err(OriginalArtifactPublicationReadbackErrorV1::ChangedDuringRead);
        }
        let fresh = now_unix_millis()?;
        if fresh < started {
            return Err(OriginalArtifactPublicationReadbackErrorV1::Clock);
        }
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: head_after.signed.witness.generation,
            expected_predecessor_head_digest: head_after.signed.witness.predecessor_head_digest,
            minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
            now: fresh,
        };
        let authenticated = self.verifier.verify_signed_head(
            &head_after.signed,
            &requirement,
            /*require_current_signer*/ true,
        )?;
        if authenticated != head_after {
            return Err(OriginalArtifactPublicationReadbackErrorV1::ChangedDuringRead);
        }
        // No file, witness or peer I/O follows this final original signature
        // validation. This is a point-in-time read, never a continuation token.
        Ok(OriginalArtifactPublicationReadbackV1 {
            checkpoint: after.checkpoint,
            current: current_after,
            observed_unix_millis: fresh,
        })
    }

    fn current_registry_view_bounded(
        &self,
        at: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let current = self
            .discover_current_head(at)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let receipt = self.current_registry_receipt_bounded(&current)?;
        let registry =
            read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
        if registry.snapshot().head_digest != current.signed.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(VerifiedCurrentRegistryViewV1::new(
            receipt,
            registry,
            current.witness_digest,
            current.trust_digest,
        ))
    }

    fn current_registry_receipt_bounded(
        &self,
        current: &VerifiedCurrentArtifactHeadV1,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        let mut matched: Option<RegistrySnapshotReceipt> = None;
        // This is the actual decoding scan, not an earlier directory count.
        // A concurrent directory growth can never enlarge this iterator's bound.
        for (index, entry) in fs::read_dir(self.root.join("transactions"))?
            .take(MAX_READBACK_TRANSACTION_RECORDS + 1)
            .enumerate()
        {
            if index >= MAX_READBACK_TRANSACTION_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            let entry = entry?;
            let metadata = fs::symlink_metadata(entry.path())?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            if entry.path().extension().and_then(|value| value.to_str()) != Some("checkpoint") {
                continue;
            }
            let checkpoint =
                decode_checkpoint(&read_small_record(&entry.path(), MAX_SMALL_RECORD_BYTES)?)?;
            if phase_code(checkpoint.phase)
                < phase_code(ArtifactPublicationPhaseV1::RegistryDurable)
            {
                continue;
            }
            let Some(registry_receipt) = checkpoint.registry_receipt else {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            };
            if registry_receipt.head_digest != current.signed.witness.head_digest
                || registry_receipt.binding != current.signed.binding
            {
                continue;
            }
            if let Some(witness_receipt) = checkpoint.witness_receipt
                && (witness_receipt.witness_digest != current.witness_digest
                    || witness_receipt.binding != current.signed.binding)
            {
                return Err(ArtifactOwnerHostError::CurrentHeadConflict);
            }
            match matched {
                Some(existing) if existing != registry_receipt => {
                    return Err(ArtifactOwnerHostError::IdentityConflict);
                }
                Some(_) => {}
                None => matched = Some(registry_receipt),
            }
        }
        matched.ok_or(ArtifactOwnerHostError::CheckpointMissing)
    }
}

fn now_unix_millis() -> Result<u64, OriginalArtifactPublicationReadbackErrorV1> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OriginalArtifactPublicationReadbackErrorV1::Clock)?;
    u64::try_from(elapsed.as_millis())
        .map_err(|_| OriginalArtifactPublicationReadbackErrorV1::Clock)
}
