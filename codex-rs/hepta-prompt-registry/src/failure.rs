//! Stable, redacted failure/recovery semantics shared by publishers and users.
//! A recovery suggestion never authorizes a retry, mutates lifecycle state, or
//! turns an unknown durable outcome into an absent operation.

use serde::Serialize;

use crate::AdmissionError;
use crate::DurableRegistryError;
use crate::Error;
use crate::PromptRegistryV2Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PromptRegistryRecoveryV1 {
    Reject,
    Recompile,
    Reauthorize,
    RetryAfterAvailability,
    RelieveCapacity,
    ReopenAndReconcile,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PromptRegistryFailureV1 {
    IdentityConflict,
    SnapshotChanged,
    SelectionUnavailable,
    Withdrawn,
    AuthorizationRejected,
    AuthorizationExpired,
    InvalidInput,
    IntegrityRejected,
    ConfigurationRejected,
    UnsafeStorage,
    CapacityExceeded,
    StoreUnavailable,
    OwnerBusy,
    ReopenRequired,
    IndeterminateDurability,
}

impl PromptRegistryFailureV1 {
    #[must_use]
    pub const fn recovery(self) -> PromptRegistryRecoveryV1 {
        match self {
            Self::SnapshotChanged | Self::SelectionUnavailable => {
                PromptRegistryRecoveryV1::Recompile
            }
            Self::AuthorizationExpired => PromptRegistryRecoveryV1::Reauthorize,
            Self::StoreUnavailable | Self::OwnerBusy => {
                PromptRegistryRecoveryV1::RetryAfterAvailability
            }
            Self::CapacityExceeded => PromptRegistryRecoveryV1::RelieveCapacity,
            Self::ReopenRequired | Self::IndeterminateDurability => {
                PromptRegistryRecoveryV1::ReopenAndReconcile
            }
            Self::IdentityConflict
            | Self::Withdrawn
            | Self::AuthorizationRejected
            | Self::InvalidInput
            | Self::IntegrityRejected
            | Self::ConfigurationRejected
            | Self::UnsafeStorage => PromptRegistryRecoveryV1::Reject,
        }
    }

    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::IdentityConflict => "prompt_registry_identity_conflict",
            Self::SnapshotChanged => "prompt_registry_snapshot_changed",
            Self::SelectionUnavailable => "prompt_registry_selection_unavailable",
            Self::Withdrawn => "prompt_registry_withdrawn",
            Self::AuthorizationRejected => "prompt_registry_authorization_rejected",
            Self::AuthorizationExpired => "prompt_registry_authorization_expired",
            Self::InvalidInput => "prompt_registry_invalid_input",
            Self::IntegrityRejected => "prompt_registry_integrity_rejected",
            Self::ConfigurationRejected => "prompt_registry_configuration_rejected",
            Self::UnsafeStorage => "prompt_registry_unsafe_storage",
            Self::CapacityExceeded => "prompt_registry_capacity_exceeded",
            Self::StoreUnavailable => "prompt_registry_store_unavailable",
            Self::OwnerBusy => "prompt_registry_owner_busy",
            Self::ReopenRequired => "prompt_registry_reopen_required",
            Self::IndeterminateDurability => "prompt_registry_indeterminate_durability",
        }
    }
}

