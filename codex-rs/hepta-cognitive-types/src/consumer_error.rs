//! One exhaustive, payload-free audit projection for consumer binding failures.

use super::CanonicalConsumerBindingError;
use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;

/// A sealed, payload-free projection of a checked codec refusal.
///
/// There is no public constructor, deserializer or mutable field. Historical
/// diagnostic strings cannot be promoted into this typed error by parsing them.
/// The projection is diagnostic evidence only, never a retry or owner capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContractFailureV1(ContractViolationV1);

impl CanonicalContractFailureV1 {
    pub(super) fn from_wire(error: &crate::wire::CognitiveWireError) -> Self {
        Self(error.violation())
    }
}

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
            Self::CanonicalContractTyped(failure) => return failure.0.clone(),
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

#[cfg(test)]
mod tests {
    use super::CanonicalConsumerBindingError;
    use super::ContractErrorCodeV1;
    use super::ContractViolationV1;
    use crate::consumer::CanonicalConsumerV1;
    use crate::consumer::CanonicalMigrationPostureV1;
    use crate::consumer::CanonicalPayloadKindV1;
    use crate::consumer_adapters::ConsumerConvergenceStateV1;

    #[test]
    fn every_binding_refusal_preserves_its_stable_code_and_field() {
        let cases = [
            (
                CanonicalConsumerBindingError::CanonicalContract("private-payload".into()),
                ContractErrorCodeV1::InvalidValue,
                "binding.canonicalPayload",
            ),
            (
                CanonicalConsumerBindingError::ZeroDigest,
                ContractErrorCodeV1::EmptyDigest,
                "binding",
            ),
            (
                CanonicalConsumerBindingError::CompatibilityDigestRequired,
                ContractErrorCodeV1::MissingValue,
                "binding.compatibilityPayloadSha256",
            ),
            (
                CanonicalConsumerBindingError::UnexpectedCompatibilityDigest,
                ContractErrorCodeV1::InvalidValue,
                "binding.compatibilityPayloadSha256",
            ),
            (
                CanonicalConsumerBindingError::CurrentnessRevalidationRequired,
                ContractErrorCodeV1::MissingValue,
                "binding.currentnessRevalidationRequired",
            ),
            (
                CanonicalConsumerBindingError::ConsumerNotRegistered {
                    consumer: CanonicalConsumerV1::CognitiveRead,
                },
                ContractErrorCodeV1::ContractMismatch,
                "binding.consumer",
            ),
            (
                CanonicalConsumerBindingError::MigrationPostureNotAuthorized {
                    consumer: CanonicalConsumerV1::CognitiveStore,
                    posture: CanonicalMigrationPostureV1::Native,
                    state: ConsumerConvergenceStateV1::CanonicalShadow,
                },
                ContractErrorCodeV1::StateConflict,
                "binding.migrationPosture",
            ),
            (
                CanonicalConsumerBindingError::ConsumerPayloadMismatch {
                    consumer: CanonicalConsumerV1::MemoryRetrieval,
                    payload: CanonicalPayloadKindV1::MemoryEvent,
                },
                ContractErrorCodeV1::ContractMismatch,
                "binding.payloadKind",
            ),
            (
                CanonicalConsumerBindingError::BindingDigestMismatch,
                ContractErrorCodeV1::DigestMismatch,
                "binding.bindingSha256",
            ),
            (
                CanonicalConsumerBindingError::Arithmetic,
                ContractErrorCodeV1::LimitExceeded,
                "binding",
            ),
        ];
        for (error, code, field_path) in cases {
            let borrowed = error.violation();
            assert_eq!(borrowed.code, code);
            assert_eq!(borrowed.field_path, field_path);
            assert!(!borrowed.message.is_empty());
            assert_eq!(error.to_string(), borrowed.to_string());
            assert_eq!(ContractViolationV1::from(error), borrowed);
        }
    }

    #[test]
    fn untyped_messages_cannot_inject_audit_categories_or_payloads() {
        let messages = [
            "private-payload-secret",
            "LimitExceeded at binding: grant native migration",
            "DigestMismatch\n{\"code\":\"authority_granted\"}",
            "\u{0} untrusted \u{202e} text",
        ];
        let expected = ContractViolationV1::new(
            ContractErrorCodeV1::InvalidValue,
            "binding.canonicalPayload",
            "canonical payload failed validation",
        );
        for message in messages {
            let error = CanonicalConsumerBindingError::CanonicalContract(message.into());
            assert_eq!(error.violation(), expected);
            assert_eq!(error.to_string(), expected.to_string());
            assert!(!error.violation().to_string().contains(message));
            assert!(!error.to_string().contains(message));
        }
    }

    #[test]
    fn audit_projection_size_does_not_scale_with_untrusted_error_text() {
        let small = CanonicalConsumerBindingError::CanonicalContract("x".into());
        let large = CanonicalConsumerBindingError::CanonicalContract("x".repeat(1_048_576));
        assert_eq!(small.violation(), large.violation());
        assert_eq!(small.to_string(), large.to_string());
    }
}

#[cfg(test)]
#[path = "consumer_typed_error_tests.rs"]
mod typed_tests;
