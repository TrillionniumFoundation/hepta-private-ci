//! Shared owner-facing contracts for typed cell definitions, CAS payloads and
//! checkpointed cell state.
//!
//! These owners execute against the repository's immutable registry and
//! create-only payload store.  They produce signed, replayable receipts while
//! deliberately carrying no activation, model-invocation or effect authority.
//! Host and independent-observer evidence is optional at this layer: a receipt
//! without both bindings is a source qualification witness, never a production
//! qualification.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::fs::File;
use std::path::Path;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;

use crate::ArtifactRegistry;
use crate::ArtifactStorageError;
use crate::read_candidate_payload;
use crate::write_candidate_payload_beneath;

pub const CELL_DEFINITION_REGISTRY_SCHEMA_V1: &str = "hepta.cell-definition-registry.v1";
pub const ARTIFACT_WRITE_RECEIPT_SCHEMA_V1: &str = "hepta.artifact-write-receipt.v1";
pub const ARTIFACT_LOAD_RECEIPT_SCHEMA_V1: &str = "hepta.artifact-load-receipt.v1";
pub const STATE_COMMIT_RECEIPT_SCHEMA_V1: &str = "hepta.state-commit-receipt.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionOwnerError {
    Definition(String),
    CellGenerationConflict(StableId),
    GenerationNotAdvanced(StableId),
    InvalidSequence,
    InvalidReceipt,
    Artifact(ArtifactStorageError),
    ArtifactUnavailable(StableId),
    PayloadMismatch,
    StateConflict(StableId),
    StateTombstoned(StableId),
    StateNotFound(StableId),
    SignatureInvalid,
}

impl fmt::Display for ProductionOwnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ProductionOwnerError {}

