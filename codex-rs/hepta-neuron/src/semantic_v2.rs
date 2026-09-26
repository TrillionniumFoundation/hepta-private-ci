//! Versioned Neuron semantic identity and durable commit disposition.
//!
//! V1 receipts mixed execution telemetry into semantic identity and represented
//! materially different terminal outcomes with one `abstain` bit. These V2
//! types make both boundaries explicit without changing the V1 wire formats.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_DISPOSITION_REASONS: usize = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronSemanticV2Error {
    EmptyDigest(&'static str),
    InvalidObservation,
    InvalidBodyBundle,
    InvalidCalibrationWindow,
    EmptyReasons,
    TooManyReasons,
    DuplicateReason,
    InvalidEncoding,
}

impl fmt::Display for NeuronSemanticV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronSemanticV2Error {}

/// Immutable identity of the selected computation.
///
/// Runtime latency, queue age, resident memory and allocation observations are
/// deliberately absent. They belong to [`ModelExecutionObservationV1`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelSemanticIdentityV2 {
    pub model_id: StableId,
    pub model_manifest_digest: Digest32,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_id: StableId,
    pub quantization_digest: Digest32,
    pub backend_id: StableId,
    pub runtime_digest: Digest32,
    pub device_identity_digest: Digest32,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub artifact_use_digest: Digest32,
}

