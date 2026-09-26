//! Deterministic, owner-bound vector candidate generation.
//!
//! The vector owner is deliberately read-only.  It accepts a sealed snapshot
//! produced by the encoder/index owner, verifies the exact generation and model
//! binding, and emits one bounded `EncoderVector` generator batch.  It never
//! invents records, freshness, or out-of-distribution evidence.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

use crate::MAX_GENERATION_BOUND_CANDIDATES;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalGeneratorBatchV1;
use crate::RetrievalGeneratorOwnerV1;
use crate::RetrievalGeneratorReceiptV1;
use crate::RetrievalSourceCompletenessV1;

pub const MAX_VECTOR_DIMENSIONS: usize = 4096;
pub const MAX_VECTOR_INDEX_RECORDS: usize = 16_384;

const VECTOR_INDEX_DOMAIN: &[u8] = b"hepta.memory-retrieval.vector-index.v1";
const VECTOR_SUPPORT_DOMAIN: &[u8] = b"hepta.memory-retrieval.vector-support.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VectorIndexRecordV1 {
    pub record: MemoryRecord,
    /// Q32 components in the closed interval [-1, 1].
    pub embedding: Vec<FixedQ32>,
    /// Calibrated owner-supplied OOD probability for this indexed record.
    pub ood: ProbabilityQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VectorIndexSnapshotV1 {
    pub generation_vector_digest: Digest32,
    pub owner_generation_digest: Digest32,
    pub model_digest: Digest32,
    pub dimensions: u32,
    pub records: Vec<VectorIndexRecordV1>,
    pub index_digest: Digest32,
}

