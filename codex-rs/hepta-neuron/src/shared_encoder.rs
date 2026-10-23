use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_SHARED_FEATURE_Q24: i64 = 8 * (1_i64 << 24);

pub const MAX_SHARED_ENCODER_CELLS_V1: usize = 4_096;
pub const MAX_SHARED_ENCODER_FEATURES_V1: usize = 4_096;

/// Exact input presented to one shared Encoder forward.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedEncoderRequestV1 {
    pub request_id: StableId,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub input_digest: Digest32,
    pub input_features_q24: Vec<i64>,
}

/// Output attested by the concrete Encoder backend.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedEncoderOutputV1 {
    pub request_id: StableId,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub input_digest: Digest32,
    pub feature_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
}

/// Immutable feature artifact shared by every Cell in one invocation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedFeatureBatchV1 {
    request_id: StableId,
    encoder_digest: Digest32,
    generation: Generation,
    input_digest: Digest32,
    feature_digest: Digest32,
    feature_vector_q24: Arc<[i64]>,
    cell_ids: Arc<[StableId]>,
}

impl SharedFeatureBatchV1 {
    #[must_use]
    pub fn request_id(&self) -> &StableId {
        &self.request_id
    }

    #[must_use]
    pub fn encoder_digest(&self) -> Digest32 {
        self.encoder_digest
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn input_digest(&self) -> Digest32 {
        self.input_digest
    }

    #[must_use]
    pub fn feature_digest(&self) -> Digest32 {
        self.feature_digest
    }

    /// The one immutable feature slice returned by the shared Encoder.
    #[must_use]
    pub fn feature_vector_q24(&self) -> &[i64] {
        &self.feature_vector_q24
    }

    #[must_use]
    pub fn cell_ids(&self) -> &[StableId] {
        &self.cell_ids
    }

    /// Every accepted Cell receives this same slice; no per-Cell copy is made.
    #[must_use]
    pub fn features_for_cell(&self, cell_id: &StableId) -> Option<&[i64]> {
        self.cell_ids
            .iter()
            .any(|candidate| candidate == cell_id)
            .then_some(self.feature_vector_q24())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SharedEncoderDriverError {
    Unavailable,
    Rejected,
    Indeterminate,
}

impl fmt::Display for SharedEncoderDriverError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SharedEncoderDriverError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SharedEncoderError {
    EmptyDigest(&'static str),
    RequestBindingMismatch,
    InputDigestMismatch,
    EncoderBindingMismatch,
    GenerationMismatch,
    EmptyInput,
    InputLimitExceeded(usize),
    EmptyCells,
    CellLimitExceeded(usize),
    DuplicateCellId(String),
    OutputDigestMismatch,
    EmptyOutput,
    OutputLimitExceeded(usize),
    InputRangeViolation,
    OutputRangeViolation,
    Driver(SharedEncoderDriverError),
}

impl fmt::Display for SharedEncoderError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SharedEncoderError {}

impl From<SharedEncoderDriverError> for SharedEncoderError {
    fn from(error: SharedEncoderDriverError) -> Self {
        Self::Driver(error)
    }
}

/// A concrete host/model adapter implements one Encoder forward here. The
/// owner calls it once per request, regardless of the number of Cells.
pub trait SharedEncoderDriver {
    fn encode(
        &mut self,
        request: &SharedEncoderRequestV1,
    ) -> Result<SharedEncoderOutputV1, SharedEncoderDriverError>;
}

/// Owner for one immutable Encoder artifact and generation.
pub struct SharedEncoderOwnerV1<D> {
    encoder_digest: Digest32,
    generation: Generation,
    driver: D,
}

impl<D> SharedEncoderOwnerV1<D>
where
    D: SharedEncoderDriver,
{
    pub fn new(
        encoder_digest: Digest32,
        generation: Generation,
        driver: D,
    ) -> Result<Self, SharedEncoderError> {
        if encoder_digest.is_zero() {
            return Err(SharedEncoderError::EmptyDigest("encoder"));
        }
        Ok(Self {
            encoder_digest,
            generation,
            driver,
        })
    }

    /// Bind one shared Encoder owner to the existing runtime configuration.
    ///
    /// The runtime config supplies the immutable Encoder digest and generation;
    /// the concrete driver remains the only host/model execution boundary.
    pub fn from_runtime_config(
        config: &crate::NeuronRuntimeConfigV1,
        driver: D,
    ) -> Result<Self, SharedEncoderError> {
        Self::new(config.encoder_digest, config.generation, driver)
    }

    #[must_use]
    pub fn encoder_digest(&self) -> Digest32 {
        self.encoder_digest
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    /// Performs exactly one physical Encoder call and returns one immutable
    /// feature artifact addressed to all accepted Cell ids.
    pub fn encode_for_cells(
        &mut self,
        request: &SharedEncoderRequestV1,
        cell_ids: &[StableId],
    ) -> Result<SharedFeatureBatchV1, SharedEncoderError> {
        validate_request(self, request)?;
        validate_cells(cell_ids)?;

        let output = self.driver.encode(request)?;
        validate_output(self, request, &output)?;

        let feature_vector_q24 = Arc::from(output.feature_vector_q24.into_boxed_slice());
        let cell_ids = Arc::from(cell_ids.to_vec().into_boxed_slice());
        Ok(SharedFeatureBatchV1 {
            request_id: request.request_id.clone(),
            encoder_digest: self.encoder_digest,
            generation: self.generation,
            input_digest: request.input_digest,
            feature_digest: output.feature_digest,
            feature_vector_q24,
            cell_ids,
        })
    }

    pub fn into_driver(self) -> D {
        self.driver
    }
}

fn validate_request<D>(
    owner: &SharedEncoderOwnerV1<D>,
    request: &SharedEncoderRequestV1,
) -> Result<(), SharedEncoderError> {
    if request.encoder_digest.is_zero() {
        return Err(SharedEncoderError::EmptyDigest("request encoder"));
    }
    if request.input_digest.is_zero() {
        return Err(SharedEncoderError::EmptyDigest("input"));
    }
    if request.encoder_digest != owner.encoder_digest {
        return Err(SharedEncoderError::EncoderBindingMismatch);
    }
    if request.generation != owner.generation {
        return Err(SharedEncoderError::GenerationMismatch);
    }
    if request.input_features_q24.is_empty() {
        return Err(SharedEncoderError::EmptyInput);
    }
    if request.input_features_q24.len() > MAX_SHARED_ENCODER_FEATURES_V1 {
        return Err(SharedEncoderError::InputLimitExceeded(
            request.input_features_q24.len(),
        ));
    }
    if request
        .input_features_q24
        .iter()
        .any(|value| !(-MAX_SHARED_FEATURE_Q24..=MAX_SHARED_FEATURE_Q24).contains(value))
    {
        return Err(SharedEncoderError::InputRangeViolation);
    }
    if canonical_shared_encoder_input_digest_v1(&request.input_features_q24) != request.input_digest
    {
        return Err(SharedEncoderError::InputDigestMismatch);
    }
    Ok(())
}

fn validate_cells(cell_ids: &[StableId]) -> Result<(), SharedEncoderError> {
    if cell_ids.is_empty() {
        return Err(SharedEncoderError::EmptyCells);
    }
    if cell_ids.len() > MAX_SHARED_ENCODER_CELLS_V1 {
        return Err(SharedEncoderError::CellLimitExceeded(cell_ids.len()));
    }
    for (index, cell_id) in cell_ids.iter().enumerate() {
        if cell_ids[..index].iter().any(|previous| previous == cell_id) {
            return Err(SharedEncoderError::DuplicateCellId(cell_id.to_string()));
        }
    }
    Ok(())
}

fn validate_output<D>(
    owner: &SharedEncoderOwnerV1<D>,
    request: &SharedEncoderRequestV1,
    output: &SharedEncoderOutputV1,
) -> Result<(), SharedEncoderError> {
    if output.request_id != request.request_id {
        return Err(SharedEncoderError::RequestBindingMismatch);
    }
    if output.generation != request.generation || output.generation != owner.generation {
        return Err(SharedEncoderError::GenerationMismatch);
    }
    if output.encoder_digest != owner.encoder_digest {
        return Err(SharedEncoderError::EncoderBindingMismatch);
    }
    if output.input_digest != request.input_digest {
        return Err(SharedEncoderError::InputDigestMismatch);
    }
    if output.feature_vector_q24.is_empty() {
        return Err(SharedEncoderError::EmptyOutput);
    }
    if output.feature_vector_q24.len() > MAX_SHARED_ENCODER_FEATURES_V1 {
        return Err(SharedEncoderError::OutputLimitExceeded(
            output.feature_vector_q24.len(),
        ));
    }
    if output
        .feature_vector_q24
        .iter()
        .any(|value| !(-MAX_SHARED_FEATURE_Q24..=MAX_SHARED_FEATURE_Q24).contains(value))
    {
        return Err(SharedEncoderError::OutputRangeViolation);
    }
    if output.feature_digest.is_zero()
        || output.feature_digest
            != canonical_shared_encoder_feature_digest_v1(&output.feature_vector_q24)
    {
        return Err(SharedEncoderError::OutputDigestMismatch);
    }
    Ok(())
}

pub fn canonical_shared_encoder_input_digest_v1(values: &[i64]) -> Digest32 {
    digest_q24_vector(b"hepta.neuron.shared-encoder.input.q24.v1", values)
}

pub fn canonical_shared_encoder_feature_digest_v1(values: &[i64]) -> Digest32 {
    digest_q24_vector(b"hepta.neuron.shared-encoder.feature.q24.v1", values)
}

fn digest_q24_vector(domain: &[u8], values: &[i64]) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "shared_encoder_tests.rs"]
mod tests;
