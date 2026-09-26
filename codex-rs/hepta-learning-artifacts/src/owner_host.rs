//! Named product-owner host for immutable learning-artifact publication.
//!
//! The host owns the local writer fence and durable publication checkpoints.
//! It authenticates a bounded writer lease and signed registry-head witnesses
//! with host-supplied Ed25519 trust. Selection, activation, promotion and release
//! remain outside this component.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
#[cfg(test)]
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::ArtifactEvent;
use crate::ArtifactManifest;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationTransactionSnapshotV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::ArtifactRegistryError;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryAppendReceipt;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistryHeadWitnessV1;
use crate::RegistrySnapshotReceipt;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::read_candidate_payload;
use crate::read_registry_head_witness;
use crate::read_registry_snapshot;
use crate::storage::encode_head_witness;
use crate::storage::encode_snapshot;
use crate::validate_registry_head_witness;
use crate::write_candidate_payload_beneath;
use crate::write_registry_head_witness_beneath;
use crate::write_registry_snapshot_beneath;

#[path = "owner_manifest.rs"]
mod manifest;
#[path = "owner_record_io.rs"]
mod record_io;
#[path = "owner_registry_transition.rs"]
mod registry_transition;
#[path = "owner_selected_descriptor.rs"]
mod selected_descriptor;
use record_io::sync_owner_directory;
use record_io::write_bounded_create_only_or_exact;
use record_io::write_create_only_or_exact;