impl VectorIndexSnapshotV1 {
    pub fn new(
        generation_vector_digest: Digest32,
        owner_generation_digest: Digest32,
        model_digest: Digest32,
        dimensions: u32,
        mut records: Vec<VectorIndexRecordV1>,
    ) -> Result<Self, VectorOwnerErrorV1> {
        records.sort_by(|left, right| {
            left.record
                .record_id
                .cmp(&right.record.record_id)
                .then_with(|| left.record.revision.cmp(&right.record.revision))
        });
        let mut value = Self {
            generation_vector_digest,
            owner_generation_digest,
            model_digest,
            dimensions,
            records,
            index_digest: Digest32::ZERO,
        };
        value.index_digest = value.compute_index_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), VectorOwnerErrorV1> {
        ensure_digest("generation vector", self.generation_vector_digest)?;
        ensure_digest("owner generation", self.owner_generation_digest)?;
        ensure_digest("model", self.model_digest)?;
        let dimensions = usize::try_from(self.dimensions)
            .map_err(|_| VectorOwnerErrorV1::InvalidDimensions)?;
        if dimensions == 0 || dimensions > MAX_VECTOR_DIMENSIONS {
            return Err(VectorOwnerErrorV1::InvalidDimensions);
        }
        if self.records.len() > MAX_VECTOR_INDEX_RECORDS {
            return Err(VectorOwnerErrorV1::IndexLimitExceeded);
        }

        let mut identities = BTreeSet::new();
        let mut previous = None;
        for row in &self.records {
            row.record
                .validate()
                .map_err(|error| VectorOwnerErrorV1::InvalidRecord(error.to_string()))?;
            if row.record.state != RecordState::Live {
                return Err(VectorOwnerErrorV1::TombstoneRecord(
                    row.record.record_id.to_string(),
                ));
            }
            if row.embedding.len() != dimensions {
                return Err(VectorOwnerErrorV1::EmbeddingDimensionMismatch(
                    row.record.record_id.to_string(),
                ));
            }
            validate_embedding(&row.embedding)?;
            let identity = (row.record.record_id.clone(), row.record.revision);
            if !identities.insert(identity.clone()) {
                return Err(VectorOwnerErrorV1::DuplicateRecord(
                    row.record.record_id.to_string(),
                ));
            }
            if previous.as_ref().is_some_and(|value| value >= &identity) {
                return Err(VectorOwnerErrorV1::NonCanonicalRecordOrder);
            }
            previous = Some(identity);
        }
        if self.index_digest != self.compute_index_digest() {
            return Err(VectorOwnerErrorV1::DigestMismatch("vector index"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_index_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(VECTOR_INDEX_DOMAIN);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.owner_generation_digest);
        push_digest(&mut bytes, self.model_digest);
        bytes.extend_from_slice(&self.dimensions.to_be_bytes());
        push_len(&mut bytes, self.records.len());
        for row in &self.records {
            push_id(&mut bytes, row.record.record_id.as_str());
            bytes.extend_from_slice(&row.record.revision.get().to_be_bytes());
            push_digest(&mut bytes, row.record.record_digest());
            bytes.extend_from_slice(&row.ood.raw().to_be_bytes());
            push_len(&mut bytes, row.embedding.len());
            for component in &row.embedding {
                bytes.extend_from_slice(&component.raw().to_be_bytes());
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VectorQueryV1 {
    pub query_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_digest: Digest32,
    pub embedding: Vec<FixedQ32>,
    pub maximum_candidates: u32,
    pub maximum_ood: ProbabilityQ32,
}

impl VectorQueryV1 {
    pub fn validate(&self) -> Result<(), VectorOwnerErrorV1> {
        ensure_digest("query", self.query_digest)?;
        ensure_digest("generation vector", self.generation_vector_digest)?;
        ensure_digest("model", self.model_digest)?;
        if self.embedding.is_empty() || self.embedding.len() > MAX_VECTOR_DIMENSIONS {
            return Err(VectorOwnerErrorV1::InvalidDimensions);
        }
        validate_embedding(&self.embedding)?;
        let maximum_candidates = usize::try_from(self.maximum_candidates)
            .map_err(|_| VectorOwnerErrorV1::InvalidCandidateLimit)?;
        if maximum_candidates == 0 || maximum_candidates > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(VectorOwnerErrorV1::InvalidCandidateLimit);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum VectorOwnerErrorV1 {
    EmptyDigest(&'static str),
    InvalidDimensions,
    InvalidCandidateLimit,
    IndexLimitExceeded,
    InvalidRecord(String),
    TombstoneRecord(String),
    DuplicateRecord(String),
    NonCanonicalRecordOrder,
    EmbeddingDimensionMismatch(String),
    ComponentOutOfRange,
    GenerationVectorMismatch,
    ModelMismatch,
    DigestMismatch(&'static str),
    Arithmetic,
    Generator(String),
}

impl fmt::Display for VectorOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for VectorOwnerErrorV1 {}

pub fn generate_vector_batch_v1(
    snapshot: &VectorIndexSnapshotV1,
    query: &VectorQueryV1,
) -> Result<RetrievalGeneratorBatchV1, VectorOwnerErrorV1> {
    snapshot.validate()?;
    query.validate()?;
    if query.generation_vector_digest != snapshot.generation_vector_digest {
        return Err(VectorOwnerErrorV1::GenerationVectorMismatch);
    }
    if query.model_digest != snapshot.model_digest {
        return Err(VectorOwnerErrorV1::ModelMismatch);
    }
    if query.embedding.len()
        != usize::try_from(snapshot.dimensions)
            .map_err(|_| VectorOwnerErrorV1::InvalidDimensions)?
    {
        return Err(VectorOwnerErrorV1::InvalidDimensions);
    }

    let mut scored = snapshot
        .records
        .iter()
        .filter(|row| row.ood <= query.maximum_ood)
        .map(|row| {
            Ok((
                row,
                similarity_score(&query.embedding, &row.embedding)?,
            ))
        })
        .collect::<Result<Vec<_>, VectorOwnerErrorV1>>()?;
    scored.sort_by(|left, right| {
        right
            .1
            .cmp(&left.1)
            .then_with(|| left.0.record.record_id.cmp(&right.0.record.record_id))
            .then_with(|| left.0.record.revision.cmp(&right.0.record.revision))
    });

    let available = scored.len();
    scored.truncate(
        usize::try_from(query.maximum_candidates)
            .map_err(|_| VectorOwnerErrorV1::InvalidCandidateLimit)?,
    );
    let completeness = if scored.len() < available {
        RetrievalSourceCompletenessV1::LimitReached
    } else {
        RetrievalSourceCompletenessV1::Exhausted
    };
    let candidate_count = u32::try_from(scored.len())
        .map_err(|_| VectorOwnerErrorV1::InvalidCandidateLimit)?;
    let receipt = RetrievalGeneratorReceiptV1::new(
        RetrievalGeneratorOwnerV1::EncoderVector,
        snapshot.generation_vector_digest,
        snapshot.owner_generation_digest,
        candidate_count,
        completeness,
    )
    .map_err(|error| VectorOwnerErrorV1::Generator(error.to_string()))?;

    let candidates = scored
        .into_iter()
        .enumerate()
        .map(|(index, (row, score))| {
            let rank = u32::try_from(index + 1)
                .map_err(|_| VectorOwnerErrorV1::InvalidCandidateLimit)?;
            Ok(RetrievalChannelCandidateV1 {
                record: row.record.clone(),
                channel: RetrievalChannelV1::Vector,
                channel_rank: rank,
                normalized_score: score,
                ood: row.ood,
                support_digest: support_digest(snapshot, query, row, score),
                contradiction_group_digest: None,
                generation_vector_digest: snapshot.generation_vector_digest,
            })
        })
        .collect::<Result<Vec<_>, VectorOwnerErrorV1>>()?;
    let batch = RetrievalGeneratorBatchV1 {
        receipt,
        candidates,
    };
    batch
        .validate()
        .map_err(|error| VectorOwnerErrorV1::Generator(error.to_string()))?;
    Ok(batch)
}

fn similarity_score(
    query: &[FixedQ32],
    record: &[FixedQ32],
) -> Result<FixedQ32, VectorOwnerErrorV1> {
    if query.len() != record.len() || query.is_empty() {
        return Err(VectorOwnerErrorV1::InvalidDimensions);
    }
    let total_distance = query
        .iter()
        .zip(record)
        .try_fold(0_i128, |sum, (left, right)| {
            let distance = (i128::from(left.raw()) - i128::from(right.raw())).abs();
            sum.checked_add(distance)
                .ok_or(VectorOwnerErrorV1::Arithmetic)
        })?;
    let dimensions = i128::try_from(query.len()).map_err(|_| VectorOwnerErrorV1::Arithmetic)?;
    // Components are in [-1, 1], so average L1 distance is in [0, 2].
    // Map it monotonically to [1, 0] without floating point.
    let normalized_distance = total_distance
        .checked_div(dimensions)
        .and_then(|value| value.checked_div(2))
        .ok_or(VectorOwnerErrorV1::Arithmetic)?;
    let one = i128::from(FixedQ32::ONE.raw());
    let raw = one.saturating_sub(normalized_distance).clamp(0, one);
    Ok(FixedQ32::from_raw(
        i64::try_from(raw).map_err(|_| VectorOwnerErrorV1::Arithmetic)?,
    ))
}

fn validate_embedding(embedding: &[FixedQ32]) -> Result<(), VectorOwnerErrorV1> {
    let bound = FixedQ32::ONE.raw();
    if embedding
        .iter()
        .any(|value| value.raw() < -bound || value.raw() > bound)
    {
        return Err(VectorOwnerErrorV1::ComponentOutOfRange);
    }
    Ok(())
}

fn support_digest(
    snapshot: &VectorIndexSnapshotV1,
    query: &VectorQueryV1,
    row: &VectorIndexRecordV1,
    score: FixedQ32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(VECTOR_SUPPORT_DOMAIN);
    push_digest(&mut bytes, snapshot.index_digest);
    push_digest(&mut bytes, query.query_digest);
    push_digest(&mut bytes, row.record.record_digest());
    bytes.extend_from_slice(&score.raw().to_be_bytes());
    bytes.extend_from_slice(&row.ood.raw().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn ensure_digest(name: &'static str, value: Digest32) -> Result<(), VectorOwnerErrorV1> {
    if value.is_zero() {
        return Err(VectorOwnerErrorV1::EmptyDigest(name));
    }
    Ok(())
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    push_len(bytes, value.len());
    bytes.extend_from_slice(value.as_bytes());
}
