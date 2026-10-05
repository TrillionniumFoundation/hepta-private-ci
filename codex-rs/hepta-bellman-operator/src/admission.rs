//! Shared admission stages and actionable failure dispositions.
//!
//! These types describe existing owner boundaries. They do not create a
//! second selector, evaluator, artifact registry, or runtime.

use crate::OperatorDatasetBindingError;
use crate::TabularPayloadError;
use codex_hepta_learning_ledger::SignedEvidenceError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorAdmissionStageV1 {
    RawInput,
    StructurallyValidated,
    SourceAuthenticated,
    CurrentAtUse,
    ImmutableCandidate,
    IndependentlyEvaluated,
    SelectedReadOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorFailureScopeV1 {
    Request,
    Candidate,
    Consumer,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorRecoveryActionV1 {
    CorrectRequest,
    ObtainFreshOwnerEvidence,
    RejectCandidate,
    ReloadSelectedCandidate,
    AbstainUnsupportedCell,
    StopConsumer,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OperatorFailureDispositionV1 {
    pub scope: OperatorFailureScopeV1,
    pub action: OperatorRecoveryActionV1,
}

impl OperatorFailureDispositionV1 {
    #[must_use]
    pub const fn stops_consumer(self) -> bool {
        matches!(self.action, OperatorRecoveryActionV1::StopConsumer)
    }

    #[must_use]
    pub const fn rejects_candidate(self) -> bool {
        matches!(self.action, OperatorRecoveryActionV1::RejectCandidate)
    }
}

pub trait ClassifyOperatorAdmissionFailure {
    fn disposition(&self) -> OperatorFailureDispositionV1;
}

impl ClassifyOperatorAdmissionFailure for OperatorDatasetBindingError {
    fn disposition(&self) -> OperatorFailureDispositionV1 {
        use OperatorFailureScopeV1 as Scope;
        use OperatorRecoveryActionV1 as Action;

        match self {
            Self::SignedEvidence(error) => match error {
                SignedEvidenceError::Revoked
                | SignedEvidenceError::ValidityWindow
                | SignedEvidenceError::ContextMismatch
                | SignedEvidenceError::UnknownSigner => OperatorFailureDispositionV1 {
                    scope: Scope::Candidate,
                    action: Action::ObtainFreshOwnerEvidence,
                },
                SignedEvidenceError::PayloadLimit => OperatorFailureDispositionV1 {
                    scope: Scope::Request,
                    action: Action::CorrectRequest,
                },
                SignedEvidenceError::Principal(_)
                | SignedEvidenceError::InvalidTrust
                | SignedEvidenceError::InvalidKey
                | SignedEvidenceError::RoleMismatch
                | SignedEvidenceError::PayloadMismatch
                | SignedEvidenceError::InvalidSignature
                | SignedEvidenceError::ControllerCollision => OperatorFailureDispositionV1 {
                    scope: Scope::Candidate,
                    action: Action::RejectCandidate,
                },
            },
            Self::DatasetReceipt(_) | Self::TrustContextMismatch => OperatorFailureDispositionV1 {
                scope: Scope::Candidate,
                action: Action::ObtainFreshOwnerEvidence,
            },
            Self::ClockRegression | Self::Owner(_) => OperatorFailureDispositionV1 {
                scope: Scope::Consumer,
                action: Action::StopConsumer,
            },
            Self::Learned(_) | Self::WorldModel(_) => OperatorFailureDispositionV1 {
                scope: Scope::Candidate,
                action: Action::RejectCandidate,
            },
            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::EvidenceSetMismatch
            | Self::DuplicateEvidence
            | Self::DuplicateIdentity
            | Self::Bounds
            | Self::Arithmetic => OperatorFailureDispositionV1 {
                scope: Scope::Request,
                action: Action::CorrectRequest,
            },
        }
    }
}

impl ClassifyOperatorAdmissionFailure for TabularPayloadError {
    fn disposition(&self) -> OperatorFailureDispositionV1 {
        use OperatorFailureScopeV1 as Scope;
        use OperatorRecoveryActionV1 as Action;

        match self {
            Self::UnsupportedCell => OperatorFailureDispositionV1 {
                scope: Scope::Request,
                action: Action::AbstainUnsupportedCell,
            },
            Self::Binding => OperatorFailureDispositionV1 {
                scope: Scope::Consumer,
                action: Action::ReloadSelectedCandidate,
            },
            Self::Authority => OperatorFailureDispositionV1 {
                scope: Scope::Consumer,
                action: Action::StopConsumer,
            },
            Self::Bounds | Self::Encoding | Self::Grid => OperatorFailureDispositionV1 {
                scope: Scope::Candidate,
                action: Action::RejectCandidate,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unsupported_cells_abstain_without_invalidating_the_candidate() {
        assert_eq!(
            TabularPayloadError::UnsupportedCell.disposition(),
            OperatorFailureDispositionV1 {
                scope: OperatorFailureScopeV1::Request,
                action: OperatorRecoveryActionV1::AbstainUnsupportedCell,
            }
        );
    }

    #[test]
    fn payload_authority_failure_stops_the_consumer() {
        assert!(
            TabularPayloadError::Authority
                .disposition()
                .stops_consumer()
        );
    }

    #[test]
    fn malformed_candidate_payload_is_candidate_global() {
        assert!(
            TabularPayloadError::Encoding
                .disposition()
                .rejects_candidate()
        );
    }

    #[test]
    fn revoked_evidence_requires_fresh_owner_admission() {
        let failure = OperatorDatasetBindingError::SignedEvidence(SignedEvidenceError::Revoked);
        assert_eq!(
            failure.disposition(),
            OperatorFailureDispositionV1 {
                scope: OperatorFailureScopeV1::Candidate,
                action: OperatorRecoveryActionV1::ObtainFreshOwnerEvidence,
            }
        );
    }
}