const MAX_TRUSTED_SIGNERS: usize = 32;
const MAX_HEAD_RECORDS: usize = 4_096;
const MAX_SMALL_RECORD_BYTES: usize = 16 * 1024;
const CHECKPOINT_MAGIC: &str = "HEPTA-ARTIFACT-CHECKPOINT-V1";
const CURRENT_HEAD_MAGIC: &str = "HEPTA-ARTIFACT-CURRENT-HEAD-V1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedArtifactSignerV1 {
    pub signer_id: StableId,
    pub verifying_key: [u8; 32],
    pub minimum_authority_epoch: u64,
    pub maximum_authority_epoch: u64,
    pub valid_from: u64,
    pub expires_at: u64,
    pub revoked_at: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerTrustV1 {
    pub registry_id: StableId,
    pub withdrawal_scope_digest: Digest32,
    pub minimum_registry_generation: Generation,
    pub genesis_predecessor_head_digest: Digest32,
    pub minimum_authority_epoch: u64,
    pub writer_signers: Vec<TrustedArtifactSignerV1>,
    pub head_signers: Vec<TrustedArtifactSignerV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedArtifactWriterLeaseV1 {
    pub lease_id: StableId,
    pub producer_id: StableId,
    pub registry_id: StableId,
    pub withdrawal_scope_digest: Digest32,
    pub signer_id: StableId,
    pub signing_key_digest: Digest32,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: [u8; 64],
}

impl SignedArtifactWriterLeaseV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.writer-lease.v1".to_vec();
        push_id(&mut bytes, &self.lease_id);
        push_id(&mut bytes, &self.producer_id);
        push_id(&mut bytes, &self.registry_id);
        bytes.extend_from_slice(self.withdrawal_scope_digest.as_array());
        push_id(&mut bytes, &self.signer_id);
        bytes.extend_from_slice(self.signing_key_digest.as_array());
        for value in [
            self.authority_epoch,
            self.lease_generation,
            self.issued_at,
            self.expires_at,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCurrentArtifactHeadV1 {
    pub withdrawal_scope_digest: Digest32,
    pub binding: Digest32,
    pub witness: RegistryHeadWitnessV1,
    pub signature: [u8; 64],
}

impl SignedCurrentArtifactHeadV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.current-head.v1".to_vec();
        bytes.extend_from_slice(self.withdrawal_scope_digest.as_array());
        bytes.extend_from_slice(self.binding.as_array());
        push_id(&mut bytes, &self.witness.registry_id);
        bytes.extend_from_slice(&self.witness.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.witness.head_digest.as_array());
        bytes.extend_from_slice(self.witness.predecessor_head_digest.as_array());
        bytes.extend_from_slice(&self.witness.authority_epoch.to_be_bytes());
        push_id(&mut bytes, &self.witness.signer_id);
        bytes.extend_from_slice(self.witness.signing_key_digest.as_array());
        bytes.extend_from_slice(&self.witness.issued_at.to_be_bytes());
        bytes.extend_from_slice(&self.witness.expires_at.to_be_bytes());
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedCurrentArtifactHeadV1 {
    pub signed: SignedCurrentArtifactHeadV1,
    pub witness_digest: Digest32,
    pub trust_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerPublicationCheckpointV1 {
    pub operation_id: StableId,
    pub phase: ArtifactPublicationPhaseV1,
    pub intent_digest: Digest32,
    pub admission_digest: Digest32,
    pub withdrawal_scope_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub expected_registry_predecessor_head: Digest32,
    pub state_digest: Digest32,
    pub original_writer_lease_digest: Digest32,
    pub registry_receipt: Option<RegistrySnapshotReceipt>,
    pub witness_receipt: Option<RegistryHeadWitnessReceipt>,
    pub acknowledged_at: Option<u64>,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerRecoveryV1 {
    pub checkpoint: ArtifactOwnerPublicationCheckpointV1,
    pub requires_exact_snapshot: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug)]
struct VerifiedArtifactWriterLeaseV1 {
    producer_id: StableId,
    lease_digest: Digest32,
}

#[derive(Clone, Debug)]
pub struct ArtifactOwnerVerifierV1 {
    trust: ArtifactOwnerTrustV1,
    trust_digest: Digest32,
    writer_signers: BTreeMap<StableId, TrustedArtifactSignerV1>,
    head_signers: BTreeMap<StableId, TrustedArtifactSignerV1>,
}

impl ArtifactOwnerVerifierV1 {
    pub fn new(mut trust: ArtifactOwnerTrustV1) -> Result<Self, ArtifactOwnerHostError> {
        if trust.withdrawal_scope_digest.is_zero()
            || trust.minimum_authority_epoch == 0
            || trust.writer_signers.is_empty()
            || trust.writer_signers.len() > MAX_TRUSTED_SIGNERS
            || trust.head_signers.is_empty()
            || trust.head_signers.len() > MAX_TRUSTED_SIGNERS
        {
            return Err(ArtifactOwnerHostError::InvalidTrust);
        }
        trust
            .writer_signers
            .sort_by(|left, right| left.signer_id.cmp(&right.signer_id));
        trust
            .head_signers
            .sort_by(|left, right| left.signer_id.cmp(&right.signer_id));
        let writer_signers = validate_signers(&trust.writer_signers)?;
        let head_signers = validate_signers(&trust.head_signers)?;

        let mut bytes = b"hepta.learning-artifacts.owner-trust.v1".to_vec();
        push_id(&mut bytes, &trust.registry_id);
        bytes.extend_from_slice(trust.withdrawal_scope_digest.as_array());
        bytes.extend_from_slice(&trust.minimum_registry_generation.get().to_be_bytes());
        bytes.extend_from_slice(trust.genesis_predecessor_head_digest.as_array());
        bytes.extend_from_slice(&trust.minimum_authority_epoch.to_be_bytes());
        digest_signer_set(&mut bytes, &trust.writer_signers);
        digest_signer_set(&mut bytes, &trust.head_signers);
        Ok(Self {
            trust,
            trust_digest: Digest32::of_bytes(&bytes),
            writer_signers,
            head_signers,
        })
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    /// Authenticate one CURRENT head and the exact immutable registry snapshot
    /// backing it. The returned view is opaque outside this crate and is the
    /// only public input accepted by final-use candidate revalidation.
    pub fn verify_current_registry_view(
        &self,
        snapshot_file: File,
        snapshot_receipt: RegistrySnapshotReceipt,
        signed_head: &SignedCurrentArtifactHeadV1,
        requirement: &RegistryHeadRequirementV1,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let verified = self.verify_signed_head(signed_head, requirement, true)?;
        if snapshot_receipt.binding != signed_head.binding
            || snapshot_receipt.head_digest != signed_head.witness.head_digest
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let registry = read_registry_snapshot(snapshot_file, snapshot_receipt)?;
        if registry.snapshot().head_digest != signed_head.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(VerifiedCurrentRegistryViewV1::new(
            snapshot_receipt,
            registry,
            verified.witness_digest,
            verified.trust_digest,
        ))
    }

    fn verify_writer_lease(
        &self,
        lease: &SignedArtifactWriterLeaseV1,
        now: u64,
    ) -> Result<VerifiedArtifactWriterLeaseV1, ArtifactOwnerHostError> {
        if lease.registry_id != self.trust.registry_id
            || lease.withdrawal_scope_digest != self.trust.withdrawal_scope_digest
            || lease.authority_epoch < self.trust.minimum_authority_epoch
            || lease.authority_epoch == 0
            || lease.lease_generation == 0
            || lease.issued_at > now
            || now > lease.expires_at
            || lease.issued_at > lease.expires_at
        {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        let signer = self
            .writer_signers
            .get(&lease.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        verify_signer_context(
            signer,
            lease.signing_key_digest,
            lease.authority_epoch,
            lease.issued_at,
            now,
            true,
        )?;
        verify_signature(
            &signer.verifying_key,
            &lease.signing_bytes(),
            &lease.signature,
        )?;
        let mut digest_bytes = lease.signing_bytes();
        digest_bytes.extend_from_slice(&lease.signature);
        Ok(VerifiedArtifactWriterLeaseV1 {
            producer_id: lease.producer_id.clone(),
            lease_digest: Digest32::of_bytes(&digest_bytes),
        })
    }

    fn verify_signed_head(
        &self,
        signed: &SignedCurrentArtifactHeadV1,
        requirement: &RegistryHeadRequirementV1,
        require_current_signer: bool,
    ) -> Result<VerifiedCurrentArtifactHeadV1, ArtifactOwnerHostError> {
        if signed.withdrawal_scope_digest != self.trust.withdrawal_scope_digest
            || signed.binding.is_zero()
        {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let signer = self
            .head_signers
            .get(&signed.witness.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        verify_signer_context(
            signer,
            signed.witness.signing_key_digest,
            signed.witness.authority_epoch,
            signed.witness.issued_at,
            requirement.now,
            require_current_signer,
        )?;
        verify_signature(
            &signer.verifying_key,
            &signed.signing_bytes(),
            &signed.signature,
        )?;
        let receipt = validate_registry_head_witness(&signed.witness, requirement)
            .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?;
        Ok(VerifiedCurrentArtifactHeadV1 {
            signed: signed.clone(),
            witness_digest: receipt.witness_digest,
            trust_digest: self.trust_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

/// The one named local product writer for learning artifacts.
///
/// Construction acquires an exclusive OS file lock. The lock, trust snapshot
/// and signed lease stay immutable for the host lifetime. A new lease or trust
/// generation requires constructing a new host.
pub struct LearningArtifactOwnerHost {
    root: PathBuf,
    writer_fence: File,
    verifier: ArtifactOwnerVerifierV1,
    lease: SignedArtifactWriterLeaseV1,
    verified_lease: VerifiedArtifactWriterLeaseV1,
    required_current_head: Option<SignedCurrentArtifactHeadV1>,
}

impl fmt::Debug for LearningArtifactOwnerHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactOwnerHost")
            .field("root", &self.root)
            .field("trust_digest", &self.verifier.trust_digest())
            .field("producer_id", &self.verified_lease.producer_id)
            .finish()
    }
}

impl Drop for LearningArtifactOwnerHost {
    fn drop(&mut self) {
        let _ = self.writer_fence.unlock();
    }
}

impl LearningArtifactOwnerHost {
    pub fn open(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        lease: SignedArtifactWriterLeaseV1,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        Self::open_internal(root, trust, lease, None, now)
    }

    /// Open with an independently retained signed current-head floor.
    ///
    /// This is the production restart path after a current head has ever been
    /// published. Restoring an older local backup that does not contain and
    /// extend this anchor fails closed even when the restored directory is
    /// internally self-consistent.
    pub fn open_with_required_current_head(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        lease: SignedArtifactWriterLeaseV1,
        required_current_head: SignedCurrentArtifactHeadV1,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let host = Self::open_internal(root, trust, lease, Some(required_current_head), now)?;
        host.discover_current_head(now)?;
        Ok(host)
    }

    fn open_internal(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        lease: SignedArtifactWriterLeaseV1,
        required_current_head: Option<SignedCurrentArtifactHeadV1>,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        fs::create_dir_all(root.as_ref())?;
        let root = fs::canonicalize(root)?;
        for directory in [
            "writer",
            "transactions",
            "payloads",
            "registries",
            "witnesses",
            "heads",
        ] {
            ensure_real_directory(&root, directory)?;
        }
        let verifier = ArtifactOwnerVerifierV1::new(trust)?;
        let verified_lease = verifier.verify_writer_lease(&lease, now)?;
        let fence_path = root.join("writer").join("owner.lock");
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true);
        #[cfg(unix)]
        options.mode(0o600);
        let writer_fence = options.open(fence_path)?;
        match writer_fence.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(ArtifactOwnerHostError::WriterFenceBusy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }
        Ok(Self {
            root,
            writer_fence,
            verifier,
            lease,
            verified_lease,
            required_current_head,
        })
    }

    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.verified_lease.producer_id
    }

    #[must_use]
    pub const fn writer_lease_digest(&self) -> Digest32 {
        self.verified_lease.lease_digest
    }

    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.verifier.trust_digest()
    }

    fn require_current_writer(
        &self,
        now: u64,
    ) -> Result<VerifiedArtifactWriterLeaseV1, ArtifactOwnerHostError> {
        self.verifier.verify_writer_lease(&self.lease, now)
    }

    pub fn begin_publication(
        &self,
        operation_id: StableId,
        admission: WithdrawalBoundArtifactAdmissionV3,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        registry: &ArtifactRegistry,
        expected_registry_predecessor_head: Digest32,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError> {
        let writer = self.require_current_writer(now)?;
        if admission.validated_manifest.manifest.producer_id != writer.producer_id
            || admission.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest
            || withdrawal_registry.scope_digest()
                != Some(self.verifier.trust.withdrawal_scope_digest)
        {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        let transaction = ArtifactPublicationTransactionV1::begin(
            operation_id,
            admission,
            withdrawal_registry,
            registry,
            expected_registry_predecessor_head,
            now,
        )?;
        self.persist_publication_manifest(&transaction)?;
        self.persist_checkpoint(&transaction)?;
        Ok(transaction)
    }

    /// Append the compatibility registration under the owner fence. The full
    /// V2/V3 admission remains authoritative in the publication transaction.
    pub fn stage_compatibility_registration(
        &self,
        transaction: &ArtifactPublicationTransactionV1,
        registry: &mut ArtifactRegistry,
        now: u64,
    ) -> Result<RegistryAppendReceipt, ArtifactOwnerHostError> {
        let writer = self.require_current_writer(now)?;
        let admission = &transaction.intent().admission;
        let v2 = &admission.validated_manifest.manifest;
        if v2.producer_id != writer.producer_id {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        if registry.snapshot().head_digest
            != transaction.intent().expected_registry_predecessor_head
        {
            return Err(ArtifactOwnerHostError::RegistryPredecessorMismatch);
        }
        let event_id = StableId::new(format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        ))
        .map_err(|_| ArtifactOwnerHostError::InternalInvariant)?;
        let predecessor_id = if v2.predecessor_ids.len() == 1 {
            v2.predecessor_ids.first().cloned()
        } else {
            None
        };
        Ok(registry.append(ArtifactEvent::Register {
            event_id,
            manifest: ArtifactManifest {
                artifact_id: v2.artifact_id.clone(),
                kind: v2.kind,
                generation: v2.generation,
                predecessor_id,
                content_digest: v2.bytes_digest,
                objective_digest: v2.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: v2.producer_id.clone(),
                compatibility_digest: v2.compatibility_digest,
                encoded_size_bytes: v2.encoded_size_bytes,
            },
        })?)
    }

    /// Persist or reconcile immutable payload bytes, then checkpoint the
    /// PayloadDurable phase. Existing bytes are accepted only after full
    /// registry-bound digest and length validation.
    pub fn ensure_payload_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        staged_registry: &ArtifactRegistry,
        bytes: &[u8],
        now: u64,
    ) -> Result<PathBuf, ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        let manifest = &transaction.intent().admission.validated_manifest.manifest;
        let relative = PathBuf::from("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.bytes_digest
        ));
        match write_candidate_payload_beneath(
            &self.root,
            &relative,
            staged_registry,
            &manifest.artifact_id,
            bytes,
        ) {
            Ok(digest) => {
                transaction.record_payload_durable(digest, bytes.len() as u64)?;
            }
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                let loaded = read_candidate_payload(
                    File::open(self.root.join(&relative))?,
                    staged_registry,
                    &manifest.artifact_id,
                )?;
                transaction
                    .record_payload_durable(Digest32::of_bytes(&loaded), loaded.len() as u64)?;
            }
            Err(error) => return Err(error.into()),
        }
        sync_owner_directory(&self.root.join("payloads"))?;
        self.persist_checkpoint(transaction)?;
        Ok(relative)
    }

    pub fn ensure_registry_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        registry: &ArtifactRegistry,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        binding: Digest32,
        now: u64,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        let encoded = encode_snapshot(registry, binding)?;
        let expected = RegistrySnapshotReceipt {
            binding,
            head_digest: registry.snapshot().head_digest,
            file_digest: Digest32::of_bytes(&encoded),
            records: registry.records().len(),
            encoded_bytes: encoded.len(),
        };
        let relative = PathBuf::from("registries").join(format!(
            "{}-{}.snapshot",
            expected.head_digest, expected.file_digest
        ));
        let receipt =
            match write_registry_snapshot_beneath(&self.root, &relative, registry, binding) {
                Ok(receipt) => receipt,
                Err(crate::ArtifactStorageError::AlreadyExists) => {
                    let reopened =
                        read_registry_snapshot(File::open(self.root.join(&relative))?, expected)?;
                    if reopened.snapshot().head_digest != expected.head_digest {
                        return Err(ArtifactOwnerHostError::CheckpointMismatch);
                    }
                    expected
                }
                Err(error) => return Err(error.into()),
            };
        sync_owner_directory(&self.root.join("registries"))?;
        transaction.record_registry_durable(registry, receipt, withdrawal_registry, now)?;
        self.persist_checkpoint(transaction)?;
        Ok(receipt)
    }

    /// Publish an authenticated immutable head record and the canonical witness
    /// file, then checkpoint WitnessDurable. A crash after head creation but
    /// before the checkpoint is reconciled by exact existing-file validation.
    pub fn ensure_witness_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        signed: &SignedCurrentArtifactHeadV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<RegistryHeadWitnessReceipt, ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        let current = self.discover_current_head(now)?;
        let expected_predecessor = transaction.intent().expected_registry_predecessor_head;
        let requirement = match current.as_ref() {
            Some(current) if current.signed.witness.head_digest == signed.witness.head_digest => {
                RegistryHeadRequirementV1 {
                    registry_id: self.verifier.trust.registry_id.clone(),
                    minimum_generation: signed.witness.generation,
                    expected_predecessor_head_digest: expected_predecessor,
                    minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
                    now,
                }
            }
            Some(current) if current.signed.witness.head_digest == expected_predecessor => {
                RegistryHeadRequirementV1 {
                    registry_id: self.verifier.trust.registry_id.clone(),
                    minimum_generation: current
                        .signed
                        .witness
                        .generation
                        .next()
                        .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?,
                    expected_predecessor_head_digest: expected_predecessor,
                    minimum_authority_epoch: current.signed.witness.authority_epoch,
                    now,
                }
            }
            None if expected_predecessor == self.verifier.trust.genesis_predecessor_head_digest => {
                RegistryHeadRequirementV1 {
                    registry_id: self.verifier.trust.registry_id.clone(),
                    minimum_generation: self.verifier.trust.minimum_registry_generation,
                    expected_predecessor_head_digest: expected_predecessor,
                    minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
                    now,
                }
            }
            Some(_) | None => return Err(ArtifactOwnerHostError::CurrentHeadConflict),
        };
        let verified = self
            .verifier
            .verify_signed_head(signed, &requirement, true)?;
        let encoded = encode_head_witness(&signed.witness, signed.binding)?;
        let expected_receipt = RegistryHeadWitnessReceipt {
            binding: signed.binding,
            witness_digest: verified.witness_digest,
            file_digest: Digest32::of_bytes(&encoded),
            encoded_bytes: encoded.len(),
        };
        let relative = PathBuf::from("witnesses").join(format!(
            "{}-{}.witness",
            signed.witness.generation.get(),
            verified.witness_digest
        ));
        let receipt = match write_registry_head_witness_beneath(
            &self.root,
            &relative,
            &signed.witness,
            &requirement,
            signed.binding,
        ) {
            Ok(receipt) => receipt,
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                let reopened = read_registry_head_witness(
                    File::open(self.root.join(&relative))?,
                    expected_receipt,
                    &requirement,
                )?;
                if reopened != signed.witness {
                    return Err(ArtifactOwnerHostError::CurrentHeadConflict);
                }
                expected_receipt
            }
            Err(error) => return Err(error.into()),
        };
        sync_owner_directory(&self.root.join("witnesses"))?;
        self.persist_signed_head_record(signed)?;
        let discovered = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadConflict)?;
        if discovered.signed != *signed {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        transaction.record_witness_durable(
            &signed.witness,
            &requirement,
            receipt,
            withdrawal_registry,
            now,
        )?;
        self.persist_checkpoint(transaction)?;
        Ok(receipt)
    }

    pub fn acknowledge(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<crate::ArtifactPublicationReceiptV1, ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        let current = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadConflict)?;
        let status = transaction.status();
        if status.registry_head_digest != Some(current.signed.witness.head_digest)
            || status.witness_digest != Some(current.witness_digest)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let receipt = transaction.acknowledge(withdrawal_registry, now)?;
        self.persist_checkpoint(transaction)?;
        Ok(receipt)
    }

    /// Recover an exact durable registry snapshot by its chain head.
    ///
    /// The genesis predecessor resolves to an empty registry. Non-genesis heads
    /// must be bound by at least one RegistryDurable-or-later transaction
    /// checkpoint, and every matching checkpoint must name the same receipt.
    pub fn recover_registry_by_head(
        &self,
        head_digest: Digest32,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        if head_digest == self.verifier.trust.genesis_predecessor_head_digest {
            return Ok(ArtifactRegistry::new());
        }
        if let Some((_, registry)) = self.transition_registry(head_digest)? {
            return Ok(registry);
        }
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
            let Some(receipt) = checkpoint.registry_receipt else {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            };
            if receipt.head_digest != head_digest {
                continue;
            }
            match matched {
                Some(existing) if existing != receipt => {
                    return Err(ArtifactOwnerHostError::IdentityConflict);
                }
                Some(_) => {}
                None => matched = Some(receipt),
            }
        }
        let receipt = matched.ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        let path = self.root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        ));
        Ok(read_registry_snapshot(File::open(path)?, receipt)?)
    }

    /// Recover the artifact registry that exactly backs the authenticated
    /// current head. A current-head side effect may have crossed the boundary
    /// before the transaction advanced from RegistryDurable; that uncertainty
    /// is recoverable but must block unrelated publication until reconciled.
    fn current_registry_receipt(
        &self,
        current: &VerifiedCurrentArtifactHeadV1,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        if let Some(receipt) = self.current_transition_receipt(current)? {
            return Ok(receipt);
        }
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

    /// Return the authenticated exact registry view backing the newest signed
    /// CURRENT head discovered by this owner. The opaque result cannot be
    /// fabricated from a bare file and receipt by a product consumer.
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let current = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let receipt = self.current_registry_receipt(&current)?;
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

    pub fn recover_current_registry(
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

    /// Return the latest non-terminal transaction checkpoints. Product service
    /// composition uses this as a startup fence: unrelated writes may not start
    /// while a prior operation still requires reconciliation.
    pub fn recovery_required_operations(
        &self,
    ) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
        let mut latest: BTreeMap<StableId, ArtifactOwnerPublicationCheckpointV1> = BTreeMap::new();
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
            match latest.get(&checkpoint.operation_id) {
                Some(existing) if phase_code(existing.phase) >= phase_code(checkpoint.phase) => {}
                Some(_) | None => {
                    latest.insert(checkpoint.operation_id.clone(), checkpoint);
                }
            }
        }
        Ok(latest
            .into_values()
            .filter(|checkpoint| checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged)
            .collect())
    }

    pub fn recover_publication(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<ArtifactOwnerRecoveryV1>, ArtifactOwnerHostError> {
        let mut latest = None;
        let mut missing_seen = false;
        let mut invariant: Option<(Digest32, Digest32, Digest32, Digest32)> = None;
        for phase in ordered_phases() {
            let path = self.checkpoint_path(operation_id, phase);
            if !path.exists() {
                missing_seen = true;
                continue;
            }
            if missing_seen {
                return Err(ArtifactOwnerHostError::CheckpointGap);
            }
            let bytes = read_small_record(&path, MAX_SMALL_RECORD_BYTES)?;
            let checkpoint = decode_checkpoint(&bytes)?;
            if checkpoint.operation_id != *operation_id || checkpoint.phase != phase {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            let key = (
                checkpoint.intent_digest,
                checkpoint.admission_digest,
                checkpoint.withdrawal_scope_digest,
                checkpoint.expected_registry_predecessor_head,
            );
            if invariant.is_some_and(|value| value != key) {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            invariant = Some(key);
            latest = Some(checkpoint);
        }
        Ok(latest.map(|checkpoint| ArtifactOwnerRecoveryV1 {
            requires_exact_snapshot: checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged,
            checkpoint,
            authority: AuthorityPosture::DENY_ALL,
        }))
    }

    /// Resume only when the caller can reproduce the exact digest-bound
    /// transaction snapshot matching the durable host checkpoint.
    pub fn resume_publication(
        &self,
        snapshot: ArtifactPublicationTransactionSnapshotV1,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        let recovery = self
            .recover_publication(&snapshot.intent.operation_id)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        let expected =
            checkpoint_from_snapshot(&snapshot, recovery.checkpoint.original_writer_lease_digest);
        if expected != recovery.checkpoint {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let transaction = ArtifactPublicationTransactionV1::from_snapshot(snapshot)?;
        self.persist_publication_manifest(&transaction)?;
        Ok(transaction)
    }

    pub fn discover_current_head(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError> {
        let latest = self.discover_current_head_unanchored(now)?;
        if let Some(anchor) = &self.required_current_head {
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
            let verified =
                self.verifier
                    .verify_signed_head(&candidate, &historical_requirement, false)?;
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
            true,
        )?;
        if now > latest.signed.witness.expires_at {
            return Err(ArtifactOwnerHostError::CurrentHeadExpired);
        }
        Ok(Some(latest))
    }

    fn persist_checkpoint(
        &self,
        transaction: &ArtifactPublicationTransactionV1,
    ) -> Result<(), ArtifactOwnerHostError> {
        let checkpoint =
            checkpoint_from_snapshot(&transaction.snapshot(), self.verified_lease.lease_digest);
        let bytes = encode_checkpoint(&checkpoint);
        write_create_only_or_exact(
            &self.checkpoint_path(&checkpoint.operation_id, checkpoint.phase),
            &bytes,
        )
    }

    fn checkpoint_path(
        &self,
        operation_id: &StableId,
        phase: ArtifactPublicationPhaseV1,
    ) -> PathBuf {
        let operation_digest = Digest32::of_bytes(operation_id.as_str().as_bytes());
        self.root.join("transactions").join(format!(
            "{}-{}.checkpoint",
            operation_digest,
            phase_code(phase)
        ))
    }

    fn persist_signed_head_record(
        &self,
        signed: &SignedCurrentArtifactHeadV1,
    ) -> Result<(), ArtifactOwnerHostError> {
        write_create_only_or_exact(
            &self.signed_head_record_path(signed),
            &encode_signed_head(signed),
        )
    }

    fn signed_head_record_path(&self, signed: &SignedCurrentArtifactHeadV1) -> PathBuf {
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
        self.verifier
            .verify_signed_head(anchor, &requirement, false)?;
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

fn checkpoint_from_snapshot(
    snapshot: &ArtifactPublicationTransactionSnapshotV1,
    original_writer_lease_digest: Digest32,
) -> ArtifactOwnerPublicationCheckpointV1 {
    ArtifactOwnerPublicationCheckpointV1 {
        operation_id: snapshot.intent.operation_id.clone(),
        phase: snapshot.phase,
        intent_digest: snapshot.intent.intent_digest,
        admission_digest: snapshot.intent.admission.admission_digest,
        withdrawal_scope_digest: snapshot.intent.admission.withdrawal_scope_digest,
        withdrawal_head_digest: snapshot.intent.admission.withdrawal_head_digest,
        expected_registry_predecessor_head: snapshot.intent.expected_registry_predecessor_head,
        state_digest: snapshot.state_digest,
        original_writer_lease_digest,
        registry_receipt: snapshot.registry_receipt,
        witness_receipt: snapshot.witness_receipt,
        acknowledged_at: snapshot.acknowledged_at,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn ordered_phases() -> [ArtifactPublicationPhaseV1; 5] {
    [
        ArtifactPublicationPhaseV1::Prepared,
        ArtifactPublicationPhaseV1::PayloadDurable,
        ArtifactPublicationPhaseV1::RegistryDurable,
        ArtifactPublicationPhaseV1::WitnessDurable,
        ArtifactPublicationPhaseV1::Acknowledged,
    ]
}

const fn phase_code(phase: ArtifactPublicationPhaseV1) -> u8 {
    match phase {
        ArtifactPublicationPhaseV1::Prepared => 0,
        ArtifactPublicationPhaseV1::PayloadDurable => 1,
        ArtifactPublicationPhaseV1::RegistryDurable => 2,
        ArtifactPublicationPhaseV1::WitnessDurable => 3,
        ArtifactPublicationPhaseV1::Acknowledged => 4,
    }
}

fn phase_from_code(value: &str) -> Result<ArtifactPublicationPhaseV1, ArtifactOwnerHostError> {
    match value {
        "0" => Ok(ArtifactPublicationPhaseV1::Prepared),
        "1" => Ok(ArtifactPublicationPhaseV1::PayloadDurable),
        "2" => Ok(ArtifactPublicationPhaseV1::RegistryDurable),
        "3" => Ok(ArtifactPublicationPhaseV1::WitnessDurable),
        "4" => Ok(ArtifactPublicationPhaseV1::Acknowledged),
        _ => Err(ArtifactOwnerHostError::CheckpointMismatch),
    }
}

fn encode_checkpoint(value: &ArtifactOwnerPublicationCheckpointV1) -> Vec<u8> {
    let registry = value.registry_receipt.map_or_else(
        || "-".to_owned(),
        |receipt| {
            format!(
                "{},{},{},{},{}",
                receipt.binding,
                receipt.head_digest,
                receipt.file_digest,
                receipt.records,
                receipt.encoded_bytes
            )
        },
    );
    let witness = value.witness_receipt.map_or_else(
        || "-".to_owned(),
        |receipt| {
            format!(
                "{},{},{},{}",
                receipt.binding, receipt.witness_digest, receipt.file_digest, receipt.encoded_bytes
            )
        },
    );
    format!(
        "{CHECKPOINT_MAGIC}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{registry}\n{witness}\n{}\n",
        value.operation_id,
        phase_code(value.phase),
        value.intent_digest,
        value.admission_digest,
        value.withdrawal_scope_digest,
        value.withdrawal_head_digest,
        value.expected_registry_predecessor_head,
        value.state_digest,
        value.original_writer_lease_digest,
        value
            .acknowledged_at
            .map_or_else(|| "-".to_owned(), |at| at.to_string()),
    )
    .into_bytes()
}

fn decode_checkpoint(
    bytes: &[u8],
) -> Result<ArtifactOwnerPublicationCheckpointV1, ArtifactOwnerHostError> {
    let text =
        std::str::from_utf8(bytes).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
    let fields = text.lines().collect::<Vec<_>>();
    if fields.len() != 13 || fields[0] != CHECKPOINT_MAGIC {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(ArtifactOwnerPublicationCheckpointV1 {
        operation_id: StableId::new(fields[1].to_owned())
            .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
        phase: phase_from_code(fields[2])?,
        intent_digest: parse_digest(fields[3])?,
        admission_digest: parse_digest(fields[4])?,
        withdrawal_scope_digest: parse_digest(fields[5])?,
        withdrawal_head_digest: parse_digest(fields[6])?,
        expected_registry_predecessor_head: parse_digest(fields[7])?,
        state_digest: parse_digest(fields[8])?,
        original_writer_lease_digest: parse_digest(fields[9])?,
        registry_receipt: parse_registry_receipt(fields[10])?,
        witness_receipt: parse_witness_receipt(fields[11])?,
        acknowledged_at: parse_optional_u64(fields[12])?,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn parse_registry_receipt(
    value: &str,
) -> Result<Option<RegistrySnapshotReceipt>, ArtifactOwnerHostError> {
    if value == "-" {
        return Ok(None);
    }
    let fields = value.split(',').collect::<Vec<_>>();
    if fields.len() != 5 {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(Some(RegistrySnapshotReceipt {
        binding: parse_digest(fields[0])?,
        head_digest: parse_digest(fields[1])?,
        file_digest: parse_digest(fields[2])?,
        records: parse_usize(fields[3])?,
        encoded_bytes: parse_usize(fields[4])?,
    }))
}

fn parse_witness_receipt(
    value: &str,
) -> Result<Option<RegistryHeadWitnessReceipt>, ArtifactOwnerHostError> {
    if value == "-" {
        return Ok(None);
    }
    let fields = value.split(',').collect::<Vec<_>>();
    if fields.len() != 4 {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(Some(RegistryHeadWitnessReceipt {
        binding: parse_digest(fields[0])?,
        witness_digest: parse_digest(fields[1])?,
        file_digest: parse_digest(fields[2])?,
        encoded_bytes: parse_usize(fields[3])?,
    }))
}

fn encode_signed_head(value: &SignedCurrentArtifactHeadV1) -> Vec<u8> {
    format!(
        "{CURRENT_HEAD_MAGIC}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n",
        value.withdrawal_scope_digest,
        value.binding,
        value.witness.registry_id,
        value.witness.generation.get(),
        value.witness.head_digest,
        value.witness.predecessor_head_digest,
        value.witness.authority_epoch,
        value.witness.signer_id,
        value.witness.signing_key_digest,
        value.witness.issued_at,
        value.witness.expires_at,
        encode_hex(&value.signature),
    )
    .into_bytes()
}

fn decode_signed_head(bytes: &[u8]) -> Result<SignedCurrentArtifactHeadV1, ArtifactOwnerHostError> {
    let text =
        std::str::from_utf8(bytes).map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?;
    let fields = text.lines().collect::<Vec<_>>();
    if fields.len() != 13 || fields[0] != CURRENT_HEAD_MAGIC {
        return Err(ArtifactOwnerHostError::CurrentHeadContext);
    }
    Ok(SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: parse_digest(fields[1])?,
        binding: parse_digest(fields[2])?,
        witness: RegistryHeadWitnessV1 {
            registry_id: StableId::new(fields[3].to_owned())
                .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?,
            generation: Generation::new(parse_u64(fields[4])?)
                .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?,
            head_digest: parse_digest(fields[5])?,
            predecessor_head_digest: parse_digest(fields[6])?,
            authority_epoch: parse_u64(fields[7])?,
            signer_id: StableId::new(fields[8].to_owned())
                .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?,
            signing_key_digest: parse_digest(fields[9])?,
            issued_at: parse_u64(fields[10])?,
            expires_at: parse_u64(fields[11])?,
        },
        signature: decode_signature(fields[12])?,
    })
}

fn validate_signers(
    signers: &[TrustedArtifactSignerV1],
) -> Result<BTreeMap<StableId, TrustedArtifactSignerV1>, ArtifactOwnerHostError> {
    let mut result = BTreeMap::new();
    for signer in signers {
        if signer.minimum_authority_epoch == 0
            || signer.maximum_authority_epoch < signer.minimum_authority_epoch
            || signer.valid_from > signer.expires_at
        {
            return Err(ArtifactOwnerHostError::InvalidTrust);
        }
        let key = VerifyingKey::from_bytes(&signer.verifying_key)
            .map_err(|_| ArtifactOwnerHostError::InvalidKey)?;
        if key.is_weak() {
            return Err(ArtifactOwnerHostError::InvalidKey);
        }
        if result
            .insert(signer.signer_id.clone(), signer.clone())
            .is_some()
        {
            return Err(ArtifactOwnerHostError::InvalidTrust);
        }
    }
    Ok(result)
}

fn verify_signer_context(
    signer: &TrustedArtifactSignerV1,
    signing_key_digest: Digest32,
    authority_epoch: u64,
    issued_at: u64,
    now: u64,
    require_current: bool,
) -> Result<(), ArtifactOwnerHostError> {
    if signing_key_digest != Digest32::of_bytes(&signer.verifying_key)
        || authority_epoch < signer.minimum_authority_epoch
        || authority_epoch > signer.maximum_authority_epoch
        || issued_at < signer.valid_from
        || issued_at > signer.expires_at
        || now < issued_at
    {
        return Err(ArtifactOwnerHostError::SignerContext);
    }
    if signer.revoked_at.is_some_and(|at| issued_at >= at)
        || (require_current && signer.revoked_at.is_some_and(|at| now >= at))
        || (require_current && now > signer.expires_at)
    {
        return Err(ArtifactOwnerHostError::SignerRevoked);
    }
    Ok(())
}

fn verify_signature(
    verifying_key: &[u8; 32],
    message: &[u8],
    signature: &[u8; 64],
) -> Result<(), ArtifactOwnerHostError> {
    VerifyingKey::from_bytes(verifying_key)
        .map_err(|_| ArtifactOwnerHostError::InvalidKey)?
        .verify_strict(message, &Signature::from_bytes(signature))
        .map_err(|_| ArtifactOwnerHostError::InvalidSignature)
}

fn digest_signer_set(bytes: &mut Vec<u8>, signers: &[TrustedArtifactSignerV1]) {
    bytes.extend_from_slice(&(signers.len() as u64).to_be_bytes());
    for signer in signers {
        push_id(bytes, &signer.signer_id);
        bytes.extend_from_slice(&signer.verifying_key);
        bytes.extend_from_slice(&signer.minimum_authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&signer.maximum_authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&signer.valid_from.to_be_bytes());
        bytes.extend_from_slice(&signer.expires_at.to_be_bytes());
        match signer.revoked_at {
            Some(at) => {
                bytes.push(1);
                bytes.extend_from_slice(&at.to_be_bytes());
            }
            None => bytes.push(0),
        }
    }
}

fn ensure_real_directory(root: &Path, name: &str) -> Result<(), ArtifactOwnerHostError> {
    let path = root.join(name);
    match fs::symlink_metadata(&path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(ArtifactOwnerHostError::PathBoundary);
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            fs::create_dir(&path)?;
        }
        Err(error) => return Err(error.into()),
    }
    Ok(())
}

fn read_small_record(path: &Path, limit: usize) -> Result<Vec<u8>, ArtifactOwnerHostError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > limit as u64 {
        return Err(ArtifactOwnerHostError::Capacity);
    }
    let mut file = File::open(path)?;
    match file.try_lock_shared() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => return Err(ArtifactOwnerHostError::WriterFenceBusy),
        Err(TryLockError::Error(error)) => return Err(error.into()),
    }
    let mut bytes = Vec::new();
    (&mut file).take(limit as u64 + 1).read_to_end(&mut bytes)?;
    let _ = file.unlock();
    if bytes.len() > limit {
        return Err(ArtifactOwnerHostError::Capacity);
    }
    Ok(bytes)
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactOwnerHostError> {
    Digest32::from_str(value).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactOwnerHostError> {
    value
        .parse::<u64>()
        .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)
}

fn parse_usize(value: &str) -> Result<usize, ArtifactOwnerHostError> {
    value
        .parse::<usize>()
        .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)
}

fn parse_optional_u64(value: &str) -> Result<Option<u64>, ArtifactOwnerHostError> {
    if value == "-" {
        Ok(None)
    } else {
        parse_u64(value).map(Some)
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    let mut value = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(&mut value, "{byte:02x}");
    }
    value
}

fn decode_signature(value: &str) -> Result<[u8; 64], ArtifactOwnerHostError> {
    if value.len() != 128 {
        return Err(ArtifactOwnerHostError::CurrentHeadContext);
    }
    let raw = value.as_bytes();
    let mut signature = [0u8; 64];
    for (index, output) in signature.iter_mut().enumerate() {
        let high =
            decode_hex_digit(raw[index * 2]).ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let low = decode_hex_digit(raw[index * 2 + 1])
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        *output = (high << 4) | low;
    }
    Ok(signature)
}

const fn decode_hex_digit(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[derive(Debug)]
pub enum ArtifactOwnerHostError {
    Storage(crate::ArtifactStorageError),
    Publication(ArtifactPublicationError),
    Registry(ArtifactRegistryError),
    Io(std::io::ErrorKind),
    InvalidTrust,
    InvalidKey,
    UnknownSigner,
    InvalidSignature,
    SignerContext,
    SignerRevoked,
    WriterLeaseContext,
    WriterFenceBusy,
    RegistryPredecessorMismatch,
    CurrentHeadContext,
    CurrentHeadConflict,
    CurrentHeadFork,
    CurrentHeadExpired,
    CurrentHeadRollback,
    CheckpointMissing,
    CheckpointGap,
    CheckpointMismatch,
    IdentityConflict,
    PathBoundary,
    Capacity,
    Indeterminate,
    InternalInvariant,
}

impl fmt::Display for ArtifactOwnerHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerHostError {}

impl From<std::io::Error> for ArtifactOwnerHostError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

impl From<crate::ArtifactStorageError> for ArtifactOwnerHostError {
    fn from(value: crate::ArtifactStorageError) -> Self {
        Self::Storage(value)
    }
}

impl From<ArtifactPublicationError> for ArtifactOwnerHostError {
    fn from(value: ArtifactPublicationError) -> Self {
        Self::Publication(value)
    }
}

impl From<ArtifactRegistryError> for ArtifactOwnerHostError {
    fn from(value: ArtifactRegistryError) -> Self {
        Self::Registry(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ArtifactKind;

    use std::process::Command;
    use std::process::Stdio;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;
    use std::thread;
    use std::time::Duration;

    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::DatasetWithdrawalScopeV1;
    use crate::LearningArtifactManifestV2;
    use crate::ProvenanceModeV1;
    use crate::admit_manifest_at_withdrawal_head_v3;
    use crate::test_support::FixtureError;
    use crate::test_support::FixtureValue;

    static NEXT_TEST_DIR: AtomicU64 = AtomicU64::new(1);

    pub(super) struct TestDir(pub(super) PathBuf);

    impl TestDir {
        pub(super) fn new() -> Self {
            let id = NEXT_TEST_DIR.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "hepta-learning-artifact-owner-{}-{id}",
                std::process::id()
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).fixture("create test owner dir");
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).fixture("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn signer() -> SigningKey {
        SigningKey::from_bytes(&[7u8; 32])
    }

    fn trusted_signer(key: &SigningKey) -> TrustedArtifactSignerV1 {
        TrustedArtifactSignerV1 {
            signer_id: id("owner-authority"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 10,
            valid_from: 1,
            expires_at: 10_000,
            revoked_at: None,
        }
    }

    fn trust(key: &SigningKey, scope_digest: Digest32) -> ArtifactOwnerTrustV1 {
        ArtifactOwnerTrustV1 {
            registry_id: id("learning-artifacts"),
            withdrawal_scope_digest: scope_digest,
            minimum_registry_generation: Generation::new(1).fixture("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![trusted_signer(key)],
            head_signers: vec![trusted_signer(key)],
        }
    }

    fn lease(key: &SigningKey, scope_digest: Digest32) -> SignedArtifactWriterLeaseV1 {
        let mut value = SignedArtifactWriterLeaseV1 {
            lease_id: id("writer-lease"),
            producer_id: id("trainer"),
            registry_id: id("learning-artifacts"),
            withdrawal_scope_digest: scope_digest,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: 10,
            expires_at: 1_000,
            signature: [0; 64],
        };
        value.signature = key.sign(&value.signing_bytes()).to_bytes();
        value
    }

    fn withdrawal_scope() -> DatasetWithdrawalScopeV1 {
        DatasetWithdrawalScopeV1 {
            authority_domain_id: id("dataset-authority"),
            registry_id: id("withdrawals"),
            scope_id: id("scope"),
        }
    }

    fn manifest() -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("candidate"),
            kind: ArtifactKind::Model,
            generation: Generation::new(1).fixture("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![digest("dataset")],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("payload"),
            encoded_size_bytes: 7,
            training_code_digest: digest("code"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("trainer"),
            created_at: 10,
            expires_at: 1_000,
        }
    }

    fn signed_head(
        key: &SigningKey,
        scope_digest: Digest32,
        head_digest: Digest32,
    ) -> SignedCurrentArtifactHeadV1 {
        let mut value = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: scope_digest,
            binding: digest("binding"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("learning-artifacts"),
                generation: Generation::new(1).fixture("generation"),
                head_digest,
                predecessor_head_digest: Digest32::ZERO,
                authority_epoch: 1,
                signer_id: id("owner-authority"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 1_000,
            },
            signature: [0; 64],
        };
        value.signature = key.sign(&value.signing_bytes()).to_bytes();
        value
    }

    #[test]
    fn owner_host_exclusively_fences_writer_lease() {
        let directory = TestDir::new();
        let key = signer();
        let scope_digest = withdrawal_scope().digest();
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("first owner");
        assert!(matches!(
            LearningArtifactOwnerHost::open(
                &directory.0,
                trust(&key, scope_digest),
                lease(&key, scope_digest),
                20,
            )
            .fixture_error("second owner must be fenced"),
            ArtifactOwnerHostError::WriterFenceBusy
        ));
        drop(owner);
        LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("fence is released");
    }

    #[test]
    fn owner_host_checkpoint_recovery_requires_exact_snapshot() {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let scope_digest = scope.digest();
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("owner");
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            20,
        )
        .fixture("admission");
        let registry = ArtifactRegistry::new();
        let mut transaction = owner
            .begin_publication(
                id("operation"),
                admission,
                &withdrawals,
                &registry,
                Digest32::ZERO,
                20,
            )
            .fixture("begin");
        transaction
            .record_payload_durable(digest("payload"), 7)
            .fixture("payload durable");
        owner
            .persist_checkpoint(&transaction)
            .fixture("payload checkpoint");
        let snapshot = transaction.snapshot();
        drop(owner);

        let reopened = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            21,
        )
        .fixture("reopen");
        let recovery = reopened
            .recover_publication(&id("operation"))
            .fixture("recover")
            .fixture("checkpoint exists");
        assert_eq!(
            recovery.checkpoint.phase,
            ArtifactPublicationPhaseV1::PayloadDurable
        );
        assert!(recovery.requires_exact_snapshot);
        let resumed = reopened
            .resume_publication(snapshot, 21)
            .fixture("exact snapshot resumes");
        assert_eq!(resumed.phase(), ArtifactPublicationPhaseV1::PayloadDurable);
    }

    #[test]
    fn independent_current_head_anchor_rejects_restored_old_backup() {
        let current_directory = TestDir::new();
        let old_backup = TestDir::new();
        let key = signer();
        let scope_digest = withdrawal_scope().digest();

        let current = LearningArtifactOwnerHost::open(
            &current_directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("current owner");
        let head = signed_head(&key, scope_digest, digest("current-head"));
        current
            .persist_signed_head_record(&head)
            .fixture("persist current head");
        drop(current);

        let failure = LearningArtifactOwnerHost::open_with_required_current_head(
            &old_backup.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            head,
            21,
        )
        .fixture_error("old backup must not satisfy independent current-head floor");
        assert!(matches!(
            failure,
            ArtifactOwnerHostError::CurrentHeadRollback
        ));
    }

    fn deterministic_publication(
        owner: &LearningArtifactOwnerHost,
        withdrawals: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> (ArtifactRegistry, ArtifactPublicationTransactionV1) {
        let admission = admit_manifest_at_withdrawal_head_v3(
            withdrawals,
            withdrawals.head_digest(),
            manifest(),
            now,
        )
        .fixture("process admission");
        let mut registry = ArtifactRegistry::new();
        let transaction = owner
            .begin_publication(
                id("process-operation"),
                admission,
                withdrawals,
                &registry,
                Digest32::ZERO,
                now,
            )
            .fixture("process begin");
        owner
            .stage_compatibility_registration(&transaction, &mut registry, now)
            .fixture("stage compatibility registration");
        (registry, transaction)
    }

    fn durable_process_marker(root: &Path, stage: &str) {
        let path = root.join(format!("worker-{stage}.ready"));
        let mut file = File::create(path).fixture("create process marker");
        file.write_all(stage.as_bytes())
            .and_then(|()| file.sync_all())
            .fixture("sync process marker");
    }

    fn worker_stage(root: &Path, stage: &str) {
        let key = signer();
        let scope = withdrawal_scope();
        let scope_digest = scope.digest();
        let owner = LearningArtifactOwnerHost::open(
            root,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("worker owner");
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
        let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
        let payload_relative = PathBuf::from("payloads").join(format!(
            "{}-{}.bin",
            id("candidate"),
            digest("payload")
        ));
        let binding = digest("binding");

        match stage {
            "prepared" => {}
            "payload-effect" => {
                write_candidate_payload_beneath(
                    root,
                    &payload_relative,
                    &registry,
                    &id("candidate"),
                    b"payload",
                )
                .fixture("payload effect");
            }
            "payload-durable" | "registry-effect" | "registry-durable" | "head-effect"
            | "witness-durable" | "acknowledged" => {
                owner
                    .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
                    .fixture("payload durable");
                if stage == "payload-durable" {
                    durable_process_marker(root, stage);
                    loop {
                        thread::sleep(Duration::from_secs(1));
                    }
                }

                if stage == "registry-effect" {
                    let encoded = encode_snapshot(&registry, binding).fixture("encode registry");
                    let receipt = RegistrySnapshotReceipt {
                        binding,
                        head_digest: registry.snapshot().head_digest,
                        file_digest: Digest32::of_bytes(&encoded),
                        records: registry.records().len(),
                        encoded_bytes: encoded.len(),
                    };
                    let relative = PathBuf::from("registries").join(format!(
                        "{}-{}.snapshot",
                        receipt.head_digest, receipt.file_digest
                    ));
                    write_registry_snapshot_beneath(root, relative, &registry, binding)
                        .fixture("registry effect");
                    durable_process_marker(root, stage);
                    loop {
                        thread::sleep(Duration::from_secs(1));
                    }
                }

                owner
                    .ensure_registry_durable(&mut transaction, &registry, &withdrawals, binding, 20)
                    .fixture("registry durable");
                if stage == "registry-durable" {
                    durable_process_marker(root, stage);
                    loop {
                        thread::sleep(Duration::from_secs(1));
                    }
                }

                let head = signed_head(&key, scope_digest, registry.snapshot().head_digest);
                if stage == "head-effect" {
                    let requirement = RegistryHeadRequirementV1 {
                        registry_id: id("learning-artifacts"),
                        minimum_generation: Generation::new(1).fixture("generation"),
                        expected_predecessor_head_digest: Digest32::ZERO,
                        minimum_authority_epoch: 1,
                        now: 20,
                    };
                    write_registry_head_witness_beneath(
                        root,
                        PathBuf::from("witnesses").join(format!(
                            "{}-{}.witness",
                            head.witness.generation.get(),
                            owner
                                .verifier
                                .verify_signed_head(&head, &requirement, true)
                                .fixture("verify head")
                                .witness_digest
                        )),
                        &head.witness,
                        &requirement,
                        binding,
                    )
                    .fixture("witness side effect");
                    owner
                        .persist_signed_head_record(&head)
                        .fixture("signed head side effect");
                    durable_process_marker(root, stage);
                    loop {
                        thread::sleep(Duration::from_secs(1));
                    }
                }

                owner
                    .ensure_witness_durable(&mut transaction, &head, &withdrawals, 20)
                    .fixture("witness durable");
                if stage == "witness-durable" {
                    durable_process_marker(root, stage);
                    loop {
                        thread::sleep(Duration::from_secs(1));
                    }
                }

                owner
                    .acknowledge(&mut transaction, &withdrawals, 20)
                    .fixture("acknowledge");
            }
            other => panic!("unknown process fault stage: {other}"),
        }

        durable_process_marker(root, stage);
        loop {
            thread::sleep(Duration::from_secs(1));
        }
    }

    #[test]
    #[ignore = "worker is invoked only by owner_host_process_kill_reopen_matrix"]
    fn owner_host_process_fault_worker() {
        if std::env::var("HEPTA_ARTIFACT_OWNER_WORKER").ok().as_deref() != Some("1") {
            return;
        }
        let root = std::env::var_os("HEPTA_ARTIFACT_OWNER_ROOT")
            .map(PathBuf::from)
            .fixture("worker root");
        let stage = std::env::var("HEPTA_ARTIFACT_OWNER_STAGE").fixture("worker stage");
        worker_stage(&root, &stage);
    }

    fn wait_for_worker_marker(child: &mut std::process::Child, root: &Path, stage: &str) {
        let marker = root.join(format!("worker-{stage}.ready"));
        for _ in 0..500 {
            if marker.is_file() {
                return;
            }
            if child.try_wait().fixture("poll worker").is_some() {
                panic!("owner worker exited before durable marker at stage {stage}");
            }
            thread::sleep(Duration::from_millis(10));
        }
        panic!("owner worker did not reach stage marker: {stage}");
    }

    #[test]
    fn owner_host_process_kill_reopen_matrix() {
        let executable = std::env::current_exe().fixture("current test executable");
        for (stage, expected_phase) in [
            ("prepared", ArtifactPublicationPhaseV1::Prepared),
            ("payload-effect", ArtifactPublicationPhaseV1::Prepared),
            (
                "payload-durable",
                ArtifactPublicationPhaseV1::PayloadDurable,
            ),
            (
                "registry-effect",
                ArtifactPublicationPhaseV1::PayloadDurable,
            ),
            (
                "registry-durable",
                ArtifactPublicationPhaseV1::RegistryDurable,
            ),
            ("head-effect", ArtifactPublicationPhaseV1::RegistryDurable),
            (
                "witness-durable",
                ArtifactPublicationPhaseV1::WitnessDurable,
            ),
            ("acknowledged", ArtifactPublicationPhaseV1::Acknowledged),
        ] {
            let directory = TestDir::new();
            let mut child = Command::new(&executable)
                .arg("--ignored")
                .arg("--exact")
                .arg("owner_host::tests::owner_host_process_fault_worker")
                .arg("--nocapture")
                .env("HEPTA_ARTIFACT_OWNER_WORKER", "1")
                .env("HEPTA_ARTIFACT_OWNER_ROOT", &directory.0)
                .env("HEPTA_ARTIFACT_OWNER_STAGE", stage)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .fixture("spawn owner worker");
            wait_for_worker_marker(&mut child, &directory.0, stage);
            child.kill().fixture("kill owner worker");
            child.wait().fixture("reap owner worker");

            let key = signer();
            let scope_digest = withdrawal_scope().digest();
            let reopened = LearningArtifactOwnerHost::open(
                &directory.0,
                trust(&key, scope_digest),
                lease(&key, scope_digest),
                21,
            )
            .fixture("reopen owner after process death");
            let recovery = reopened
                .recover_publication(&id("process-operation"))
                .fixture("recover process checkpoint")
                .fixture("process checkpoint exists");
            assert_eq!(recovery.checkpoint.phase, expected_phase);

            if stage == "head-effect" {
                let current = reopened
                    .discover_current_head(21)
                    .fixture("discover head after owner death")
                    .fixture("signed head survived process death");
                assert_eq!(
                    current.signed.witness.head_digest,
                    recovery
                        .checkpoint
                        .registry_receipt
                        .fixture("registry receipt before head effect")
                        .head_digest
                );
            }
        }
    }

    #[test]
    fn current_head_rotation_preserves_history_and_requires_current_key_epoch() {
        let directory = TestDir::new();
        let old_only_directory = TestDir::new();
        let old_key = signer();
        let new_key = SigningKey::from_bytes(&[9u8; 32]);
        let scope_digest = withdrawal_scope().digest();

        let mut rotated_trust = trust(&old_key, scope_digest);
        let mut historical_signer = trusted_signer(&old_key);
        historical_signer.revoked_at = Some(25);
        let current_signer = TrustedArtifactSignerV1 {
            signer_id: id("owner-authority-v2"),
            verifying_key: new_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 2,
            maximum_authority_epoch: 10,
            valid_from: 25,
            expires_at: 10_000,
            revoked_at: None,
        };
        rotated_trust.head_signers = vec![historical_signer, current_signer];

        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            rotated_trust.clone(),
            lease(&old_key, scope_digest),
            40,
        )
        .fixture("rotated owner");

        let head_one = signed_head(&old_key, scope_digest, digest("head-one"));
        owner
            .persist_signed_head_record(&head_one)
            .fixture("persist historical head");

        let mut head_two = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: scope_digest,
            binding: digest("binding"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("learning-artifacts"),
                generation: Generation::new(2).fixture("generation"),
                head_digest: digest("head-two"),
                predecessor_head_digest: head_one.witness.head_digest,
                authority_epoch: 2,
                signer_id: id("owner-authority-v2"),
                signing_key_digest: Digest32::of_bytes(&new_key.verifying_key().to_bytes()),
                issued_at: 30,
                expires_at: 1_000,
            },
            signature: [0; 64],
        };
        head_two.signature = new_key.sign(&head_two.signing_bytes()).to_bytes();
        owner
            .persist_signed_head_record(&head_two)
            .fixture("persist rotated head");

        let latest = owner
            .discover_current_head(40)
            .fixture("discover rotated chain")
            .fixture("rotated current head");
        assert_eq!(latest.signed, head_two);

        let old_only_owner = LearningArtifactOwnerHost::open(
            &old_only_directory.0,
            rotated_trust,
            lease(&old_key, scope_digest),
            40,
        )
        .fixture("old-only owner");
        old_only_owner
            .persist_signed_head_record(&head_one)
            .fixture("persist old-only head");
        assert!(matches!(
            old_only_owner
                .discover_current_head(40)
                .fixture_error("revoked signer cannot remain current"),
            ArtifactOwnerHostError::SignerRevoked
        ));

        let mut stale_epoch = head_two;
        stale_epoch.witness.authority_epoch = 1;
        stale_epoch.signature = new_key.sign(&stale_epoch.signing_bytes()).to_bytes();
        let requirement = RegistryHeadRequirementV1 {
            registry_id: id("learning-artifacts"),
            minimum_generation: Generation::new(2).fixture("generation"),
            expected_predecessor_head_digest: head_one.witness.head_digest,
            minimum_authority_epoch: 2,
            now: 30,
        };
        assert!(matches!(
            owner
                .verifier
                .verify_signed_head(&stale_epoch, &requirement, true)
                .fixture_error("rotated signer cannot regress authority epoch"),
            ArtifactOwnerHostError::SignerContext
        ));
    }

    #[test]
    fn authenticated_current_head_is_discovered_and_signature_drift_rejects() {
        let directory = TestDir::new();
        let key = signer();
        let scope_digest = withdrawal_scope().digest();
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("owner");
        let head = signed_head(&key, scope_digest, digest("head"));
        let requirement = RegistryHeadRequirementV1 {
            registry_id: id("learning-artifacts"),
            minimum_generation: Generation::new(1).fixture("generation"),
            expected_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            now: 20,
        };
        owner
            .verifier
            .verify_signed_head(&head, &requirement, true)
            .fixture("signed head");
        owner
            .persist_signed_head_record(&head)
            .fixture("persist signed head");
        let discovered = owner
            .discover_current_head(20)
            .fixture("discover")
            .fixture("current head");
        assert_eq!(discovered.signed, head);

        let mut drift = head;
        drift.signature[0] ^= 1;
        assert!(matches!(
            owner
                .verifier
                .verify_signed_head(&drift, &requirement, true)
                .fixture_error("signature drift"),
            ArtifactOwnerHostError::InvalidSignature
        ));
    }
}
