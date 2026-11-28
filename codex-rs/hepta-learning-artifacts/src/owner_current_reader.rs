//! Shared CURRENT discovery and immutable snapshot verification.
//!
//! The writer host and read-only consumers use the same head-chain, independent
//! floor and durable checkpoint checks. This module has no publication route.

use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactRegistry;
use crate::RegistryHeadRequirementV1;
use crate::RegistrySnapshotReceipt;
use crate::VerifiedCurrentRegistryViewV1;
use crate::read_registry_snapshot;

use super::ArtifactOwnerHostError;
use super::ArtifactOwnerTrustV1;
use super::ArtifactOwnerVerifierV1;
use super::MAX_HEAD_RECORDS;
use super::MAX_SMALL_RECORD_BYTES;
use super::SignedCurrentArtifactHeadV1;
use super::VerifiedCurrentArtifactHeadV1;
use super::decode_checkpoint;
use super::decode_signed_head;
use super::encode_signed_head;
use super::phase_code;
use super::read_small_record;
use super::verify_signer_context;

/// Read the existing owner's CURRENT store without acquiring its writer fence.
///
/// This reader accepts no writer lease and exposes no publication operation.
/// The floor must come from independently retained owner state, never from the
/// candidate's submitted selection bundle. Construction creates no files.
#[derive(Debug)]
pub struct ArtifactOwnerCurrentReaderV1 {
    root: PathBuf,
    verifier: ArtifactOwnerVerifierV1,
    required_current_head: SignedCurrentArtifactHeadV1,
}

impl ArtifactOwnerCurrentReaderV1 {
    pub fn open_existing(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        required_current_head: SignedCurrentArtifactHeadV1,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let metadata = fs::symlink_metadata(root.as_ref())?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
        let root = fs::canonicalize(root)?;
        for directory in ["transactions", "registries", "heads"] {
            let metadata = fs::symlink_metadata(root.join(directory))?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(ArtifactOwnerHostError::PathBoundary);
            }
        }
        let reader = Self {
            root,
            verifier: ArtifactOwnerVerifierV1::new(trust)?,
            required_current_head,
        };
        reader.store_reader().discover_current_head(now)?;
        Ok(reader)
    }

    fn store_reader(&self) -> ArtifactOwnerStoreReader<'_> {
        ArtifactOwnerStoreReader {
            root: &self.root,
            verifier: &self.verifier,
            required_current_head: Some(&self.required_current_head),
        }
    }

    /// Discover CURRENT, read its exact durable snapshot, then rediscover it.
    ///
    /// Two bounded attempts tolerate a concurrent publication. A changing or
    /// invalid store fails closed; a previously returned view is never a
    /// fallback. This is a point-in-time read, not a lock across inference or
    /// effects. Consumers must obtain another view at their final-use boundary.
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let store = self.store_reader();
        for _ in 0..2 {
            let (view, before) = store.current_registry_view(now)?;
            let after = store.discover_current_head(now)?;
            if after.as_ref() == Some(&before) {
                return Ok(view);
            }
        }
        Err(ArtifactOwnerHostError::CurrentHeadConflict)
    }
}

pub(super) struct ArtifactOwnerStoreReader<'a> {
    pub(super) root: &'a Path,
    pub(super) verifier: &'a ArtifactOwnerVerifierV1,
    pub(super) required_current_head: Option<&'a SignedCurrentArtifactHeadV1>,
}

