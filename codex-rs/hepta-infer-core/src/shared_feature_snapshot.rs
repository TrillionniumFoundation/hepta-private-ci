//! Opt-in immutable Q24 feature sharing inside one process.
//!
//! The owner must provide a *fresh, independently authenticated* scope /
//! generation / fence binding at each use, including final dispatch. Neither
//! possession of this Arc nor its digest grants inference or promotion authority.
//! No worker wire schema, legacy replay or production routing is changed here.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::NeuronFeatureContractError;
use crate::NeuronFeatureRequestViewV1;
use crate::neuron_feature_request_view_digest_v1;

const Q24: i64 = 1 << 24;
const MAX_ABS_FEATURE_Q24: i64 = 8 * Q24;
const MAX_FEATURE_DIMENSION: usize = 512;

/// Identifies the *shareable source feature*, not a per-Cell tick or head.
/// Source provenance is supplied by the upstream owner and must be verified
/// there against the actual immutable encoder, tokenizer and input artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureSnapshotBindingV1 {
    pub sharing_scope_id: StableId,
    pub generation: Generation,
    pub fence: u64,
    pub encoder_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub normalization_digest: Digest32,
    pub quantization_digest: Digest32,
    pub source_digest: Digest32,
}

/// Caller-owned per-Cell metadata, intentionally excluding the shared vector.
/// The tick-specific input digest may legitimately differ between Cells while
/// their frozen upstream features are identical.
#[derive(Clone, Copy)]
pub struct NeuronFeatureRequestMetadataV1<'a> {
    pub request_id: &'a StableId,
    pub generation: Generation,
    pub model_id: &'a StableId,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub weights_digest: Digest32,
    pub input_digest: Digest32,
    pub expected_output_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FeatureSnapshotError {
    EmptyDigest(&'static str),
    InvalidFence,
    FeatureLimit,
    Arithmetic,
    BindingMismatch,
    InvalidRequest(NeuronFeatureContractError),
}

impl fmt::Display for FeatureSnapshotError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for FeatureSnapshotError {}

/// One bounded immutable buffer allocated once and shared by cheap Arc clones.
/// Private payload prevents mutation or unguarded read through this API.
pub struct FeatureSnapshotRefV1 {
    binding: FeatureSnapshotBindingV1,
    features: Arc<[i64]>,
    feature_content_digest: Digest32,
    snapshot_digest: Digest32,
}

impl FeatureSnapshotRefV1 {
    /// Takes ownership of the original Vec; does not allocate a buffer per Cell.
    /// The receipt is a content identity, not a signature or a runtime witness.
    pub fn new(
        binding: FeatureSnapshotBindingV1,
        features: Vec<i64>,
    ) -> Result<Self, FeatureSnapshotError> {
        validate_binding(&binding)?;
        if features.is_empty()
            || features.len() > MAX_FEATURE_DIMENSION
            || features
                .iter()
                .any(|x| !(-MAX_ABS_FEATURE_Q24..=MAX_ABS_FEATURE_Q24).contains(x))
        {
            return Err(FeatureSnapshotError::FeatureLimit);
        }
        let mut payload = b"hepta.inference.feature-q24-content.v1".to_vec();
        payload.extend_from_slice(
            &u64::try_from(features.len())
                .map_err(|_| FeatureSnapshotError::Arithmetic)?
                .to_be_bytes(),
        );
        for value in &features {
            payload.extend_from_slice(&value.to_be_bytes());
        }
        let feature_content_digest = Digest32::of_bytes(&payload);
        let snapshot_digest = compute_snapshot_digest(&binding, feature_content_digest)?;
        Ok(Self {
            binding,
            features: Arc::from(features.into_boxed_slice()),
            feature_content_digest,
            snapshot_digest,
        })
    }

    #[must_use]
    pub fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub fn feature_content_digest(&self) -> Digest32 {
        self.feature_content_digest
    }

    /// Cheap in-process sharing; this cannot be serialized into an authority
    /// token. The caller must re-read the current owner binding at final use.
    pub fn share(
        &self,
        current_owner_binding: &FeatureSnapshotBindingV1,
    ) -> Result<Self, FeatureSnapshotError> {
        self.check_binding(current_owner_binding)?;
        Ok(Self {
            binding: self.binding.clone(),
            features: Arc::clone(&self.features),
            feature_content_digest: self.feature_content_digest,
            snapshot_digest: self.snapshot_digest,
        })
    }

    /// Borrow only while a freshly resolved owner binding matches exactly.
    /// The caller must revalidate at dispatch, not just at enqueue time.
    pub fn borrow_q24(
        &self,
        current_owner_binding: &FeatureSnapshotBindingV1,
    ) -> Result<&[i64], FeatureSnapshotError> {
        self.check_binding(current_owner_binding)?;
        Ok(&self.features)
    }

    /// Build a fully typed, borrow-only V1 request view. This can be digested
    /// or consumed by an in-process backend without rematerializing the input.
    /// Encoding as the existing owned V1 / worker wire request still copies.
    pub fn request_view<'a>(
        &'a self,
        current_owner_binding: &FeatureSnapshotBindingV1,
        metadata: NeuronFeatureRequestMetadataV1<'a>,
    ) -> Result<NeuronFeatureRequestViewV1<'a>, FeatureSnapshotError> {
        self.check_binding(current_owner_binding)?;
        if metadata.generation != self.binding.generation
            || metadata.encoder_digest != self.binding.encoder_digest
        {
            return Err(FeatureSnapshotError::BindingMismatch);
        }
        let view = NeuronFeatureRequestViewV1 {
            request_id: metadata.request_id,
            generation: metadata.generation,
            model_id: metadata.model_id,
            encoder_digest: metadata.encoder_digest,
            head_digest: metadata.head_digest,
            weights_digest: metadata.weights_digest,
            input_digest: metadata.input_digest,
            feature_vector_q24: &self.features,
            expected_output_width: metadata.expected_output_width,
        };
        neuron_feature_request_view_digest_v1(&view)
            .map_err(FeatureSnapshotError::InvalidRequest)?;
        Ok(view)
    }

    fn check_binding(
        &self,
        current_owner_binding: &FeatureSnapshotBindingV1,
    ) -> Result<(), FeatureSnapshotError> {
        // Caller supplies *current* state; this type is not an authority oracle.
        if &self.binding != current_owner_binding {
            return Err(FeatureSnapshotError::BindingMismatch);
        }
        Ok(())
    }
}