impl From<ArtifactStorageError> for ProductionOwnerError {
    fn from(error: ArtifactStorageError) -> Self {
        Self::Artifact(error)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DefinitionPublicationDispositionV1 {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellDefinitionRecordV1 {
    pub sequence: LogicalSequence,
    pub predecessor_head_digest: Digest32,
    pub definition: CellDefinitionV2,
    pub definition_digest: Digest32,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellDefinitionRegistrySnapshotV1 {
    pub records: Vec<CellDefinitionRecordV1>,
    pub head_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellDefinitionPublicationReceiptV1 {
    pub disposition: DefinitionPublicationDispositionV1,
    pub cell_id: StableId,
    pub generation: Generation,
    pub definition_digest: Digest32,
    pub sequence: LogicalSequence,
    pub predecessor_head_digest: Digest32,
    pub head_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Default)]
pub struct CellDefinitionOwnerV1 {
    records: Vec<CellDefinitionRecordV1>,
    latest: BTreeMap<StableId, CellDefinitionRecordV1>,
}

impl CellDefinitionOwnerV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn publish(
        &mut self,
        definition: CellDefinitionV2,
    ) -> Result<CellDefinitionPublicationReceiptV1, ProductionOwnerError> {
        definition
            .validate()
            .map_err(|error| ProductionOwnerError::Definition(error.to_string()))?;
        let definition_digest = definition
            .content_digest()
            .map_err(|error| ProductionOwnerError::Definition(error.to_string()))?;
        if let Some(previous) = self.latest.get(&definition.cell_id) {
            if definition.generation < previous.definition.generation {
                return Err(ProductionOwnerError::GenerationNotAdvanced(
                    definition.cell_id,
                ));
            }
            if definition.generation == previous.definition.generation {
                if definition_digest != previous.definition_digest {
                    return Err(ProductionOwnerError::CellGenerationConflict(
                        definition.cell_id,
                    ));
                }
                return Ok(publication_receipt(
                    DefinitionPublicationDispositionV1::IdempotentReplay,
                    previous,
                ));
            }
        }
        let sequence = LogicalSequence::new(
            u64::try_from(self.records.len())
                .map_err(|_| ProductionOwnerError::InvalidSequence)?
                .checked_add(1)
                .ok_or(ProductionOwnerError::InvalidSequence)?,
        )
        .map_err(|_| ProductionOwnerError::InvalidSequence)?;
        let predecessor_head_digest = self.head_digest();
        let event_digest = digest_definition_event(&definition, definition_digest);
        let chain_digest = digest_chain(predecessor_head_digest, sequence, event_digest);
        let record = CellDefinitionRecordV1 {
            sequence,
            predecessor_head_digest,
            definition,
            definition_digest,
            event_digest,
            chain_digest,
        };
        self.records.push(record.clone());
        self.latest
            .insert(record.definition.cell_id.clone(), record.clone());
        Ok(publication_receipt(
            DefinitionPublicationDispositionV1::Appended,
            &record,
        ))
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest)
    }

    #[must_use]
    pub fn records(&self) -> &[CellDefinitionRecordV1] {
        &self.records
    }

    #[must_use]
    pub fn latest(&self, cell_id: &StableId) -> Option<&CellDefinitionV2> {
        self.latest.get(cell_id).map(|record| &record.definition)
    }

    #[must_use]
    pub fn snapshot(&self) -> CellDefinitionRegistrySnapshotV1 {
        CellDefinitionRegistrySnapshotV1 {
            records: self.records.clone(),
            head_digest: self.head_digest(),
        }
    }

    pub fn from_snapshot(
        snapshot: CellDefinitionRegistrySnapshotV1,
    ) -> Result<Self, ProductionOwnerError> {
        let mut owner = Self::new();
        for expected in snapshot.records {
            let receipt = owner.publish(expected.definition.clone())?;
            let actual = owner
                .records
                .last()
                .ok_or(ProductionOwnerError::InvalidReceipt)?;
            if receipt.disposition != DefinitionPublicationDispositionV1::Appended
                || actual != &expected
            {
                return Err(ProductionOwnerError::InvalidReceipt);
            }
        }
        if owner.head_digest() != snapshot.head_digest {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        Ok(owner)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactWriteReceiptV1 {
    pub operation_id: StableId,
    pub artifact_id: StableId,
    pub artifact_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub registry_head_digest: Digest32,
    pub path_digest: Digest32,
    pub owner_id: StableId,
    pub host_evidence_digest: Option<Digest32>,
    pub observer_evidence_digest: Option<Digest32>,
    pub authority: AuthorityPosture,
    pub receipt_digest: Digest32,
    pub signature: [u8; 64],
}

impl ArtifactWriteReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        digest_receipt_fields(
            ARTIFACT_WRITE_RECEIPT_SCHEMA_V1,
            &[
                self.operation_id.as_str().as_bytes(),
                self.artifact_id.as_str().as_bytes(),
                self.artifact_digest.as_array(),
                &self.encoded_size_bytes.to_be_bytes(),
                self.registry_head_digest.as_array(),
                self.path_digest.as_array(),
                self.owner_id.as_str().as_bytes(),
                self.host_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
                self.observer_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
            ],
        )
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.signing_bytes())
    }

    pub fn verify(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        if self.receipt_digest != self.content_digest()
            || self.authority.grants_any()
            || self.host_evidence_digest.is_some_and(Digest32::is_zero)
            || self.observer_evidence_digest.is_some_and(Digest32::is_zero)
        {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        key.verify_strict(
            &self.signing_bytes(),
            &Signature::from_bytes(&self.signature),
        )
        .map_err(|_| ProductionOwnerError::SignatureInvalid)
    }

    /// Production qualification additionally requires both independent host
    /// and observer evidence.  `verify` remains the repository qualification
    /// path so existing replay fixtures can explicitly carry no host data.
    pub fn verify_production(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        self.verify(key)?;
        require_production_evidence(self.host_evidence_digest, self.observer_evidence_digest)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLoadReceiptV1 {
    pub operation_id: StableId,
    pub artifact_id: StableId,
    pub artifact_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub payload_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub path_digest: Digest32,
    pub owner_id: StableId,
    pub host_evidence_digest: Option<Digest32>,
    pub observer_evidence_digest: Option<Digest32>,
    pub authority: AuthorityPosture,
    pub receipt_digest: Digest32,
    pub signature: [u8; 64],
}

impl ArtifactLoadReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        digest_receipt_fields(
            ARTIFACT_LOAD_RECEIPT_SCHEMA_V1,
            &[
                self.operation_id.as_str().as_bytes(),
                self.artifact_id.as_str().as_bytes(),
                self.artifact_digest.as_array(),
                &self.encoded_size_bytes.to_be_bytes(),
                self.payload_digest.as_array(),
                self.registry_head_digest.as_array(),
                self.path_digest.as_array(),
                self.owner_id.as_str().as_bytes(),
                self.host_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
                self.observer_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
            ],
        )
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.signing_bytes())
    }

    pub fn verify(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        if self.receipt_digest != self.content_digest()
            || self.authority.grants_any()
            || self.host_evidence_digest.is_some_and(Digest32::is_zero)
            || self.observer_evidence_digest.is_some_and(Digest32::is_zero)
        {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        key.verify_strict(
            &self.signing_bytes(),
            &Signature::from_bytes(&self.signature),
        )
        .map_err(|_| ProductionOwnerError::SignatureInvalid)
    }

    pub fn verify_production(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        self.verify(key)?;
        require_production_evidence(self.host_evidence_digest, self.observer_evidence_digest)
    }
}

#[derive(Clone, Debug)]
pub struct ArtifactCasOwnerV1 {
    owner_id: StableId,
    signing_key: SigningKey,
}

impl ArtifactCasOwnerV1 {
    pub fn new(owner_id: StableId, signing_key: SigningKey) -> Result<Self, ProductionOwnerError> {
        if owner_id.as_str().is_empty() {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        Ok(Self {
            owner_id,
            signing_key,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn write_candidate(
        &self,
        operation_id: StableId,
        root: impl AsRef<Path>,
        relative: impl AsRef<Path>,
        registry: &ArtifactRegistry,
        artifact_id: &StableId,
        bytes: &[u8],
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<ArtifactWriteReceiptV1, ProductionOwnerError> {
        let digest =
            write_candidate_payload_beneath(root, &relative, registry, artifact_id, bytes)?;
        let manifest = registry
            .manifest(artifact_id)
            .ok_or_else(|| ProductionOwnerError::ArtifactUnavailable(artifact_id.clone()))?;
        let mut receipt = ArtifactWriteReceiptV1 {
            operation_id,
            artifact_id: artifact_id.clone(),
            artifact_digest: digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            registry_head_digest: registry.snapshot().head_digest,
            path_digest: path_digest(relative),
            owner_id: self.owner_id.clone(),
            host_evidence_digest,
            observer_evidence_digest,
            authority: AuthorityPosture::DENY_ALL,
            receipt_digest: Digest32::ZERO,
            signature: [0; 64],
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.signature = self.signing_key.sign(&receipt.signing_bytes()).to_bytes();
        Ok(receipt)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn load_candidate(
        &self,
        operation_id: StableId,
        file: File,
        registry: &ArtifactRegistry,
        artifact_id: &StableId,
        expected_write: &ArtifactWriteReceiptV1,
        relative: impl AsRef<Path>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<(Vec<u8>, ArtifactLoadReceiptV1), ProductionOwnerError> {
        expected_write.verify(&self.signing_key.verifying_key())?;
        if expected_write.artifact_id != *artifact_id
            || expected_write.path_digest != path_digest(relative)
        {
            return Err(ProductionOwnerError::PayloadMismatch);
        }
        let bytes = read_candidate_payload(file, registry, artifact_id)?;
        let manifest = registry
            .manifest(artifact_id)
            .ok_or_else(|| ProductionOwnerError::ArtifactUnavailable(artifact_id.clone()))?;
        if expected_write.artifact_digest != manifest.content_digest
            || expected_write.encoded_size_bytes != bytes.len() as u64
            || Digest32::of_bytes(&bytes) != expected_write.artifact_digest
        {
            return Err(ProductionOwnerError::PayloadMismatch);
        }
        let mut receipt = ArtifactLoadReceiptV1 {
            operation_id,
            artifact_id: artifact_id.clone(),
            artifact_digest: manifest.content_digest,
            encoded_size_bytes: bytes.len() as u64,
            payload_digest: Digest32::of_bytes(&bytes),
            registry_head_digest: registry.snapshot().head_digest,
            path_digest: expected_write.path_digest,
            owner_id: self.owner_id.clone(),
            host_evidence_digest,
            observer_evidence_digest,
            authority: AuthorityPosture::DENY_ALL,
            receipt_digest: Digest32::ZERO,
            signature: [0; 64],
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.signature = self.signing_key.sign(&receipt.signing_bytes()).to_bytes();
        Ok((bytes, receipt))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateCommitReceiptV1 {
    pub operation_id: StableId,
    pub cell_id: StableId,
    pub generation: Generation,
    pub state_schema_digest: Digest32,
    pub predecessor_state_digest: Digest32,
    pub state_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub sequence: LogicalSequence,
    pub owner_id: StableId,
    pub host_evidence_digest: Option<Digest32>,
    pub observer_evidence_digest: Option<Digest32>,
    pub authority: AuthorityPosture,
    pub receipt_digest: Digest32,
    pub signature: [u8; 64],
}

impl StateCommitReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        digest_receipt_fields(
            STATE_COMMIT_RECEIPT_SCHEMA_V1,
            &[
                self.operation_id.as_str().as_bytes(),
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                self.state_schema_digest.as_array(),
                self.predecessor_state_digest.as_array(),
                self.state_digest.as_array(),
                &self.encoded_size_bytes.to_be_bytes(),
                &self.sequence.get().to_be_bytes(),
                self.owner_id.as_str().as_bytes(),
                self.host_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
                self.observer_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
            ],
        )
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.signing_bytes())
    }

    pub fn verify(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        if self.receipt_digest != self.content_digest()
            || self.authority.grants_any()
            || self.state_schema_digest.is_zero()
            || self.state_digest.is_zero()
            || self.encoded_size_bytes == 0
            || self.host_evidence_digest.is_some_and(Digest32::is_zero)
            || self.observer_evidence_digest.is_some_and(Digest32::is_zero)
        {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        key.verify_strict(
            &self.signing_bytes(),
            &Signature::from_bytes(&self.signature),
        )
        .map_err(|_| ProductionOwnerError::SignatureInvalid)
    }

    pub fn verify_production(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        self.verify(key)?;
        require_production_evidence(self.host_evidence_digest, self.observer_evidence_digest)
    }
}

/// Signed retirement witness for a state domain.  A tombstone is durable
/// owner state; it is not inferred from an in-memory phase transition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateTombstoneReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub reason_digest: Digest32,
    pub owner_id: StableId,
    pub host_evidence_digest: Option<Digest32>,
    pub observer_evidence_digest: Option<Digest32>,
    pub authority: AuthorityPosture,
    pub receipt_digest: Digest32,
    pub signature: [u8; 64],
}

impl StateTombstoneReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        digest_receipt_fields(
            "hepta.state-tombstone-receipt.v1",
            &[
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                self.reason_digest.as_array(),
                self.owner_id.as_str().as_bytes(),
                self.host_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
                self.observer_evidence_digest
                    .map_or(Digest32::ZERO, |value| value)
                    .as_array(),
            ],
        )
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.signing_bytes())
    }

    pub fn verify(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        if self.receipt_digest != self.content_digest()
            || self.cell_id.as_str().is_empty()
            || self.reason_digest.is_zero()
            || self.owner_id.as_str().is_empty()
            || self.authority.grants_any()
            || self.host_evidence_digest.is_some_and(Digest32::is_zero)
            || self.observer_evidence_digest.is_some_and(Digest32::is_zero)
        {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        key.verify_strict(
            &self.signing_bytes(),
            &Signature::from_bytes(&self.signature),
        )
        .map_err(|_| ProductionOwnerError::SignatureInvalid)
    }

    pub fn verify_production(&self, key: &VerifyingKey) -> Result<(), ProductionOwnerError> {
        self.verify(key)?;
        require_production_evidence(self.host_evidence_digest, self.observer_evidence_digest)
    }
}

#[derive(Clone, Debug)]
struct StateEntryV1 {
    receipt: StateCommitReceiptV1,
    bytes: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateCheckpointSnapshotV1 {
    pub entries: Vec<(StateCommitReceiptV1, Vec<u8>)>,
    pub tombstones: Vec<StateTombstoneReceiptV1>,
    /// The active head is separate from append-only history.  Rollback moves
    /// this pointer to an existing predecessor while retaining every receipt
    /// so sequence numbers, signatures and tombstone evidence cannot be
    /// reused after a restart.
    pub active_heads: Vec<(StableId, Digest32)>,
}

#[derive(Clone, Debug)]
pub struct StateCheckpointOwnerV1 {
    owner_id: StableId,
    signing_key: SigningKey,
    entries: BTreeMap<StableId, Vec<StateEntryV1>>,
    tombstones: BTreeMap<StableId, StateTombstoneReceiptV1>,
    active_heads: BTreeMap<StableId, Digest32>,
}

impl StateCheckpointOwnerV1 {
    pub fn new(owner_id: StableId, signing_key: SigningKey) -> Result<Self, ProductionOwnerError> {
        if owner_id.as_str().is_empty() {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        Ok(Self {
            owner_id,
            signing_key,
            entries: BTreeMap::new(),
            tombstones: BTreeMap::new(),
            active_heads: BTreeMap::new(),
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn commit(
        &mut self,
        operation_id: StableId,
        cell_id: StableId,
        generation: Generation,
        state_schema_digest: Digest32,
        predecessor_state_digest: Digest32,
        bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, ProductionOwnerError> {
        if state_schema_digest.is_zero() || bytes.is_empty() {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        if self.tombstones.contains_key(&cell_id) {
            return Err(ProductionOwnerError::StateTombstoned(cell_id));
        }
        let history = self.entries.entry(cell_id.clone()).or_default();
        if let Some(existing) = history
            .iter()
            .find(|entry| entry.receipt.operation_id == operation_id)
        {
            if existing.bytes == bytes
                && existing.receipt.generation == generation
                && existing.receipt.state_schema_digest == state_schema_digest
            {
                return Ok(existing.receipt.clone());
            }
            return Err(ProductionOwnerError::StateConflict(cell_id));
        }
        let active_head = self
            .active_heads
            .get(&cell_id)
            .copied()
            .or_else(|| history.last().map(|entry| entry.receipt.state_digest));
        if let Some(active_head) = active_head {
            let active_generation = history
                .iter()
                .find(|entry| entry.receipt.state_digest == active_head)
                .map(|entry| entry.receipt.generation)
                .ok_or(ProductionOwnerError::StateConflict(cell_id.clone()))?;
            if predecessor_state_digest != active_head || generation < active_generation {
                return Err(ProductionOwnerError::StateConflict(cell_id));
            }
        } else if !predecessor_state_digest.is_zero() {
            return Err(ProductionOwnerError::StateConflict(cell_id));
        }
        let sequence = LogicalSequence::new(
            u64::try_from(history.len())
                .map_err(|_| ProductionOwnerError::InvalidSequence)?
                .checked_add(1)
                .ok_or(ProductionOwnerError::InvalidSequence)?,
        )
        .map_err(|_| ProductionOwnerError::InvalidSequence)?;
        let mut receipt = StateCommitReceiptV1 {
            operation_id,
            cell_id,
            generation,
            state_schema_digest,
            predecessor_state_digest,
            state_digest: Digest32::of_bytes(&bytes),
            encoded_size_bytes: bytes.len() as u64,
            sequence,
            owner_id: self.owner_id.clone(),
            host_evidence_digest,
            observer_evidence_digest,
            authority: AuthorityPosture::DENY_ALL,
            receipt_digest: Digest32::ZERO,
            signature: [0; 64],
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.signature = self.signing_key.sign(&receipt.signing_bytes()).to_bytes();
        history.push(StateEntryV1 {
            receipt: receipt.clone(),
            bytes,
        });
        self.active_heads
            .insert(receipt.cell_id.clone(), receipt.state_digest);
        Ok(receipt)
    }

    pub fn reload(
        &self,
        cell_id: &StableId,
        receipt: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, ProductionOwnerError> {
        receipt.verify(&self.signing_key.verifying_key())?;
        let entry = self
            .entries
            .get(cell_id)
            .and_then(|history| history.iter().find(|entry| entry.receipt == *receipt))
            .ok_or_else(|| ProductionOwnerError::StateNotFound(cell_id.clone()))?;
        if Digest32::of_bytes(&entry.bytes) != receipt.state_digest
            || entry.bytes.len() as u64 != receipt.encoded_size_bytes
        {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        Ok(entry.bytes.clone())
    }

    pub fn rollback(
        &mut self,
        cell_id: &StableId,
        target: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, ProductionOwnerError> {
        target.verify(&self.signing_key.verifying_key())?;
        let history = self
            .entries
            .get_mut(cell_id)
            .ok_or_else(|| ProductionOwnerError::StateNotFound(cell_id.clone()))?;
        let target_index = history
            .iter()
            .position(|entry| entry.receipt == *target)
            .ok_or_else(|| ProductionOwnerError::StateNotFound(cell_id.clone()))?;
        let bytes = history[target_index].bytes.clone();
        self.active_heads
            .insert(cell_id.clone(), target.state_digest);
        Ok(bytes)
    }

    pub fn tombstone(
        &mut self,
        cell_id: StableId,
        generation: Generation,
        reason_digest: Digest32,
    ) -> Result<StateTombstoneReceiptV1, ProductionOwnerError> {
        self.tombstone_with_evidence(cell_id, generation, reason_digest, None, None)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn tombstone_with_evidence(
        &mut self,
        cell_id: StableId,
        generation: Generation,
        reason_digest: Digest32,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateTombstoneReceiptV1, ProductionOwnerError> {
        if reason_digest.is_zero() || !self.entries.contains_key(&cell_id) {
            return Err(ProductionOwnerError::StateNotFound(cell_id));
        }
        if self.tombstones.contains_key(&cell_id) {
            return Err(ProductionOwnerError::StateTombstoned(cell_id));
        }
        let mut receipt = StateTombstoneReceiptV1 {
            cell_id: cell_id.clone(),
            generation,
            reason_digest,
            owner_id: self.owner_id.clone(),
            host_evidence_digest,
            observer_evidence_digest,
            authority: AuthorityPosture::DENY_ALL,
            receipt_digest: Digest32::ZERO,
            signature: [0; 64],
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.signature = self.signing_key.sign(&receipt.signing_bytes()).to_bytes();
        self.tombstones.insert(cell_id, receipt.clone());
        Ok(receipt)
    }

    #[must_use]
    pub fn snapshot(&self) -> StateCheckpointSnapshotV1 {
        let entries = self
            .entries
            .values()
            .flat_map(|history| {
                history
                    .iter()
                    .map(|entry| (entry.receipt.clone(), entry.bytes.clone()))
            })
            .collect();
        let tombstones = self.tombstones.values().cloned().collect();
        let active_heads = self
            .active_heads
            .iter()
            .map(|(cell_id, digest)| (cell_id.clone(), *digest))
            .collect();
        StateCheckpointSnapshotV1 {
            entries,
            tombstones,
            active_heads,
        }
    }

    pub fn from_snapshot(
        snapshot: StateCheckpointSnapshotV1,
        owner_id: StableId,
        signing_key: SigningKey,
    ) -> Result<Self, ProductionOwnerError> {
        let expected_active_heads = snapshot.active_heads.clone();
        let mut owner = Self::new(owner_id, signing_key)?;
        for (receipt, bytes) in snapshot.entries {
            receipt.verify(&owner.signing_key.verifying_key())?;
            if Digest32::of_bytes(&bytes) != receipt.state_digest
                || bytes.len() as u64 != receipt.encoded_size_bytes
            {
                return Err(ProductionOwnerError::InvalidReceipt);
            }
            let history = owner.entries.entry(receipt.cell_id.clone()).or_default();
            if history
                .last()
                .is_some_and(|last| last.receipt.sequence >= receipt.sequence)
            {
                return Err(ProductionOwnerError::InvalidReceipt);
            }
            history.push(StateEntryV1 { receipt, bytes });
        }
        if owner
            .entries
            .keys()
            .any(|cell_id| !expected_active_heads.iter().any(|(id, _)| id == cell_id))
        {
            return Err(ProductionOwnerError::InvalidReceipt);
        }
        for receipt in snapshot.tombstones {
            receipt.verify(&owner.signing_key.verifying_key())?;
            if receipt.reason_digest.is_zero() || !owner.entries.contains_key(&receipt.cell_id) {
                return Err(ProductionOwnerError::InvalidReceipt);
            }
            owner.tombstones.insert(receipt.cell_id.clone(), receipt);
        }
        for (cell_id, active_head) in snapshot.active_heads {
            let history = owner
                .entries
                .get(&cell_id)
                .ok_or(ProductionOwnerError::InvalidReceipt)?;
            if !history
                .iter()
                .any(|entry| entry.receipt.state_digest == active_head)
            {
                return Err(ProductionOwnerError::InvalidReceipt);
            }
            owner.active_heads.insert(cell_id, active_head);
        }
        Ok(owner)
    }
}

fn publication_receipt(
    disposition: DefinitionPublicationDispositionV1,
    record: &CellDefinitionRecordV1,
) -> CellDefinitionPublicationReceiptV1 {
    let mut bytes = b"hepta.cell-definition-publication-receipt.v1".to_vec();
    bytes.extend_from_slice(record.definition.cell_id.as_str().as_bytes());
    bytes.extend_from_slice(&record.definition.generation.get().to_be_bytes());
    bytes.extend_from_slice(record.definition_digest.as_array());
    bytes.extend_from_slice(&record.sequence.get().to_be_bytes());
    bytes.extend_from_slice(record.predecessor_head_digest.as_array());
    bytes.extend_from_slice(record.chain_digest.as_array());
    CellDefinitionPublicationReceiptV1 {
        disposition,
        cell_id: record.definition.cell_id.clone(),
        generation: record.definition.generation,
        definition_digest: record.definition_digest,
        sequence: record.sequence,
        predecessor_head_digest: record.predecessor_head_digest,
        head_digest: record.chain_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn digest_definition_event(definition: &CellDefinitionV2, definition_digest: Digest32) -> Digest32 {
    let mut bytes = CELL_DEFINITION_REGISTRY_SCHEMA_V1.as_bytes().to_vec();
    bytes.extend_from_slice(definition.cell_id.as_str().as_bytes());
    bytes.extend_from_slice(&definition.generation.get().to_be_bytes());
    bytes.extend_from_slice(definition_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_chain(predecessor: Digest32, sequence: LogicalSequence, event: Digest32) -> Digest32 {
    let mut bytes = b"hepta.cell-definition-chain.v1".to_vec();
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.get().to_be_bytes());
    bytes.extend_from_slice(event.as_array());
    Digest32::of_bytes(&bytes)
}

fn path_digest(path: impl AsRef<Path>) -> Digest32 {
    Digest32::of_bytes(path.as_ref().to_string_lossy().as_bytes())
}

fn digest_receipt_fields(domain: &str, fields: &[&[u8]]) -> Vec<u8> {
    let mut bytes = domain.as_bytes().to_vec();
    for field in fields {
        bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        bytes.extend_from_slice(field);
    }
    bytes
}

fn require_production_evidence(
    host: Option<Digest32>,
    observer: Option<Digest32>,
) -> Result<(), ProductionOwnerError> {
    let (Some(host), Some(observer)) = (host, observer) else {
        return Err(ProductionOwnerError::InvalidReceipt);
    };
    if host.is_zero() || observer.is_zero() || host == observer {
        return Err(ProductionOwnerError::InvalidReceipt);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellRoleV1;
    use codex_hepta_types::CellUpdateModeV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn definition(generation: u64) -> CellDefinitionV2 {
        let digest = Digest32::of_bytes(&[generation as u8]);
        CellDefinitionV2 {
            cell_id: id("cell.owner"),
            generation: Generation::new(generation).expect("generation"),
            scope_digest: digest,
            lineage_digest: Digest32::of_bytes(b"lineage"),
            role: CellRoleV1::Representation,
            capability_profile: CellCapabilityProfileV1 {
                role: CellRoleV1::Representation,
                observation_schema_digest: digest,
                output_schema_digest: digest,
                state_schema_digest: digest,
                input_port_digest: digest,
                output_port_digest: digest,
                termination_port_digest: digest,
                owner_module: id("hepta.neuron"),
                persistence_class: CellPersistenceClassV1::Checkpointed,
                update_mode: CellUpdateModeV1::InferenceOnly,
                fallback_role: None,
                objective_digest: digest,
                resource_budget_digest: digest,
                evaluation_profile_digest: digest,
                authority: AuthorityPosture::DENY_ALL,
            },
            parameter_bundle_digest: digest,
            state_schema_digest: digest,
            port_abi_digest: digest,
            owner_module: id("hepta.neuron"),
            objective_digest: digest,
            fallback_role: None,
            evidence_owner: id("observer.owner"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn definition_publication_is_monotonic_and_replayable() {
        let mut owner = CellDefinitionOwnerV1::new();
        let first = owner.publish(definition(1)).expect("publish");
        assert_eq!(
            first.disposition,
            DefinitionPublicationDispositionV1::Appended
        );
        let replay = owner.publish(definition(1)).expect("replay");
        assert_eq!(
            replay.disposition,
            DefinitionPublicationDispositionV1::IdempotentReplay
        );
        owner.publish(definition(2)).expect("successor");
        let restored = CellDefinitionOwnerV1::from_snapshot(owner.snapshot()).expect("reload");
        assert_eq!(
            restored.latest(&id("cell.owner")),
            owner.latest(&id("cell.owner"))
        );
    }

    #[test]
    fn cas_write_load_and_revocation_are_fail_closed() {
        let key = SigningKey::from_bytes(&[7; 32]);
        let owner = ArtifactCasOwnerV1::new(id("artifact.owner"), key.clone()).expect("owner");
        let manifest = crate::ArtifactManifest {
            artifact_id: id("artifact.payload"),
            kind: crate::ArtifactKind::Model,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: Digest32::of_bytes(b"payload"),
            objective_digest: Digest32::of_bytes(b"objective"),
            support_digest: Digest32::of_bytes(b"support"),
            producer_id: id("producer"),
            compatibility_digest: Digest32::of_bytes(b"compat"),
            encoded_size_bytes: 7,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(crate::ArtifactEvent::Register {
                event_id: id("event.payload"),
                manifest,
            })
            .expect("register");
        let root_path = std::env::temp_dir().join(format!(
            "hepta-production-owner-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir(&root_path).expect("tempdir");
        let write = owner
            .write_candidate(
                id("operation.write"),
                &root_path,
                "payload.bin",
                &registry,
                &id("artifact.payload"),
                b"payload",
                None,
                None,
            )
            .expect("write");
        write.verify(&key.verifying_key()).expect("write verify");
        assert!(write.verify_production(&key.verifying_key()).is_err());
        let file = std::fs::File::open(root_path.join("payload.bin")).expect("open");
        let (bytes, load) = owner
            .load_candidate(
                id("operation.load"),
                file,
                &registry,
                &id("artifact.payload"),
                &write,
                "payload.bin",
                Some(Digest32::of_bytes(b"host")),
                Some(Digest32::of_bytes(b"observer")),
            )
            .expect("load");
        assert_eq!(bytes, b"payload");
        load.verify(&key.verifying_key()).expect("load verify");
        load.verify_production(&key.verifying_key())
            .expect("production load verify");
        std::fs::remove_dir_all(root_path).expect("cleanup");
    }

    #[test]
    fn state_commit_reloads_rolls_back_and_tombstones() {
        let key = SigningKey::from_bytes(&[8; 32]);
        let mut owner = StateCheckpointOwnerV1::new(id("state.owner"), key.clone()).expect("owner");
        let schema = Digest32::of_bytes(b"schema");
        let first = owner
            .commit(
                id("operation.state.1"),
                id("cell.state"),
                Generation::new(1).expect("generation"),
                schema,
                Digest32::ZERO,
                b"first".to_vec(),
                None,
                None,
            )
            .expect("commit");
        assert!(first.verify_production(&key.verifying_key()).is_err());
        let second = owner
            .commit(
                id("operation.state.2"),
                id("cell.state"),
                Generation::new(1).expect("generation"),
                schema,
                first.state_digest,
                b"second".to_vec(),
                None,
                None,
            )
            .expect("commit");
        assert_eq!(
            owner.reload(&id("cell.state"), &second).expect("reload"),
            b"second"
        );
        assert_eq!(
            owner.rollback(&id("cell.state"), &first).expect("rollback"),
            b"first"
        );
        let rolled_forward = owner
            .commit(
                id("operation.state.rolled-forward"),
                id("cell.state"),
                Generation::new(1).expect("generation"),
                schema,
                first.state_digest,
                b"rolled-forward".to_vec(),
                None,
                None,
            )
            .expect("commit after rollback");
        assert_eq!(
            owner
                .reload(&id("cell.state"), &rolled_forward)
                .expect("reload after rollback"),
            b"rolled-forward"
        );
        let snapshot = owner.snapshot();
        let tombstone = owner
            .tombstone(
                id("cell.state"),
                Generation::new(2).expect("generation"),
                Digest32::of_bytes(b"retire"),
            )
            .expect("tombstone");
        tombstone
            .verify(&key.verifying_key())
            .expect("tombstone verify");
        assert!(tombstone.verify_production(&key.verifying_key()).is_err());
        assert!(matches!(
            owner.commit(
                id("operation.state.3"),
                id("cell.state"),
                Generation::new(2).expect("generation"),
                schema,
                second.state_digest,
                b"third".to_vec(),
                None,
                None,
            ),
            Err(ProductionOwnerError::StateTombstoned(_))
        ));
        let reopened =
            StateCheckpointOwnerV1::from_snapshot(snapshot, id("state.owner"), key.clone())
                .expect("reopen before tombstone");
        assert_eq!(
            reopened
                .reload(&id("cell.state"), &rolled_forward)
                .expect("reload from append-only snapshot"),
            b"rolled-forward"
        );
        let tombstone_snapshot = owner.snapshot();
        let mut reopened_tombstoned =
            StateCheckpointOwnerV1::from_snapshot(tombstone_snapshot, id("state.owner"), key)
                .expect("reopen tombstone");
        assert!(matches!(
            reopened_tombstoned.commit(
                id("operation.state.after-reopen"),
                id("cell.state"),
                Generation::new(3).expect("generation"),
                schema,
                rolled_forward.state_digest,
                b"resurrection".to_vec(),
                None,
                None,
            ),
            Err(ProductionOwnerError::StateTombstoned(_))
        ));
    }
}
