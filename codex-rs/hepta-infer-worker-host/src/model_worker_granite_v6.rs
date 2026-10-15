//! Research-only composition of one Granite97 V5 export, one independently
//! admitted physical-review receipt, and the existing shared V3 Cell Reader.
//!
//! A reviewer JSON field saying "model_replayed" is NOT execution attestation.
//! The review bytes/digest must originate from an independently trusted owner.
//! This module binds data and performs real local Q24 Cell arithmetic; it never
//! issues authorizations, selects models, loads pretrained weights or runs tools.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_infer_core::sequence_feature_v3::ImmutableFeatureSequenceV3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::GraniteFeatureExpectationV5;
use super::SequenceBatchObservationV3;
use super::SequenceCellHeadV3;
use super::SequenceReadFenceV3;
use super::evaluate_sequence_heads_v3;
use super::import_granite97_token_v5;

const REVIEW_SCHEMA: &str = "hepta.stem.granite97-independent-physical-review.v1";
const MAX_REVIEW_BYTES: usize = 65_536;

#[derive(Clone)]
pub struct GraniteReviewAdmissionV6 {
    /// Complete source and model expectation from an independent owner.
    pub feature: GraniteFeatureExpectationV5,
    /// Exact exported JSON bytes, locked independently of the exporter.
    pub admitted_export_digest: Digest32,
    /// Independently admitted, exact physical-review receipt bytes.
    /// This digest alone is NOT proof of reviewer identity or physical work.
    pub admitted_review_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReviewedGraniteBatchV6 {
    pub feature_content_digest: Digest32,
    pub exported_bytes_digest: Digest32,
    pub review_bytes_digest: Digest32,
    pub q24_values_digest: Digest32,
    pub reviewer_encoder_forwards: u64,
    pub reviewer_encoder_cpu_ns: u64,
    pub reviewer_encoder_wall_ns: u64,
    pub reviewer_original_tensor_count: usize,
    pub reader: SequenceBatchObservationV3,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReviewedGraniteErrorV6 {
    MissingAdmission,
    InvalidExportDigest,
    InvalidReviewDigest,
    InvalidReviewSchema,
    InvalidReviewContents,
    NoIndependentReplay,
    InvalidFeature,
    ReaderRejected,
}

impl fmt::Display for ReviewedGraniteErrorV6 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for ReviewedGraniteErrorV6 {}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IndependentPhysicalReviewV1 {
    schema: String,
    source_sha256: String,
    input_digest: String,
    export_sha256: String,
    material_sha256: String,
    encoder_digest: String,
    feature_q24_sha256: String,
    producer_claimed_forwards: u64,
    producer_claimed_cpu_ns: u64,
    producer_claimed_wall_ns: u64,
    reviewer_encoder_forwards: u64,
    reviewer_encoder_cpu_ns: u64,
    reviewer_encoder_wall_ns: u64,
    exact_tensors: usize,
    model_replayed: bool,
    selected_model: bool,
    production_authorized: bool,
    authority: String,
}

fn decode_sha(value: &str) -> Result<Digest32, ReviewedGraniteErrorV6> {
    let digest = Digest32::from_str(value)
        .map_err(|_| ReviewedGraniteErrorV6::InvalidReviewContents)?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(ReviewedGraniteErrorV6::InvalidReviewContents);
    }
    Ok(digest)
}

/// Bind original exported bytes and an externally admitted, separately produced
/// review before accepting any V3 Cell computations. The caller supplies
/// current scope/revocation/freshness from its owning control plane. An
/// adversary who controls both the reviewer and its "independent" expected
/// digest is NOT stopped by this data-binding contract.
pub fn read_independently_reviewed_granite_v6(
    exported_json: &[u8],
    review_json: &[u8],
    admission: &GraniteReviewAdmissionV6,
    heads: &[Arc<SequenceCellHeadV3>],
    maximum_attention_pairs: u64,
) -> Result<ReviewedGraniteBatchV6, ReviewedGraniteErrorV6> {
    if admission.admitted_export_digest.is_zero()
        || admission.admitted_review_digest.is_zero()
        || admission.feature.material_digest.is_zero()
    {
        return Err(ReviewedGraniteErrorV6::MissingAdmission);
    }
    let export_sha = Digest32::of_bytes(exported_json);
    if export_sha != admission.admitted_export_digest {
        return Err(ReviewedGraniteErrorV6::InvalidExportDigest);
    }
    if review_json.is_empty() || review_json.len() > MAX_REVIEW_BYTES {
        return Err(ReviewedGraniteErrorV6::InvalidReviewSchema);
    }
    let review_sha = Digest32::of_bytes(review_json);
    if review_sha != admission.admitted_review_digest {
        return Err(ReviewedGraniteErrorV6::InvalidReviewDigest);
    }
    // Struct-level serde decoding rejects unknown, duplicate, omitted and
    // ill-typed properties instead of silently materializing a generic map.
    let review: IndependentPhysicalReviewV1 = serde_json::from_slice(review_json)
        .map_err(|_| ReviewedGraniteErrorV6::InvalidReviewSchema)?;
    if review.schema != REVIEW_SCHEMA {
        return Err(ReviewedGraniteErrorV6::InvalidReviewSchema);
    }
    if !review.model_replayed
        || review.selected_model
        || review.production_authorized
        || review.authority != "DENY_ALL"
        || review.reviewer_encoder_forwards != 1
        || review.reviewer_encoder_cpu_ns == 0
        || review.reviewer_encoder_wall_ns == 0
        || !(1..=250_000).contains(&review.exact_tensors)
    {
        return Err(ReviewedGraniteErrorV6::NoIndependentReplay);
    }

    // Reject stale/mixed original material and source before parsing the
    // potentially large, unsigned feature tensor.
    if decode_sha(&review.source_sha256)?
        != Digest32::of_bytes(&admission.feature.source_bytes)
        || decode_sha(&review.input_digest)?
            != admission.feature.identity.base.input_digest
        || decode_sha(&review.export_sha256)? != export_sha
        || decode_sha(&review.material_sha256)? != admission.feature.material_digest
        || decode_sha(&review.encoder_digest)?
            != admission.feature.identity.base.encoder_digest
    {
        return Err(ReviewedGraniteErrorV6::InvalidReviewContents);
    }

    // Existing V5 importer independently reconstructs token IDs, full source,
    // Q24 geometry, model/tokenizer/preprocessor and expiry.
    let imported = import_granite97_token_v5(exported_json, &admission.feature)
        .map_err(|_| ReviewedGraniteErrorV6::InvalidFeature)?;
    if imported.authority.grants_any()
        || imported.claimed_encoder_forwards != review.producer_claimed_forwards
        || imported.claimed_encoder_cpu_ns != review.producer_claimed_cpu_ns
        || imported.claimed_encoder_wall_ns != review.producer_claimed_wall_ns
        || imported.material_digest != admission.feature.material_digest
        || imported.complete_model_input_digest != admission.feature.identity.base.input_digest
    {
        return Err(ReviewedGraniteErrorV6::InvalidReviewContents);
    }

    let values = imported.snapshot.values_q24();
    let mut feature_bytes = Vec::with_capacity(values.len() * 8);
    for value in values {
        feature_bytes.extend_from_slice(&value.to_be_bytes());
    }
    let q24_sha = Digest32::of_bytes(&feature_bytes);
    if decode_sha(&review.feature_q24_sha256)? != q24_sha {
        return Err(ReviewedGraniteErrorV6::InvalidReviewContents);
    }

    let reader = evaluate_sequence_heads_v3(
        &SequenceReadFenceV3 {
            now_ms: admission.feature.now_ms,
            expected_identity: admission.feature.identity.clone(),
            expected_content_digest: imported.snapshot.content_digest(),
            maximum_attention_pairs,
        },
        &imported.snapshot,
        heads,
    )
    .map_err(|_| ReviewedGraniteErrorV6::ReaderRejected)?;

    let mut receipt = b"hepta.stem.independently-reviewed-multicell.v6\0".to_vec();
    for digest in [
        export_sha,
        review_sha,
        admission.feature.identity.base.input_digest,
        imported.snapshot.content_digest(),
        q24_sha,
        reader.observation_digest,
    ] {
        receipt.extend_from_slice(digest.as_array());
    }
    receipt.extend_from_slice(&review.reviewer_encoder_forwards.to_be_bytes());
    receipt.extend_from_slice(&review.reviewer_encoder_cpu_ns.to_be_bytes());
    receipt.extend_from_slice(&review.reviewer_encoder_wall_ns.to_be_bytes());
    receipt.extend_from_slice(&(review.exact_tensors as u64).to_be_bytes());
    receipt.extend_from_slice(&maximum_attention_pairs.to_be_bytes());
    Ok(ReviewedGraniteBatchV6 {
        feature_content_digest: imported.snapshot.content_digest(),
        exported_bytes_digest: export_sha,
        review_bytes_digest: review_sha,
        q24_values_digest: q24_sha,
        reviewer_encoder_forwards: review.reviewer_encoder_forwards,
        reviewer_encoder_cpu_ns: review.reviewer_encoder_cpu_ns,
        reviewer_encoder_wall_ns: review.reviewer_encoder_wall_ns,
        reviewer_original_tensor_count: review.exact_tensors,
        reader,
        receipt_digest: Digest32::of_bytes(&receipt),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "model_worker_granite_v6_tests.rs"]
mod tests;