fn validate_binding(binding: &FeatureSnapshotBindingV1) -> Result<(), FeatureSnapshotError> {
    if binding.fence == 0 {
        return Err(FeatureSnapshotError::InvalidFence);
    }
    for (name, digest) in [
        ("encoder", binding.encoder_digest),
        ("tokenizer", binding.tokenizer_digest),
        ("preprocessor", binding.preprocessor_digest),
        ("normalization", binding.normalization_digest),
        ("quantization", binding.quantization_digest),
        ("source", binding.source_digest),
    ] {
        if digest.is_zero() {
            return Err(FeatureSnapshotError::EmptyDigest(name));
        }
    }
    Ok(())
}

fn compute_snapshot_digest(
    binding: &FeatureSnapshotBindingV1,
    content: Digest32,
) -> Result<Digest32, FeatureSnapshotError> {
    let mut payload = b"hepta.inference.feature-snapshot.v1".to_vec();
    let id = binding.sharing_scope_id.as_str().as_bytes();
    payload.extend_from_slice(
        &u32::try_from(id.len())
            .map_err(|_| FeatureSnapshotError::Arithmetic)?
            .to_be_bytes(),
    );
    payload.extend_from_slice(id);
    payload.extend_from_slice(&binding.generation.get().to_be_bytes());
    payload.extend_from_slice(&binding.fence.to_be_bytes());
    for digest in [
        binding.encoder_digest,
        binding.tokenizer_digest,
        binding.preprocessor_digest,
        binding.normalization_digest,
        binding.quantization_digest,
        binding.source_digest,
        content,
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&payload))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::NeuronFeatureRequestV1;
    use crate::neuron_feature_request_digest_v1;

    fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
        result.unwrap_or_else(|error| panic!("fixture: {error:?}"))
    }

    fn binding() -> FeatureSnapshotBindingV1 {
        FeatureSnapshotBindingV1 {
            sharing_scope_id: checked(StableId::new("scope:shared.1")),
            generation: checked(Generation::new(4)),
            fence: 11,
            encoder_digest: Digest32::of_bytes(b"encoder"),
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
            normalization_digest: Digest32::of_bytes(b"normalization"),
            quantization_digest: Digest32::of_bytes(b"quantization"),
            source_digest: Digest32::of_bytes(b"source-event"),
        }
    }

    #[test]
    fn multiple_cells_share_exact_same_immutable_allocation() {
        let key = binding();
        let snapshot = checked(FeatureSnapshotRefV1::new(key.clone(), vec![Q24, -Q24]));
        let a = checked(snapshot.share(&key));
        let b = checked(snapshot.share(&key));
        assert_eq!(
            checked(a.borrow_q24(&key)).as_ptr(),
            checked(b.borrow_q24(&key)).as_ptr()
        );
        assert_eq!(a.snapshot_digest(), b.snapshot_digest());
        assert_ne!(a.feature_content_digest(), Digest32::ZERO);
    }

    #[test]
    fn scope_generation_fence_or_encoder_replacement_blocks_reuse() {
        let key = binding();
        let snapshot = checked(FeatureSnapshotRefV1::new(key.clone(), vec![Q24]));
        let mut changed = key.clone();
        changed.fence += 1;
        assert!(matches!(
            snapshot.borrow_q24(&changed),
            Err(FeatureSnapshotError::BindingMismatch)
        ));
        changed = key.clone();
        changed.generation = checked(Generation::new(5));
        assert!(snapshot.share(&changed).is_err());
        changed = key.clone();
        changed.sharing_scope_id = checked(StableId::new("scope:other"));
        assert!(snapshot.borrow_q24(&changed).is_err());
        changed = key.clone();
        changed.tokenizer_digest = Digest32::of_bytes(b"new-tokenizer");
        assert!(snapshot.borrow_q24(&changed).is_err());
        changed = key.clone();
        changed.encoder_digest = Digest32::of_bytes(b"new-encoder");
        assert!(snapshot.borrow_q24(&changed).is_err());
    }

    #[test]
    fn rejects_missing_provenance_zero_fence_and_bad_q24() {
        let mut key = binding();
        key.fence = 0;
        assert!(matches!(
            FeatureSnapshotRefV1::new(key, vec![Q24]),
            Err(FeatureSnapshotError::InvalidFence)
        ));
        let mut key = binding();
        key.quantization_digest = Digest32::ZERO;
        assert!(matches!(
            FeatureSnapshotRefV1::new(key, vec![Q24]),
            Err(FeatureSnapshotError::EmptyDigest("quantization"))
        ));
        let key = binding();
        assert!(matches!(
            FeatureSnapshotRefV1::new(key.clone(), Vec::new()),
            Err(FeatureSnapshotError::FeatureLimit)
        ));
        assert!(matches!(
            FeatureSnapshotRefV1::new(key.clone(), vec![0; 513]),
            Err(FeatureSnapshotError::FeatureLimit)
        ));
        assert!(matches!(
            FeatureSnapshotRefV1::new(key, vec![MAX_ABS_FEATURE_Q24 + 1]),
            Err(FeatureSnapshotError::FeatureLimit)
        ));
    }

    #[test]
    fn borrowed_view_matches_legacy_v1_digest_without_new_vector() {
        let key = binding();
        let q24 = vec![Q24 / 2, -Q24 / 4];
        let snapshot = checked(FeatureSnapshotRefV1::new(key.clone(), q24.clone()));
        let request_id = checked(StableId::new("request.cell.1"));
        let model_id = checked(StableId::new("model.cell.1"));
        let head = Digest32::of_bytes(b"head");
        let weights = Digest32::of_bytes(b"weights");
        let input = Digest32::of_bytes(b"per-cell-tick");
        let view = checked(snapshot.request_view(
            &key,
            NeuronFeatureRequestMetadataV1 {
                request_id: &request_id,
                generation: key.generation,
                model_id: &model_id,
                encoder_digest: key.encoder_digest,
                head_digest: head,
                weights_digest: weights,
                input_digest: input,
                expected_output_width: 5,
            },
        ));
        let digest = checked(neuron_feature_request_view_digest_v1(&view));
        assert_eq!(
            digest,
            checked(neuron_feature_request_digest_v1(&NeuronFeatureRequestV1 {
                request_id,
                generation: key.generation,
                model_id,
                encoder_digest: key.encoder_digest,
                head_digest: head,
                weights_digest: weights,
                input_digest: input,
                feature_vector_q24: q24,
                expected_output_width: 5,
            }))
        );
    }

    #[test]
    fn cannot_borrow_for_wrong_encoder_generation_or_bad_output_size() {
        let key = binding();
        let snapshot = checked(FeatureSnapshotRefV1::new(key.clone(), vec![Q24]));
        let request_id = checked(StableId::new("request.cell.2"));
        let model_id = checked(StableId::new("model.cell.2"));
        let mut metadata = NeuronFeatureRequestMetadataV1 {
            request_id: &request_id,
            generation: key.generation,
            model_id: &model_id,
            encoder_digest: Digest32::of_bytes(b"wrong"),
            head_digest: Digest32::of_bytes(b"head"),
            weights_digest: Digest32::of_bytes(b"weights"),
            input_digest: Digest32::of_bytes(b"input"),
            expected_output_width: 5,
        };
        assert!(matches!(
            snapshot.request_view(&key, metadata),
            Err(FeatureSnapshotError::BindingMismatch)
        ));
        metadata.encoder_digest = key.encoder_digest;
        metadata.generation = checked(Generation::new(5));
        assert!(snapshot.request_view(&key, metadata).is_err());
        metadata.generation = key.generation;
        metadata.expected_output_width = 513;
        assert!(matches!(
            snapshot.request_view(&key, metadata),
            Err(FeatureSnapshotError::InvalidRequest(
                NeuronFeatureContractError::FeatureLimit
            ))
        ));
    }

    #[test]
    fn payload_and_provenance_change_snapshot_identity() {
        let key = binding();
        let x = checked(FeatureSnapshotRefV1::new(key.clone(), vec![Q24]));
        let y = checked(FeatureSnapshotRefV1::new(key.clone(), vec![Q24 / 2]));
        assert_ne!(x.feature_content_digest(), y.feature_content_digest());
        assert_ne!(x.snapshot_digest(), y.snapshot_digest());
        let mut changed = key;
        changed.source_digest = Digest32::of_bytes(b"different-source");
        let z = checked(FeatureSnapshotRefV1::new(changed, vec![Q24]));
        assert_eq!(x.feature_content_digest(), z.feature_content_digest());
        assert_ne!(x.snapshot_digest(), z.snapshot_digest());
    }
}
