//! Deterministic multimodal stem for the shared Encoder seam.
//!
//! Each configured modality owns a bounded Q24 affine projector. One stem
//! invocation evaluates every present modality in the declared order, emits
//! zeroes for missing modalities, and appends a Q24 missing-modality mask to
//! the ordered feature vector. The output carries source, manifest, and stem
//! digests so a later shared Encoder receipt can bind the exact provenance.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MULTIMODAL_Q24_SCALE: i128 = 1_i128 << 24;
const MULTIMODAL_Q24_ONE: i64 = 1_i64 << 24;

/// Maximum number of modality slots in one stem manifest.
pub const MAX_MULTIMODAL_MODALITIES_V1: usize = 32;
/// Maximum input width accepted by one modality projector.
pub const MAX_MULTIMODAL_INPUT_WIDTH_V1: usize = 4_096;
/// Maximum output width emitted by one modality projector.
pub const MAX_MULTIMODAL_OUTPUT_WIDTH_V1: usize = 1_024;
/// Maximum total Encoder width, including one missing-mask value per slot.
pub const MAX_MULTIMODAL_FEATURES_V1: usize = 4_096;
/// Maximum signed Q24 magnitude accepted by parameters and values.
pub const MAX_MULTIMODAL_Q24_V1: i64 = 8 * MULTIMODAL_Q24_ONE;
/// Maximum number of affine parameters in one modality projector.
pub const MAX_MULTIMODAL_PROJECTOR_PARAMS_V1: usize = 262_144;

/// One immutable affine projector for a declared modality.
///
/// The projector digest covers its modality id, generation, dimensions, and
/// parameters. It is therefore impossible to substitute one modality's
/// projector while retaining the same manifest digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModalityProjectorV1 {
    modality_id: StableId,
    generation: Generation,
    projector_digest: Digest32,
    input_width: usize,
    output_width: usize,
    weights_q24: Arc<[i64]>,
    bias_q24: Arc<[i64]>,
}

impl ModalityProjectorV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        modality_id: StableId,
        generation: Generation,
        projector_digest: Digest32,
        input_width: usize,
        output_width: usize,
        weights_q24: Vec<i64>,
        bias_q24: Vec<i64>,
    ) -> Result<Self, MultimodalStemError> {
        validate_projector_shape(
            &projector_digest,
            input_width,
            output_width,
            &weights_q24,
            &bias_q24,
        )?;
        let expected_digest = canonical_modality_projector_digest_v1(
            &modality_id,
            generation,
            input_width,
            output_width,
            &weights_q24,
            &bias_q24,
        );
        if expected_digest != projector_digest {
            return Err(MultimodalStemError::ProjectorDigestMismatch);
        }
        Ok(Self {
            modality_id,
            generation,
            projector_digest,
            input_width,
            output_width,
            weights_q24: Arc::from(weights_q24.into_boxed_slice()),
            bias_q24: Arc::from(bias_q24.into_boxed_slice()),
        })
    }

    #[must_use]
    pub fn modality_id(&self) -> &StableId {
        &self.modality_id
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn projector_digest(&self) -> Digest32 {
        self.projector_digest
    }

    #[must_use]
    pub const fn input_width(&self) -> usize {
        self.input_width
    }

    #[must_use]
    pub const fn output_width(&self) -> usize {
        self.output_width
    }

    #[must_use]
    pub fn weights_q24(&self) -> &[i64] {
        &self.weights_q24
    }

    #[must_use]
    pub fn bias_q24(&self) -> &[i64] {
        &self.bias_q24
    }

    fn project(&self, features_q24: &[i64]) -> Result<Vec<i64>, MultimodalStemError> {
        if features_q24.len() != self.input_width {
            return Err(MultimodalStemError::InputWidthMismatch {
                modality: self.modality_id.to_string(),
                expected: self.input_width,
                actual: features_q24.len(),
            });
        }
        if features_q24.is_empty() {
            return Err(MultimodalStemError::EmptyInput(
                self.modality_id.to_string(),
            ));
        }
        if features_q24
            .iter()
            .any(|value| !(-MAX_MULTIMODAL_Q24_V1..=MAX_MULTIMODAL_Q24_V1).contains(value))
        {
            return Err(MultimodalStemError::InputRangeViolation {
                modality: self.modality_id.to_string(),
            });
        }

        let mut output = Vec::with_capacity(self.output_width);
        for row in 0..self.output_width {
            let mut accumulator = i128::from(self.bias_q24[row])
                .checked_mul(MULTIMODAL_Q24_SCALE)
                .ok_or(MultimodalStemError::ArithmeticOverflow)?;
            let row_start = row
                .checked_mul(self.input_width)
                .ok_or(MultimodalStemError::ArithmeticOverflow)?;
            for (offset, feature) in features_q24.iter().copied().enumerate() {
                let product = i128::from(feature)
                    .checked_mul(i128::from(self.weights_q24[row_start + offset]))
                    .ok_or(MultimodalStemError::ArithmeticOverflow)?;
                accumulator = accumulator
                    .checked_add(product)
                    .ok_or(MultimodalStemError::ArithmeticOverflow)?;
            }
            let value = accumulator
                .checked_div(MULTIMODAL_Q24_SCALE)
                .ok_or(MultimodalStemError::ArithmeticOverflow)?;
            let value =
                i64::try_from(value).map_err(|_| MultimodalStemError::ArithmeticOverflow)?;
            if !(-MAX_MULTIMODAL_Q24_V1..=MAX_MULTIMODAL_Q24_V1).contains(&value) {
                return Err(MultimodalStemError::OutputRangeViolation {
                    modality: self.modality_id.to_string(),
                });
            }
            output.push(value);
        }
        Ok(output)
    }
}

