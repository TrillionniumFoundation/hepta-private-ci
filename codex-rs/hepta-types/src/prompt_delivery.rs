use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::StableId;

/// Maximum number of observed token positions carried by the canonical
/// PromptDeliveryObservationV1 contract. 8,192 u32 positions fit the
/// protocol registry's 32 KiB bounded-array ceiling exactly.
pub const MAX_PROMPT_TOKEN_POSITIONS_V1: usize = 8_192;

const PROMPT_DELIVERY_DIGEST_DOMAIN: &[u8] = b"hepta.prompt-delivery-observation.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptDeliveryRejectionV1 {
    RuntimeRejected,
    ProviderRejected,
    PayloadRejected,
    StaleAttachment,
}

impl PromptDeliveryRejectionV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RuntimeRejected => "runtime_rejected",
            Self::ProviderRejected => "provider_rejected",
            Self::PayloadRejected => "payload_rejected",
            Self::StaleAttachment => "stale_attachment",
        }
    }

    const fn tag(self) -> u8 {
        match self {
            Self::RuntimeRejected => 0,
            Self::ProviderRejected => 1,
            Self::PayloadRejected => 2,
            Self::StaleAttachment => 3,
        }
    }
}

/// Canonical cross-module delivery observation produced by `runtime.codex`
/// and consumed by learning/evaluation modules.
///
/// This type intentionally contains no runtime handle or authority. A value is
/// evidence only after the producer has bound `provider_request_digest` to the
/// exact request bytes that crossed the runtime boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryObservationV1 {
    pub compilation_id: StableId,
    pub provider_request_digest: Digest32,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectionV1>,
    pub observed_token_positions: Vec<u32>,
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
        if self.observed_token_positions.len() > MAX_PROMPT_TOKEN_POSITIONS_V1 {
            return Err(PromptDeliveryErrorV1::TokenPositionLimitExceeded);
        }
        if self
            .observed_token_positions
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        {
            return Err(PromptDeliveryErrorV1::NonCanonicalTokenPositions);
        }
        Ok(())
    }

    /// Digest of every semantic field in the registered V1 observation.
    pub fn semantic_digest(&self) -> Result<Digest32, PromptDeliveryErrorV1> {
        self.validate()?;
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PROMPT_DELIVERY_DIGEST_DOMAIN);
        push_id(&mut bytes, &self.compilation_id);
        bytes.extend_from_slice(self.provider_request_digest.as_array());
        bytes.push(u8::from(self.delivered));
        match self.rejected_reason {
            Some(reason) => {
                bytes.push(1);
                bytes.push(reason.tag());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(
            &u32::try_from(self.observed_token_positions.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for position in &self.observed_token_positions {
            bytes.extend_from_slice(&position.to_be_bytes());
        }
        bytes.push(u8::from(self.truncation_observed));
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptDeliveryErrorV1 {
    EmptyProviderRequestDigest,
    InvalidDisposition,
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
