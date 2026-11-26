//! Additive shared-Stem/Q24-to-Neuron boundary for external owner integration.
//!
//! The supplied access context is **not authenticated by this pure module**:
//! host inference.control must independently authenticate principal, scope,
//! authority epoch, grant, current generation, artifact selection and final use.
//! Matching digests or successful construction is NEVER production permission.
//!
//! A feature may be reused across Cell Heads only inside the same validated
//! scope/principal/stem-generation binding. The cache owner remains external.
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::NeuronFeatureRequestV1;
use crate::neuron_feature_request_digest_v1;

const Q24: i64 = 1 << 24;
const MAX_Q24: i64 = 8 * Q24;
const MAX_FEATURE_WIDTH: usize = 512;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemFeatureRefV1 {
    pub scope_id: StableId,
    pub principal_id: StableId,
    pub stem_model_id: StableId,
    pub stem_generation: Generation,
    pub authority_epoch: u64,
    pub lease_expires_at_ms: u64,
    pub stem_weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub projection_digest: Digest32,
    pub input_digest: Digest32,
    pub feature_digest: Digest32,
    pub feature_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemAccessContextV1 {
    pub scope_id: StableId,
    pub principal_id: StableId,
    pub stem_generation: Generation,
    pub authority_epoch: u64,
    pub now_ms: u64,
    /// A security **claim**, not evidence of independent authentication.
    pub revocation_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemHeadBindingV1 {
    pub request_id: StableId,
    pub head_model_id: StableId,
    pub head_digest: Digest32,
    pub head_weights_digest: Digest32,
    pub required_stem_model_id: StableId,
    pub required_stem_generation: Generation,
    pub required_encoder_digest: Digest32,
    pub required_tokenizer_digest: Digest32,
    pub required_preprocessor_digest: Digest32,
    pub required_projection_digest: Digest32,
    pub required_feature_width: usize,
    pub expected_output_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundStemNeuronRequestV1 {
    pub request: NeuronFeatureRequestV1,
    pub feature_ref_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StemFeatureBindingError {
    EmptyDigest,
    ScopeMismatch,
    PrincipalMismatch,
    GenerationMismatch,
    AuthorityEpochMismatch,
    LeaseExpired,
    Revoked,
    InvalidFeatureWidth,
    InvalidFeatureValue,
    FeatureDigestMismatch,
    InvalidHead,
    IncompatibleHead,
    InvalidNeuronRequest,
}

impl fmt::Display for StemFeatureBindingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for StemFeatureBindingError {}

/// Deterministic research-side digest of the exact signed Q24 vector.
/// This digest is **not** a signed worker observation, inference receipt,
/// or replacement for the Neuron request digest.
pub fn stem_feature_vector_digest_v1(values: &[i64]) -> Result<Digest32, StemFeatureBindingError> {
    if values.is_empty() || values.len() > MAX_FEATURE_WIDTH {
        return Err(StemFeatureBindingError::InvalidFeatureWidth);
    }
    let mut bytes = b"hepta.inference.stem-feature-vector.v1".to_vec();
    bytes.extend_from_slice(&(values.len() as u32).to_be_bytes());
    for value in values {
        if !(-MAX_Q24..=MAX_Q24).contains(value) {
            return Err(StemFeatureBindingError::InvalidFeatureValue);
        }
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Immutable identity for the complete frozen Stem feature pipeline.
///
/// The encoder digest must bind the tokenizer, preprocessing, model weights,
/// Matryoshka/quantization projection, feature dimension and generation.
/// Using *only* the model weights digest would permit incompatible features
/// to masquerade as the same encoder across different Cell Heads.
#[must_use]
pub fn stem_encoder_pipeline_digest_v1(source: &StemFeatureRefV1) -> Digest32 {
    let mut bytes = b"hepta.inference.stem-encoder-pipeline.v1".to_vec();
    let model_id = source.stem_model_id.to_string();
    bytes.extend_from_slice(&(model_id.len() as u32).to_be_bytes());
    bytes.extend_from_slice(model_id.as_bytes());
    bytes.extend_from_slice(&source.stem_generation.get().to_be_bytes());
    bytes.extend_from_slice(&(source.feature_width as u32).to_be_bytes());
    for digest in [
        source.stem_weights_digest,
        source.tokenizer_digest,
        source.preprocessor_digest,
        source.projection_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

/// Pure, fail-closed assembly of an existing NeuronFeatureRequestV1.
/// An owner MUST perform real final-use admission and subsequently dispatch
/// the returned request, verify its terminal result and CAS the checkpoint.
pub fn bind_stem_feature_request_v1(
    source: &StemFeatureRefV1,
    access: &StemAccessContextV1,
    selected_head: StemHeadBindingV1,
    vector_q24: &[i64],
) -> Result<BoundStemNeuronRequestV1, StemFeatureBindingError> {
    for digest in [
        source.stem_weights_digest,
        source.tokenizer_digest,
        source.preprocessor_digest,
        source.projection_digest,
        source.input_digest,
        source.feature_digest,
        selected_head.head_digest,
        selected_head.head_weights_digest,
        selected_head.required_encoder_digest,
        selected_head.required_tokenizer_digest,
        selected_head.required_preprocessor_digest,
        selected_head.required_projection_digest,
    ] {
        if digest.is_zero() {
            return Err(StemFeatureBindingError::EmptyDigest);
        }
    }
    if source.scope_id != access.scope_id {
        return Err(StemFeatureBindingError::ScopeMismatch);
    }
    if source.principal_id != access.principal_id {
        return Err(StemFeatureBindingError::PrincipalMismatch);
    }
    if source.stem_generation != access.stem_generation {
        return Err(StemFeatureBindingError::GenerationMismatch);
    }
    if source.authority_epoch == 0 || source.authority_epoch != access.authority_epoch {
        return Err(StemFeatureBindingError::AuthorityEpochMismatch);
    }
    if access.revocation_observed {
        return Err(StemFeatureBindingError::Revoked);
    }
    if access.now_ms >= source.lease_expires_at_ms {
        return Err(StemFeatureBindingError::LeaseExpired);
    }
    if vector_q24.len() != source.feature_width {
        return Err(StemFeatureBindingError::InvalidFeatureWidth);
    }
    let observed_feature_digest = stem_feature_vector_digest_v1(vector_q24)?;
    if observed_feature_digest != source.feature_digest {
        return Err(StemFeatureBindingError::FeatureDigestMismatch);
    }
    if selected_head.expected_output_width == 0 || selected_head.expected_output_width > 512 {
        return Err(StemFeatureBindingError::InvalidHead);
    }
    let pipeline_digest = stem_encoder_pipeline_digest_v1(source);
    if selected_head.required_stem_model_id != source.stem_model_id
        || selected_head.required_stem_generation != source.stem_generation
        || selected_head.required_encoder_digest != pipeline_digest
        || selected_head.required_tokenizer_digest != source.tokenizer_digest
        || selected_head.required_preprocessor_digest != source.preprocessor_digest
        || selected_head.required_projection_digest != source.projection_digest
        || selected_head.required_feature_width != source.feature_width
    {
        return Err(StemFeatureBindingError::IncompatibleHead);
    }
    let request = NeuronFeatureRequestV1 {
        request_id: selected_head.request_id,
        generation: source.stem_generation,
        model_id: selected_head.head_model_id,
        encoder_digest: pipeline_digest,
        head_digest: selected_head.head_digest,
        weights_digest: selected_head.head_weights_digest,
        input_digest: source.input_digest,
        feature_vector_q24: vector_q24.to_vec(),
        expected_output_width: selected_head.expected_output_width,
    };
    neuron_feature_request_digest_v1(&request)
        .map_err(|_| StemFeatureBindingError::InvalidNeuronRequest)?;
    let mut bytes = b"hepta.inference.stem-feature-ref.v1".to_vec();
    for id in [
        &source.scope_id,
        &source.principal_id,
        &source.stem_model_id,
    ] {
        let raw = id.to_string();
        bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
        bytes.extend_from_slice(raw.as_bytes());
    }
    bytes.extend_from_slice(&source.stem_generation.get().to_be_bytes());
    bytes.extend_from_slice(&source.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&source.lease_expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(&(source.feature_width as u32).to_be_bytes());
    for digest in [
        source.stem_weights_digest,
        source.tokenizer_digest,
        source.preprocessor_digest,
        source.projection_digest,
        source.input_digest,
        source.feature_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(BoundStemNeuronRequestV1 {
        request,
        feature_ref_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid stable fixture ID")
    }

    fn generation(n: u64) -> Generation {
        Generation::new(n).expect("valid generation")
    }

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    fn fixture() -> (
        StemFeatureRefV1,
        StemAccessContextV1,
        StemHeadBindingV1,
        Vec<i64>,
    ) {
        let features = vec![Q24 / 2, -Q24 / 4];
        let source = StemFeatureRefV1 {
            scope_id: id("scope-A"),
            principal_id: id("principal-A"),
            stem_model_id: id("jina-v5-text-nano"),
            stem_generation: generation(7),
            authority_epoch: 15,
            lease_expires_at_ms: 1000,
            stem_weights_digest: digest(b"stem"),
            tokenizer_digest: digest(b"tokenizer"),
            preprocessor_digest: digest(b"preprocessor"),
            projection_digest: digest(b"matryoshka256-q24"),
            input_digest: digest(b"scoped-input"),
            feature_digest: stem_feature_vector_digest_v1(&features)
                .expect("valid fixture feature digest"),
            feature_width: features.len(),
        };
        let access = StemAccessContextV1 {
            scope_id: id("scope-A"),
            principal_id: id("principal-A"),
            stem_generation: generation(7),
            authority_epoch: 15,
            now_ms: 900,
            revocation_observed: false,
        };
        let selected = StemHeadBindingV1 {
            request_id: id("req-1"),
            head_model_id: id("cell-head-1"),
            head_digest: digest(b"head-config"),
            head_weights_digest: digest(b"head-weights"),
            required_stem_model_id: id("jina-v5-text-nano"),
            required_stem_generation: generation(7),
            required_encoder_digest: stem_encoder_pipeline_digest_v1(&source),
            required_tokenizer_digest: digest(b"tokenizer"),
            required_preprocessor_digest: digest(b"preprocessor"),
            required_projection_digest: digest(b"matryoshka256-q24"),
            required_feature_width: features.len(),
            expected_output_width: 5,
        };
        (source, access, selected, features)
    }

    #[test]
    fn builds_only_denied_authority_and_exact_existing_neuron_request() {
        let (source, access, selected, values) = fixture();
        let result = bind_stem_feature_request_v1(&source, &access, selected, &values)
            .expect("valid scoped feature");
        assert_eq!(result.request.feature_vector_q24, values);
        assert_eq!(
            stem_feature_vector_digest_v1(&values)
                .expect("valid Q24 golden vector")
                .to_string(),
            "148ae0b91ab97729f72d745e989ac7b03614438cc6030edb2f79748049c70b59"
        );
        assert_eq!(result.request.generation, generation(7));
        assert_eq!(
            result.request.encoder_digest.to_string(),
            "67d4c68e2092bcde7fdccca0386fb39442deac2a0ecb8ff8d98a5510067f5504"
        );
        assert!(!result.feature_ref_digest.is_zero());
        assert!(!result.authority.grants_any());
    }

    #[test]
    fn stale_scope_principal_generation_epoch_or_lease_fails_closed() {
        let (source, mut access, head, values) = fixture();
        access.scope_id = id("another-scope");
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head.clone(), &values),
            Err(StemFeatureBindingError::ScopeMismatch)
        );
        access.scope_id = id("scope-A");
        access.principal_id = id("another-principal");
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head.clone(), &values),
            Err(StemFeatureBindingError::PrincipalMismatch)
        );
        access.principal_id = id("principal-A");
        access.stem_generation = generation(8);
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head.clone(), &values),
            Err(StemFeatureBindingError::GenerationMismatch)
        );
        access.stem_generation = generation(7);
        access.authority_epoch += 1;
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head.clone(), &values),
            Err(StemFeatureBindingError::AuthorityEpochMismatch)
        );
        access.authority_epoch = 15;
        access.now_ms = 1000;
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head.clone(), &values),
            Err(StemFeatureBindingError::LeaseExpired)
        );
        access.now_ms = 900;
        access.revocation_observed = true;
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head, &values),
            Err(StemFeatureBindingError::Revoked)
        );
    }

    #[test]
    fn head_cannot_rebind_to_another_stem_or_feature_projection() {
        let (source, access, mut selected, values) = fixture();
        selected.required_stem_model_id = id("unrelated-encoder");
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, selected.clone(), &values),
            Err(StemFeatureBindingError::IncompatibleHead)
        );
        selected.required_stem_model_id = id("jina-v5-text-nano");
        selected.required_encoder_digest = digest(b"raw-stem-weights-only");
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, selected.clone(), &values),
            Err(StemFeatureBindingError::IncompatibleHead)
        );
        selected.required_encoder_digest = stem_encoder_pipeline_digest_v1(&source);
        selected.required_projection_digest = digest(b"other-projection");
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, selected.clone(), &values),
            Err(StemFeatureBindingError::IncompatibleHead)
        );
        selected.required_projection_digest = digest(b"matryoshka256-q24");
        selected.required_tokenizer_digest = digest(b"other-tokenizer");
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, selected.clone(), &values),
            Err(StemFeatureBindingError::IncompatibleHead)
        );
        selected.required_tokenizer_digest = digest(b"tokenizer");
        selected.required_feature_width = 512;
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, selected, &values),
            Err(StemFeatureBindingError::IncompatibleHead)
        );
    }

    #[test]
    fn exact_q24_width_and_bytes_must_match_feature_ref() {
        let (mut source, access, head, values) = fixture();
        let mut changed = values.clone();
        changed[0] += 1;
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head.clone(), &changed),
            Err(StemFeatureBindingError::FeatureDigestMismatch)
        );
        source.feature_width = 3;
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head.clone(), &values),
            Err(StemFeatureBindingError::InvalidFeatureWidth)
        );
        source.feature_width = values.len();
        source.feature_digest = Digest32::ZERO;
        assert_eq!(
            bind_stem_feature_request_v1(&source, &access, head, &values),
            Err(StemFeatureBindingError::EmptyDigest)
        );
        assert_eq!(
            stem_feature_vector_digest_v1(&vec![0; 513]),
            Err(StemFeatureBindingError::InvalidFeatureWidth)
        );
        assert_eq!(
            stem_feature_vector_digest_v1(&[MAX_Q24 + 1]),
            Err(StemFeatureBindingError::InvalidFeatureValue)
        );
    }
}
