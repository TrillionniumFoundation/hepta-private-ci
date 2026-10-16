//! Research-only user-space admission of original Granite97 export, reviewed
//! physical-replay bytes and independent Cell Head artifacts into one V3 Reader.
//!
//! The JSON admission record is NOT an authority grant. Callers must obtain its
//! exact bytes, model/source identities and physical review SHA from their own
//! independent owner. Even internally matching digests can be fabricated by
//! an untrusted single producer; selection/FinalUse remain inaccessible.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_infer_core::sequence_feature_v3::FeatureModalityV3;
use codex_hepta_infer_core::sequence_feature_v3::FeatureSequenceIdentityV3;
use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::GraniteFeatureExpectationV5;
use super::GraniteReviewAdmissionV6;
use super::SequenceAttentionPolicyV3;
use super::SequenceCellHeadV3;
use super::SequenceHeadBindingV3;
use super::SequenceHeadParametersV3;
use super::read_independently_reviewed_granite_v6;

const MAX_ADMISSION_BYTES: usize = 1_000_000;
const MAX_SOURCE_BYTES: usize = 65_536;
const MAX_HEADS: usize = 32;
const STEM_WIDTH: usize = 384;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CellHeadSourceV7 {
    cell_id: String,
    attention: String,
    query_q24: Vec<i64>,
    key_q24: Vec<i64>,
    value_q24: Vec<i64>,
    local_q24: Vec<i64>,
    bias_q24: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IndependentReviewAdmissionV7 {
    schema: String,
    principal_id: String,
    purpose_id: String,
    generation: u64,
    authority_epoch: u64,
    /// Material/feature/receipt digests must originate from an external owner,
    /// not be learned from untrusted producer content while admitting it.
    material_digest: String,
    source_digest: String,
    complete_input_digest: String,
    tokenizer_digest: String,
    normalizer_digest: String,
    quantization_digest: String,
    preprocessing_digest: String,
    adapter_digest: String,
    export_bytes_digest: String,
    independent_review_bytes_digest: String,
    maximum_expires_at_ms: u64,
    maximum_attention_pairs: u64,
    heads: Vec<CellHeadSourceV7>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ShadowCellSummaryV7 {
    pub cell_id: String,
    pub head_digest: String,
    pub score_q24: i64,
    pub attention_pairs: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct GraniteShadowSummaryV7 {
    pub schema: &'static str,
    pub model_digest: String,
    pub original_source_digest: String,
    pub admission_bytes_digest: String,
    pub complete_input_digest: String,
    pub exported_bytes_digest: String,
    pub independently_reviewed_bytes_digest: String,
    pub sequence_content_digest: String,
    pub reader_observation_digest: String,
    pub gate_receipt_digest: String,
    pub q24_payload_bytes: usize,
    pub actual_reader_attention_pairs: u64,
    pub claimed_reviewer_encoder_forwards: u64,
    pub claimed_reviewer_encoder_cpu_ns: u64,
    pub claimed_reviewer_encoder_wall_ns: u64,
    pub claimed_original_weight_tensors: usize,
    pub cells: Vec<ShadowCellSummaryV7>,
    pub authority: &'static str,
    pub model_selected: bool,
    pub production_authorized: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShadowAdmissionErrorV7 {
    MalformedAdmission,
    InvalidIdentity,
    InvalidSource,
    InvalidHead,
    InvalidReview,
}

impl fmt::Display for ShadowAdmissionErrorV7 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for ShadowAdmissionErrorV7 {}

fn digest(raw: &str) -> Result<Digest32, ShadowAdmissionErrorV7> {
    let value = Digest32::from_str(raw).map_err(|_| ShadowAdmissionErrorV7::InvalidIdentity)?;
    if value.is_zero() || value.to_string() != raw {
        return Err(ShadowAdmissionErrorV7::InvalidIdentity);
    }
    Ok(value)
}

/// Evaluate only already-submitted local bytes, no filesystem/network/clock
/// lookup, grant mutation or model dispatch. The caller must provide a trusted
/// fresh clock; the CLI uses its local wall clock rather than a caller's claim.
/// This gate checks the *content* of a separately reviewed response, not the
/// cryptographic authenticity of the reviewer or its runtime measurements.
pub fn read_shadow_granite_v3_v7(
    independent_admission: &[u8],
    original_source: &[u8],
    exported_json: &[u8],
    independently_reviewed_json: &[u8],
    now_ms: u64,
) -> Result<GraniteShadowSummaryV7, ShadowAdmissionErrorV7> {
    if independent_admission.is_empty() || independent_admission.len() > MAX_ADMISSION_BYTES {
        return Err(ShadowAdmissionErrorV7::MalformedAdmission);
    }
    if original_source.is_empty() || original_source.len() > MAX_SOURCE_BYTES || now_ms == 0 {
        return Err(ShadowAdmissionErrorV7::InvalidSource);
    }
    let admitted: IndependentReviewAdmissionV7 = serde_json::from_slice(independent_admission)
        .map_err(|_| ShadowAdmissionErrorV7::MalformedAdmission)?;
    if admitted.schema != "hepta.stem.granite-v3-local-admission.v7"
        || admitted.heads.is_empty()
        || admitted.heads.len() > MAX_HEADS
        || admitted.maximum_attention_pairs == 0
        || admitted.maximum_attention_pairs > 2_000_000
        || admitted.maximum_expires_at_ms <= now_ms
    {
        return Err(ShadowAdmissionErrorV7::MalformedAdmission);
    }
    if Digest32::of_bytes(original_source) != digest(&admitted.source_digest)? {
        return Err(ShadowAdmissionErrorV7::InvalidSource);
    }
    let principal = StableId::new(admitted.principal_id)
        .map_err(|_| ShadowAdmissionErrorV7::InvalidIdentity)?;
    let purpose =
        StableId::new(admitted.purpose_id).map_err(|_| ShadowAdmissionErrorV7::InvalidIdentity)?;
    let generation = Generation::new(admitted.generation)
        .map_err(|_| ShadowAdmissionErrorV7::InvalidIdentity)?;
    let material = digest(&admitted.material_digest)?;
    let encoder = super::granite97_encoder_identity_v5(material);
    let tokenizer = digest(&admitted.tokenizer_digest)?;
    let normalizer = digest(&admitted.normalizer_digest)?;
    let quantization = digest(&admitted.quantization_digest)?;
    let preprocessing = digest(&admitted.preprocessing_digest)?;
    let adapter = digest(&admitted.adapter_digest)?;
    let input_digest = digest(&admitted.complete_input_digest)?;
    let identity = FeatureSequenceIdentityV3 {
        base: SharedFeatureIdentityV2 {
            principal_id: principal,
            purpose_id: purpose,
            generation,
            authority_epoch: admitted.authority_epoch,
            encoder_digest: encoder,
            tokenizer_digest: tokenizer,
            normalizer_digest: normalizer,
            quantization_digest: quantization,
            input_digest,
        },
        modality: FeatureModalityV3::Text,
        preprocessing_digest: preprocessing,
        adapter_digest: adapter,
    };
    identity
        .digest()
        .map_err(|_| ShadowAdmissionErrorV7::InvalidIdentity)?;
    let mut heads = Vec::with_capacity(admitted.heads.len());
    for candidate in admitted.heads {
        if [
            &candidate.query_q24,
            &candidate.key_q24,
            &candidate.value_q24,
            &candidate.local_q24,
        ]
        .iter()
        .any(|weights| weights.len() != STEM_WIDTH)
        {
            return Err(ShadowAdmissionErrorV7::InvalidHead);
        }
        let attention = match candidate.attention.as_str() {
            "causal" => SequenceAttentionPolicyV3::Causal,
            "bidirectional" => SequenceAttentionPolicyV3::Bidirectional,
            _ => return Err(ShadowAdmissionErrorV7::InvalidHead),
        };
        let head = SequenceCellHeadV3::new(
            SequenceHeadBindingV3 {
                cell_id: StableId::new(candidate.cell_id)
                    .map_err(|_| ShadowAdmissionErrorV7::InvalidHead)?,
                encoder_digest: encoder,
                tokenizer_digest: tokenizer,
                normalizer_digest: normalizer,
                quantization_digest: quantization,
                preprocessing_digest: preprocessing,
                adapter_digest: adapter,
                modality: FeatureModalityV3::Text,
                attention,
            },
            SequenceHeadParametersV3 {
                query_q24: candidate.query_q24,
                key_q24: candidate.key_q24,
                value_q24: candidate.value_q24,
                local_q24: candidate.local_q24,
                bias_q24: candidate.bias_q24,
            },
        )
        .map_err(|_| ShadowAdmissionErrorV7::InvalidHead)?;
        heads.push(Arc::new(head));
    }
    let feature_expectation = GraniteFeatureExpectationV5 {
        identity,
        source_bytes: original_source.to_vec(),
        material_digest: material,
        now_ms,
        maximum_expires_at_ms: admitted.maximum_expires_at_ms,
    };
    let review_admission = GraniteReviewAdmissionV6 {
        feature: feature_expectation,
        admitted_export_digest: digest(&admitted.export_bytes_digest)?,
        admitted_review_digest: digest(&admitted.independent_review_bytes_digest)?,
    };
    let result = read_independently_reviewed_granite_v6(
        exported_json,
        independently_reviewed_json,
        &review_admission,
        &heads,
        admitted.maximum_attention_pairs,
    )
    .map_err(|_| ShadowAdmissionErrorV7::InvalidReview)?;
    if result.authority.grants_any() || result.reader.authority.grants_any() {
        return Err(ShadowAdmissionErrorV7::InvalidReview);
    }
    let admission_digest = Digest32::of_bytes(independent_admission);
    let shadow_receipt_digest = Digest32::of_parts(&[
        b"hepta.stem.shadow-gate-receipt.v7\0",
        admission_digest.as_array(),
        result.receipt_digest.as_array(),
    ]);
    let mut cells = Vec::with_capacity(result.reader.cells.len());
    for observation in &result.reader.cells {
        cells.push(ShadowCellSummaryV7 {
            cell_id: observation.cell_id.to_string(),
            head_digest: observation.head_digest.to_string(),
            score_q24: observation.score_q24,
            attention_pairs: observation.attention_pairs,
        });
    }
    Ok(GraniteShadowSummaryV7 {
        schema: "hepta.stem.granite-v3-local-shadow-result.v7",
        model_digest: encoder.to_string(),
        original_source_digest: Digest32::of_bytes(original_source).to_string(),
        admission_bytes_digest: admission_digest.to_string(),
        complete_input_digest: input_digest.to_string(),
        exported_bytes_digest: result.exported_bytes_digest.to_string(),
        independently_reviewed_bytes_digest: result.review_bytes_digest.to_string(),
        sequence_content_digest: result.feature_content_digest.to_string(),
        reader_observation_digest: result.reader.observation_digest.to_string(),
        gate_receipt_digest: shadow_receipt_digest.to_string(),
        q24_payload_bytes: result.reader.feature_payload_bytes,
        actual_reader_attention_pairs: result.reader.attention_pairs,
        claimed_reviewer_encoder_forwards: result.reviewer_encoder_forwards,
        claimed_reviewer_encoder_cpu_ns: result.reviewer_encoder_cpu_ns,
        claimed_reviewer_encoder_wall_ns: result.reviewer_encoder_wall_ns,
        claimed_original_weight_tensors: result.reviewer_original_tensor_count,
        cells,
        authority: "DENY_ALL",
        model_selected: false,
        production_authorized: false,
    })
}

#[cfg(test)]
#[path = "model_worker_granite_v7_tests.rs"]
mod tests;