/// One source feature vector for a present modality.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModalityInputV1 {
    pub modality_id: StableId,
    pub features_q24: Vec<i64>,
}

/// A request to project a possibly incomplete multimodal observation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MultimodalStemRequestV1 {
    pub generation: Generation,
    pub source_digest: Digest32,
    pub modality_manifest_digest: Digest32,
    pub inputs: Vec<ModalityInputV1>,
}

/// Ordered projected features plus a Q24 missing-modality mask.
///
/// `feature_vector_q24` is the ordered concatenation of each projector's
/// output, followed by one mask value per manifest slot (`0` present,
/// `1.0` Q24 missing). This lets the next shared Encoder consume the mask as
/// part of the same immutable input while retaining the compact integer mask
/// for receipt and audit code.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MultimodalStemOutputV1 {
    generation: Generation,
    source_digest: Digest32,
    modality_manifest_digest: Digest32,
    stem_digest: Digest32,
    missing_mask: u64,
    projected_feature_width: usize,
    feature_vector_q24: Arc<[i64]>,
}

impl MultimodalStemOutputV1 {
    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub fn modality_manifest_digest(&self) -> Digest32 {
        self.modality_manifest_digest
    }

    #[must_use]
    pub fn manifest_digest(&self) -> Digest32 {
        self.modality_manifest_digest
    }

    #[must_use]
    pub fn stem_digest(&self) -> Digest32 {
        self.stem_digest
    }

    /// One bit per ordered manifest slot; `1` means the modality was absent.
    #[must_use]
    pub const fn missing_mask(&self) -> u64 {
        self.missing_mask
    }

    #[must_use]
    pub const fn projected_feature_width(&self) -> usize {
        self.projected_feature_width
    }

    /// Ordered modality projections followed by the missing mask values.
    #[must_use]
    pub fn feature_vector_q24(&self) -> &[i64] {
        &self.feature_vector_q24
    }
}

/// Pure, deterministic multimodal stem configuration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MultimodalStemProjectionV1 {
    generation: Generation,
    modality_manifest_digest: Digest32,
    projectors: Arc<[ModalityProjectorV1]>,
    projected_feature_width: usize,
    feature_width: usize,
}

