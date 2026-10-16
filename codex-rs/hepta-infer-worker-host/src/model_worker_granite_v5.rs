//! Research-only Granite97 token-export admission into the shared V3 Reader.
//!
//! The Python producer may execute the SHA-pinned real pretrained Encoder, but
//! an unsigned export is NOT a trusted model execution receipt. This module
//! independently checks every original input byte, token ID, mask, source scope,
//! model/material identity, Q24 tensor and expiry before constructing an Arc V3.
//! It neither loads a model nor grants Worker/FinalUse/external effect authority.

use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_infer_core::sequence_feature_v3::{
    FeatureCoordinatesV3, FeatureModalityV3, FeatureSequenceIdentityV3, ImmutableFeatureSequenceV3,
};
use codex_hepta_types::{AuthorityPosture, Digest32};
use serde::Deserialize;

const MODEL_ID: &str = "ibm-granite/granite-embedding-97m-multilingual-r2";
const REVISION: &str = "835ad14087e140460703cf0fae09f97d469d65c2";
const SCHEMA: &str = "hepta.stem.granite97-token-export.v5";
const MAX_JSON_BYTES: usize = 2_500_000;
const MAX_SOURCE_BYTES: usize = 65_536;
const MAX_ROWS: usize = 256;
const WIDTH: usize = 384;
const Q24_BOUND: i64 = 8 * (1 << 24);

/// Source bytes and model identity come from a separate admission owner.
/// The unsigned producer JSON cannot modify them or extend the TTL.
#[derive(Clone)]
pub struct GraniteFeatureExpectationV5 {
    pub identity: FeatureSequenceIdentityV3,
    pub source_bytes: Vec<u8>,
    pub material_digest: Digest32,
    pub now_ms: u64,
    pub maximum_expires_at_ms: u64,
}

#[derive(Clone, Debug)]
pub struct ImportedGraniteFeaturesV5 {
    pub snapshot: Arc<ImmutableFeatureSequenceV3>,
    pub material_digest: Digest32,
    pub source_digest: Digest32,
    pub complete_model_input_digest: Digest32,
    /// Self-reported by the exporter; NOT an independent physical-work witness.
    pub claimed_encoder_forwards: u64,
    pub claimed_encoder_cpu_ns: u64,
    pub claimed_encoder_wall_ns: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GraniteFeatureImportErrorV5 {
    Malformed,
    InvalidSource,
    InvalidIdentity,
    InvalidModel,
    InvalidGeometry,
    InvalidValue,
    Expired,
    InvalidFeature,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ExportV5 {
    schema: String,
    model_id: String,
    revision: String,
    material_digest: String,
    encoder_digest: String,
    tokenizer_digest: String,
    normalizer_digest: String,
    quantization_digest: String,
    preprocessing_digest: String,
    adapter_digest: String,
    source_sha256: String,
    input_digest: String,
    principal_id: String,
    purpose_id: String,
    generation: u64,
    authority_epoch: u64,
    input_ids: Vec<u32>,
    attention_mask: Vec<u8>,
    values_q24: Vec<i64>,
    width: usize,
    expires_at_ms: u64,
    encoder_forwards: u64,
    encoder_cpu_ns: u64,
    encoder_wall_ns: u64,
}

/// Domain-separated binding of the real source bytes AND complete admitted
/// tokenizer inputs. No separate truncation, source-only pooling or label path.
pub fn granite97_complete_input_digest_v5(
    source: &[u8],
    input_ids: &[u32],
    mask: &[u8],
) -> Result<Digest32, GraniteFeatureImportErrorV5> {
    if source.is_empty()
        || source.len() > MAX_SOURCE_BYTES
        || input_ids.is_empty()
        || input_ids.len() > MAX_ROWS
        || input_ids.len() != mask.len()
        || mask.iter().any(|x| *x != 1)
        || input_ids.iter().any(|id| *id > 1_000_000)
    {
        return Err(GraniteFeatureImportErrorV5::InvalidSource);
    }
    let mut bytes = b"hepta.stem.granite97.complete-token-input.v5\0".to_vec();
    bytes.extend_from_slice(&(source.len() as u64).to_be_bytes());
    bytes.extend_from_slice(source);
    bytes.extend_from_slice(&(input_ids.len() as u32).to_be_bytes());
    for token in input_ids {
        bytes.extend_from_slice(&token.to_be_bytes());
    }
    bytes.extend_from_slice(mask);
    Ok(Digest32::of_bytes(&bytes))
}

fn parse_digest(raw: &str) -> Result<Digest32, GraniteFeatureImportErrorV5> {
    let digest = Digest32::from_str(raw).map_err(|_| GraniteFeatureImportErrorV5::Malformed)?;
    if digest.is_zero() || digest.to_string() != raw {
        return Err(GraniteFeatureImportErrorV5::Malformed);
    }
    Ok(digest)
}

pub fn granite97_encoder_identity_v5(material_digest: Digest32) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.stem.granite97.frozen-model.v5\0",
        material_digest.as_array(),
    ])
}

