//! Explicit semantic-identity policy for canonical cognitive consumers.
//!
//! Wire V1 preserves the caller's Unicode scalar sequence. That byte-preserving
//! codec policy is not a logical-identity policy: every owner that assigns
//! semantic uniqueness must choose an owner policy before constructing a
//! contract. The five registered canonical consumers use the repository's
//! ASCII-bounded `StableId` grammar and never treat free text as an identity key.

use crate::consumer::CanonicalConsumerV1;
use crate::consumer_adapters::registered_consumer_v1;
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

pub const REGISTERED_CONSUMER_IDENTITY_POLICIES_V1: [ConsumerIdentityPolicyRegistrationV1; 5] = [
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

/// Apply the reviewed identity policy for one registered consumer.
///
/// `StableIdAsciiV1` returns an owned checked identifier. The two policies that
/// depend on an owner's normalization or confusable-rejection evidence fail
/// closed here: only that owner may issue such evidence. This function proves
/// identity grammar only; it grants no currentness, authority, migration,
/// activation or release capability.
pub fn validate_consumer_semantic_identity_v1(
    consumer: CanonicalConsumerV1,
    value: &str,
) -> Result<ContractIdV1, SemanticIdentityErrorV1> {
    let registration = registered_consumer_identity_policy_v1(consumer)
        .ok_or(SemanticIdentityErrorV1::ConsumerPolicyMissing)?;
    let canonical_registration = registered_consumer_v1(consumer.as_str())
        .ok_or(SemanticIdentityErrorV1::ConsumerPolicyMissing)?;
    if registration.owner != canonical_registration.owner || registration.free_text_identity_allowed
    {
        return Err(SemanticIdentityErrorV1::PolicyRegistryMismatch);
    }
    match registration.policy {
        SemanticIdentityPolicyV1::StableIdAsciiV1 => validate_stable_semantic_identity_v1(value),
        SemanticIdentityPolicyV1::OwnerNormalizedProfileV1 { .. }
        | SemanticIdentityPolicyV1::RejectNormalizationVariantsV1 => {
            Err(SemanticIdentityErrorV1::OwnerEvidenceRequired)
        }
    }
}

/// Validate the generic ASCII-bounded identity grammar directly.
///
/// Callers that know the target consumer should prefer
/// [`validate_consumer_semantic_identity_v1`] so owner-policy registry drift is
/// detected rather than silently accepting a locally valid identifier.
pub fn validate_stable_semantic_identity_v1(
    value: &str,
) -> Result<ContractIdV1, SemanticIdentityErrorV1> {
    ContractIdV1::new(value).map_err(|_| SemanticIdentityErrorV1::NotStableId)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SemanticIdentityErrorV1 {
    NotStableId,
    ConsumerPolicyMissing,
    PolicyRegistryMismatch,
    OwnerEvidenceRequired,
}

/// The codec policy is frozen and intentionally distinct from the owner policy.
#[must_use]
pub const fn wire_unicode_policy_v1() -> UnicodeNormalizationPolicyV1 {
    UNICODE_NORMALIZATION_POLICY_V1
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;

    #[test]
    fn identity_registry_is_closed_unique_and_owner_consistent() {
        assert_eq!(REGISTERED_CONSUMER_IDENTITY_POLICIES_V1.len(), 5);
        let mut observed = BTreeSet::new();
        for consumer in CanonicalConsumerV1::ALL {
            let registration = registered_consumer_identity_policy_v1(consumer)
                .expect("closed identity-policy registry");
            let canonical = registered_consumer_v1(consumer.as_str())
                .expect("closed canonical-consumer registry");
            assert!(observed.insert(registration.consumer));
            assert_eq!(registration.consumer, consumer);
            assert_eq!(registration.consumer.as_str(), canonical.consumer);
            assert_eq!(registration.owner, canonical.owner);
            assert!(!registration.owner.is_empty());
            assert_eq!(
                registration.policy,
                SemanticIdentityPolicyV1::StableIdAsciiV1
            );
            assert!(!registration.free_text_identity_allowed);
            assert_eq!(
                validate_consumer_semantic_identity_v1(consumer, "operation:ascii-1")
                    .expect("registered stable identity")
                    .as_str(),
                "operation:ascii-1"
            );
        }
        assert_eq!(observed.len(), CanonicalConsumerV1::ALL.len());
    }

    #[test]
    fn every_consumer_rejects_normalization_variants_and_confusables() {
        for consumer in CanonicalConsumerV1::ALL {
            for value in [
                "event:café",
                "event:cafe\u{301}",
                "event:c\u{430}fe",
                "event:space separated",
            ] {
                assert_eq!(
                    validate_consumer_semantic_identity_v1(consumer, value),
                    Err(SemanticIdentityErrorV1::NotStableId)
                );
            }
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