impl DurableRegistryError {
    #[must_use]
    pub const fn failure(&self) -> PromptRegistryFailureV1 {
        use PromptRegistryFailureV1 as Failure;
        match self {
            Self::Corrupt => Failure::IntegrityRejected,
            Self::CapacityExceeded | Self::StorageFull => Failure::CapacityExceeded,
            Self::ConfigurationMismatch => Failure::ConfigurationRejected,
            Self::Unavailable => Failure::StoreUnavailable,
            Self::UnsafeStateDirectory => Failure::UnsafeStorage,
            Self::StateLocked => Failure::OwnerBusy,
            Self::IndeterminateDurability => Failure::IndeterminateDurability,
            Self::ReopenRequired => Failure::ReopenRequired,
            Self::Core(error) => match error {
                Error::CapacityExceeded => Failure::CapacityExceeded,
                Error::FactorConflict(_)
                | Error::RealizationConflict(_)
                | Error::RelationConflict(_)
                | Error::RealizationProfileConflict(_) => Failure::IdentityConflict,
                Error::PayloadDigestMismatch => Failure::IntegrityRejected,
                Error::ExternalSelfAdmission | Error::SelfReview => Failure::AuthorizationRejected,
                Error::ZeroCapacity
                | Error::EmptyDigest(_)
                | Error::PayloadTooLarge
                | Error::InvalidFactorMetadata
                | Error::FactorNotFound(_)
                | Error::FactorNotAdmitted(_)
                | Error::InvalidTransition
                | Error::RevisionOverflow
                | Error::InvalidRelation
                | Error::InvalidFactorGraphSource => Failure::InvalidInput,
            },
            Self::Admission(error) => match error {
                AdmissionError::Revoked => Failure::Withdrawn,
                AdmissionError::Expired | AdmissionError::NotYetValid => {
                    Failure::AuthorizationExpired
                }
                AdmissionError::AuthorityUnavailable => Failure::StoreUnavailable,
                AdmissionError::InvalidGrant
                | AdmissionError::InvalidTrust
                | AdmissionError::InvalidSignature
                | AdmissionError::SignerMismatch
                | AdmissionError::FactorBindingMismatch
                | AdmissionError::ScopeMismatch
                | AdmissionError::UntrustedFactor
                | AdmissionError::SelfReview
                | AdmissionError::AlreadyUsed => Failure::AuthorizationRejected,
            },
            Self::Read(error) => match error {
                PromptRegistryV2Error::SnapshotStale => Failure::SnapshotChanged,
                PromptRegistryV2Error::RequiredFactorUnavailable
                | PromptRegistryV2Error::PayloadUnavailable => Failure::SelectionUnavailable,
                PromptRegistryV2Error::PayloadDigestMismatch
                | PromptRegistryV2Error::DigestMismatch(_)
                | PromptRegistryV2Error::InvalidFrontier
                | PromptRegistryV2Error::NonCanonicalBindings => Failure::IntegrityRejected,
                PromptRegistryV2Error::AuthorityGranted => Failure::AuthorizationRejected,
                PromptRegistryV2Error::ReadLimitExceeded => Failure::CapacityExceeded,
                PromptRegistryV2Error::EmptyDigest(_)
                | PromptRegistryV2Error::ZeroTokenCost
                | PromptRegistryV2Error::InvalidModelVersion
                | PromptRegistryV2Error::InvalidExpiry
                | PromptRegistryV2Error::DuplicateFactorFilter(_)
                | PromptRegistryV2Error::NonCanonicalRequiredFactors => Failure::InvalidInput,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn read_integrity_failures_never_become_recompile_or_availability_retries() {
        for error in [
            PromptRegistryV2Error::PayloadDigestMismatch,
            PromptRegistryV2Error::DigestMismatch("payload"),
            PromptRegistryV2Error::InvalidFrontier,
        ] {
            let failure = DurableRegistryError::Read(error).failure();
            assert_eq!(failure, PromptRegistryFailureV1::IntegrityRejected);
            assert_eq!(failure.recovery(), PromptRegistryRecoveryV1::Reject);
        }
        assert_eq!(
            DurableRegistryError::Read(PromptRegistryV2Error::SnapshotStale)
                .failure()
                .recovery(),
            PromptRegistryRecoveryV1::Recompile
        );
    }

    #[test]
    fn mutation_conflict_capacity_and_unknown_commit_have_distinct_recovery() {
        let cases = [
            (
                DurableRegistryError::Core(Error::FactorConflict("secret-id".into())),
                PromptRegistryRecoveryV1::Reject,
            ),
            (
                DurableRegistryError::StorageFull,
                PromptRegistryRecoveryV1::RelieveCapacity,
            ),
            (
                DurableRegistryError::IndeterminateDurability,
                PromptRegistryRecoveryV1::ReopenAndReconcile,
            ),
            (
                DurableRegistryError::ReopenRequired,
                PromptRegistryRecoveryV1::ReopenAndReconcile,
            ),
        ];
        for (error, expected) in cases {
            assert_eq!(error.failure().recovery(), expected);
            assert!(!error.failure().code().contains("secret-id"));
        }
    }
}
