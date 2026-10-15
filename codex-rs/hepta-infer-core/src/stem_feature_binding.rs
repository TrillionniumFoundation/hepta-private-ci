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
use std::sync::Arc;

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

/// Immutable, in-process Q24 *buffer*, not a second Stem authority owner.
///
/// The source descriptor is an unverified claim at construction. Callers must
/// retrieve an independently authenticated, fresh StemAccessContextV1 from
/// the one inference-control owner for EACH dispatch/final use. Only then may
/// a returned borrowed view be handed to the separately authorized executor.
#[derive(Clone, Debug)]
pub struct SharedStemQ24BufferV1 {
    source: StemFeatureRefV1,
    values: Arc<[i64]>,
    // Cached immutable source IDs are *not* an access grant. Every borrow
    // still checks current principal, scope, epoch, lease and Head identity.
    pipeline_digest: Digest32,
    feature_ref_digest: Digest32,
}

impl SharedStemQ24BufferV1 {
    /// Consumes the original bounded Vec once; Arc clones share one allocation.
    /// An exact Q24 content digest is required but is NOT a signature.
    pub fn from_unverified_source(
        source: StemFeatureRefV1,
        values: Vec<i64>,
    ) -> Result<Self, StemFeatureBindingError> {
        Self::from_unverified_arc(source, Arc::from(values.into_boxed_slice()))
    }

    /// Reuse an already immutable Q24 Arc allocation from the ORIGINAL
    /// inference-core shared feature owner. Source metadata is still only a
    /// claim: recompute the STEM-DOMAIN Q24 digest exactly once, and require
    /// fresh Principal/Scope/Epoch/Lease/Head checks at *every* later use.
    ///
    /// A generic neuron.runtime SharedFeatureBufferV1 digest is NOT the
    /// hepta.inference.stem-feature-vector.v1 digest. The caller must supply
    /// the correct distinct source feature digest. No authority is granted.
    pub fn from_unverified_arc(
        source: StemFeatureRefV1,
        values: Arc<[i64]>,
    ) -> Result<Self, StemFeatureBindingError> {
        if source.feature_digest.is_zero() {
            return Err(StemFeatureBindingError::EmptyDigest);
        }
        if values.len() != source.feature_width {
            return Err(StemFeatureBindingError::InvalidFeatureWidth);
        }
        if stem_feature_vector_digest_v1(&values)? != source.feature_digest {
            return Err(StemFeatureBindingError::FeatureDigestMismatch);
        }
        let pipeline_digest = stem_encoder_pipeline_digest_v1(&source);
        let feature_ref_digest = stem_feature_ref_digest_v1(&source);
        Ok(Self {
            source,
            values,
            pipeline_digest,
            feature_ref_digest,
        })
    }

    /// Borrow features for exactly one selected Head. This executes the
    /// SAME Principal/Scope/Epoch/Generation/Lease/Revocation/Head gates as
    /// the historical owned V1 binding, not a weakened cache-only check.
    ///
    /// Neither this buffer nor the returned view grants model dispatch.
    pub fn borrow_for_head<'a>(
        &'a self,
        current_access_claim: &StemAccessContextV1,
        selected_head: &'a StemHeadBindingV1,
    ) -> Result<StemFeatureRequestViewV1<'a>, StemFeatureBindingError> {
        // This Arc buffer was content-checked at construction and is
        // immutable thereafter. Revalidate live access + selected Head for
        // EVERY use, without rehashing the same Q24 bytes for each Cell.
        borrow_stem_feature_request_checked_v1(
            &self.source,
            current_access_claim,
            selected_head,
            self.values.as_ref(),
            FeatureDigestVerification::ImmutableBufferVerified {
                pipeline_digest: self.pipeline_digest,
                feature_ref_digest: self.feature_ref_digest,
            },
        )
    }

    /// Legacy owned V1 serialization with one *necessary* feature Vec copy.
    /// All Principal/Scope/Epoch/Lease/Generation/Revocation/Head gates are
    /// rechecked on the supplied CURRENT owner claim before allocating.
    /// The private Arc's previously verified bytes need not be rehashed.
    ///
    /// Does NOT consume or establish signed Final-use authority.
    pub fn materialize_owned_for_head(
        &self,
        current_access_claim: &StemAccessContextV1,
        selected_head: &StemHeadBindingV1,
    ) -> Result<BoundStemNeuronRequestV1, StemFeatureBindingError> {
        self.borrow_for_head(current_access_claim, selected_head)?
            .materialize_owned_v1()
    }
}

