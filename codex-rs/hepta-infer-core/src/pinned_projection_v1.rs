//! Pinned, non-authorizing Q24 feature projection for a shared Encoder.
//!
//! A genuine pretrained Encoder may produce 768-dimensional features, while
//! the current CPU Cell Head and SharedFeatureCacheV2 accept at most 512.
//! No caller may silently truncate an Encoder tensor or widen a production
//! budget. This adapter requires every row of a complete, immutable, pinned
//! projection before inserting a new shared feature snapshot.
//!
//! This module does NOT load pretrained weights, validate a CAS signature,
//! verify a source grant, train a projection, or authorize physical inference.
//! The upstream owner must attest the admitted joint input and its Q24 source
//! features, and downstream final-use admission remains mandatory.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;

use crate::shared_feature_v2::ImmutableFeatureSnapshotV2;
use crate::shared_feature_v2::SharedFeatureCacheV2;
use crate::shared_feature_v2::SharedFeatureErrorV2;
use crate::shared_feature_v2::SharedFeatureIdentityV2;

const Q24: i64 = 1 << 24;
const Q24_ABS_BOUND: i64 = 8 * Q24;
const MAX_SOURCE_WIDTH: usize = 1024;
const MAX_CELL_WIDTH: usize = 512;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProjectionSourcePinsV1 {
    pub encoder_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub normalizer_digest: Digest32,
    pub quantization_digest: Digest32,
}

