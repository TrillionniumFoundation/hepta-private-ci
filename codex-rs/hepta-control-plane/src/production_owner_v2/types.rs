use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::PlannerStoreError;
use crate::ProductExecutionErrorV1;
use crate::TrustedClockErrorV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalProducerEnvelopeV1 {
    pub producer_id: StableId,
    pub owner_id: StableId,
    pub owner_generation: Generation,
    pub policy_epoch: u64,
    pub policy_digest: Digest32,
    pub operation_identity_digest: Digest32,
    pub payload_digest: Digest32,
    pub evidence_digest: Digest32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
    pub deadline_micros: u64,
}

impl CanonicalProducerEnvelopeV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.control.canonical-producer-envelope.v1\0".to_vec();
        push_id(&mut bytes, &self.producer_id);
        push_id(&mut bytes, &self.owner_id);
        bytes.extend_from_slice(&self.owner_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.policy_epoch.to_be_bytes());
        bytes.extend_from_slice(self.policy_digest.as_array());
        bytes.extend_from_slice(self.operation_identity_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(self.evidence_digest.as_array());
        bytes.extend_from_slice(&self.observed_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.deadline_micros.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalProducerVerificationErrorV1 {
    Rejected,
    Unavailable,
}

impl fmt::Display for CanonicalProducerVerificationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalProducerVerificationErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalProducerVerificationV1 {
    pub verifier_id: StableId,
    pub envelope_digest: Digest32,
    pub verification_digest: Digest32,
}

pub trait CanonicalProducerVerifierV1: Send + Sync {
    fn verify(
        &self,
        envelope: &CanonicalProducerEnvelopeV1,
    ) -> Result<CanonicalProducerVerificationV1, CanonicalProducerVerificationErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalUseObservationV1 {
    pub snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub final_payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOwnerPortV1 {
    pub(super) producer_id: StableId,
    pub(super) owner_id: StableId,
    pub(super) owner_generation: Generation,
    pub(super) policy_epoch: u64,
    pub(super) policy_digest: Digest32,
    pub(super) operation_identity_digest: Digest32,
    pub(super) payload_digest: Digest32,
    pub(super) observed_at_micros: u64,
    pub(super) expires_at_micros: u64,
    pub(super) deadline_micros: u64,
    pub(super) envelope_digest: Digest32,
    pub(super) verifier_id: StableId,
    pub(super) verification_digest: Digest32,
}

impl AuthenticatedOwnerPortV1 {
    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.producer_id
    }

    #[must_use]
    pub fn operation_identity_digest(&self) -> Digest32 {
        self.operation_identity_digest
    }

    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub fn verifier_id(&self) -> &StableId {
        &self.verifier_id
    }

    #[must_use]
    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlRuntimeOwnerErrorV1 {
    InvalidOwnerConfiguration,
    EmptyDigest(&'static str),
    OwnerBindingMismatch,
    GenerationBindingMismatch,
    PolicyBindingMismatch,
    ProducerVerification(CanonicalProducerVerificationErrorV1),
    ProducerVerificationBindingMismatch,
    ProducerPortConsumed,
    ProducerPayloadMismatch,
    MissingAuthorityRequest,
    MissingAuthorization,
    Clock(TrustedClockErrorV1),
    Store(String),
    Execution(ProductExecutionErrorV1),
}

impl fmt::Display for ControlRuntimeOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ControlRuntimeOwnerErrorV1 {}

impl From<TrustedClockErrorV1> for ControlRuntimeOwnerErrorV1 {
    fn from(error: TrustedClockErrorV1) -> Self {
        Self::Clock(error)
    }
}

impl From<PlannerStoreError> for ControlRuntimeOwnerErrorV1 {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error.to_string())
    }
}

impl From<ProductExecutionErrorV1> for ControlRuntimeOwnerErrorV1 {
    fn from(error: ProductExecutionErrorV1) -> Self {
        Self::Execution(error)
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}