/// An in-process, *borrow-only* view of the existing Stem-to-Neuron V1
/// request. A fresh externally authenticated owner admission and final-use
/// fence are required for any actual execution. This view is NEVER a grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemFeatureRequestViewV1<'a> {
    request_id: &'a StableId,
    generation: Generation,
    model_id: &'a StableId,
    encoder_digest: Digest32,
    head_digest: Digest32,
    weights_digest: Digest32,
    input_digest: Digest32,
    feature_vector_q24: &'a [i64],
    expected_output_width: usize,
    feature_ref_digest: Digest32,
    authority: AuthorityPosture,
}

impl<'a> StemFeatureRequestViewV1<'a> {
    /// Read-only access to the validated Q24 vector. This does not grant
    /// authorization to dispatch it or keep using it after revocation.
    #[must_use]
    pub fn feature_vector_q24(&self) -> &[i64] {
        self.feature_vector_q24
    }

    #[must_use]
    pub fn feature_ref_digest(&self) -> Digest32 {
        self.feature_ref_digest
    }

    #[must_use]
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Revalidate the exact original feature/Head against newly supplied
    /// access claims immediately before moving into a legacy V1 request.
    /// The caller must obtain these claims from the *real authenticated owner*;
    /// this pure function cannot establish their authenticity or final-use.
    pub fn materialize_owned_after_refresh(
        &self,
        source: &StemFeatureRefV1,
        access: &StemAccessContextV1,
        selected_head: &StemHeadBindingV1,
    ) -> Result<BoundStemNeuronRequestV1, StemFeatureBindingError> {
        let current =
            borrow_stem_feature_request_v1(source, access, selected_head, self.feature_vector_q24)?;
        if current.request_id != self.request_id
            || current.model_id != self.model_id
            || current.generation != self.generation
            || current.encoder_digest != self.encoder_digest
            || current.head_digest != self.head_digest
            || current.weights_digest != self.weights_digest
            || current.input_digest != self.input_digest
            || current.expected_output_width != self.expected_output_width
            || current.feature_ref_digest != self.feature_ref_digest
        {
            return Err(StemFeatureBindingError::IncompatibleHead);
        }
        current.materialize_owned_v1()
    }

