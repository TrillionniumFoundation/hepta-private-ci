//! HPTC-backed prompt-delivery observation with an explicit V1 migration witness.
//!
//! V1 remains byte-for-byte frozen. V2 is a distinct protocol identity and never
//! reinterprets a historical V1 digest as HPTC bytes.

use std::error::Error;
use std::fmt;

use crate::CanonicalDigestError;
use crate::CanonicalFieldV1;
use crate::CanonicalValueV1;
use crate::Digest32;
use crate::PromptDeliveryErrorV1;
use crate::PromptDeliveryObservationV1;
use crate::StableId;
use crate::canonical_digest_v1;

/// V2 commits all positions as one array in frozen HPTC V1. Earlier V2
/// constructors admitted 4097..=8192 positions that could never be committed.
/// Reject that unsupported range at admission; do not truncate or change HPTC.
/// V1 keeps its independent 8192-position compatibility bound.
pub const MAX_PROMPT_V2_TOKEN_POSITIONS: usize = crate::MAX_CANONICAL_CONTAINER_ITEMS_V1;
pub const MAX_PROMPT_V2_REJECTION_REASON_BYTES: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryRejectReasonV2(StableId);

impl PromptDeliveryRejectReasonV2 {
    pub fn new(value: StableId) -> Result<Self, PromptDeliveryErrorV2> {
        if value.as_str().len() > MAX_PROMPT_V2_REJECTION_REASON_BYTES {
            return Err(PromptDeliveryErrorV2::InvalidRejectionReason);
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_id(&self) -> &StableId {
        &self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryObservationV2 {
    compilation_id: StableId,
    provider_request_digest: Digest32,
    delivered: bool,
    rejected_reason: Option<PromptDeliveryRejectReasonV2>,
    observed_token_positions: Option<Vec<u32>>,
    truncation_observed: bool,
    legacy_v1_digest: Option<Digest32>,
}

impl PromptDeliveryObservationV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        compilation_id: StableId,
        provider_request_digest: Digest32,
        delivered: bool,
        rejected_reason: Option<PromptDeliveryRejectReasonV2>,
        observed_token_positions: Option<Vec<u32>>,
        truncation_observed: bool,
        legacy_v1_digest: Option<Digest32>,
    ) -> Result<Self, PromptDeliveryErrorV2> {
        let value = Self {
            compilation_id,
            provider_request_digest,
            delivered,
            rejected_reason,
            observed_token_positions,
            truncation_observed,
            legacy_v1_digest,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn from_v1(value: &PromptDeliveryObservationV1) -> Result<Self, PromptDeliveryErrorV2> {
        let legacy_v1_digest = value
            .semantic_digest()
            .map_err(PromptDeliveryErrorV2::LegacyV1)?;
        let rejected_reason = value
            .rejected_reason
            .as_ref()
            .map(|reason| PromptDeliveryRejectReasonV2::new(reason.as_id().clone()))
            .transpose()?;
        Self::new(
            value.compilation_id.clone(),
            value.provider_request_digest,
            value.delivered,
            rejected_reason,
            value.observed_token_positions.clone(),
            value.truncation_observed,
            Some(legacy_v1_digest),
        )
    }

    pub fn validate(&self) -> Result<(), PromptDeliveryErrorV2> {
        if self.provider_request_digest.is_zero() {
            return Err(PromptDeliveryErrorV2::EmptyProviderRequestDigest);
        }
        if self.legacy_v1_digest.is_some_and(Digest32::is_zero) {
            return Err(PromptDeliveryErrorV2::EmptyLegacyV1Digest);
        }
        if (self.delivered && self.rejected_reason.is_some())
            || (!self.delivered && self.rejected_reason.is_none())
        {
            return Err(PromptDeliveryErrorV2::InvalidDisposition);
        }
        if let Some(positions) = &self.observed_token_positions {
            if positions.is_empty() {
                return Err(PromptDeliveryErrorV2::EmptyTokenPositions);
            }
            if positions.len() > MAX_PROMPT_V2_TOKEN_POSITIONS {
                return Err(PromptDeliveryErrorV2::TokenPositionLimitExceeded);
            }
            if positions.windows(2).any(|pair| pair[0] >= pair[1]) {
                return Err(PromptDeliveryErrorV2::NonCanonicalTokenPositions);
            }
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, PromptDeliveryErrorV2> {
        self.validate()?;
        let type_id = StableId::new("platform.types:prompt-delivery-observation-v2")
            .map_err(|_| PromptDeliveryErrorV2::InvalidTypeIdentity)?;
        let rejected_reason = self
            .rejected_reason
            .iter()
            .map(|reason| CanonicalValueV1::StableId(reason.as_id()))
            .collect::<Vec<_>>();
        let observed_token_positions = self
            .observed_token_positions
            .as_deref()
            .unwrap_or_default()
            .iter()
            .map(|position| CanonicalValueV1::U64(u64::from(*position)))
            .collect::<Vec<_>>();
        let legacy_v1_digest = self
            .legacy_v1_digest
            .iter()
            .copied()
            .map(CanonicalValueV1::Digest)
            .collect::<Vec<_>>();
        let fields = [
            CanonicalFieldV1 {
                name: "compilation_id",
                value: CanonicalValueV1::StableId(&self.compilation_id),
            },
            CanonicalFieldV1 {
                name: "delivered",
                value: CanonicalValueV1::Bool(self.delivered),
            },
            CanonicalFieldV1 {
                name: "legacy_v1_digest",
                value: CanonicalValueV1::Array(&legacy_v1_digest),
            },
            CanonicalFieldV1 {
                name: "observed_token_positions",
                value: CanonicalValueV1::Array(&observed_token_positions),
            },
            CanonicalFieldV1 {
                name: "provider_request_digest",
                value: CanonicalValueV1::Digest(self.provider_request_digest),
            },
            CanonicalFieldV1 {
                name: "rejected_reason",
                value: CanonicalValueV1::Array(&rejected_reason),
            },
            CanonicalFieldV1 {
                name: "truncation_observed",
                value: CanonicalValueV1::Bool(self.truncation_observed),
            },
        ];
        canonical_digest_v1(&type_id, 2, &fields).map_err(PromptDeliveryErrorV2::Canonical)
    }

    #[must_use]
    pub fn compilation_id(&self) -> &StableId {
        &self.compilation_id
    }

    #[must_use]
    pub const fn provider_request_digest(&self) -> Digest32 {
        self.provider_request_digest
    }

    #[must_use]
    pub const fn delivered(&self) -> bool {
        self.delivered
    }

    #[must_use]
    pub fn rejected_reason(&self) -> Option<&PromptDeliveryRejectReasonV2> {
        self.rejected_reason.as_ref()
    }

    #[must_use]
    pub fn observed_token_positions(&self) -> Option<&[u32]> {
        self.observed_token_positions.as_deref()
    }

    #[must_use]
    pub const fn truncation_observed(&self) -> bool {
        self.truncation_observed
    }

    #[must_use]
    pub const fn legacy_v1_digest(&self) -> Option<Digest32> {
        self.legacy_v1_digest
    }
}

impl TryFrom<&PromptDeliveryObservationV1> for PromptDeliveryObservationV2 {
    type Error = PromptDeliveryErrorV2;

    fn try_from(value: &PromptDeliveryObservationV1) -> Result<Self, Self::Error> {
        Self::from_v1(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptDeliveryErrorV2 {
    EmptyProviderRequestDigest,
    EmptyLegacyV1Digest,
    InvalidRejectionReason,
    InvalidDisposition,
    EmptyTokenPositions,
    TokenPositionLimitExceeded,
    NonCanonicalTokenPositions,
    InvalidTypeIdentity,
    LegacyV1(PromptDeliveryErrorV1),
    Canonical(CanonicalDigestError),
}

impl fmt::Display for PromptDeliveryErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PromptDeliveryErrorV2 {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::PromptDeliveryRejectReasonV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn v1_migration_is_explicit_and_hptc_bound() {
        let v1 = PromptDeliveryObservationV1 {
            compilation_id: id("compilation-1"),
            provider_request_digest: digest("request"),
            delivered: false,
            rejected_reason: Some(
                PromptDeliveryRejectReasonV1::new(id("provider.rejected")).expect("reason"),
            ),
            observed_token_positions: Some(vec![1, 4, 9]),
            truncation_observed: true,
        };
        let v2 = PromptDeliveryObservationV2::from_v1(&v1).expect("migration");
        assert_eq!(
            v2.legacy_v1_digest(),
            Some(v1.semantic_digest().expect("v1 digest"))
        );
        assert_eq!(
            v2.semantic_digest().expect("digest"),
            v2.semantic_digest().expect("digest")
        );
        assert_ne!(
            v2.semantic_digest().expect("v2 digest"),
            v1.semantic_digest().expect("v1 digest")
        );
    }

    #[test]
    fn v2_rejects_ambiguous_disposition_and_noncanonical_positions() {
        assert_eq!(
            PromptDeliveryObservationV2::new(
                id("compilation"),
                digest("request"),
                true,
                Some(PromptDeliveryRejectReasonV2::new(id("rejected")).expect("reason")),
                None,
                false,
                None,
            ),
            Err(PromptDeliveryErrorV2::InvalidDisposition)
        );
        assert_eq!(
            PromptDeliveryObservationV2::new(
                id("compilation"),
                digest("request"),
                true,
                None,
                Some(vec![2, 2]),
                false,
                None,
            ),
            Err(PromptDeliveryErrorV2::NonCanonicalTokenPositions)
        );
    }

    #[test]
    fn every_v2_semantic_field_changes_the_commitment() {
        let baseline = PromptDeliveryObservationV2::new(
            id("compilation"),
            digest("request"),
            true,
            None,
            Some(vec![1, 2]),
            false,
            None,
        )
        .expect("baseline");
        let baseline_digest = baseline.semantic_digest().expect("digest");
        let changed = PromptDeliveryObservationV2::new(
            id("compilation-2"),
            digest("request"),
            true,
            None,
            Some(vec![1, 2]),
            false,
            None,
        )
        .expect("changed");
        assert_ne!(baseline_digest, changed.semantic_digest().expect("digest"));
        let changed = PromptDeliveryObservationV2::new(
            id("compilation"),
            digest("request-2"),
            true,
            None,
            Some(vec![1, 2]),
            false,
            None,
        )
        .expect("changed");
        assert_ne!(baseline_digest, changed.semantic_digest().expect("digest"));
        let changed = PromptDeliveryObservationV2::new(
            id("compilation"),
            digest("request"),
            true,
            None,
            Some(vec![1, 3]),
            true,
            Some(digest("legacy")),
        )
        .expect("changed");
        assert_ne!(baseline_digest, changed.semantic_digest().expect("digest"));
    }
}
