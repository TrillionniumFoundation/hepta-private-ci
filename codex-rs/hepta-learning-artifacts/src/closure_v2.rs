//! Product-facing artifact closure types layered over the stable V1 registry.
//!
//! The V2 surface makes lineage, runtime identity, expiry, withdrawal and
//! anti-rollback facts independently inspectable instead of compressing them
//! into one opaque support digest. It still grants no selection, activation,
//! promotion or release authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::ArtifactKind;

const MAX_ARTIFACT_BYTES: u64 = 64 * 1024 * 1024;
const MAX_DATASET_INPUTS: usize = 64;
const MAX_LINEAGE_DIGESTS: usize = 1_024;
const MAX_PREDECESSORS: usize = 64;
const MAX_WITHDRAWALS: usize = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProvenanceModeV1 {
    DatasetDerived,
    DatasetIndependent,
}

impl ProvenanceModeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::DatasetDerived => 0,
            Self::DatasetIndependent => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactManifestV2 {
    pub artifact_id: StableId,
    pub kind: ArtifactKind,
    pub generation: Generation,
    pub provenance_mode: ProvenanceModeV1,
    pub source_dataset_digests: Vec<Digest32>,
    pub lineage_digests: Vec<Digest32>,
    pub predecessor_ids: Vec<StableId>,
    pub rollback_predecessor: Option<StableId>,
    pub bytes_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub training_code_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub device_profile_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub schema_profile_digest: Digest32,
    pub normalization_digest: Digest32,
    pub producer_id: StableId,
    pub created_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedArtifactManifestV2 {
    pub manifest: LearningArtifactManifestV2,
    pub manifest_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn validate_artifact_manifest_v2(
    mut manifest: LearningArtifactManifestV2,
    now: u64,
) -> Result<ValidatedArtifactManifestV2, ArtifactClosureError> {
    if manifest.encoded_size_bytes == 0 || manifest.encoded_size_bytes > MAX_ARTIFACT_BYTES {
        return Err(ArtifactClosureError::ArtifactSize);
    }
    if manifest.created_at > now
        || manifest.created_at > manifest.expires_at
        || now > manifest.expires_at
    {
        return Err(ArtifactClosureError::ManifestTimeWindow);
    }
    for (label, digest) in [
        ("artifact bytes", manifest.bytes_digest),
        ("training code", manifest.training_code_digest),
        ("runtime tuple", manifest.runtime_tuple_digest),
        ("device profile", manifest.device_profile_digest),
        ("objective class", manifest.objective_class_digest),
        ("compatibility", manifest.compatibility_digest),
        ("schema profile", manifest.schema_profile_digest),
        ("normalization", manifest.normalization_digest),
    ] {
        require_digest(digest, label)?;
    }
    if manifest.source_dataset_digests.len() > MAX_DATASET_INPUTS
        || manifest.lineage_digests.is_empty()
        || manifest.lineage_digests.len() > MAX_LINEAGE_DIGESTS
        || manifest.predecessor_ids.len() > MAX_PREDECESSORS
    {
        return Err(ArtifactClosureError::LineageLimit);
    }
    match manifest.provenance_mode {
        ProvenanceModeV1::DatasetDerived if manifest.source_dataset_digests.is_empty() => {
            return Err(ArtifactClosureError::DatasetProvenanceRequired);
        }
        ProvenanceModeV1::DatasetIndependent if !manifest.source_dataset_digests.is_empty() => {
            return Err(ArtifactClosureError::UnexpectedDatasetProvenance);
        }
        ProvenanceModeV1::DatasetDerived | ProvenanceModeV1::DatasetIndependent => {}
    }
    if manifest
        .source_dataset_digests
        .iter()
        .chain(manifest.lineage_digests.iter())
        .any(|digest| digest.is_zero())
    {
        return Err(ArtifactClosureError::EmptyDigest("artifact lineage"));
    }

    manifest.source_dataset_digests.sort_unstable();
    reject_duplicate_digests(&manifest.source_dataset_digests)?;
    manifest.lineage_digests.sort_unstable();
    reject_duplicate_digests(&manifest.lineage_digests)?;
    manifest.predecessor_ids.sort();
    reject_duplicate_ids(&manifest.predecessor_ids)?;
    if manifest
        .predecessor_ids
        .iter()
        .any(|predecessor| predecessor == &manifest.artifact_id)
    {
        return Err(ArtifactClosureError::SelfPredecessor);
    }
    if let Some(rollback) = &manifest.rollback_predecessor
        && !manifest.predecessor_ids.contains(rollback)
    {
        return Err(ArtifactClosureError::RollbackPredecessorMissing);
    }

    let manifest_digest = digest_manifest(&manifest)?;
    Ok(ValidatedArtifactManifestV2 {
        manifest,
        manifest_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalNoticeV1 {
    pub notice_id: StableId,
    pub dataset_digest: Digest32,
    pub source_tombstone_digest: Digest32,
    pub authority_id: StableId,
    pub credential_chain_digest: Digest32,
    pub signing_key_digest: Digest32,
    pub authority_epoch: u64,
    pub issued_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalRecordV1 {
    pub sequence: LogicalSequence,
    pub predecessor_chain_digest: Digest32,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
    pub notice: DatasetWithdrawalNoticeV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WithdrawalAppendDispositionV1 {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalReceiptV1 {
    pub disposition: WithdrawalAppendDispositionV1,
    pub sequence: LogicalSequence,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalRegistrySnapshotV1 {
    records: Vec<DatasetWithdrawalRecordV1>,
    pub head_digest: Digest32,
}

impl DatasetWithdrawalRegistrySnapshotV1 {
    #[must_use]
    pub fn records(&self) -> &[DatasetWithdrawalRecordV1] {
        &self.records
    }
}

#[derive(Clone, Debug, Default)]
pub struct DatasetWithdrawalRegistry {
    records: Vec<DatasetWithdrawalRecordV1>,
    notice_digests: BTreeMap<StableId, Digest32>,
    withdrawn_datasets: BTreeMap<Digest32, u64>,
}

impl DatasetWithdrawalRegistry {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn append(
        &mut self,
        notice: DatasetWithdrawalNoticeV1,
    ) -> Result<DatasetWithdrawalReceiptV1, ArtifactClosureError> {
        validate_withdrawal_notice(&notice)?;
        let event_digest = digest_withdrawal_notice(&notice);
        if let Some(existing) = self.notice_digests.get(&notice.notice_id) {
            if *existing != event_digest {
                return Err(ArtifactClosureError::WithdrawalIdentityConflict(
                    notice.notice_id.to_string(),
                ));
            }
            let record = self
                .records
                .iter()
                .find(|record| record.notice.notice_id == notice.notice_id)
                .ok_or(ArtifactClosureError::InternalInvariant)?;
            return Ok(withdrawal_receipt(
                record,
                WithdrawalAppendDispositionV1::IdempotentReplay,
            ));
        }
        if self.records.len() >= MAX_WITHDRAWALS {
            return Err(ArtifactClosureError::WithdrawalLimit);
        }
        let sequence_value = u64::try_from(self.records.len())
            .map_err(|_| ArtifactClosureError::Arithmetic)?
            .checked_add(1)
            .ok_or(ArtifactClosureError::Arithmetic)?;
        let sequence =
            LogicalSequence::new(sequence_value).map_err(|_| ArtifactClosureError::Arithmetic)?;
        let predecessor_chain_digest = self
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        let chain_digest =
            digest_withdrawal_chain(predecessor_chain_digest, sequence, event_digest);
        let record = DatasetWithdrawalRecordV1 {
            sequence,
            predecessor_chain_digest,
            event_digest,
            chain_digest,
            notice,
        };
        self.notice_digests
            .insert(record.notice.notice_id.clone(), event_digest);
        self.withdrawn_datasets
            .entry(record.notice.dataset_digest)
            .and_modify(|epoch| *epoch = (*epoch).max(record.notice.authority_epoch))
            .or_insert(record.notice.authority_epoch);
        let receipt = withdrawal_receipt(&record, WithdrawalAppendDispositionV1::Appended);
        self.records.push(record);
        Ok(receipt)
    }

    #[must_use]
    pub fn is_withdrawn(&self, dataset_digest: Digest32) -> bool {
        self.withdrawn_datasets.contains_key(&dataset_digest)
    }

    pub fn admit_manifest(
        &self,
        manifest: LearningArtifactManifestV2,
        now: u64,
    ) -> Result<ValidatedArtifactManifestV2, ArtifactClosureError> {
        let validated = validate_artifact_manifest_v2(manifest, now)?;
        if validated
            .manifest
            .source_dataset_digests
            .iter()
            .any(|digest| self.is_withdrawn(*digest))
        {
            return Err(ArtifactClosureError::WithdrawnDataset);
        }
        Ok(validated)
    }

    #[must_use]
    pub fn snapshot(&self) -> DatasetWithdrawalRegistrySnapshotV1 {
        DatasetWithdrawalRegistrySnapshotV1 {
            records: self.records.clone(),
            head_digest: self
                .records
                .last()
                .map_or(Digest32::ZERO, |record| record.chain_digest),
        }
    }

    pub fn from_snapshot(
        snapshot: DatasetWithdrawalRegistrySnapshotV1,
    ) -> Result<Self, ArtifactClosureError> {
        let expected_head = snapshot.head_digest;
        let mut registry = Self::new();
        for expected in snapshot.records {
            let receipt = registry.append(expected.notice.clone())?;
            let actual = registry
                .records
                .last()
                .ok_or(ArtifactClosureError::InternalInvariant)?;
            if actual != &expected || receipt.disposition != WithdrawalAppendDispositionV1::Appended
            {
                return Err(ArtifactClosureError::WithdrawalSnapshotMismatch);
            }
        }
        let actual_head = registry
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        if actual_head != expected_head {
            return Err(ArtifactClosureError::WithdrawalSnapshotMismatch);
        }
        Ok(registry)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryHeadWitnessV1 {
    pub registry_id: StableId,
    pub generation: Generation,
    pub head_digest: Digest32,
    pub predecessor_head_digest: Digest32,
    pub authority_epoch: u64,
    pub signer_id: StableId,
    pub signing_key_digest: Digest32,
    pub issued_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryHeadRequirementV1 {
    pub registry_id: StableId,
    pub minimum_generation: Generation,
    pub expected_predecessor_head_digest: Digest32,
    pub minimum_authority_epoch: u64,
    pub now: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryHeadReceiptV1 {
    pub witness_digest: Digest32,
    pub generation: Generation,
    pub authority_epoch: u64,
    pub authority: AuthorityPosture,
}

pub fn validate_registry_head_witness(
    witness: &RegistryHeadWitnessV1,
    requirement: &RegistryHeadRequirementV1,
) -> Result<RegistryHeadReceiptV1, ArtifactClosureError> {
    if witness.registry_id != requirement.registry_id {
        return Err(ArtifactClosureError::RegistryIdentityMismatch);
    }
    if witness.generation < requirement.minimum_generation {
        return Err(ArtifactClosureError::RegistryGenerationRollback);
    }
    if witness.authority_epoch < requirement.minimum_authority_epoch || witness.authority_epoch == 0
    {
        return Err(ArtifactClosureError::RegistryEpochRollback);
    }
    if witness.predecessor_head_digest != requirement.expected_predecessor_head_digest {
        return Err(ArtifactClosureError::RegistryPredecessorMismatch);
    }
    for (label, digest) in [
        ("registry head", witness.head_digest),
        ("registry signing key", witness.signing_key_digest),
    ] {
        require_digest(digest, label)?;
    }
    if witness.issued_at > requirement.now
        || witness.issued_at > witness.expires_at
        || requirement.now > witness.expires_at
    {
        return Err(ArtifactClosureError::RegistryWitnessTimeWindow);
    }

    let mut bytes = b"hepta.learning-artifacts.registry-head-witness.v1".to_vec();
    push_id(&mut bytes, &witness.registry_id);
    bytes.extend_from_slice(&witness.generation.get().to_be_bytes());
    bytes.extend_from_slice(witness.head_digest.as_array());
    bytes.extend_from_slice(witness.predecessor_head_digest.as_array());
    bytes.extend_from_slice(&witness.authority_epoch.to_be_bytes());
    push_id(&mut bytes, &witness.signer_id);
    bytes.extend_from_slice(witness.signing_key_digest.as_array());
    bytes.extend_from_slice(&witness.issued_at.to_be_bytes());
    bytes.extend_from_slice(&witness.expires_at.to_be_bytes());
    Ok(RegistryHeadReceiptV1 {
        witness_digest: Digest32::of_bytes(&bytes),
        generation: witness.generation,
        authority_epoch: witness.authority_epoch,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactLifecycleStateV1 {
    Proposed,
    Trained,
    Evaluated,
    Shadow,
    Canary,
    OperatorAccepted,
    Selected,
    Quarantined,
    Revoked,
    Retired,
}

impl ArtifactLifecycleStateV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Proposed => 0,
            Self::Trained => 1,
            Self::Evaluated => 2,
            Self::Shadow => 3,
            Self::Canary => 4,
            Self::OperatorAccepted => 5,
            Self::Selected => 6,
            Self::Quarantined => 7,
            Self::Revoked => 8,
            Self::Retired => 9,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLifecycleEventV1 {
    pub event_id: StableId,
    pub artifact_id: StableId,
    pub prior_state: ArtifactLifecycleStateV1,
    pub next_state: ArtifactLifecycleStateV1,
    pub actor_id: StableId,
    pub actor_credential_digest: Digest32,
    pub evidence_digest: Digest32,
    pub authority_epoch: u64,
    pub occurred_at: u64,
}

pub fn validate_artifact_lifecycle_transition(
    producer_id: &StableId,
    event: &ArtifactLifecycleEventV1,
) -> Result<Digest32, ArtifactClosureError> {
    for (label, digest) in [
        ("lifecycle actor credential", event.actor_credential_digest),
        ("lifecycle evidence", event.evidence_digest),
    ] {
        require_digest(digest, label)?;
    }
    if event.authority_epoch == 0 || event.occurred_at == 0 {
        return Err(ArtifactClosureError::InvalidLifecycleAuthority);
    }
    if event.actor_id == *producer_id
        && matches!(
            event.next_state,
            ArtifactLifecycleStateV1::Evaluated
                | ArtifactLifecycleStateV1::OperatorAccepted
                | ArtifactLifecycleStateV1::Selected
                | ArtifactLifecycleStateV1::Quarantined
                | ArtifactLifecycleStateV1::Revoked
        )
    {
        return Err(ArtifactClosureError::ProducerSelfDecision);
    }
    if !allowed_transition(event.prior_state, event.next_state) {
        return Err(ArtifactClosureError::InvalidLifecycleTransition);
    }

    let mut bytes = b"hepta.learning-artifacts.lifecycle-event.v1".to_vec();
    push_id(&mut bytes, &event.event_id);
    push_id(&mut bytes, &event.artifact_id);
    bytes.push(event.prior_state.tag());
    bytes.push(event.next_state.tag());
    push_id(&mut bytes, &event.actor_id);
    bytes.extend_from_slice(event.actor_credential_digest.as_array());
    bytes.extend_from_slice(event.evidence_digest.as_array());
    bytes.extend_from_slice(&event.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&event.occurred_at.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

const fn allowed_transition(
    prior: ArtifactLifecycleStateV1,
    next: ArtifactLifecycleStateV1,
) -> bool {
    matches!(
        (prior, next),
        (
            ArtifactLifecycleStateV1::Proposed,
            ArtifactLifecycleStateV1::Trained
        ) | (
            ArtifactLifecycleStateV1::Trained,
            ArtifactLifecycleStateV1::Evaluated
        ) | (
            ArtifactLifecycleStateV1::Evaluated,
            ArtifactLifecycleStateV1::Shadow
        ) | (
            ArtifactLifecycleStateV1::Shadow,
            ArtifactLifecycleStateV1::Canary
        ) | (
            ArtifactLifecycleStateV1::Canary,
            ArtifactLifecycleStateV1::OperatorAccepted
        ) | (
            ArtifactLifecycleStateV1::OperatorAccepted,
            ArtifactLifecycleStateV1::Selected
        ) | (
            ArtifactLifecycleStateV1::Selected,
            ArtifactLifecycleStateV1::Retired
        ) | (
            ArtifactLifecycleStateV1::Revoked,
            ArtifactLifecycleStateV1::Retired
        ) | (
            ArtifactLifecycleStateV1::Proposed
                | ArtifactLifecycleStateV1::Trained
                | ArtifactLifecycleStateV1::Evaluated
                | ArtifactLifecycleStateV1::Shadow
                | ArtifactLifecycleStateV1::Canary
                | ArtifactLifecycleStateV1::OperatorAccepted
                | ArtifactLifecycleStateV1::Selected,
            ArtifactLifecycleStateV1::Revoked
        ) | (
            ArtifactLifecycleStateV1::Proposed
                | ArtifactLifecycleStateV1::Trained
                | ArtifactLifecycleStateV1::Evaluated
                | ArtifactLifecycleStateV1::Shadow
                | ArtifactLifecycleStateV1::Canary,
            ArtifactLifecycleStateV1::Quarantined
        )
    )
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactClosureError {
    EmptyDigest(&'static str),
    ArtifactSize,
    ManifestTimeWindow,
    LineageLimit,
    DatasetProvenanceRequired,
    UnexpectedDatasetProvenance,
    DuplicateLineage,
    DuplicatePredecessor(String),
    SelfPredecessor,
    RollbackPredecessorMissing,
    WithdrawalIdentityConflict(String),
    WithdrawalLimit,
    WithdrawalSnapshotMismatch,
    WithdrawnDataset,
    RegistryIdentityMismatch,
    RegistryGenerationRollback,
    RegistryEpochRollback,
    RegistryPredecessorMismatch,
    RegistryWitnessTimeWindow,
    InvalidLifecycleAuthority,
    ProducerSelfDecision,
    InvalidLifecycleTransition,
    InternalInvariant,
    Arithmetic,
}

impl fmt::Display for ArtifactClosureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactClosureError {}

fn digest_manifest(
    manifest: &LearningArtifactManifestV2,
) -> Result<Digest32, ArtifactClosureError> {
    let mut bytes = b"hepta.learning-artifacts.manifest.v2".to_vec();
    push_id(&mut bytes, &manifest.artifact_id);
    bytes.push(manifest.kind.tag());
    bytes.extend_from_slice(&manifest.generation.get().to_be_bytes());
    bytes.push(manifest.provenance_mode.tag());
    push_digest_vec(&mut bytes, &manifest.source_dataset_digests)?;
    push_digest_vec(&mut bytes, &manifest.lineage_digests)?;
    push_id_vec(&mut bytes, &manifest.predecessor_ids)?;
    push_optional_id(&mut bytes, manifest.rollback_predecessor.as_ref());
    for digest in [
        manifest.bytes_digest,
        manifest.training_code_digest,
        manifest.runtime_tuple_digest,
        manifest.device_profile_digest,
        manifest.objective_class_digest,
        manifest.compatibility_digest,
        manifest.schema_profile_digest,
        manifest.normalization_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&manifest.encoded_size_bytes.to_be_bytes());
    push_id(&mut bytes, &manifest.producer_id);
    bytes.extend_from_slice(&manifest.created_at.to_be_bytes());
    bytes.extend_from_slice(&manifest.expires_at.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_withdrawal_notice(
    notice: &DatasetWithdrawalNoticeV1,
) -> Result<(), ArtifactClosureError> {
    for (label, digest) in [
        ("withdrawn dataset", notice.dataset_digest),
        ("source tombstone", notice.source_tombstone_digest),
        ("withdrawal credential", notice.credential_chain_digest),
        ("withdrawal signing key", notice.signing_key_digest),
    ] {
        require_digest(digest, label)?;
    }
    if notice.authority_epoch == 0 || notice.issued_at == 0 {
        return Err(ArtifactClosureError::RegistryEpochRollback);
    }
    Ok(())
}

fn digest_withdrawal_notice(notice: &DatasetWithdrawalNoticeV1) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.dataset-withdrawal.v1".to_vec();
    push_id(&mut bytes, &notice.notice_id);
    bytes.extend_from_slice(notice.dataset_digest.as_array());
    bytes.extend_from_slice(notice.source_tombstone_digest.as_array());
    push_id(&mut bytes, &notice.authority_id);
    bytes.extend_from_slice(notice.credential_chain_digest.as_array());
    bytes.extend_from_slice(notice.signing_key_digest.as_array());
    bytes.extend_from_slice(&notice.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&notice.issued_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_withdrawal_chain(
    predecessor: Digest32,
    sequence: LogicalSequence,
    event_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.dataset-withdrawal-chain.v1".to_vec();
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.get().to_be_bytes());
    bytes.extend_from_slice(event_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn withdrawal_receipt(
    record: &DatasetWithdrawalRecordV1,
    disposition: WithdrawalAppendDispositionV1,
) -> DatasetWithdrawalReceiptV1 {
    DatasetWithdrawalReceiptV1 {
        disposition,
        sequence: record.sequence,
        event_digest: record.event_digest,
        chain_digest: record.chain_digest,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn reject_duplicate_digests(values: &[Digest32]) -> Result<(), ArtifactClosureError> {
    if values.windows(2).any(|adjacent| adjacent[0] == adjacent[1]) {
        return Err(ArtifactClosureError::DuplicateLineage);
    }
    Ok(())
}

fn reject_duplicate_ids(values: &[StableId]) -> Result<(), ArtifactClosureError> {
    if let Some(adjacent) = values
        .windows(2)
        .find(|adjacent| adjacent[0] == adjacent[1])
    {
        return Err(ArtifactClosureError::DuplicatePredecessor(
            adjacent[0].to_string(),
        ));
    }
    Ok(())
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), ArtifactClosureError> {
    if digest.is_zero() {
        return Err(ArtifactClosureError::EmptyDigest(label));
    }
    Ok(())
}

fn push_digest_vec(bytes: &mut Vec<u8>, values: &[Digest32]) -> Result<(), ArtifactClosureError> {
    bytes.extend_from_slice(
        &u32::try_from(values.len())
            .map_err(|_| ArtifactClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for value in values {
        bytes.extend_from_slice(value.as_array());
    }
    Ok(())
}

fn push_id_vec(bytes: &mut Vec<u8>, values: &[StableId]) -> Result<(), ArtifactClosureError> {
    bytes.extend_from_slice(
        &u32::try_from(values.len())
            .map_err(|_| ArtifactClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for value in values {
        push_id(bytes, value);
    }
    Ok(())
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "closure_v2_tests.rs"]
mod tests;