impl ArtifactOwnerStoreReader<'_> {
    fn current_registry_receipt(
        &self,
        current: &VerifiedCurrentArtifactHeadV1,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        let mut matched: Option<RegistrySnapshotReceipt> = None;
        for entry in fs::read_dir(self.root.join("transactions"))? {
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

    fn registry_snapshot_path(&self, receipt: RegistrySnapshotReceipt) -> PathBuf {
        self.root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        ))
    }

    pub(super) fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<
        (VerifiedCurrentRegistryViewV1, VerifiedCurrentArtifactHeadV1),
        ArtifactOwnerHostError,
    > {
        let current = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let receipt = self.current_registry_receipt(&current)?;
        let registry =
            read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
        if registry.snapshot().head_digest != current.signed.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok((
            VerifiedCurrentRegistryViewV1::new(
                receipt,
                registry,
                current.witness_digest,
                current.trust_digest,
            ),
            current,
        ))
    }

    pub(super) fn recover_current_registry(
        &self,
        now: u64,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        let Some(current) = self.discover_current_head(now)? else {
            return Ok(ArtifactRegistry::new());
        };
        let receipt = self.current_registry_receipt(&current)?;
        let registry =
            read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
        if registry.snapshot().head_digest != current.signed.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(registry)
    }

    pub(super) fn discover_current_head(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError> {
        let latest = self.discover_current_head_unanchored(now)?;
        if let Some(anchor) = self.required_current_head {
            self.enforce_required_current_head(anchor, latest.as_ref())?;
        }
        Ok(latest)
    }

    fn discover_current_head_unanchored(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError> {
        let mut records = Vec::new();
        for entry in fs::read_dir(self.root.join("heads"))? {
            if records.len() >= MAX_HEAD_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            let entry = entry?;
            let metadata = fs::symlink_metadata(entry.path())?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(ArtifactOwnerHostError::CurrentHeadContext);
            }
            if entry.path().extension().and_then(|value| value.to_str()) != Some("head") {
                continue;
            }
            records.push(decode_signed_head(&read_small_record(
                &entry.path(),
                MAX_SMALL_RECORD_BYTES,
            )?)?);
        }
        if records.is_empty() {
            return Ok(None);
        }

        let mut by_predecessor: BTreeMap<Digest32, Vec<SignedCurrentArtifactHeadV1>> =
            BTreeMap::new();
        for record in records {
            by_predecessor
                .entry(record.witness.predecessor_head_digest)
                .or_default()
                .push(record);
        }
        let mut predecessor = self.verifier.trust.genesis_predecessor_head_digest;
        let mut minimum_generation = self.verifier.trust.minimum_registry_generation;
        let mut minimum_epoch = self.verifier.trust.minimum_authority_epoch;
        let mut consumed = 0usize;
        let mut latest = None;
        while let Some(candidates) = by_predecessor.remove(&predecessor) {
            if candidates.len() != 1 {
                return Err(ArtifactOwnerHostError::CurrentHeadFork);
            }
            let candidate = candidates
                .into_iter()
                .next()
                .ok_or(ArtifactOwnerHostError::InternalInvariant)?;
            let historical_requirement = RegistryHeadRequirementV1 {
                registry_id: self.verifier.trust.registry_id.clone(),
                minimum_generation,
                expected_predecessor_head_digest: predecessor,
                minimum_authority_epoch: minimum_epoch,
                now: candidate.witness.issued_at,
            };
            let verified = self.verifier.verify_signed_head(
                &candidate,
                &historical_requirement,
                /*require_current_signer*/ false,
            )?;
            predecessor = candidate.witness.head_digest;
            minimum_generation = candidate
                .witness
                .generation
                .next()
                .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?;
            minimum_epoch = candidate.witness.authority_epoch;
            consumed += 1;
            latest = Some(verified);
        }
        if by_predecessor.values().any(|values| !values.is_empty()) {
            return Err(ArtifactOwnerHostError::CurrentHeadFork);
        }
        if consumed == 0 {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let latest = latest.ok_or(ArtifactOwnerHostError::InternalInvariant)?;
        let signer = self
            .verifier
            .head_signers
            .get(&latest.signed.witness.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        verify_signer_context(
            signer,
            latest.signed.witness.signing_key_digest,
            latest.signed.witness.authority_epoch,
            latest.signed.witness.issued_at,
            now,
            /*require_current*/ true,
        )?;
        if now > latest.signed.witness.expires_at {
            return Err(ArtifactOwnerHostError::CurrentHeadExpired);
        }
        Ok(Some(latest))
    }

    pub(super) fn signed_head_record_path(&self, signed: &SignedCurrentArtifactHeadV1) -> PathBuf {
        self.root.join("heads").join(format!(
            "{}-{}.head",
            signed.witness.generation.get(),
            Digest32::of_bytes(&signed.signing_bytes())
        ))
    }

    fn enforce_required_current_head(
        &self,
        anchor: &SignedCurrentArtifactHeadV1,
        latest: Option<&VerifiedCurrentArtifactHeadV1>,
    ) -> Result<(), ArtifactOwnerHostError> {
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: anchor.witness.generation,
            expected_predecessor_head_digest: anchor.witness.predecessor_head_digest,
            minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
            now: anchor.witness.issued_at,
        };
        self.verifier.verify_signed_head(
            anchor,
            &requirement,
            /*require_current_signer*/ false,
        )?;
        let path = self.signed_head_record_path(anchor);
        if !path.is_file()
            || read_small_record(&path, MAX_SMALL_RECORD_BYTES)? != encode_signed_head(anchor)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadRollback);
        }
        let latest = latest.ok_or(ArtifactOwnerHostError::CurrentHeadRollback)?;
        if latest.signed.witness.generation < anchor.witness.generation
            || (latest.signed.witness.generation == anchor.witness.generation
                && latest.signed.witness.head_digest != anchor.witness.head_digest)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadRollback);
        }
        Ok(())
    }
}
