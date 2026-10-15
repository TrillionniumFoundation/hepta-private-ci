//! Research-only sequence-aware CPU Reader for immutable shared Stem features.
//!
//! Unlike pooled V1/V2, this operator consumes the ordered rows, masks, and
//! spatial/temporal coordinates of FeatureSequence V3. It runs real bounded
//! fixed-point Q24 arithmetic for independently parameterized Cell heads.
//! It does NOT run an Encoder, train weights, authenticate feature producers,
//! validate final-use grants, dispatch a worker, or execute external effects.
//! The caller must independently admit every model/source/use before invoking it.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_infer_core::sequence_feature_v3::FeatureModalityV3;
use codex_hepta_infer_core::sequence_feature_v3::FeatureSequenceIdentityV3;
use codex_hepta_infer_core::sequence_feature_v3::ImmutableFeatureSequenceV3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const Q24: i64 = 1 << 24;
const Q24_BOUND: i64 = 8 * Q24;
const MAX_WIDTH: usize = 512;
const MAX_ACTIVE_HEADS: usize = 32;
const MAX_ATTENTION_PAIRS: u64 = 2_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SequenceAttentionPolicyV3 {
    /// A row may consume only itself and preceding, unmasked rows.
    Causal,
    /// All unmasked rows may exchange information, with coordinate weighting.
    Bidirectional,
}

/// Immutable artifact binding. A digest binds the bytes; it is NOT a signature.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequenceHeadBindingV3 {
    pub cell_id: StableId,
    pub encoder_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub normalizer_digest: Digest32,
    pub quantization_digest: Digest32,
    pub preprocessing_digest: Digest32,
    pub adapter_digest: Digest32,
    pub modality: FeatureModalityV3,
    pub attention: SequenceAttentionPolicyV3,
}

