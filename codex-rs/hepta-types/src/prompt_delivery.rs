use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::StableId;

/// The registered protocol permits up to 32 KiB for token positions.
/// 8,192 canonical u32 positions consume that bound exactly.
pub const MAX_PROMPT_TOKEN_POSITIONS_V1: usize = 8_192;
pub const MAX_PROMPT_REJECTION_REASON_BYTES_V1: usize = 64;

const PROMPT_DELIVERY_DIGEST_DOMAIN: &[u8] = b"hepta.prompt-delivery-observation.v1";

/// Open, bounded rejection reason for PromptDeliveryObservationV1.
///
/// The canonical schema registers an enum-shaped field but intentionally does
/// not freeze provider/runtime-specific members. The stable identifier is
/// therefore validated and digest-bound without inventing a closed value set.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryRejectReasonV1(StableId);

impl PromptDeliveryRejectReasonV1 {
    pub fn new(value: StableId) -> Result<Self, PromptDeliveryErrorV1> {
        if value.as_str().is_empty() || value.as_str().len() > MAX_PROMPT_REJECTION_REASON_BYTES_V1 {
            return Err(PromptDeliveryErrorV1::InvalidRejectionReason);
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_id(&self) -> &StableId {
        &self.0
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

/// Canonical cross-module delivery observation produced by runtime.codex and
/// consumed by the learning/evaluation plane.
///
/// This is evidence, not authority. A producer must bind
/// provider_request_digest to the exact provider request at its physical
/// boundary before constructing this value.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryObservationV1 {
    pub compilation_id: StableId,
    pub provider_request_digest: Digest32,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectReasonV1>,
    pub observed_token_positions: Option<Vec<u32>>,
    pub truncation_observed: bool,
}

impl PromptDeliveryObservationV1 {
    pub fn validate(&self) -> Result<(), PromptDeliveryErrorV1> {
        if self.provider_request_digest.is_zero() {
            return Err(PromptDeliveryErrorV1::EmptyProviderRequestDigest);
        }
        if (self.delivered && self.rejected_reason.is_some())
            || (!self.delivered && self.rejected_reason.is_none())
        {
            return Err(PromptDeliveryErrorV1::InvalidDisposition);
        }
        if let Some(positions) = &self.observed_token_positions {
            if positions.is_empty() {
                return Err(PromptDeliveryErrorV1::EmptyTokenPositions);
            }
            if positions.len() > MAX_PROMPT_TOKEN_POSITIONS_V1 {
                return Err(PromptDeliveryErrorV1::TokenPositionLimitExceeded);
            }
            if positions.windows(2).any(|pair| pair[0] >= pair[1]) {
                return Err(PromptDeliveryErrorV1::NonCanonicalTokenPositions);
            }
        }
        Ok(())
    }

    /// Digest over every semantic field in the registered V1 observation.
    pub fn semantic_digest(&self) -> Result<Digest32, PromptDeliveryErrorV1> {
        self.validate()?;
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PROMPT_DELIVERY_DIGEST_DOMAIN);
        push_id(&mut bytes, &self.compilation_id);
        bytes.extend_from_slice(self.provider_request_digest.as_array());
        bytes.push(u8::from(self.delivered));
        match &self.rejected_reason {
            Some(reason) => {
                bytes.push(1);
                push_id(&mut bytes, reason.as_id());
            }
            None => bytes.push(0),
        }
        match &self.observed_token_positions {
            Some(positions) => {
                bytes.push(1);
                bytes.extend_from_slice(
                    &u32::try_from(positions.len()).unwrap_or(u32::MAX).to_be_bytes(),
                );
                for position in positions {
                    bytes.extend_from_slice(&position.to_be_bytes());
                }
            }
            None => bytes.push(0),
        }
        bytes.push(u8::from(self.truncation_observed));
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptDeliveryErrorV1 {
    EmptyProviderRequestDigest,
    InvalidRejectionReason,
    InvalidDisposition,
    EmptyTokenPositions,
    TokenPositionLimitExceeded,
    NonCanonicalTokenPositions,
}

impl fmt::Display for PromptDeliveryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PromptDeliveryErrorV1 {}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "prompt_delivery_tests.rs"]
mod tests;