impl MultimodalStemProjectionV1 {
    pub fn new(
        generation: Generation,
        projectors: Vec<ModalityProjectorV1>,
    ) -> Result<Self, MultimodalStemError> {
        if projectors.is_empty() {
            return Err(MultimodalStemError::EmptyManifest);
        }
        if projectors.len() > MAX_MULTIMODAL_MODALITIES_V1 {
            return Err(MultimodalStemError::ModalityLimitExceeded(projectors.len()));
        }
        let mut seen = Vec::with_capacity(projectors.len());
        let mut projected_feature_width = 0_usize;
        for projector in &projectors {
            if projector.generation != generation {
                return Err(MultimodalStemError::GenerationMismatch);
            }
            if seen
                .iter()
                .any(|id: &StableId| id == projector.modality_id())
            {
                return Err(MultimodalStemError::DuplicateModality(
                    projector.modality_id.to_string(),
                ));
            }
            seen.push(projector.modality_id.clone());
            projected_feature_width = projected_feature_width
                .checked_add(projector.output_width)
                .ok_or(MultimodalStemError::FeatureLimitExceeded)?;
        }
        let feature_width = projected_feature_width
            .checked_add(projectors.len())
            .ok_or(MultimodalStemError::FeatureLimitExceeded)?;
        if feature_width > MAX_MULTIMODAL_FEATURES_V1 {
            return Err(MultimodalStemError::FeatureLimitExceeded);
        }
        let modality_manifest_digest =
            canonical_multimodal_manifest_digest_v1(generation, &projectors);
        Ok(Self {
            generation,
            modality_manifest_digest,
            projectors: Arc::from(projectors.into_boxed_slice()),
            projected_feature_width,
            feature_width,
        })
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn modality_manifest_digest(&self) -> Digest32 {
        self.modality_manifest_digest
    }

    #[must_use]
    pub fn manifest_digest(&self) -> Digest32 {
        self.modality_manifest_digest
    }

    #[must_use]
    pub fn projectors(&self) -> &[ModalityProjectorV1] {
        &self.projectors
    }

    #[must_use]
    pub const fn projected_feature_width(&self) -> usize {
        self.projected_feature_width
    }

    #[must_use]
    pub const fn feature_width(&self) -> usize {
        self.feature_width
    }

    /// Project every present modality once and append the ordered missing mask.
    pub fn project(
        &self,
        request: &MultimodalStemRequestV1,
    ) -> Result<MultimodalStemOutputV1, MultimodalStemError> {
        if request.generation != self.generation {
            return Err(MultimodalStemError::GenerationMismatch);
        }
        if request.modality_manifest_digest != self.modality_manifest_digest {
            return Err(MultimodalStemError::ManifestDigestMismatch);
        }
        if request.inputs.is_empty() {
            return Err(MultimodalStemError::NoModalitiesPresent);
        }
        if request.inputs.len() > self.projectors.len() {
            return Err(MultimodalStemError::InputLimitExceeded(
                request.inputs.len(),
            ));
        }
        validate_inputs(self, &request.inputs)?;
        let expected_source_digest = canonical_multimodal_source_digest_v1(&request.inputs);
        if request.source_digest.is_zero() {
            return Err(MultimodalStemError::EmptyDigest("source"));
        }
        if request.source_digest != expected_source_digest {
            return Err(MultimodalStemError::SourceDigestMismatch);
        }

        let mut missing_mask = 0_u64;
        let mut present_count = 0_usize;
        let mut feature_vector = Vec::with_capacity(self.feature_width);
        for (index, projector) in self.projectors.iter().enumerate() {
            let input = request
                .inputs
                .iter()
                .find(|candidate| candidate.modality_id == projector.modality_id);
            match input {
                Some(input) => {
                    present_count += 1;
                    feature_vector.extend(projector.project(&input.features_q24)?);
                }
                None => {
                    missing_mask |= 1_u64 << index;
                    feature_vector.extend(vec![0_i64; projector.output_width]);
                }
            }
        }
        if present_count == 0 {
            return Err(MultimodalStemError::NoModalitiesPresent);
        }
        for index in 0..self.projectors.len() {
            let value = if missing_mask & (1_u64 << index) != 0 {
                MULTIMODAL_Q24_ONE
            } else {
                0
            };
            feature_vector.push(value);
        }
        if feature_vector.len() != self.feature_width {
            return Err(MultimodalStemError::FeatureLimitExceeded);
        }
        let stem_digest = canonical_multimodal_stem_digest_v1(
            self.generation,
            request.source_digest,
            self.modality_manifest_digest,
            missing_mask,
            &feature_vector,
        );
        Ok(MultimodalStemOutputV1 {
            generation: self.generation,
            source_digest: request.source_digest,
            modality_manifest_digest: self.modality_manifest_digest,
            stem_digest,
            missing_mask,
            projected_feature_width: self.projected_feature_width,
            feature_vector_q24: Arc::from(feature_vector.into_boxed_slice()),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MultimodalStemError {
    EmptyDigest(&'static str),
    EmptyManifest,
    ModalityLimitExceeded(usize),
    DuplicateModality(String),
    GenerationMismatch,
    ManifestDigestMismatch,
    SourceDigestMismatch,
    NoModalitiesPresent,
    InputLimitExceeded(usize),
    UnknownModality(String),
    DuplicateInput(String),
    EmptyInput(String),
    InputWidthMismatch {
        modality: String,
        expected: usize,
        actual: usize,
    },
    InputRangeViolation {
        modality: String,
    },
    InvalidInputWidth,
    InvalidOutputWidth,
    ProjectorParameterLimitExceeded(usize),
    ProjectorParameterShapeMismatch,
    ProjectorParameterRangeViolation,
    ProjectorDigestMismatch,
    FeatureLimitExceeded,
    ArithmeticOverflow,
    OutputRangeViolation {
        modality: String,
    },
}

impl fmt::Display for MultimodalStemError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for MultimodalStemError {}

fn validate_projector_shape(
    projector_digest: &Digest32,
    input_width: usize,
    output_width: usize,
    weights_q24: &[i64],
    bias_q24: &[i64],
) -> Result<(), MultimodalStemError> {
    if projector_digest.is_zero() {
        return Err(MultimodalStemError::EmptyDigest("projector"));
    }
    if !(1..=MAX_MULTIMODAL_INPUT_WIDTH_V1).contains(&input_width) {
        return Err(MultimodalStemError::InvalidInputWidth);
    }
    if !(1..=MAX_MULTIMODAL_OUTPUT_WIDTH_V1).contains(&output_width) {
        return Err(MultimodalStemError::InvalidOutputWidth);
    }
    let parameter_count = output_width.checked_mul(input_width).ok_or(
        MultimodalStemError::ProjectorParameterLimitExceeded(usize::MAX),
    )?;
    if parameter_count > MAX_MULTIMODAL_PROJECTOR_PARAMS_V1 {
        return Err(MultimodalStemError::ProjectorParameterLimitExceeded(
            parameter_count,
        ));
    }
    if weights_q24.len() != parameter_count || bias_q24.len() != output_width {
        return Err(MultimodalStemError::ProjectorParameterShapeMismatch);
    }
    if weights_q24
        .iter()
        .chain(bias_q24.iter())
        .any(|value| !(-MAX_MULTIMODAL_Q24_V1..=MAX_MULTIMODAL_Q24_V1).contains(value))
    {
        return Err(MultimodalStemError::ProjectorParameterRangeViolation);
    }
    Ok(())
}

fn validate_inputs(
    stem: &MultimodalStemProjectionV1,
    inputs: &[ModalityInputV1],
) -> Result<(), MultimodalStemError> {
    for (index, input) in inputs.iter().enumerate() {
        if inputs[..index]
            .iter()
            .any(|previous| previous.modality_id == input.modality_id)
        {
            return Err(MultimodalStemError::DuplicateInput(
                input.modality_id.to_string(),
            ));
        }
        let projector = stem
            .projectors
            .iter()
            .find(|candidate| candidate.modality_id == input.modality_id)
            .ok_or_else(|| MultimodalStemError::UnknownModality(input.modality_id.to_string()))?;
        if input.features_q24.is_empty() {
            return Err(MultimodalStemError::EmptyInput(
                input.modality_id.to_string(),
            ));
        }
        if input.features_q24.len() != projector.input_width {
            return Err(MultimodalStemError::InputWidthMismatch {
                modality: input.modality_id.to_string(),
                expected: projector.input_width,
                actual: input.features_q24.len(),
            });
        }
        if input
            .features_q24
            .iter()
            .any(|value| !(-MAX_MULTIMODAL_Q24_V1..=MAX_MULTIMODAL_Q24_V1).contains(value))
        {
            return Err(MultimodalStemError::InputRangeViolation {
                modality: input.modality_id.to_string(),
            });
        }
    }
    Ok(())
}

/// Canonical digest of one modality projector's immutable definition.
#[allow(clippy::too_many_arguments)]
pub fn canonical_modality_projector_digest_v1(
    modality_id: &StableId,
    generation: Generation,
    input_width: usize,
    output_width: usize,
    weights_q24: &[i64],
    bias_q24: &[i64],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.multimodal.projector.v1");
    push_id(&mut bytes, modality_id);
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    push_len(&mut bytes, input_width);
    push_len(&mut bytes, output_width);
    push_q24_vector(&mut bytes, weights_q24);
    push_q24_vector(&mut bytes, bias_q24);
    Digest32::of_bytes(&bytes)
}

/// Canonical digest of the ordered modality manifest.
pub fn canonical_multimodal_manifest_digest_v1(
    generation: Generation,
    projectors: &[ModalityProjectorV1],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.multimodal.manifest.v1");
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    push_len(&mut bytes, projectors.len());
    for projector in projectors {
        push_id(&mut bytes, projector.modality_id());
        bytes.extend_from_slice(&projector.generation.get().to_be_bytes());
        bytes.extend_from_slice(projector.projector_digest.as_array());
        push_len(&mut bytes, projector.input_width);
        push_len(&mut bytes, projector.output_width);
    }
    Digest32::of_bytes(&bytes)
}

/// Canonical digest of present source vectors, independent of input order.
pub fn canonical_multimodal_source_digest_v1(inputs: &[ModalityInputV1]) -> Digest32 {
    let mut order: Vec<usize> = (0..inputs.len()).collect();
    order.sort_by_key(|index| inputs[*index].modality_id.clone());
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.multimodal.source.v1");
    push_len(&mut bytes, inputs.len());
    for index in order {
        let input = &inputs[index];
        push_id(&mut bytes, &input.modality_id);
        push_q24_vector(&mut bytes, &input.features_q24);
    }
    Digest32::of_bytes(&bytes)
}

/// Canonical digest of the final ordered projections and missing mask.
pub fn canonical_multimodal_stem_digest_v1(
    generation: Generation,
    source_digest: Digest32,
    modality_manifest_digest: Digest32,
    missing_mask: u64,
    feature_vector_q24: &[i64],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.multimodal.stem.v1");
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(source_digest.as_array());
    bytes.extend_from_slice(modality_manifest_digest.as_array());
    bytes.extend_from_slice(&missing_mask.to_be_bytes());
    push_q24_vector(&mut bytes, feature_vector_q24);
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_q24_vector(bytes: &mut Vec<u8>, values: &[i64]) {
    push_len(bytes, values.len());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&(value as u64).to_be_bytes());
}

#[cfg(test)]
#[path = "multimodal_stem_tests.rs"]
mod tests;
