//! Explicit semantic-identity policy for canonical cognitive consumers.
//!
//! Wire V1 preserves the caller's Unicode scalar sequence. That byte-preserving
//! codec policy is not a logical-identity policy: every owner that assigns
//! semantic uniqueness must choose an owner policy before constructing a
//! contract. The five registered canonical consumers use the repository's
//! ASCII-bounded `StableId` grammar and never treat free text as an identity key.

use crate::consumer::CanonicalConsumerV1;
use crate::contract::UNICODE_NORMALIZATION_POLICY_V1;
use crate::contract::UnicodeNormalizationPolicyV1;
use crate::hnmf::ContractIdV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SemanticIdentityPolicyV1 {
    /// Use `StableId`: ASCII alphanumeric plus `.`, `_`, `-` and `:`.
    StableIdAsciiV1,
    /// The real owner applies and records the named normalization profile before
    /// contract construction. This crate cannot manufacture that owner proof.
    OwnerNormalizedProfileV1 { profile: &'static str },
    /// The owner rejects normalization variants and confusable spellings rather
    /// than changing bytes in the generic codec.
    RejectNormalizationVariantsV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ConsumerIdentityPolicyRegistrationV1 {
    pub consumer: CanonicalConsumerV1,
    pub owner: &'static str,
    pub policy: SemanticIdentityPolicyV1,
    pub free_text_identity_allowed: bool,
}

pub const REGISTERED_CONSUMER_IDENTITY_POLICIES_V1:
    [ConsumerIdentityPolicyRegistrationV1; 5] = [
    ConsumerIdentityPolicyRegistrationV1 {
        consumer: CanonicalConsumerV1::CognitiveRead,
        owner: "cognitive-platform",
        policy: SemanticIdentityPolicyV1::StableIdAsciiV1,
        free_text_identity_allowed: false,
    },
    ConsumerIdentityPolicyRegistrationV1 {
        consumer: CanonicalConsumerV1::CognitiveStore,
        owner: "cognitive-platform",
        policy: SemanticIdentityPolicyV1::StableIdAsciiV1,
        free_text_identity_allowed: false,
    },
    ConsumerIdentityPolicyRegistrationV1 {
        consumer: CanonicalConsumerV1::MemoryRetrieval,
        owner: "memory-retrieval",
        policy: SemanticIdentityPolicyV1::StableIdAsciiV1,
        free_text_identity_allowed: false,
    },
    ConsumerIdentityPolicyRegistrationV1 {
        consumer: CanonicalConsumerV1::CompactEngine,
        owner: "memory-platform",
        policy: SemanticIdentityPolicyV1::StableIdAsciiV1,
        free_text_identity_allowed: false,
    },
    ConsumerIdentityPolicyRegistrationV1 {
        consumer: CanonicalConsumerV1::IntelligenceControl,
        owner: "intelligence-control",
        policy: SemanticIdentityPolicyV1::StableIdAsciiV1,
        free_text_identity_allowed: false,
    },
];

#[must_use]
pub fn registered_consumer_identity_policy_v1(
    consumer: CanonicalConsumerV1,
) -> Option<&'static ConsumerIdentityPolicyRegistrationV1> {
    REGISTERED_CONSUMER_IDENTITY_POLICIES_V1
        .iter()
        .find(|registration| registration.consumer == consumer)
}

/// Validate the only generic identity policy currently selected by product
/// consumers. Owner-normalized and reject-variant policies require owner-local
/// evidence and therefore deliberately have no generic success constructor.
pub fn validate_stable_semantic_identity_v1(
    value: &str,
) -> Result<ContractIdV1, SemanticIdentityErrorV1> {
    ContractIdV1::new(value).map_err(|_| SemanticIdentityErrorV1::NotStableId)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SemanticIdentityErrorV1 {
    NotStableId,
    OwnerEvidenceRequired,
}

/// The codec policy is frozen and intentionally distinct from the owner policy.
#[must_use]
pub const fn wire_unicode_policy_v1() -> UnicodeNormalizationPolicyV1 {
    UNICODE_NORMALIZATION_POLICY_V1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_registered_consumer_has_an_explicit_non_text_identity_policy() {
        assert_eq!(REGISTERED_CONSUMER_IDENTITY_POLICIES_V1.len(), 5);
        for consumer in CanonicalConsumerV1::ALL {
            let registration = registered_consumer_identity_policy_v1(consumer)
                .expect("closed identity-policy registry");
            assert_eq!(registration.consumer, consumer);
            assert!(!registration.owner.is_empty());
            assert_eq!(
                registration.policy,
                SemanticIdentityPolicyV1::StableIdAsciiV1
            );
            assert!(!registration.free_text_identity_allowed);
        }
    }

    #[test]
    fn stable_identity_rejects_normalization_variants_and_confusables() {
        validate_stable_semantic_identity_v1("event:ascii-1").expect("stable id");
        for value in [
            "event:café",
            "event:cafe\u{301}",
            "event:c\u{430}fe",
            "event:space separated",
        ] {
            assert_eq!(
                validate_stable_semantic_identity_v1(value),
                Err(SemanticIdentityErrorV1::NotStableId)
            );
        }
    }

    #[test]
    fn wire_preserves_codepoints_instead_of_claiming_logical_identity() {
        assert_eq!(
            wire_unicode_policy_v1(),
            UnicodeNormalizationPolicyV1::PreserveCodePoints
        );
        assert_ne!("é".as_bytes(), "e\u{301}".as_bytes());
    }
}