impl ModelSemanticIdentityV2 {
    pub fn semantic_digest(&self) -> Result<Digest32, NeuronSemanticV2Error> {
        let digests = [
            ("model manifest", self.model_manifest_digest),
            ("weights", self.weights_digest),
            ("tokenizer", self.tokenizer_digest),
            ("preprocessor", self.preprocessor_digest),
            ("quantization", self.quantization_digest),
            ("runtime", self.runtime_digest),
            ("device", self.device_identity_digest),
            ("encoder", self.encoder_digest),
            ("head", self.head_digest),
            ("artifact use", self.artifact_use_digest),
        ];
        validate_digests(&digests)?;

        let mut bytes = b"hepta.neuron.model-semantic-identity.v2".to_vec();
        push_id(&mut bytes, &self.model_id);
        bytes.extend_from_slice(self.model_manifest_digest.as_array());
        bytes.extend_from_slice(self.weights_digest.as_array());
        bytes.extend_from_slice(self.tokenizer_digest.as_array());
        bytes.extend_from_slice(self.preprocessor_digest.as_array());
        push_id(&mut bytes, &self.quantization_id);
        bytes.extend_from_slice(self.quantization_digest.as_array());
        push_id(&mut bytes, &self.backend_id);
        bytes.extend_from_slice(self.runtime_digest.as_array());
        bytes.extend_from_slice(self.device_identity_digest.as_array());
        bytes.extend_from_slice(self.encoder_digest.as_array());
        bytes.extend_from_slice(self.head_digest.as_array());
        bytes.extend_from_slice(self.artifact_use_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Non-semantic measurements observed for one model invocation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelExecutionObservationV1 {
    pub latency_micros: u64,
    pub queue_age_micros: u64,
    pub resident_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub observed_at_monotonic_micros: u64,
}

impl ModelExecutionObservationV1 {
    pub fn observation_digest(&self) -> Result<Digest32, NeuronSemanticV2Error> {
        if self.observed_at_monotonic_micros == 0 {
            return Err(NeuronSemanticV2Error::InvalidObservation);
        }
        let mut bytes = b"hepta.neuron.model-execution-observation.v1".to_vec();
        for value in [
            self.latency_micros,
            self.queue_age_micros,
            self.resident_bytes,
            self.transient_allocation_bytes,
            self.observed_at_monotonic_micros,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Complete body/base/organ/cell identity interpreted by one Neuron tick.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronBodyBundleIdentityV1 {
    pub body_manifest_digest: Digest32,
    pub body_generation: Generation,
    pub base_bundle_digest: Digest32,
    pub organ_id: StableId,
    pub organ_bundle_digest: Digest32,
    pub cell_slot_id: Option<StableId>,
    pub cell_bundle_digest: Option<Digest32>,
    pub effective_parameter_digest: Digest32,
    pub source_revision_digest: Digest32,
}

impl NeuronBodyBundleIdentityV1 {
    pub fn semantic_digest(&self) -> Result<Digest32, NeuronSemanticV2Error> {
        let digests = [
            ("body manifest", self.body_manifest_digest),
            ("base bundle", self.base_bundle_digest),
            ("organ bundle", self.organ_bundle_digest),
            ("effective parameters", self.effective_parameter_digest),
            ("source revision", self.source_revision_digest),
        ];
        validate_digests(&digests)?;
        if self.cell_slot_id.is_some() != self.cell_bundle_digest.is_some()
            || self.cell_bundle_digest.is_some_and(Digest32::is_zero)
        {
            return Err(NeuronSemanticV2Error::InvalidBodyBundle);
        }

        let mut bytes = b"hepta.neuron.body-bundle-identity.v1".to_vec();
        bytes.extend_from_slice(self.body_manifest_digest.as_array());
        bytes.extend_from_slice(&self.body_generation.get().to_be_bytes());
        bytes.extend_from_slice(self.base_bundle_digest.as_array());
        push_id(&mut bytes, &self.organ_id);
        bytes.extend_from_slice(self.organ_bundle_digest.as_array());
        match (&self.cell_slot_id, self.cell_bundle_digest) {
            (Some(slot), Some(bundle)) => {
                bytes.push(1);
                push_id(&mut bytes, slot);
                bytes.extend_from_slice(bundle.as_array());
            }
            (None, None) => bytes.push(0),
            _ => return Err(NeuronSemanticV2Error::InvalidBodyBundle),
        }
        bytes.extend_from_slice(self.effective_parameter_digest.as_array());
        bytes.extend_from_slice(self.source_revision_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CalibrationExpiryPolicyV1 {
    /// Product default: reject before model invocation or state mutation.
    RejectBeforeMutation,
    /// Explicit compatibility mode for replay/qualification only.
    StateAdvanceAbstainLegacy,
}

impl CalibrationExpiryPolicyV1 {
    #[must_use]
    pub const fn code(self) -> u8 {
        match self {
            Self::RejectBeforeMutation => 1,
            Self::StateAdvanceAbstainLegacy => 2,
        }
    }

    pub fn decide(
        self,
        logical_sequence: u64,
        valid_from_sequence: u64,
        expires_after_sequence: u64,
    ) -> Result<CalibrationWindowDecisionV1, NeuronSemanticV2Error> {
        if valid_from_sequence == 0 || valid_from_sequence > expires_after_sequence {
            return Err(NeuronSemanticV2Error::InvalidCalibrationWindow);
        }
        if logical_sequence < valid_from_sequence || logical_sequence > expires_after_sequence {
            return Ok(match self {
                Self::RejectBeforeMutation => CalibrationWindowDecisionV1::RejectNoUpdate,
                Self::StateAdvanceAbstainLegacy => {
                    CalibrationWindowDecisionV1::StateAdvanceAbstainLegacy
                }
            });
        }
        Ok(CalibrationWindowDecisionV1::Admit)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CalibrationWindowDecisionV1 {
    Admit,
    RejectNoUpdate,
    StateAdvanceAbstainLegacy,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum AbstainReasonV1 {
    LowConfidence,
    OutOfDomain,
    SparseCollapse,
    DenseCollapse,
    ProjectionLimit,
    CalibrationExpiredLegacy,
    HostPolicy,
}

impl AbstainReasonV1 {
    const fn code(self) -> u8 {
        match self {
            Self::LowConfidence => 1,
            Self::OutOfDomain => 2,
            Self::SparseCollapse => 3,
            Self::DenseCollapse => 4,
            Self::ProjectionLimit => 5,
            Self::CalibrationExpiredLegacy => 6,
            Self::HostPolicy => 7,
        }
    }

    fn from_code(value: u8) -> Result<Self, NeuronSemanticV2Error> {
        match value {
            1 => Ok(Self::LowConfidence),
            2 => Ok(Self::OutOfDomain),
            3 => Ok(Self::SparseCollapse),
            4 => Ok(Self::DenseCollapse),
            5 => Ok(Self::ProjectionLimit),
            6 => Ok(Self::CalibrationExpiredLegacy),
            7 => Ok(Self::HostPolicy),
            _ => Err(NeuronSemanticV2Error::InvalidEncoding),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum DegradationReasonV1 {
    LatencyEnvelope,
    AllocationEnvelope,
    CheckpointEnvelope,
    WriteAmplificationEnvelope,
    QueueEnvelope,
    HostDelivery,
}

impl DegradationReasonV1 {
    const fn code(self) -> u8 {
        match self {
            Self::LatencyEnvelope => 1,
            Self::AllocationEnvelope => 2,
            Self::CheckpointEnvelope => 3,
            Self::WriteAmplificationEnvelope => 4,
            Self::QueueEnvelope => 5,
            Self::HostDelivery => 6,
        }
    }

    fn from_code(value: u8) -> Result<Self, NeuronSemanticV2Error> {
        match value {
            1 => Ok(Self::LatencyEnvelope),
            2 => Ok(Self::AllocationEnvelope),
            3 => Ok(Self::CheckpointEnvelope),
            4 => Ok(Self::WriteAmplificationEnvelope),
            5 => Ok(Self::QueueEnvelope),
            6 => Ok(Self::HostDelivery),
            _ => Err(NeuronSemanticV2Error::InvalidEncoding),
        }
    }
}

/// Durable terminal classification of one locally committed operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronCommitDispositionV1 {
    CommittedReady,
    CommittedAbstained {
        reasons: Vec<AbstainReasonV1>,
    },
    CommittedDegraded {
        reasons: Vec<DegradationReasonV1>,
        abstain_reasons: Vec<AbstainReasonV1>,
    },
}

impl NeuronCommitDispositionV1 {
    pub fn abstained(
        reasons: Vec<AbstainReasonV1>,
    ) -> Result<Self, NeuronSemanticV2Error> {
        let reasons = canonical_reasons(reasons)?;
        Ok(Self::CommittedAbstained { reasons })
    }

    pub fn degraded(
        reasons: Vec<DegradationReasonV1>,
        abstain_reasons: Vec<AbstainReasonV1>,
    ) -> Result<Self, NeuronSemanticV2Error> {
        let reasons = canonical_reasons(reasons)?;
        let abstain_reasons = canonical_optional_reasons(abstain_reasons)?;
        Ok(Self::CommittedDegraded {
            reasons,
            abstain_reasons,
        })
    }

    pub fn semantic_digest(&self) -> Result<Digest32, NeuronSemanticV2Error> {
        let mut bytes = b"hepta.neuron.commit-disposition.v1".to_vec();
        bytes.extend_from_slice(&self.encode_canonical()?);
        Ok(Digest32::of_bytes(&bytes))
    }

    pub(crate) fn encode_canonical(&self) -> Result<Vec<u8>, NeuronSemanticV2Error> {
        let mut bytes = Vec::new();
        match self {
            Self::CommittedReady => bytes.push(1),
            Self::CommittedAbstained { reasons } => {
                let canonical = canonical_reasons(reasons.clone())?;
                bytes.push(2);
                push_reason_codes(&mut bytes, &canonical);
            }
            Self::CommittedDegraded {
                reasons,
                abstain_reasons,
            } => {
                let degradation = canonical_reasons(reasons.clone())?;
                let abstention = canonical_optional_reasons(abstain_reasons.clone())?;
                bytes.push(3);
                push_reason_codes(&mut bytes, &degradation);
                push_reason_codes(&mut bytes, &abstention);
            }
        }
        Ok(bytes)
    }

    pub(crate) fn decode_canonical(bytes: &[u8]) -> Result<Self, NeuronSemanticV2Error> {
        let (&tag, mut remaining) = bytes
            .split_first()
            .ok_or(NeuronSemanticV2Error::InvalidEncoding)?;
        let value = match tag {
            1 => Self::CommittedReady,
            2 => {
                let (codes, tail) = take_reason_codes(remaining)?;
                remaining = tail;
                let reasons = codes
                    .into_iter()
                    .map(AbstainReasonV1::from_code)
                    .collect::<Result<Vec<_>, _>>()?;
                Self::abstained(reasons)?
            }
            3 => {
                let (degradation_codes, tail) = take_reason_codes(remaining)?;
                let (abstention_codes, tail) = take_reason_codes(tail)?;
                remaining = tail;
                let reasons = degradation_codes
                    .into_iter()
                    .map(DegradationReasonV1::from_code)
                    .collect::<Result<Vec<_>, _>>()?;
                let abstain_reasons = abstention_codes
                    .into_iter()
                    .map(AbstainReasonV1::from_code)
                    .collect::<Result<Vec<_>, _>>()?;
                Self::degraded(reasons, abstain_reasons)?
            }
            _ => return Err(NeuronSemanticV2Error::InvalidEncoding),
        };
        if !remaining.is_empty() {
            return Err(NeuronSemanticV2Error::InvalidEncoding);
        }
        Ok(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronOperationKeyV2 {
    pub tick_id: StableId,
    pub input_semantic_digest: Digest32,
}

impl NeuronOperationKeyV2 {
    pub fn semantic_digest(&self) -> Result<Digest32, NeuronSemanticV2Error> {
        if self.input_semantic_digest.is_zero() {
            return Err(NeuronSemanticV2Error::EmptyDigest("operation input"));
        }
        let mut bytes = b"hepta.neuron.operation-key.v2".to_vec();
        push_id(&mut bytes, &self.tick_id);
        bytes.extend_from_slice(self.input_semantic_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn validate_digests(
    values: &[(&'static str, Digest32)],
) -> Result<(), NeuronSemanticV2Error> {
    for &(name, digest) in values {
        if digest.is_zero() {
            return Err(NeuronSemanticV2Error::EmptyDigest(name));
        }
    }
    Ok(())
}

fn canonical_reasons<T>(mut values: Vec<T>) -> Result<Vec<T>, NeuronSemanticV2Error>
where
    T: Copy + Ord,
{
    if values.is_empty() {
        return Err(NeuronSemanticV2Error::EmptyReasons);
    }
    if values.len() > MAX_DISPOSITION_REASONS {
        return Err(NeuronSemanticV2Error::TooManyReasons);
    }
    let original = values.len();
    values.sort_unstable();
    values.dedup();
    if values.len() != original {
        return Err(NeuronSemanticV2Error::DuplicateReason);
    }
    Ok(values)
}

fn canonical_optional_reasons<T>(mut values: Vec<T>) -> Result<Vec<T>, NeuronSemanticV2Error>
where
    T: Copy + Ord,
{
    if values.len() > MAX_DISPOSITION_REASONS {
        return Err(NeuronSemanticV2Error::TooManyReasons);
    }
    let original = values.len();
    values.sort_unstable();
    values.dedup();
    if values.len() != original {
        return Err(NeuronSemanticV2Error::DuplicateReason);
    }
    Ok(values)
}

fn push_reason_codes<T>(bytes: &mut Vec<u8>, values: &[T])
where
    T: Copy + ReasonCode,
{
    bytes.push(u8::try_from(values.len()).unwrap_or(u8::MAX));
    bytes.extend(values.iter().copied().map(ReasonCode::reason_code));
}

trait ReasonCode {
    fn reason_code(self) -> u8;
}

impl ReasonCode for AbstainReasonV1 {
    fn reason_code(self) -> u8 {
        self.code()
    }
}

impl ReasonCode for DegradationReasonV1 {
    fn reason_code(self) -> u8 {
        self.code()
    }
}

fn take_reason_codes(bytes: &[u8]) -> Result<(Vec<u8>, &[u8]), NeuronSemanticV2Error> {
    let (&count, remaining) = bytes
        .split_first()
        .ok_or(NeuronSemanticV2Error::InvalidEncoding)?;
    let count = usize::from(count);
    if count > MAX_DISPOSITION_REASONS || remaining.len() < count {
        return Err(NeuronSemanticV2Error::InvalidEncoding);
    }
    let (codes, tail) = remaining.split_at(count);
    let unique = codes.iter().copied().collect::<BTreeSet<_>>();
    if unique.len() != codes.len() {
        return Err(NeuronSemanticV2Error::DuplicateReason);
    }
    Ok((codes.to_vec(), tail))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "semantic_v2_tests.rs"]
mod tests;
