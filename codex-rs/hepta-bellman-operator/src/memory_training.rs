//! Source-bound tensor training plans derived from the current learning owner.
//! This module admits immutable candidates, never installs or selects a model.
use std::fmt;

use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryTrainingProfileV1 {
    pub job_id: StableId,
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub predecessor_generation: Generation,
    pub generation: Generation,
    pub objective_digest: Digest32,
    pub base_digest: Digest32,
    pub encoder_digest: Digest32,
    pub trainer_digest: Digest32,
    pub scope_digest: Digest32,
    pub maximum_steps: u32,
    pub maximum_tokens_per_step: u32,
    pub maximum_payload_bytes: u64,
    pub expires_at: u64,
}

/// The source owner supplies these bytes only after checking a training-use grant.
/// This input is not itself an authority token; Agentd binds it to a source use.
pub struct MemoryTrainingSourceV1 {
    pub support_digest: Digest32,
    pub content_digest: Digest32,
    pub content: String,
}

/// Only the validating freeze function can construct this immutable job.
#[derive(Clone)]
pub struct FrozenMemoryTrainingV1 {
    profile: MemoryTrainingProfileV1,
    dataset: DatasetSnapshotReceiptV3,
    source_support: Digest32,
    content_digest: Digest32,
    content: String,
    job_digest: Digest32,
}
impl fmt::Debug for FrozenMemoryTrainingV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("FrozenMemoryTrainingV1")
            .field("profile", &self.profile)
            .field("job_digest", &self.job_digest)
            .field("source_bytes", &self.content.len())
            .finish_non_exhaustive()
    }
}
impl FrozenMemoryTrainingV1 {
    pub fn profile(&self) -> &MemoryTrainingProfileV1 {
        &self.profile
    }
    pub fn dataset(&self) -> &DatasetSnapshotReceiptV3 {
        &self.dataset
    }
    pub fn source_text(&self) -> &str {
        &self.content
    }
    pub fn source_support(&self) -> Digest32 {
        self.source_support
    }
    pub fn content_digest(&self) -> Digest32 {
        self.content_digest
    }
    pub fn job_digest(&self) -> Digest32 {
        self.job_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryTrainingObservationV1 {
    pub job_digest: Digest32,
    pub base_digest: Digest32,
    pub frozen_base_after_digest: Digest32,
    pub encoder_digest: Digest32,
    pub trainer_digest: Digest32,
    pub payload_digest: Digest32,
    pub payload_bytes: u64,
    pub completed_steps: u32,
    pub consumed_tokens: u64,
    pub trainable_parameters: u64,
    pub changed_parameters: u64,
}

#[derive(Clone, Debug)]
pub struct MemoryTensorCandidateV1 {
    frozen: FrozenMemoryTrainingV1,
    observation: MemoryTrainingObservationV1,
}
impl MemoryTensorCandidateV1 {
    pub fn frozen(&self) -> &FrozenMemoryTrainingV1 {
        &self.frozen
    }
    pub fn observation(&self) -> &MemoryTrainingObservationV1 {
        &self.observation
    }
}

#[derive(Debug)]
pub enum MemoryTrainingError {
    Ledger(ProductionLedgerError),
    Invalid(&'static str),
}
impl fmt::Display for MemoryTrainingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for MemoryTrainingError {}
impl From<ProductionLedgerError> for MemoryTrainingError {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}

pub fn freeze_memory_training_from_owner_v1(
    ledger: &LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    profile: MemoryTrainingProfileV1,
    source: MemoryTrainingSourceV1,
    now: u64,
) -> Result<FrozenMemoryTrainingV1, MemoryTrainingError> {
    ledger.revalidate_dataset_snapshot(dataset, now)?;
    if Some(profile.generation.get()) != profile.predecessor_generation.get().checked_add(1)
        || profile.objective_digest != dataset.snapshot.objective_digest
        || [
            profile.objective_digest,
            profile.base_digest,
            profile.encoder_digest,
            profile.trainer_digest,
            profile.scope_digest,
            source.support_digest,
            source.content_digest,
        ]
        .iter()
        .copied()
        .any(Digest32::is_zero)
        || profile.maximum_steps == 0
        || profile.maximum_steps > 256
        || profile.maximum_tokens_per_step < 2
        || profile.maximum_tokens_per_step > 4096
        || profile.maximum_payload_bytes == 0
        || profile.maximum_payload_bytes > 64 * 1024 * 1024
        || profile.expires_at <= now
        || profile.expires_at - now > 3600
        || source.content.is_empty()
        || source.content.len() > 1024 * 1024
        || Digest32::of_bytes(source.content.as_bytes()) != source.content_digest
        || dataset.snapshot.source_record_digests.len() > 4096
    {
        return Err(MemoryTrainingError::Invalid(
            "training profile/source bounds",
        ));
    }
    let mut decisions = 0;
    for record in ledger.read_dataset_records(dataset, now)? {
        if let LedgerEvent::AuthenticatedDecisionV2(value) = &record.event {
            if value.support_digest != source.support_digest
                || value.objective_digest != profile.objective_digest
            {
                return Err(MemoryTrainingError::Invalid(
                    "source support/objective mismatch",
                ));
            }
            decisions += 1;
        }
    }
    if decisions == 0 {
        return Err(MemoryTrainingError::Invalid(
            "no authenticated source decision",
        ));
    }
    let mut bytes = b"hepta.memory-training.job.v1\0".to_vec();
    for id in [&profile.job_id, &profile.artifact_id, &profile.producer_id] {
        bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    for digest in [
        dataset.snapshot.dataset_digest,
        source.support_digest,
        source.content_digest,
        profile.objective_digest,
        profile.base_digest,
        profile.encoder_digest,
        profile.trainer_digest,
        profile.scope_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for n in [
        profile.predecessor_generation.get(),
        profile.generation.get(),
        u64::from(profile.maximum_steps),
        u64::from(profile.maximum_tokens_per_step),
        profile.maximum_payload_bytes,
        profile.expires_at,
    ] {
        bytes.extend_from_slice(&n.to_be_bytes());
    }
    Ok(FrozenMemoryTrainingV1 {
        profile,
        dataset: dataset.clone(),
        source_support: source.support_digest,
        content_digest: source.content_digest,
        content: source.content,
        job_digest: Digest32::of_bytes(&bytes),
    })
}

/// Validate a trainer observation and exact payload after rechecking the owner.
/// Tensor semantics are independently checked by the admitted backend/consumer;
/// unsigned counters here do not prove training execution or model quality.
pub fn finish_memory_training_from_owner_v1(
    ledger: &LedgerWriter,
    frozen: FrozenMemoryTrainingV1,
    observation: MemoryTrainingObservationV1,
    payload: &[u8],
    now: u64,
) -> Result<MemoryTensorCandidateV1, MemoryTrainingError> {
    ledger.revalidate_dataset_snapshot(&frozen.dataset, now)?;
    let p = &frozen.profile;
    if now >= p.expires_at
        || observation.job_digest != frozen.job_digest
        || observation.base_digest != p.base_digest
        || observation.frozen_base_after_digest != p.base_digest
        || observation.encoder_digest != p.encoder_digest
        || observation.trainer_digest != p.trainer_digest
        || observation.payload_digest != Digest32::of_bytes(payload)
        || observation.payload_bytes != payload.len() as u64
        || payload.is_empty()
        || observation.payload_bytes > p.maximum_payload_bytes
        || observation.completed_steps == 0
        || observation.completed_steps > p.maximum_steps
        || observation.consumed_tokens < u64::from(observation.completed_steps) * 2
        || observation.consumed_tokens
            > u64::from(observation.completed_steps) * u64::from(p.maximum_tokens_per_step)
        || observation.trainable_parameters == 0
        || observation.trainable_parameters > 16_777_216
        || observation.changed_parameters == 0
        || observation.changed_parameters > observation.trainable_parameters
    {
        return Err(MemoryTrainingError::Invalid(
            "trainer observation/payload binding",
        ));
    }
    Ok(MemoryTensorCandidateV1 {
        frozen,
        observation,
    })
}
