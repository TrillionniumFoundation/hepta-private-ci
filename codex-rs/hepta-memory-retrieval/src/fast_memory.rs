//! Opt-in bounded numeric association state, independent of frozen model bytes.
//!
//! The host owns this value, persistence, current owner authentication and replay
//! eligibility. A snapshot/digest is a binding, never a credential. Every use must
//! receive the current owner snapshot; any generation drift requires an explicit
//! reset/rebuild. Numerical predictions are not facts. Final content still needs
//! owner revalidation. This normalized delta rule is not a Titans reproduction.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::MAX_GENERATION_BOUND_CANDIDATES;
use crate::MemoryCueV1;
use crate::RecallPacketV1;
use crate::RetrievalCandidateIdentityV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalPolicyV1;
use crate::recall;

const MAGIC: &[u8; 8] = b"HPTFM001";
const HEADER_BYTES: usize = 112;
const MAX_WIDTH: usize = 64;
const WEIGHT_BOUND: f64 = 8.0;
const SCHEMA: &[u8] = b"hepta.fast-memory.checkpoint.v1.f64-be";
const RULE: &[u8] = b"normalized-delta.v1:W'=clip(decay*W+eta*(y-Wk)*k/max(1,k.k),-8,8)";

#[derive(Clone, Debug, PartialEq)]
pub struct FastMemoryConfigV1 {
    pub owner_id: StableId,
    pub state_id: StableId,
    pub base_model_digest: Digest32,
    /// Bind an explicit no-adapter identity when no adapter is selected.
    pub adapter_digest: Digest32,
    pub key_width: usize,
    pub value_width: usize,
    pub learning_rate: f64,
    pub decay: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FastMemoryV1 {
    config: FastMemoryConfigV1,
    snapshot: CognitiveSnapshotKeyV1,
    binding: Digest32,
    sequence: u64,
    predecessor: Digest32,
    support_chain: Digest32,
    weights: Vec<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FastMemoryPredictionV1 {
    pub values: Vec<f64>,
    pub state_digest: Digest32,
    /// Scalar multiplications in the numeric kernel; excludes hashing and I/O.
    pub scalar_multiplications: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FastMemoryUpdateV1 {
    pub before: Digest32,
    pub after: Digest32,
    pub sequence: u64,
    pub squared_error: f64,
    pub scalar_multiplications: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FastMemoryCandidateV1 {
    pub candidate: RetrievalChannelCandidateV1,
    pub features: Vec<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FastMemoryScoreV1 {
    pub identity: RetrievalCandidateIdentityV1,
    pub score: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FastMemoryRecallV1 {
    /// Unmodified recall preserves its original policy checks and digest.
    pub base_recall: RecallPacketV1,
    /// Only a permutation of base_recall selections; no new fact is introduced.
    pub ranked: Vec<FastMemoryScoreV1>,
    pub state_digest: Digest32,
    pub scalar_multiplications: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FastMemoryErrorV1 {
    InvalidConfig,
    InvalidVector,
    SnapshotMismatch,
    StaleState,
    InvalidCheckpoint,
    InvalidReset,
    InvalidSupport,
    SequenceOverflow,
    CandidateFeatures,
    Recall(String),
}

impl fmt::Display for FastMemoryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for FastMemoryErrorV1 {}

impl FastMemoryV1 {
    pub fn new(
        config: FastMemoryConfigV1,
        snapshot: CognitiveSnapshotKeyV1,
    ) -> Result<Self, FastMemoryErrorV1> {
        if !(1..=MAX_WIDTH).contains(&config.key_width)
            || !(1..=MAX_WIDTH).contains(&config.value_width)
            || !config.learning_rate.is_finite()
            || config.learning_rate <= 0.0
            || config.learning_rate > 1.0
            || !config.decay.is_finite()
            || !(0.0..=1.0).contains(&config.decay)
            || config.base_model_digest.is_zero()
            || config.adapter_digest.is_zero()
        {
            return Err(FastMemoryErrorV1::InvalidConfig);
        }
        snapshot
            .validate()
            .map_err(|_| FastMemoryErrorV1::SnapshotMismatch)?;
        let mut bytes = Vec::new();
        for part in [
            SCHEMA,
            RULE,
            config.owner_id.as_str().as_bytes(),
            config.state_id.as_str().as_bytes(),
        ] {
            bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
            bytes.extend_from_slice(part);
        }
        for digest in [
            config.base_model_digest,
            config.adapter_digest,
            snapshot.vector_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for width in [config.key_width, config.value_width] {
            bytes.extend_from_slice(&(width as u64).to_be_bytes());
        }
        for value in [config.learning_rate, config.decay] {
            bytes.extend_from_slice(&canonical(value).to_be_bytes());
        }
        Ok(Self {
            weights: vec![0.0; config.key_width * config.value_width],
            config,
            snapshot,
            binding: Digest32::of_bytes(&bytes),
            sequence: 0,
            predecessor: Digest32::ZERO,
            support_chain: Digest32::ZERO,
        })
    }

    pub fn state_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.checkpoint())
    }

    pub fn checkpoint(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(HEADER_BYTES + 8 * self.weights.len());
        bytes.extend_from_slice(MAGIC);
        bytes.extend_from_slice(self.binding.as_array());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(self.predecessor.as_array());
        bytes.extend_from_slice(self.support_chain.as_array());
        for weight in &self.weights {
            bytes.extend_from_slice(&canonical(*weight).to_be_bytes());
        }
        bytes
    }

    /// expected_anchor must come from an independent current owner witness, not
    /// from hashing these same untrusted bytes. This method opens no file.
    pub fn restore(
        config: FastMemoryConfigV1,
        current: CognitiveSnapshotKeyV1,
        bytes: &[u8],
        expected_anchor: Digest32,
    ) -> Result<Self, FastMemoryErrorV1> {
        let mut restored = Self::new(config, current)?;
        if bytes.len() != HEADER_BYTES + 8 * restored.weights.len()
            || bytes.get(..8) != Some(MAGIC.as_slice())
            || bytes.get(8..40) != Some(restored.binding.as_array().as_slice())
            || Digest32::of_bytes(bytes) != expected_anchor
        {
            return Err(FastMemoryErrorV1::InvalidCheckpoint);
        }
        restored.sequence = u64::from_be_bytes(
            bytes[40..48]
                .try_into()
                .map_err(|_| FastMemoryErrorV1::InvalidCheckpoint)?,
        );
        restored.predecessor = Digest32::from_array(
            bytes[48..80]
                .try_into()
                .map_err(|_| FastMemoryErrorV1::InvalidCheckpoint)?,
        );
        restored.support_chain = Digest32::from_array(
            bytes[80..112]
                .try_into()
                .map_err(|_| FastMemoryErrorV1::InvalidCheckpoint)?,
        );
        for (weight, chunk) in restored
            .weights
            .iter_mut()
            .zip(bytes[HEADER_BYTES..].chunks_exact(8))
        {
            *weight = f64::from_be_bytes(
                chunk
                    .try_into()
                    .map_err(|_| FastMemoryErrorV1::InvalidCheckpoint)?,
            );
            if !weight.is_finite() || weight.abs() > WEIGHT_BOUND {
                return Err(FastMemoryErrorV1::InvalidCheckpoint);
            }
        }
        let empty = restored.sequence == 0;
        if empty != restored.support_chain.is_zero()
            || (empty && restored.weights.iter().any(|weight| *weight != 0.0))
            || (!empty && restored.predecessor.is_zero())
            || restored.checkpoint() != bytes
        {
            return Err(FastMemoryErrorV1::InvalidCheckpoint);
        }
        Ok(restored)
    }

    /// Reset preserves frozen model/encoder and owner scope, creates a new state
    /// identity, and carries only predecessor identity, never numerical state.
    pub fn reset(
        &self,
        current: CognitiveSnapshotKeyV1,
        state_id: StableId,
    ) -> Result<Self, FastMemoryErrorV1> {
        let old = &self.snapshot.vector;
        let new = &current.vector;
        if state_id == self.config.state_id
            || old.scope_id != new.scope_id
            || old.purpose_id != new.purpose_id
            || old.model_digest != new.model_digest
            || old.encoder_preprocessor_digest != new.encoder_preprocessor_digest
            || new.authority_epoch < old.authority_epoch
            || new.tombstone_frontier < old.tombstone_frontier
            || new.memory_ledger_frontier < old.memory_ledger_frontier
            || new.source_ledger_frontier < old.source_ledger_frontier
            || new.knowledge_fact_frontier < old.knowledge_fact_frontier
            || new.knowledge_graph_generation < old.knowledge_graph_generation
            || new.compact_checkpoint_generation < old.compact_checkpoint_generation
            || new.prompt_registry_revision < old.prompt_registry_revision
        {
            return Err(FastMemoryErrorV1::InvalidReset);
        }
        let mut config = self.config.clone();
        config.state_id = state_id;
        let mut reset = Self::new(config, current)?;
        reset.predecessor = self.state_digest();
        Ok(reset)
    }

    pub fn predict(
        &self,
        current: &CognitiveSnapshotKeyV1,
        key: &[f64],
    ) -> Result<FastMemoryPredictionV1, FastMemoryErrorV1> {
        current
            .validate()
            .map_err(|_| FastMemoryErrorV1::SnapshotMismatch)?;
        if current != &self.snapshot {
            return Err(FastMemoryErrorV1::SnapshotMismatch);
        }
        validate_vector(key, self.config.key_width)?;
        Ok(FastMemoryPredictionV1 {
            values: self
                .weights
                .chunks_exact(self.config.key_width)
                .map(|row| {
                    row.iter()
                        .zip(key)
                        .map(|(weight, input)| weight * input)
                        .sum()
                })
                .collect(),
            state_digest: self.state_digest(),
            scalar_multiplications: self.weights.len() as u64,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// The host must revalidate training/replay eligibility immediately before
    /// calling. support_digest binds that evidence; it does not authenticate it.
    pub fn update(
        &mut self,
        current: &CognitiveSnapshotKeyV1,
        expected_state: Digest32,
        key: &[f64],
        target: &[f64],
        support_digest: Digest32,
    ) -> Result<FastMemoryUpdateV1, FastMemoryErrorV1> {
        let prediction = self.predict(current, key)?;
        if expected_state != prediction.state_digest {
            return Err(FastMemoryErrorV1::StaleState);
        }
        validate_vector(target, self.config.value_width)?;
        if support_digest.is_zero() {
            return Err(FastMemoryErrorV1::InvalidSupport);
        }
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or(FastMemoryErrorV1::SequenceOverflow)?;
        let norm = key.iter().map(|value| value * value).sum::<f64>().max(1.0);
        let mut squared_error = 0.0;
        for (row, (target, predicted)) in self
            .weights
            .chunks_exact_mut(self.config.key_width)
            .zip(target.iter().zip(&prediction.values))
        {
            let error = target - predicted;
            squared_error += error * error;
            let step = self.config.learning_rate * error / norm;
            for (weight, input) in row.iter_mut().zip(key) {
                *weight = canonical(
                    (self.config.decay * *weight + step * input).clamp(-WEIGHT_BOUND, WEIGHT_BOUND),
                );
            }
        }
        let mut support = b"hepta.fast-memory.support-chain.v1".to_vec();
        support.extend_from_slice(self.support_chain.as_array());
        support.extend_from_slice(support_digest.as_array());
        for value in key.iter().chain(target) {
            support.extend_from_slice(&canonical(*value).to_be_bytes());
        }
        self.support_chain = Digest32::of_bytes(&support);
        self.predecessor = prediction.state_digest;
        self.sequence = sequence;
        Ok(FastMemoryUpdateV1 {
            before: prediction.state_digest,
            after: self.state_digest(),
            sequence,
            squared_error,
            scalar_multiplications: (3 * self.weights.len()
                + self.config.key_width
                + 2 * self.config.value_width) as u64,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn rerank(
        &self,
        cue: &MemoryCueV1,
        policy: &RetrievalPolicyV1,
        key: &[f64],
        candidates: &[FastMemoryCandidateV1],
    ) -> Result<FastMemoryRecallV1, FastMemoryErrorV1> {
        if candidates.len() > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(FastMemoryErrorV1::CandidateFeatures);
        }
        let prediction = self.predict(&cue.snapshot_key, key)?;
        let mut features = BTreeMap::new();
        for row in candidates {
            validate_vector(&row.features, self.config.value_width)?;
            let record = &row.candidate.record;
            record
                .validate()
                .map_err(|error| FastMemoryErrorV1::Recall(error.to_string()))?;
            let identity = RetrievalCandidateIdentityV1 {
                record_id: record.record_id.clone(),
                record_revision: record.revision,
                record_digest: record.record_digest(),
            };
            if let Some(previous) = features.insert(identity, &row.features)
                && previous != &row.features
            {
                return Err(FastMemoryErrorV1::CandidateFeatures);
            }
        }
        let base_recall = recall(
            cue,
            policy,
            candidates.iter().map(|row| row.candidate.clone()).collect(),
        )
        .map_err(|error| FastMemoryErrorV1::Recall(error.to_string()))?;
        let mut ranked = Vec::new();
        for selection in &base_recall.selections {
            let identity = RetrievalCandidateIdentityV1 {
                record_id: selection.record_id.clone(),
                record_revision: selection.record_revision,
                record_digest: selection.record_digest,
            };
            let vector = features
                .get(&identity)
                .ok_or(FastMemoryErrorV1::CandidateFeatures)?;
            let score = prediction
                .values
                .iter()
                .zip(*vector)
                .map(|(value, feature)| value * feature)
                .sum();
            ranked.push(FastMemoryScoreV1 { identity, score });
        }
        ranked.sort_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.identity.cmp(&right.identity))
        });
        Ok(FastMemoryRecallV1 {
            scalar_multiplications: prediction.scalar_multiplications
                + (ranked.len() * self.config.value_width) as u64,
            base_recall,
            ranked,
            state_digest: prediction.state_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

fn validate_vector(values: &[f64], width: usize) -> Result<(), FastMemoryErrorV1> {
    if values.len() != width
        || values
            .iter()
            .any(|value| !value.is_finite() || value.abs() > 1.0)
    {
        return Err(FastMemoryErrorV1::InvalidVector);
    }
    Ok(())
}

fn canonical(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

#[cfg(test)]
#[path = "fast_memory_tests.rs"]
mod tests;