    /// Explicit owned-wire boundary: one feature allocation is intentionally
    /// made ONLY when a legacy V1 consumer actually requires an owned request.
    /// The exact original V1 request digest is retained and checked.
    /// Private to the binding module: callers must use refreshed claims.
    fn materialize_owned_v1(&self) -> Result<BoundStemNeuronRequestV1, StemFeatureBindingError> {
        let request = NeuronFeatureRequestV1 {
            request_id: (*self.request_id).clone(),
            generation: self.generation,
            model_id: (*self.model_id).clone(),
            encoder_digest: self.encoder_digest,
            head_digest: self.head_digest,
            weights_digest: self.weights_digest,
            input_digest: self.input_digest,
            feature_vector_q24: self.feature_vector_q24.to_vec(),
            expected_output_width: self.expected_output_width,
        };
        neuron_feature_request_digest_v1(&request)
            .map_err(|_| StemFeatureBindingError::InvalidNeuronRequest)?;
        Ok(BoundStemNeuronRequestV1 {
            request,
            feature_ref_digest: self.feature_ref_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
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
    // Keep exact historical owned V1 wire/digest semantics. Any native
    // feature-sharing optimization must leave this replay pathway intact.
    borrow_stem_feature_request_v1(source, access, &selected_head, vector_q24)?
        .materialize_owned_v1()
}

/// Validate exact existing Stem/Head constraints and return a borrowed vector
/// view without calling `to_vec`. The caller must re-query the *actual*
/// authority owner at final use; the supplied StemAccessContextV1 is only a
/// claim and this pure function cannot verify independent signatures.
pub fn borrow_stem_feature_request_v1<'a>(
    source: &StemFeatureRefV1,
    access: &StemAccessContextV1,
    selected_head: &'a StemHeadBindingV1,
    vector_q24: &'a [i64],
) -> Result<StemFeatureRequestViewV1<'a>, StemFeatureBindingError> {
    // Caller-owned slices can change; they ALWAYS need a fresh full digest.
    borrow_stem_feature_request_checked_v1(
        source,
        access,
        selected_head,
        vector_q24,
        FeatureDigestVerification::RecomputeOnEveryUse,
    )
}

/// Private proof selector; only the immutable buffer constructor may choose
/// ImmutableBufferVerified, after validating the full Q24 content digest.
/// This is NOT an authority proof; Principal/Scope/Epoch/Lease/Revocation and
/// selected Head are checked again for every use in both paths.
#[derive(Clone, Copy)]
enum FeatureDigestVerification {
    RecomputeOnEveryUse,
    // Only the private immutable-storage API can construct this value.
    // The digest identities were computed against the same private source.
    ImmutableBufferVerified {
        pipeline_digest: Digest32,
        feature_ref_digest: Digest32,
    },
}

fn borrow_stem_feature_request_checked_v1<'a>(
    source: &StemFeatureRefV1,
    access: &StemAccessContextV1,
    selected_head: &'a StemHeadBindingV1,
    vector_q24: &'a [i64],
    feature_verification: FeatureDigestVerification,
) -> Result<StemFeatureRequestViewV1<'a>, StemFeatureBindingError> {
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
    // Rehash arbitrary caller slices as before. The trusted immutable-buffer
    // path was verified exactly once at construction, and Arc<[i64]> cannot
    // be mutated using the safe APIs exposed by this crate.
    if matches!(
        feature_verification,
        FeatureDigestVerification::RecomputeOnEveryUse
    ) && stem_feature_vector_digest_v1(vector_q24)? != source.feature_digest
    {
        return Err(StemFeatureBindingError::FeatureDigestMismatch);
    }
    if selected_head.expected_output_width == 0 || selected_head.expected_output_width > 512 {
        return Err(StemFeatureBindingError::InvalidHead);
    }
    let pipeline_digest = match feature_verification {
        FeatureDigestVerification::RecomputeOnEveryUse => stem_encoder_pipeline_digest_v1(source),
        FeatureDigestVerification::ImmutableBufferVerified {
            pipeline_digest, ..
        } => pipeline_digest,
    };
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
    let feature_ref_digest = match feature_verification {
        FeatureDigestVerification::RecomputeOnEveryUse => stem_feature_ref_digest_v1(source),
        FeatureDigestVerification::ImmutableBufferVerified {
            feature_ref_digest, ..
        } => feature_ref_digest,
    };
    Ok(StemFeatureRequestViewV1 {
        request_id: &selected_head.request_id,
        generation: source.stem_generation,
        model_id: &selected_head.head_model_id,
        encoder_digest: pipeline_digest,
        head_digest: selected_head.head_digest,
        weights_digest: selected_head.head_weights_digest,
        input_digest: source.input_digest,
        feature_vector_q24: vector_q24,
        expected_output_width: selected_head.expected_output_width,
        feature_ref_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Stable V1 source reference identity. It contains immutable source
/// metadata, never caller-supplied current access claims. This digest is an
/// identity marker, NOT a verified signature or authorization capability.
fn stem_feature_ref_digest_v1(source: &StemFeatureRefV1) -> Digest32 {
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
    Digest32::of_bytes(&bytes)
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
    #[test]
    fn borrowed_views_reuse_exact_q24_allocation_and_preserve_owned_v1_digest() {
        let (source, access, first_head, vector) = fixture();
        let first = borrow_stem_feature_request_v1(&source, &access, &first_head, &vector)
            .expect("borrowed, non-authorizing view");
        let mut second_head = first_head.clone();
        second_head.request_id = id("req-2");
        second_head.head_model_id = id("cell-head-2");
        let second = borrow_stem_feature_request_v1(&source, &access, &second_head, &vector)
            .expect("second Cell reuses exact feature vector");
        assert_eq!(first.feature_vector_q24.as_ptr(), vector.as_ptr());
        assert_eq!(second.feature_vector_q24.as_ptr(), vector.as_ptr());
        assert_eq!(first.feature_ref_digest, second.feature_ref_digest);
        assert!(!first.authority.grants_any());
        assert!(!second.authority.grants_any());

        let owned = first.materialize_owned_v1().expect("owned replay boundary");
        let old_contract = bind_stem_feature_request_v1(&source, &access, first_head, &vector)
            .expect("same existing V1 output");
        assert_eq!(owned, old_contract);
        assert_eq!(
            neuron_feature_request_digest_v1(&owned.request).expect("existing V1 semantic digest"),
            neuron_feature_request_digest_v1(&old_contract.request)
                .expect("legacy semantic digest")
        );
        assert!(!owned.authority.grants_any());
    }

    #[test]
    fn borrowed_view_still_rejects_principal_epoch_lease_and_revoke_mismatch() {
        let (source, mut access, head, vector) = fixture();
        access.principal_id = id("principal-B");
        assert_eq!(
            borrow_stem_feature_request_v1(&source, &access, &head, &vector),
            Err(StemFeatureBindingError::PrincipalMismatch)
        );
        access.principal_id = id("principal-A");
        access.authority_epoch += 1;
        assert_eq!(
            borrow_stem_feature_request_v1(&source, &access, &head, &vector),
            Err(StemFeatureBindingError::AuthorityEpochMismatch)
        );
        access.authority_epoch = 15;
        access.now_ms = source.lease_expires_at_ms;
        assert_eq!(
            borrow_stem_feature_request_v1(&source, &access, &head, &vector),
            Err(StemFeatureBindingError::LeaseExpired)
        );
        access.now_ms = 900;
        access.revocation_observed = true;
        assert_eq!(
            borrow_stem_feature_request_v1(&source, &access, &head, &vector),
            Err(StemFeatureBindingError::Revoked)
        );
    }

    #[test]
    fn final_owned_conversion_refreshes_lease_epoch_and_head_identity() {
        let (source, access, selected_head, values) = fixture();
        let view = borrow_stem_feature_request_v1(&source, &access, &selected_head, &values)
            .expect("initial view");
        assert_eq!(view.feature_vector_q24().as_ptr(), values.as_ptr());
        assert!(!view.feature_ref_digest().is_zero());
        assert!(!view.authority().grants_any());
        let mut refreshed = access.clone();
        refreshed.now_ms = 950;
        let ready = view
            .materialize_owned_after_refresh(&source, &refreshed, &selected_head)
            .expect("within lease");
        assert_eq!(ready.request.feature_vector_q24, values);
        assert!(!ready.authority.grants_any());

        refreshed.now_ms = source.lease_expires_at_ms;
        assert_eq!(
            view.materialize_owned_after_refresh(&source, &refreshed, &selected_head),
            Err(StemFeatureBindingError::LeaseExpired)
        );
        refreshed.now_ms = 950;
        refreshed.authority_epoch += 1;
        assert_eq!(
            view.materialize_owned_after_refresh(&source, &refreshed, &selected_head),
            Err(StemFeatureBindingError::AuthorityEpochMismatch)
        );
        refreshed.authority_epoch = access.authority_epoch;
        refreshed.revocation_observed = true;
        assert_eq!(
            view.materialize_owned_after_refresh(&source, &refreshed, &selected_head),
            Err(StemFeatureBindingError::Revoked)
        );
        refreshed.revocation_observed = false;
        let mut other_head = selected_head.clone();
        other_head.head_model_id = id("different-cell-head");
        assert_eq!(
            view.materialize_owned_after_refresh(&source, &refreshed, &other_head),
            Err(StemFeatureBindingError::IncompatibleHead)
        );
    }

    #[test]
    fn borrowed_view_fails_closed_on_payload_or_selected_head_drift() {
        let (source, access, mut head, vector) = fixture();
        let mut tampered = vector.clone();
        tampered[0] += 1;
        assert_eq!(
            borrow_stem_feature_request_v1(&source, &access, &head, &tampered),
            Err(StemFeatureBindingError::FeatureDigestMismatch)
        );
        head.required_projection_digest = digest(b"changed-projection");
        assert_eq!(
            borrow_stem_feature_request_v1(&source, &access, &head, &vector),
            Err(StemFeatureBindingError::IncompatibleHead)
        );
    }

    #[test]
    fn shared_stem_buffer_reuses_one_allocation_and_original_access_checks() {
        let (source, access, first_head, values) = fixture();
        let source_for_refresh = source.clone();
        let shared = SharedStemQ24BufferV1::from_unverified_source(source, values.clone())
            .expect("same-source immutable feature buffer");
        let shared_copy = shared.clone();
        let mut second_head = first_head.clone();
        second_head.request_id = id("other-request");
        second_head.head_model_id = id("other-head");

        let first = shared
            .borrow_for_head(&access, &first_head)
            .expect("validated first Cell view");
        let second = shared_copy
            .borrow_for_head(&access, &second_head)
            .expect("validated second Cell view");
        assert_eq!(
            first.feature_vector_q24().as_ptr(),
            second.feature_vector_q24().as_ptr(),
        );
        assert_eq!(first.feature_vector_q24(), values.as_slice());
        assert!(!first.authority().grants_any());
        assert!(!second.authority().grants_any());
        let old =
            bind_stem_feature_request_v1(&source_for_refresh, &access, first_head.clone(), &values)
                .expect("historical V1 representation");
        let new = first
            .materialize_owned_after_refresh(&source_for_refresh, &access, &first_head)
            .expect("same V1 after fresh owner claim");
        assert_eq!(new, old);
    }

    #[test]
    fn shared_buffer_fails_closed_on_digest_and_stale_owner_context() {
        let (mut source, mut access, head, values) = fixture();
        source.feature_digest = digest(b"wrong");
        assert!(matches!(
            SharedStemQ24BufferV1::from_unverified_source(source.clone(), values.clone()),
            Err(StemFeatureBindingError::FeatureDigestMismatch)
        ));
        source.feature_digest = stem_feature_vector_digest_v1(&values).expect("known good content");
        source.feature_width += 1;
        assert!(matches!(
            SharedStemQ24BufferV1::from_unverified_source(source.clone(), values.clone()),
            Err(StemFeatureBindingError::InvalidFeatureWidth)
        ));
        source.feature_width = values.len();
        let shared = SharedStemQ24BufferV1::from_unverified_source(source, values)
            .expect("same-source immutable feature");
        access.revocation_observed = true;
        assert!(matches!(
            shared.borrow_for_head(&access, &head),
            Err(StemFeatureBindingError::Revoked)
        ));
        access.revocation_observed = false;
        access.authority_epoch += 1;
        assert!(matches!(
            shared.borrow_for_head(&access, &head),
            Err(StemFeatureBindingError::AuthorityEpochMismatch)
        ));
    }

    #[test]
    fn immutable_512d_buffer_and_mutable_slice_borrow_agree_on_v1_identity() {
        let (mut source, access, mut head, _) = fixture();
        let original = vec![Q24 / 8; 512];
        source.feature_width = original.len();
        source.feature_digest =
            stem_feature_vector_digest_v1(&original).expect("bounded 512D vector");
        head.required_feature_width = original.len();
        head.required_encoder_digest = stem_encoder_pipeline_digest_v1(&source);

        let shared =
            SharedStemQ24BufferV1::from_unverified_source(source.clone(), original.clone())
                .expect("one content validation during immutable construction");
        let direct = borrow_stem_feature_request_v1(&source, &access, &head, &original)
            .expect("direct caller-provided slice validates its digest");
        let fast = shared
            .borrow_for_head(&access, &head)
            .expect("immutable Arc reuses validated digest");
        assert_eq!(fast.feature_vector_q24(), direct.feature_vector_q24());
        assert_eq!(fast.feature_ref_digest(), direct.feature_ref_digest());
        assert!(!fast.authority().grants_any());

        let direct_owned = direct
            .materialize_owned_after_refresh(&source, &access, &head)
            .expect("legacy owned V1 conversion");
        let fast_owned = fast
            .materialize_owned_after_refresh(&source, &access, &head)
            .expect("immutable borrowed V1 conversion");
        assert_eq!(direct_owned, fast_owned);

        let mut changed_original = original;
        changed_original[511] += 1;
        assert_eq!(
            borrow_stem_feature_request_v1(&source, &access, &head, &changed_original),
            Err(StemFeatureBindingError::FeatureDigestMismatch)
        );
        // Safe mutation of an unrelated Vec cannot poison immutable Arc bytes.
        assert_eq!(
            shared
                .borrow_for_head(&access, &head)
                .expect("unchanged shared content")
                .feature_vector_q24(),
            direct_owned.request.feature_vector_q24.as_slice()
        );
    }

    #[test]
    fn immutable_buffer_does_not_bypass_fresh_principal_or_lease() {
        let (source, access, head, original) = fixture();
        let shared = SharedStemQ24BufferV1::from_unverified_source(source.clone(), original)
            .expect("immutable source");
        let mut future = access.clone();
        future.principal_id = id("another-principal");
        assert!(matches!(
            shared.borrow_for_head(&future, &head),
            Err(StemFeatureBindingError::PrincipalMismatch)
        ));
        future.principal_id = access.principal_id;
        future.now_ms = source.lease_expires_at_ms;
        assert!(matches!(
            shared.borrow_for_head(&future, &head),
            Err(StemFeatureBindingError::LeaseExpired)
        ));
        future.now_ms = 900;
        future.revocation_observed = true;
        assert!(matches!(
            shared.borrow_for_head(&future, &head),
            Err(StemFeatureBindingError::Revoked)
        ));
    }

    #[test]
    fn immutable_owned_boundary_keeps_same_v1_digest_after_fresh_claim() {
        let (source, access, head, values) = fixture();
        let shared = SharedStemQ24BufferV1::from_unverified_source(source.clone(), values.clone())
            .expect("buffer initialized from exact Q24 bytes");
        let old = bind_stem_feature_request_v1(&source, &access, head.clone(), &values)
            .expect("existing owned V1 request");
        let actual = shared
            .materialize_owned_for_head(&access, &head)
            .expect("current owner claim passes");
        assert_eq!(old, actual);
        assert!(!actual.authority.grants_any());

        let mut expired = access.clone();
        expired.now_ms = source.lease_expires_at_ms;
        assert_eq!(
            shared.materialize_owned_for_head(&expired, &head),
            Err(StemFeatureBindingError::LeaseExpired)
        );
        expired.now_ms = access.now_ms;
        expired.revocation_observed = true;
        assert_eq!(
            shared.materialize_owned_for_head(&expired, &head),
            Err(StemFeatureBindingError::Revoked)
        );
    }

    #[test]
    fn cached_source_and_pipeline_digests_match_direct_for_4096_logical_heads() {
        let (source, access, mut head, features) = fixture();
        let immutable =
            SharedStemQ24BufferV1::from_unverified_source(source.clone(), features.clone())
                .expect("bounded immutable feature allocated once");
        let shared_pointer = immutable
            .borrow_for_head(&access, &head)
            .expect("borrow same immutable allocation")
            .feature_vector_q24()
            .as_ptr();
        let direct_ref = borrow_stem_feature_request_v1(&source, &access, &head, &features)
            .expect("direct-source reference")
            .feature_ref_digest();
        for index in 0..4096 {
            // Logical Heads only; NOT 4096 model executions or a host SLO.
            head.request_id = id(&format!("request:cell:{index}"));
            head.head_model_id = id(&format!("cell-head:{index}"));
            let borrow = immutable
                .borrow_for_head(&access, &head)
                .expect("each Cell checks owner and Head claims");
            assert_eq!(borrow.feature_vector_q24().as_ptr(), shared_pointer);
            assert_eq!(borrow.feature_ref_digest(), direct_ref);
            assert!(!borrow.authority().grants_any());
        }
    }

    #[test]
    fn cached_source_identity_cannot_make_changed_head_or_epoch_valid() {
        let (source, mut access, mut head, features) = fixture();
        let cached = SharedStemQ24BufferV1::from_unverified_source(source, features)
            .expect("immutability source");
        head.required_encoder_digest = digest(b"changed-encoder");
        assert!(matches!(
            cached.borrow_for_head(&access, &head),
            Err(StemFeatureBindingError::IncompatibleHead)
        ));
        access.authority_epoch += 1;
        assert!(matches!(
            cached.borrow_for_head(&access, &head),
            Err(StemFeatureBindingError::AuthorityEpochMismatch)
        ));
    }

    #[test]
    fn original_shared_q24_arc_reuses_allocation_with_stem_but_never_digest_authority() {
        let (mut source, access, mut head, _) = fixture();
        let features = vec![Q24 / 2; 512];
        source.feature_width = features.len();
        source.feature_digest =
            stem_feature_vector_digest_v1(&features).expect("Stem source domain");
        head.required_feature_width = features.len();
        head.required_encoder_digest = stem_encoder_pipeline_digest_v1(&source);

        let original = crate::SharedFeatureBufferV1::from_vec(features.clone())
            .expect("original Neuron Q24 buffer");
        assert_ne!(
            original.digest(),
            source.feature_digest,
            "Neuron V1 and Stem V1 source digests are domain-separated"
        );

        // The legacy digest cannot be smuggled in as a Stem source signature
        // or an accepted Stem feature digest, even when bytes are identical.
        let mut wrong_source = source.clone();
        wrong_source.feature_digest = original.digest();
        assert!(matches!(
            SharedStemQ24BufferV1::from_unverified_arc(
                wrong_source,
                original.shared_arc(),
            ),
            Err(StemFeatureBindingError::FeatureDigestMismatch)
        ));

        // Arc::clone increments reference count WITHOUT allocating another
        // 512-D Q24 Vec. The existing original and new Stem views own exactly
        // one underlying, immutable data allocation.
        let retained_ptr = original.as_slice().as_ptr();
        let new_stem =
            SharedStemQ24BufferV1::from_unverified_arc(source, original.shared_arc())
                .expect("actual matching Stem-domain content digest");
        let view = new_stem
            .borrow_for_head(&access, &head)
            .expect("fresh checked Stem-to-Head view");
        assert_eq!(view.feature_vector_q24().as_ptr(), retained_ptr);
        assert_eq!(view.feature_vector_q24(), features.as_slice());
        assert!(!view.authority().grants_any());

        // Physical pointer reuse is never a principal, epoch, or revocation
        // grant; changing live access still fails before returning any Head
        // decision input.
        let mut revoked = access;
        revoked.revocation_observed = true;
        assert!(matches!(
            new_stem.borrow_for_head(&revoked, &head),
            Err(StemFeatureBindingError::Revoked)
        ));
    }

}
