//! One exhaustive, payload-free audit projection for consumer binding failures.

use super::CanonicalConsumerBindingError;
use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;

impl CanonicalConsumerBindingError {
    /// Preserve the failure category without copying payload-bearing debug
    /// strings into the handoff audit surface. A refusal grants no retry,
    /// currentness, migration, read or write authority.
    ///
    /// `CanonicalContract(String)` is a historical untyped error surface. Do
    /// not parse its text to manufacture a more specific machine-readable code.
    #[must_use]
    pub fn violation(&self) -> ContractViolationV1 {
        let (code, field, message) = match self {
            Self::CanonicalContract(_) => (
                ContractErrorCodeV1::InvalidValue,
                "binding.canonicalPayload",
                "canonical payload failed validation",
            ),
            Self::ZeroDigest => (
                ContractErrorCodeV1::EmptyDigest,
                "binding",
                "binding contains an empty digest",
            ),
            Self::CompatibilityDigestRequired => (
                ContractErrorCodeV1::MissingValue,
                "binding.compatibilityPayloadSha256",
                "compatibility posture requires the exact legacy payload digest",
            ),
            Self::UnexpectedCompatibilityDigest => (
                ContractErrorCodeV1::InvalidValue,
                "binding.compatibilityPayloadSha256",
                "this migration posture forbids a compatibility payload digest",
            ),
            Self::CurrentnessRevalidationRequired => (
                ContractErrorCodeV1::MissingValue,
                "binding.currentnessRevalidationRequired",
                "the mandatory final-use revalidation marker is absent",
            ),
            Self::ConsumerNotRegistered { .. } => (
                ContractErrorCodeV1::ContractMismatch,
                "binding.consumer",
                "consumer is not registered",
            ),
            Self::MigrationPostureNotAuthorized { .. } => (
                ContractErrorCodeV1::StateConflict,
                "binding.migrationPosture",
                "current registry does not authorize this migration posture",
            ),
            Self::ConsumerPayloadMismatch { .. } => (
                ContractErrorCodeV1::ContractMismatch,
                "binding.payloadKind",
                "consumer does not accept this payload family",
            ),
            Self::BindingDigestMismatch => (
                ContractErrorCodeV1::DigestMismatch,
                "binding.bindingSha256",
                "binding digest does not match the complete binding",
            ),
            Self::Arithmetic => (
                ContractErrorCodeV1::LimitExceeded,
                "binding",
                "binding length exceeds the supported encoding range",
            ),
        };
        ContractViolationV1::new(code, field, message)
    }
}

impl From<CanonicalConsumerBindingError> for ContractViolationV1 {
    fn from(value: CanonicalConsumerBindingError) -> Self {
        value.violation()
    }
}