/// Four scalar projections over every row (4*d trainable coefficients) and bias.
/// No parameters are mutated during inference.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequenceHeadParametersV3 {
    pub query_q24: Vec<i64>,
    pub key_q24: Vec<i64>,
    pub value_q24: Vec<i64>,
    pub local_q24: Vec<i64>,
    pub bias_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequenceCellHeadV3 {
    binding: SequenceHeadBindingV3,
    parameters: SequenceHeadParametersV3,
    width: usize,
    digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequenceReadFenceV3 {
    pub now_ms: u64,
    pub expected_identity: FeatureSequenceIdentityV3,
    pub expected_content_digest: Digest32,
    /// The admitted budget, never above the static hard cap.
    pub maximum_attention_pairs: u64,
}

/// A non-authorizing numeric observation, not a proven learning or GPU receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequenceCellObservationV3 {
    pub cell_id: StableId,
    pub head_digest: Digest32,
    pub score_q24: i64,
    pub attention_pairs: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequenceBatchObservationV3 {
    pub feature_identity_digest: Digest32,
    pub feature_content_digest: Digest32,
    pub cells: Vec<SequenceCellObservationV3>,
    pub attention_pairs: u64,
    /// Canonical feature payload size, NOT observed worker RSS.
    pub feature_payload_bytes: usize,
    pub observation_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SequenceReadErrorV3 {
    InvalidHead,
    InvalidFeatureIdentity,
    StaleFeature,
    ContentMismatch,
    IncompatibleHead,
    DuplicateCell,
    BudgetExceeded,
    Arithmetic,
}

impl fmt::Display for SequenceReadErrorV3 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for SequenceReadErrorV3 {}

impl SequenceCellHeadV3 {
    pub fn new(
        binding: SequenceHeadBindingV3,
        parameters: SequenceHeadParametersV3,
    ) -> Result<Self, SequenceReadErrorV3> {
        if [
            binding.encoder_digest,
            binding.tokenizer_digest,
            binding.normalizer_digest,
            binding.quantization_digest,
            binding.preprocessing_digest,
            binding.adapter_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
        {
            return Err(SequenceReadErrorV3::InvalidHead);
        }
        let width = parameters.query_q24.len();
        if width == 0
            || width > MAX_WIDTH
            || [
                &parameters.key_q24,
                &parameters.value_q24,
                &parameters.local_q24,
            ]
            .iter()
            .any(|values| values.len() != width)
            || [
                &parameters.query_q24,
                &parameters.key_q24,
                &parameters.value_q24,
                &parameters.local_q24,
            ]
            .iter()
            .flat_map(|values| values.iter())
            .any(|value| !(-Q24..=Q24).contains(value))
            || !(-Q24_BOUND..=Q24_BOUND).contains(&parameters.bias_q24)
        {
            return Err(SequenceReadErrorV3::InvalidHead);
        }
        let mut bytes = b"hepta.infer.sequence-cell-head.q24.v3\0".to_vec();
        let id = binding.cell_id.as_str().as_bytes();
        bytes.extend_from_slice(
            &u32::try_from(id.len())
                .map_err(|_| SequenceReadErrorV3::InvalidHead)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(id);
        for digest in [
            binding.encoder_digest,
            binding.tokenizer_digest,
            binding.normalizer_digest,
            binding.quantization_digest,
            binding.preprocessing_digest,
            binding.adapter_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(binding.modality as u8);
        bytes.push(match binding.attention {
            SequenceAttentionPolicyV3::Causal => 1,
            SequenceAttentionPolicyV3::Bidirectional => 2,
        });
        bytes.extend_from_slice(&(width as u64).to_be_bytes());
        for weights in [
            &parameters.query_q24,
            &parameters.key_q24,
            &parameters.value_q24,
            &parameters.local_q24,
        ] {
            for weight in weights {
                bytes.extend_from_slice(&weight.to_be_bytes());
            }
        }
        bytes.extend_from_slice(&parameters.bias_q24.to_be_bytes());
        Ok(Self {
            binding,
            parameters,
            width,
            digest: Digest32::of_bytes(&bytes),
        })
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    #[must_use]
    pub fn cell_id(&self) -> &StableId {
        &self.binding.cell_id
    }

    #[must_use]
    pub fn parameter_count(&self) -> usize {
        self.width * 4 + 1
    }

    /// Pure manifest compatibility used by the Encoder before any forward.
    /// This is model identity only: it does not authenticate a producer/grant.
    pub(crate) fn compatible_with(
        &self,
        identity: &FeatureSequenceIdentityV3,
        width: usize,
    ) -> bool {
        self.width == width
            && self.binding.encoder_digest == identity.base.encoder_digest
            && self.binding.tokenizer_digest == identity.base.tokenizer_digest
            && self.binding.normalizer_digest == identity.base.normalizer_digest
            && self.binding.quantization_digest == identity.base.quantization_digest
            && self.binding.preprocessing_digest == identity.preprocessing_digest
            && self.binding.adapter_digest == identity.adapter_digest
            && self.binding.modality == identity.modality
    }

    pub(crate) fn attention_pairs_for(&self, active_rows: u64) -> u64 {
        match self.binding.attention {
            SequenceAttentionPolicyV3::Causal => active_rows * (active_rows + 1) / 2,
            SequenceAttentionPolicyV3::Bidirectional => active_rows * active_rows,
        }
    }
}

/// One borrowed immutable Arc input feeds every Cell. This is a physical Q24
/// Reader computation, but NOT an authenticated physical Transformer forward.
/// All identity, model compatibility, count and work checks precede arithmetic.
/// A failed batch returns no partial observations.
pub fn evaluate_sequence_heads_v3(
    fence: &SequenceReadFenceV3,
    snapshot: &Arc<ImmutableFeatureSequenceV3>,
    heads: &[Arc<SequenceCellHeadV3>],
) -> Result<SequenceBatchObservationV3, SequenceReadErrorV3> {
    if heads.is_empty() || heads.len() > MAX_ACTIVE_HEADS {
        return Err(SequenceReadErrorV3::BudgetExceeded);
    }
    if fence.maximum_attention_pairs == 0
        || fence.maximum_attention_pairs > MAX_ATTENTION_PAIRS
    {
        return Err(SequenceReadErrorV3::BudgetExceeded);
    }
    let identity_digest = fence
        .expected_identity
        .digest()
        .map_err(|_| SequenceReadErrorV3::InvalidFeatureIdentity)?;
    if snapshot.identity() != &fence.expected_identity {
        return Err(SequenceReadErrorV3::InvalidFeatureIdentity);
    }
    if fence.now_ms >= snapshot.expires_at_ms() {
        return Err(SequenceReadErrorV3::StaleFeature);
    }
    if fence.expected_content_digest.is_zero()
        || fence.expected_content_digest != snapshot.content_digest()
    {
        return Err(SequenceReadErrorV3::ContentMismatch);
    }

    let (rows, width) = snapshot.shape();
    let valid = snapshot.mask().iter().filter(|mask| **mask == 1).count() as u64;
    let mut seen = BTreeSet::new();
    let mut expected_pairs = 0_u64;
    for head in heads {
        if !seen.insert(head.cell_id().clone()) {
            return Err(SequenceReadErrorV3::DuplicateCell);
        }
        if !head.compatible_with(&fence.expected_identity, width) {
            return Err(SequenceReadErrorV3::IncompatibleHead);
        }
        let count = head.attention_pairs_for(valid);
        expected_pairs = expected_pairs
            .checked_add(count)
            .ok_or(SequenceReadErrorV3::Arithmetic)?;
    }
    if expected_pairs > fence.maximum_attention_pairs {
        return Err(SequenceReadErrorV3::BudgetExceeded);
    }

    let mut cells = Vec::with_capacity(heads.len());
    for head in heads {
        let (score, pairs) = score_head(snapshot, rows, head)?;
        cells.push(SequenceCellObservationV3 {
            cell_id: head.cell_id().clone(),
            head_digest: head.digest,
            score_q24: score,
            attention_pairs: pairs,
        });
    }
    let actual_pairs = cells.iter().map(|cell| cell.attention_pairs).sum();
    if actual_pairs != expected_pairs {
        return Err(SequenceReadErrorV3::Arithmetic);
    }
    let mut bytes = b"hepta.infer.sequence-batch-observation.v3\0".to_vec();
    bytes.extend_from_slice(identity_digest.as_array());
    bytes.extend_from_slice(snapshot.content_digest().as_array());
    bytes.extend_from_slice(&(snapshot.payload_bytes() as u64).to_be_bytes());
    bytes.extend_from_slice(&snapshot.expires_at_ms().to_be_bytes());
    bytes.extend_from_slice(&fence.now_ms.to_be_bytes());
    bytes.extend_from_slice(&fence.maximum_attention_pairs.to_be_bytes());
    bytes.extend_from_slice(&actual_pairs.to_be_bytes());
    for cell in &cells {
        let id = cell.cell_id.as_str().as_bytes();
        let id_len = u32::try_from(id.len()).map_err(|_| SequenceReadErrorV3::Arithmetic)?;
        bytes.extend_from_slice(&id_len.to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(cell.head_digest.as_array());
        bytes.extend_from_slice(&cell.score_q24.to_be_bytes());
        bytes.extend_from_slice(&cell.attention_pairs.to_be_bytes());
    }
    Ok(SequenceBatchObservationV3 {
        feature_identity_digest: identity_digest,
        feature_content_digest: snapshot.content_digest(),
        cells,
        attention_pairs: actual_pairs,
        feature_payload_bytes: snapshot.payload_bytes(),
        observation_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn score_head(
    snapshot: &ImmutableFeatureSequenceV3,
    rows: usize,
    head: &SequenceCellHeadV3,
) -> Result<(i64, u64), SequenceReadErrorV3> {
    let width = head.width;
    let mask = snapshot.mask();
    let values = snapshot.values_q24();
    let mut query = vec![0_i64; rows];
    let mut key = vec![0_i64; rows];
    let mut value = vec![0_i64; rows];
    let mut local = vec![0_i64; rows];
    for target in 0..rows {
        if mask[target] == 0 {
            continue;
        }
        let row = &values[target * width..(target + 1) * width];
        query[target] = dot(&head.parameters.query_q24, row)?;
        key[target] = dot(&head.parameters.key_q24, row)?;
        value[target] = dot(&head.parameters.value_q24, row)?;
        local[target] = dot(&head.parameters.local_q24, row)?;
    }
    let mut total = 0_i128;
    let mut count = 0_i128;
    let mut pairs = 0_u64;
    for target in 0..rows {
        if mask[target] == 0 {
            continue;
        }
        let mut weighted_value = 0_i128;
        let mut weight_total = 0_i128;
        for source in 0..rows {
            if mask[source] == 0
                || (head.binding.attention == SequenceAttentionPolicyV3::Causal
                    && source > target)
            {
                continue;
            }
            pairs += 1;
            let similarity = mul_q24(query[target], key[source])?.clamp(-Q24, Q24);
            let distance = relative_distance_divisor(
                head.binding.modality,
                snapshot.coordinates()[source],
                snapshot.coordinates()[target],
            );
            let weight = (Q24 + similarity) / distance;
            weighted_value += i128::from(weight) * i128::from(value[source]);
            weight_total += i128::from(weight);
        }
        let relation = if weight_total > 0 {
            round_div(weighted_value, weight_total)?
        } else {
            0
        };
        let mixed = (i128::from(relation) + i128::from(local[target])) / 2
            + i128::from(head.parameters.bias_q24);
        total += mixed.clamp(-i128::from(Q24_BOUND), i128::from(Q24_BOUND));
        count += 1;
    }
    if count == 0 {
        return Err(SequenceReadErrorV3::InvalidFeatureIdentity);
    }
    let result = round_div(total, count)?.clamp(-Q24_BOUND, Q24_BOUND);
    Ok((result, pairs))
}

fn dot(weights: &[i64], features: &[i64]) -> Result<i64, SequenceReadErrorV3> {
    let sum = weights.iter().zip(features).fold(0_i128, |acc, (weight, feature)| {
        acc + i128::from(*weight) * i128::from(*feature)
    });
    Ok(round_div(sum, i128::from(Q24))?.clamp(-Q24_BOUND, Q24_BOUND))
}

fn mul_q24(lhs: i64, rhs: i64) -> Result<i64, SequenceReadErrorV3> {
    round_div(
        i128::from(lhs) * i128::from(rhs),
        i128::from(Q24),
    )
}

fn round_div(value: i128, divisor: i128) -> Result<i64, SequenceReadErrorV3> {
    if divisor <= 0 {
        return Err(SequenceReadErrorV3::Arithmetic);
    }
    let magnitude = value.abs();
    let quotient = magnitude / divisor;
    let remainder = magnitude % divisor;
    let round_up = remainder * 2 > divisor
        || (remainder * 2 == divisor && quotient % 2 != 0);
    let increment = if round_up { 1_i128 } else { 0_i128 };
    let signed = (quotient + increment) * value.signum();
    i64::try_from(signed).map_err(|_| SequenceReadErrorV3::Arithmetic)
}

/// Fixed distance buckets are a reference kernel, not a trained metric.
/// Full coordinates are already included in the immutable content digest.
fn relative_distance_divisor(
    modality: FeatureModalityV3,
    source: codex_hepta_infer_core::sequence_feature_v3::FeatureCoordinatesV3,
    target: codex_hepta_infer_core::sequence_feature_v3::FeatureCoordinatesV3,
) -> i64 {
    let spatial = u64::from(source.x.abs_diff(target.x))
        + u64::from(source.y.abs_diff(target.y));
    let temporal = source.time_micros.abs_diff(target.time_micros);
    let distance = match modality {
        FeatureModalityV3::Text => 0,
        FeatureModalityV3::Image => spatial / 256,
        FeatureModalityV3::Audio => temporal / 100_000,
        FeatureModalityV3::Video | FeatureModalityV3::Multimodal => {
            spatial / 256 + temporal / 100_000
        }
    };
    1 + distance.min(1_000_000) as i64
}

#[cfg(test)]
#[path = "model_worker_sequence_v3_tests.rs"]
mod tests;
