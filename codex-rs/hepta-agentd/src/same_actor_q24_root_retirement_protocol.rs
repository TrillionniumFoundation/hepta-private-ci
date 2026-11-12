//! Data-only correlation for the bounded retirement of this Root's workers.
//! Neither request nor acknowledgement proves C execution, daemon completion,
//! authority consumption, or operating-system process exit.

use std::io;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::same_actor_q24_deployment_protocol::FRAME_BOUND;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentBinding;

pub(crate) const RETIREMENT_PURPOSE: &str =
    "hepta.same-actor-q24-deployment.root-retirement.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum OriginalRootRetirementStage {
    AuthorizeRootRetirement,
    ObserveRootWorkersJoined,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalRootRetirementRequest {
    pub(crate) schema_version: u8,
    pub(crate) purpose: String,
    pub(crate) binding: OriginalDeploymentBinding,
    pub(crate) sequence: u8,
    pub(crate) stage: OriginalRootRetirementStage,
    pub(crate) current_registration: String,
    pub(crate) current_request: String,
    pub(crate) original_intent: Option<String>,
}

impl OriginalRootRetirementRequest {
    pub(crate) fn encode_original(&self) -> io::Result<Vec<u8>> {
        self.binding.require_data()?;
        require_digest(&self.current_registration)?;
        require_digest(&self.current_request)?;
        if self.schema_version != 1 || self.purpose != RETIREMENT_PURPOSE {
            return Err(io::Error::other("original Root retirement purpose differs"));
        }
        match (self.sequence, self.stage, self.original_intent.as_deref()) {
            (1, OriginalRootRetirementStage::AuthorizeRootRetirement, None) => {}
            (2, OriginalRootRetirementStage::ObserveRootWorkersJoined, Some(intent)) => {
                require_digest(intent)?;
            }
            _ => return Err(io::Error::other("original Root retirement sequence differs")),
        }
        encode_bounded(self)
    }

    pub(crate) fn decode_original(bytes: &[u8]) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > FRAME_BOUND {
            return Err(io::Error::other("bounded Root retirement request required"));
        }
        let request: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        if request.encode_original()? != bytes {
            return Err(io::Error::other("canonical Root retirement request required"));
        }
        Ok(request)
    }

    pub(crate) fn digest(&self) -> io::Result<String> {
        Ok(Digest32::of_parts(&[
            b"hepta.same-actor-q24-deployment.root-retirement-request.v1\0",
            &self.encode_original()?,
        ])
        .to_string())
    }

    pub(crate) fn require_original(
        &self,
        binding: &OriginalDeploymentBinding,
        current_registration: &str,
        current_request: &str,
        stage: OriginalRootRetirementStage,
        original_intent: Option<&str>,
    ) -> io::Result<()> {
        self.encode_original()?;
        if self.binding != *binding
            || self.current_registration != current_registration
            || self.current_request != current_request
            || self.stage != stage
            || self.original_intent.as_deref() != original_intent
        {
            return Err(io::Error::other("original Root retirement correlation changed"));
        }
        Ok(())
    }
}

/// A Root response is a bounded observation of its own resource scope. The
/// second stage is encoded only by the actual Root finalizer after real joins.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalRootRetirementAcknowledgement {
    pub(crate) schema_version: u8,
    pub(crate) purpose: String,
    pub(crate) binding: OriginalDeploymentBinding,
    pub(crate) sequence: u8,
    pub(crate) stage: OriginalRootRetirementStage,
    pub(crate) original_request: String,
    pub(crate) original_intent: String,
}

impl OriginalRootRetirementAcknowledgement {
    pub(crate) fn require_original_request(
        &self,
        request: &OriginalRootRetirementRequest,
        intent: &str,
    ) -> io::Result<()> {
        request.encode_original()?;
        require_digest(intent)?;
        if self.schema_version != 1
            || self.purpose != RETIREMENT_PURPOSE
            || self.binding != request.binding
            || self.sequence != request.sequence
            || self.stage != request.stage
            || self.original_request != request.digest()?
            || self.original_intent != intent
        {
            return Err(io::Error::other("original Root retirement acknowledgement differs"));
        }
        Ok(())
    }

    pub(crate) fn encode_original(
        &self,
        request: &OriginalRootRetirementRequest,
        intent: &str,
    ) -> io::Result<Vec<u8>> {
        self.require_original_request(request, intent)?;
        encode_bounded(self)
    }

    pub(crate) fn decode_original(
        bytes: &[u8],
        request: &OriginalRootRetirementRequest,
        intent: &str,
    ) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > FRAME_BOUND {
            return Err(io::Error::other("bounded Root retirement acknowledgement required"));
        }
        let response: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        if response.encode_original(request, intent)? != bytes {
            return Err(io::Error::other("canonical Root retirement acknowledgement required"));
        }
        Ok(response)
    }
}

fn require_digest(value: &str) -> io::Result<()> {
    let digest = value.parse::<Digest32>().map_err(io::Error::other)?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(io::Error::other("canonical original Root retirement digest required"));
    }
    Ok(())
}

fn encode_bounded(value: &impl Serialize) -> io::Result<Vec<u8>> {
    let bytes = serde_json::to_vec(value).map_err(io::Error::other)?;
    if bytes.is_empty() || bytes.len() > FRAME_BOUND {
        return Err(io::Error::other("Root retirement frame exceeds its original bound"));
    }
    Ok(bytes)
}
