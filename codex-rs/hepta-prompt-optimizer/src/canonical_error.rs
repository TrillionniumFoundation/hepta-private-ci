use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::raw;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptStageV1 {
    Enumeration,
    Pricing,
    Selection,
    Exercise,
    Codec,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptStaleReasonV1 {
    State,
    RegistryOrRealization,
    ModelTuple,
    GenerationVector,
    GraphGeneration,
    TrustSnapshot,
    EvidenceExpired,
    PortfolioExpired,
    Policy,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalPromptError {
    EmptyDigest(&'static str),
    InvalidTime,
    CandidateLimit,
    SelectionLimit,
    TokenBudgetLimit,
    EvidenceBinding(String),
    EvidenceIndependence(String),
    InvalidPolicy,
    UnsatisfiableConstraintGraph(String),
    Stale(PromptStaleReasonV1),
    Revoked(String),
    Unavailable(String),
    TimedOut(String),
    Incomplete(String),
    Corrupt(String),
    Indeterminate(String),
    Quarantined(String),
    Arithmetic,
    Codec(String),
}

impl fmt::Display for CanonicalPromptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalPromptError {}

impl From<raw::CanonicalPromptError> for CanonicalPromptError {
    fn from(value: raw::CanonicalPromptError) -> Self {
        match value {
            raw::CanonicalPromptError::EmptyDigest(name) => Self::EmptyDigest(name),
            raw::CanonicalPromptError::InvalidTime => Self::InvalidTime,
            raw::CanonicalPromptError::CandidateLimit => Self::CandidateLimit,
            raw::CanonicalPromptError::SelectionLimit => Self::SelectionLimit,
            raw::CanonicalPromptError::TokenBudgetLimit => Self::TokenBudgetLimit,
            raw::CanonicalPromptError::RegistryReadIncomplete(count) => {
                Self::Incomplete(format!("prompt registry omitted {count} compatible rows"))
            }
            raw::CanonicalPromptError::Registry(message)
            | raw::CanonicalPromptError::KnowledgeGraph(message)
            | raw::CanonicalPromptError::LearningEvidence(message)
            | raw::CanonicalPromptError::CandidateCompleteness(message) => {
                Self::Unavailable(message)
            }
            raw::CanonicalPromptError::CandidateCompletenessBinding => {
                Self::EvidenceBinding("candidate completeness binding".to_owned())
            }
            raw::CanonicalPromptError::InvalidPricingPolicy => Self::InvalidPolicy,
            raw::CanonicalPromptError::MissingPricingEvidence(id) => {
                Self::Incomplete(format!("missing pricing evidence for {id}"))
            }
            raw::CanonicalPromptError::DuplicatePricingEvidence => {
                Self::Corrupt("duplicate pricing evidence".to_owned())
            }
            raw::CanonicalPromptError::InvalidPricingEvidence(id) => {
                Self::EvidenceBinding(format!("invalid pricing evidence for {id}"))
            }
            raw::CanonicalPromptError::UnknownFactor(id) => {
                Self::Corrupt(format!("unknown factor {id}"))
            }
            raw::CanonicalPromptError::GenerationVectorMismatch => {
                Self::Stale(PromptStaleReasonV1::GenerationVector)
            }
            raw::CanonicalPromptError::InteractionProjectionIncomplete(count) => {
                Self::Incomplete(format!("knowledge projection omitted {count} relations"))
            }
            raw::CanonicalPromptError::RequiredFactorUnavailable(id) => {
                Self::UnsatisfiableConstraintGraph(format!("required factor unavailable: {id}"))
            }
            raw::CanonicalPromptError::DuplicateInteraction
            | raw::CanonicalPromptError::DuplicatePairEvidence => {
                Self::Corrupt("duplicate interaction evidence".to_owned())
            }
            raw::CanonicalPromptError::UnexpectedPairEvidence => {
                Self::EvidenceBinding("unexpected pair evidence".to_owned())
            }
            raw::CanonicalPromptError::InvalidPairEvidence => {
                Self::EvidenceBinding("invalid pair evidence".to_owned())
            }
            raw::CanonicalPromptError::MissingPairEvidence(left, right) => {
                Self::Incomplete(format!("missing pair evidence for {left}/{right}"))
            }
            raw::CanonicalPromptError::PrerequisiteCycle(id) => {
                Self::UnsatisfiableConstraintGraph(format!("requires cycle at {id}"))
            }
            raw::CanonicalPromptError::PortfolioExpired => {
                Self::Stale(PromptStaleReasonV1::PortfolioExpired)
            }
            raw::CanonicalPromptError::Arithmetic => Self::Arithmetic,
        }
    }
}

pub(crate) fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), CanonicalPromptError> {
    if digest.is_zero() {
        return Err(CanonicalPromptError::EmptyDigest(name));
    }
    Ok(())
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

pub(crate) fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    bytes.extend_from_slice(&u64::try_from(values.len()).unwrap_or(u64::MAX).to_be_bytes());
    for value in values {
        push_id(bytes, value);
    }
}