#[derive(Clone, Debug)]
pub struct PinnedQ24ProjectionConfigV1 {
    pub source: ProjectionSourcePinsV1,
    pub source_width: usize,
    pub cell_width: usize,
    /// Dense row-major tensor: cell_width x source_width.
    pub weights_q24: Arc<[i64]>,
    /// Exactly one Q24 bias per cell feature.
    pub bias_q24: Arc<[i64]>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProjectionErrorV1 {
    InvalidPins,
    InvalidDimensions,
    InvalidWeights,
    InvalidSource,
    InvalidOutput,
    Overflow,
    Cache(SharedFeatureErrorV2),
}

impl fmt::Display for ProjectionErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for ProjectionErrorV1 {}

/// A reference-only immutable projection. It is not a model-loader receipt.
#[derive(Clone, Debug)]
pub struct PinnedQ24ProjectionV1 {
    config: PinnedQ24ProjectionConfigV1,
    projection_digest: Digest32,
    projected_normalizer_digest: Digest32,
}

impl PinnedQ24ProjectionV1 {
    pub fn new(config: PinnedQ24ProjectionConfigV1) -> Result<Self, ProjectionErrorV1> {
        if [
            config.source.encoder_digest,
            config.source.tokenizer_digest,
            config.source.normalizer_digest,
            config.source.quantization_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
        {
            return Err(ProjectionErrorV1::InvalidPins);
        }
        if config.source_width == 0
            || config.source_width > MAX_SOURCE_WIDTH
            || config.cell_width == 0
            || config.cell_width > MAX_CELL_WIDTH
        {
            return Err(ProjectionErrorV1::InvalidDimensions);
        }
        let expected = config
            .source_width
            .checked_mul(config.cell_width)
            .ok_or(ProjectionErrorV1::Overflow)?;
        if config.weights_q24.len() != expected
            || config.bias_q24.len() != config.cell_width
            || !bounded_q24(&config.weights_q24)
            || !bounded_q24(&config.bias_q24)
        {
            return Err(ProjectionErrorV1::InvalidWeights);
        }

        // Hash the actual complete weight and bias tensors, not a claimed
        // artifact digest or only a shape/metadata identity.
        let mut canonical = b"hepta.infer.pinned-q24-projection.v1".to_vec();
        for digest in [
            config.source.encoder_digest,
            config.source.tokenizer_digest,
            config.source.normalizer_digest,
            config.source.quantization_digest,
        ] {
            canonical.extend_from_slice(digest.as_array());
        }
        canonical.extend_from_slice(&(config.source_width as u64).to_be_bytes());
        canonical.extend_from_slice(&(config.cell_width as u64).to_be_bytes());
        for tensor in [&config.weights_q24, &config.bias_q24] {
            canonical.extend_from_slice(&(tensor.len() as u64).to_be_bytes());
            for element in tensor.iter() {
                canonical.extend_from_slice(&element.to_be_bytes());
            }
        }
        let projection_digest = Digest32::of_bytes(&canonical);
        // The selected Worker manifest must bind this derived preprocessor
        // digest. Merely reusing a source normalizer digest would incorrectly
        // alias two independently selected projections.
        let mut normalizer = b"hepta.infer.projected-normalizer.v1".to_vec();
        normalizer.extend_from_slice(config.source.normalizer_digest.as_array());
        normalizer.extend_from_slice(projection_digest.as_array());
        let projected_normalizer_digest = Digest32::of_bytes(&normalizer);
        Ok(Self {
            config,
            projection_digest,
            projected_normalizer_digest,
        })
    }

    pub fn projection_digest(&self) -> Digest32 {
        self.projection_digest
    }

    pub fn projected_normalizer_digest(&self) -> Digest32 {
        self.projected_normalizer_digest
    }

    pub fn source_width(&self) -> usize {
        self.config.source_width
    }

    pub fn cell_width(&self) -> usize {
        self.config.cell_width
    }

    /// Project one already-admitted source feature and publish a single
    /// immutable cache entry shared by independently admitted logical Cells.
    ///
    /// This consumes the WHOLE source width. No implicit truncation, slicing,
    /// per-Cell re-encoding, clipping, or unsigned execution grant is allowed.
    pub fn project_into_cache(
        &self,
        cache: &mut SharedFeatureCacheV2,
        now_ms: u64,
        expires_at_ms: u64,
        source_identity: &SharedFeatureIdentityV2,
        source_q24: &[i64],
    ) -> Result<Arc<ImmutableFeatureSnapshotV2>, ProjectionErrorV1> {
        source_identity
            .digest()
            .map_err(|_| ProjectionErrorV1::InvalidPins)?;
        if source_identity.encoder_digest != self.config.source.encoder_digest
            || source_identity.tokenizer_digest != self.config.source.tokenizer_digest
            || source_identity.normalizer_digest != self.config.source.normalizer_digest
            || source_identity.quantization_digest != self.config.source.quantization_digest
        {
            return Err(ProjectionErrorV1::InvalidPins);
        }
        if source_q24.len() != self.config.source_width || !bounded_q24(source_q24) {
            return Err(ProjectionErrorV1::InvalidSource);
        }

        let mut output_q24 = Vec::with_capacity(self.config.cell_width);
        for (row, bias) in self
            .config
            .weights_q24
            .chunks_exact(self.config.source_width)
            .zip(self.config.bias_q24.iter())
        {
            let mut sum = 0_i128;
            for (&weight, &feature) in row.iter().zip(source_q24.iter()) {
                sum = sum
                    .checked_add(i128::from(weight) * i128::from(feature))
                    .ok_or(ProjectionErrorV1::Overflow)?;
            }
            let projected = q24_round_ties_even(sum)?
                .checked_add(*bias)
                .ok_or(ProjectionErrorV1::Overflow)?;
            if !(-Q24_ABS_BOUND..=Q24_ABS_BOUND).contains(&projected) {
                return Err(ProjectionErrorV1::InvalidOutput);
            }
            output_q24.push(projected);
        }
        // Preserve principal, purpose, generation, authority epoch, tokenizer
        // and admitted complete-input identity. Bind the numerical projection
        // through the derived normalizer identity required by the Worker.
        let mut projected_identity = source_identity.clone();
        projected_identity.normalizer_digest = self.projected_normalizer_digest;
        cache
            .insert(
                now_ms,
                projected_identity,
                expires_at_ms,
                Arc::from(output_q24),
            )
            .map_err(ProjectionErrorV1::Cache)
    }
}

fn bounded_q24(values: &[i64]) -> bool {
    values
        .iter()
        .all(|value| (-Q24_ABS_BOUND..=Q24_ABS_BOUND).contains(value))
}

fn q24_round_ties_even(value: i128) -> Result<i64, ProjectionErrorV1> {
    let magnitude = value.checked_abs().ok_or(ProjectionErrorV1::Overflow)?;
    let whole = magnitude >> 24;
    let fraction = magnitude & i128::from(Q24 - 1);
    let half = i128::from(Q24 / 2);
    let increment = fraction > half || (fraction == half && whole & 1 == 1);
    let rounded = whole
        .checked_add(i128::from(u8::from(increment)))
        .ok_or(ProjectionErrorV1::Overflow)?;
    let signed = if value < 0 { -rounded } else { rounded };
    i64::try_from(signed).map_err(|_| ProjectionErrorV1::Overflow)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    fn pins() -> ProjectionSourcePinsV1 {
        ProjectionSourcePinsV1 {
            encoder_digest: Digest32::of_bytes(b"pinned-modernbert-weights"),
            tokenizer_digest: Digest32::of_bytes(b"pinned-tokenizer"),
            normalizer_digest: Digest32::of_bytes(b"source-normalizer"),
            quantization_digest: Digest32::of_bytes(b"source-q24"),
        }
    }

    fn identity(input: &str) -> SharedFeatureIdentityV2 {
        let p = pins();
        SharedFeatureIdentityV2 {
            principal_id: StableId::new("principal.one".to_string()).expect("principal"),
            purpose_id: StableId::new("purpose.prediction".to_string()).expect("purpose"),
            generation: Generation::new(3).expect("generation"),
            authority_epoch: 4,
            encoder_digest: p.encoder_digest,
            tokenizer_digest: p.tokenizer_digest,
            normalizer_digest: p.normalizer_digest,
            quantization_digest: p.quantization_digest,
            input_digest: Digest32::of_bytes(input.as_bytes()),
        }
    }

    fn config(
        source_width: usize,
        cell_width: usize,
        weights: Vec<i64>,
    ) -> PinnedQ24ProjectionConfigV1 {
        PinnedQ24ProjectionConfigV1 {
            source: pins(),
            source_width,
            cell_width,
            weights_q24: Arc::from(weights),
            bias_q24: Arc::from(vec![0_i64; cell_width]),
        }
    }

    #[test]
    fn full_768_wide_source_is_explicitly_projected_and_reused() {
        let mut weights = vec![0_i64; 768 * 2];
        weights[0] = Q24;
        weights[768 + 767] = Q24;
        let projector = PinnedQ24ProjectionV1::new(config(768, 2, weights))
            .expect("projector");
        let mut input = vec![0_i64; 768];
        input[0] = Q24 / 2;
        input[767] = -(Q24 / 4);
        let source = identity("admitted complete state, question and options");
        let mut cache = SharedFeatureCacheV2::new(4, 4096).expect("cache");

        let snapshot = projector
            .project_into_cache(&mut cache, 1, 100, &source, &input)
            .expect("project");
        assert_eq!(snapshot.features_q24.as_ref(), &[Q24 / 2, -(Q24 / 4)]);
        assert_eq!(snapshot.identity.input_digest, source.input_digest);
        assert_eq!(snapshot.identity.principal_id, source.principal_id);
        assert_ne!(snapshot.identity.normalizer_digest, source.normalizer_digest);
        assert_eq!(
            snapshot.identity.normalizer_digest,
            projector.projected_normalizer_digest()
        );
        let reused = projector
            .project_into_cache(&mut cache, 2, 100, &source, &input)
            .expect("reused");
        assert!(Arc::ptr_eq(&snapshot, &reused));

        let changed_input = identity("a different admitted joint input");
        let distinct = projector
            .project_into_cache(&mut cache, 3, 100, &changed_input, &input)
            .expect("new identity");
        assert!(!Arc::ptr_eq(&snapshot, &distinct));
        assert_eq!(cache.len(), 2);
    }

    #[test]
    fn rejects_implicit_truncation_and_wrong_model_pins() {
        let projector =
            PinnedQ24ProjectionV1::new(config(3, 1, vec![Q24, 0, Q24])).expect("projector");
        let mut cache = SharedFeatureCacheV2::new(2, 128).expect("cache");
        let source = identity("full input");
        assert_eq!(
            projector.project_into_cache(&mut cache, 1, 10, &source, &[Q24, 0]),
            Err(ProjectionErrorV1::InvalidSource)
        );
        let mut wrong = source.clone();
        wrong.tokenizer_digest = Digest32::of_bytes(b"different-tokenizer");
        assert_eq!(
            projector.project_into_cache(&mut cache, 1, 10, &wrong, &[Q24, 0, Q24]),
            Err(ProjectionErrorV1::InvalidPins)
        );
        assert!(cache.is_empty());
    }

    #[test]
    fn rounding_is_ties_to_even_for_both_signs() {
        let projector =
            PinnedQ24ProjectionV1::new(config(1, 1, vec![1])).expect("projector");
        let mut cache = SharedFeatureCacheV2::new(4, 128).expect("cache");
        for (label, feature, expected) in [
            ("positive even", Q24 / 2, 0),
            ("positive odd", 3 * Q24 / 2, 2),
            ("negative even", -(Q24 / 2), 0),
            ("negative odd", -(3 * Q24 / 2), -2),
        ] {
            let snapshot = projector
                .project_into_cache(&mut cache, 1, 20, &identity(label), &[feature])
                .expect("rounded");
            assert_eq!(snapshot.features_q24[0], expected);
        }
    }

    #[test]
    fn rejects_saturation_and_invalid_tensors_before_cache_mutation() {
        let projector =
            PinnedQ24ProjectionV1::new(config(2, 1, vec![8 * Q24, 8 * Q24]))
                .expect("projector");
        let mut cache = SharedFeatureCacheV2::new(2, 128).expect("cache");
        assert_eq!(
            projector.project_into_cache(
                &mut cache,
                1,
                20,
                &identity("overflow"),
                &[8 * Q24, 8 * Q24],
            ),
            Err(ProjectionErrorV1::InvalidOutput)
        );
        assert!(cache.is_empty());
        assert_eq!(
            PinnedQ24ProjectionV1::new(config(3, 1, vec![Q24; 2]))
                .err(),
            Some(ProjectionErrorV1::InvalidWeights)
        );
        let mut invalid = config(1, 1, vec![Q24]);
        invalid.source.encoder_digest = Digest32::ZERO;
        assert_eq!(
            PinnedQ24ProjectionV1::new(invalid).err(),
            Some(ProjectionErrorV1::InvalidPins)
        );
    }

    #[test]
    fn projection_weights_change_the_selected_preprocessor_identity() {
        let first =
            PinnedQ24ProjectionV1::new(config(2, 1, vec![Q24, 0])).expect("first");
        let second =
            PinnedQ24ProjectionV1::new(config(2, 1, vec![0, Q24])).expect("second");
        assert_ne!(first.projection_digest(), second.projection_digest());
        assert_ne!(
            first.projected_normalizer_digest(),
            second.projected_normalizer_digest()
        );
    }
}