/// Validate an untrusted, bounded serialized producer output against the
/// independent expected source/scope/model manifest, then call the *existing*
/// immutable V3 constructor. Source bytes never become part of the result.
/// A digest is NOT a signature and this function does NOT trust CPU counters.
pub fn import_granite97_token_v5(
    encoded: &[u8],
    expected: &GraniteFeatureExpectationV5,
) -> Result<ImportedGraniteFeaturesV5, GraniteFeatureImportErrorV5> {
    if encoded.is_empty() || encoded.len() > MAX_JSON_BYTES {
        return Err(GraniteFeatureImportErrorV5::Malformed);
    }
    if expected.source_bytes.is_empty()
        || expected.source_bytes.len() > MAX_SOURCE_BYTES
        || expected.material_digest.is_zero()
        || expected.now_ms >= expected.maximum_expires_at_ms
        || expected.identity.modality != FeatureModalityV3::Text
    {
        return Err(GraniteFeatureImportErrorV5::InvalidIdentity);
    }
    expected
        .identity
        .digest()
        .map_err(|_| GraniteFeatureImportErrorV5::InvalidIdentity)?;
    let record: ExportV5 =
        serde_json::from_slice(encoded).map_err(|_| GraniteFeatureImportErrorV5::Malformed)?;
    if record.schema != SCHEMA || record.model_id != MODEL_ID || record.revision != REVISION {
        return Err(GraniteFeatureImportErrorV5::InvalidModel);
    }
    if record.width != WIDTH
        || record.values_q24.len()
            != record
                .input_ids
                .len()
                .checked_mul(WIDTH)
                .ok_or(GraniteFeatureImportErrorV5::InvalidGeometry)?
        || record.encoder_forwards != 1
        || record.encoder_cpu_ns == 0
        || record.encoder_wall_ns == 0
    {
        return Err(GraniteFeatureImportErrorV5::InvalidGeometry);
    }
    if record
        .values_q24
        .iter()
        .any(|x| !(-Q24_BOUND..=Q24_BOUND).contains(x))
    {
        return Err(GraniteFeatureImportErrorV5::InvalidValue);
    }
    if record.expires_at_ms <= expected.now_ms
        || record.expires_at_ms > expected.maximum_expires_at_ms
    {
        return Err(GraniteFeatureImportErrorV5::Expired);
    }
    let material = parse_digest(&record.material_digest)?;
    if material != expected.material_digest
        || granite97_encoder_identity_v5(material) != parse_digest(&record.encoder_digest)?
    {
        return Err(GraniteFeatureImportErrorV5::InvalidModel);
    }
    let expected_profile = &expected.identity;
    if record.principal_id != expected_profile.base.principal_id.as_str()
        || record.purpose_id != expected_profile.base.purpose_id.as_str()
        || record.generation != expected_profile.base.generation.get()
        || record.authority_epoch != expected_profile.base.authority_epoch
    {
        return Err(GraniteFeatureImportErrorV5::InvalidIdentity);
    }
    if parse_digest(&record.encoder_digest)? != expected_profile.base.encoder_digest
        || parse_digest(&record.tokenizer_digest)? != expected_profile.base.tokenizer_digest
        || parse_digest(&record.normalizer_digest)? != expected_profile.base.normalizer_digest
        || parse_digest(&record.quantization_digest)? != expected_profile.base.quantization_digest
        || parse_digest(&record.preprocessing_digest)? != expected_profile.preprocessing_digest
        || parse_digest(&record.adapter_digest)? != expected_profile.adapter_digest
    {
        return Err(GraniteFeatureImportErrorV5::InvalidIdentity);
    }
    let source_digest = Digest32::of_bytes(&expected.source_bytes);
    if parse_digest(&record.source_sha256)? != source_digest {
        return Err(GraniteFeatureImportErrorV5::InvalidSource);
    }
    let complete_input = granite97_complete_input_digest_v5(
        &expected.source_bytes,
        &record.input_ids,
        &record.attention_mask,
    )?;
    if complete_input != parse_digest(&record.input_digest)?
        || complete_input != expected_profile.base.input_digest
    {
        return Err(GraniteFeatureImportErrorV5::InvalidSource);
    }
    let rows = record.input_ids.len();
    let snapshot = ImmutableFeatureSequenceV3::build(
        expected.identity.clone(),
        record.expires_at_ms,
        rows,
        WIDTH,
        Arc::from(record.values_q24),
        Arc::from(record.attention_mask),
        Arc::from(vec![FeatureCoordinatesV3::default(); rows]),
    )
    .map_err(|_| GraniteFeatureImportErrorV5::InvalidFeature)?;
    Ok(ImportedGraniteFeaturesV5 {
        snapshot: Arc::new(snapshot),
        material_digest: material,
        source_digest,
        complete_model_input_digest: complete_input,
        claimed_encoder_forwards: record.encoder_forwards,
        claimed_encoder_cpu_ns: record.encoder_cpu_ns,
        claimed_encoder_wall_ns: record.encoder_wall_ns,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "model_worker_granite_v5_tests.rs"]
mod tests;
