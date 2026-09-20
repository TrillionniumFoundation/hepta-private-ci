use std::path::Path;

use crate::ExtensionData;

use super::ModelProviderPolicyError;
use super::ModelProviderPolicyFuture;
use super::ModelProviderRequestKind;
use super::ModelProviderSha256Digest;
use super::ModelProviderTransport;

/// Schema shared by one physical-send input context and its proposal.
pub const EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION: u32 = 1;

/// Absolute host ceiling for one ephemeral input proposal.
pub const EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES: u32 = 999;

/// Absolute host ceiling for the proposal's conservative token claim.
pub const EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS: u32 = 999;

const MAX_SOURCE_BYTES: usize = 64;

/// Stable, non-secret identity for one ephemeral model-input source.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct EphemeralModelInputSource(String);

impl EphemeralModelInputSource {
    /// Parses a canonical source matching `[a-z][a-z0-9_.-]{0,63}`.
    pub fn parse(value: impl Into<String>) -> Result<Self, ModelProviderPolicyError> {
        let value = value.into();
        let mut bytes = value.bytes();
        let Some(first) = bytes.next() else {
            return Err(invalid_source());
        };
        if value.len() > MAX_SOURCE_BYTES
            || !first.is_ascii_lowercase()
            || !bytes.all(|byte| {
                byte.is_ascii_lowercase()
                    || byte.is_ascii_digit()
                    || matches!(byte, b'_' | b'-' | b'.')
            })
        {
            return Err(invalid_source());
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Host facts frozen for one physical model-provider send.
///
/// `attempt_id` and `base_logical_request_sha256` are provenance inputs, not
/// extension-mintable authority. The host must still validate the returned
/// proposal, render it into an attempt-local request, and obtain a real policy
/// lease for the finalized request before dispatch.
pub struct EphemeralModelInputContext<'a> {
    pub schema_version: u32,
    pub session_store: &'a ExtensionData,
    pub thread_store: &'a ExtensionData,
    pub turn_store: &'a ExtensionData,
    pub attempt_id: &'a str,
    pub base_logical_request_sha256: &'a ModelProviderSha256Digest,
    pub thread_id: &'a str,
    pub turn_id: &'a str,
    pub cwd: &'a Path,
    pub request_kind: ModelProviderRequestKind,
    pub provider_id: &'a str,
    pub model: &'a str,
    pub transport: ModelProviderTransport,
    pub generate: bool,
    pub model_context_window: Option<i64>,
    pub max_content_bytes: u32,
    pub max_content_tokens: u32,
}

/// Bounded raw domain content proposed for exactly one physical send.
///
/// This type deliberately implements neither `Clone`, `Debug`, nor serde
/// traits. It is not a persistence or logging carrier. Core owns final scope,
/// digest, wrapper, policy-witness, and history-exclusion validation.
pub struct EphemeralModelInputProposal {
    schema_version: u32,
    source: EphemeralModelInputSource,
    attempt_id: String,
    base_logical_request_sha256: ModelProviderSha256Digest,
    thread_id: String,
    turn_id: String,
    source_binding_sha256: ModelProviderSha256Digest,
    content_sha256: ModelProviderSha256Digest,
    content: String,
    claimed_token_count: u32,
}

impl EphemeralModelInputProposal {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source: EphemeralModelInputSource,
        attempt_id: impl Into<String>,
        base_logical_request_sha256: ModelProviderSha256Digest,
        thread_id: impl Into<String>,
        turn_id: impl Into<String>,
        source_binding_sha256: ModelProviderSha256Digest,
        content_sha256: ModelProviderSha256Digest,
        content: impl Into<String>,
        claimed_token_count: u32,
    ) -> Result<Self, ModelProviderPolicyError> {
        let attempt_id = attempt_id.into();
        let thread_id = thread_id.into();
        let turn_id = turn_id.into();
        let content = content.into();
        if attempt_id.trim().is_empty()
            || thread_id.trim().is_empty()
            || turn_id.trim().is_empty()
            || content.is_empty()
            || content.len() > EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize
            || claimed_token_count == 0
            || claimed_token_count > EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS
        {
            return Err(invalid_proposal());
        }
        Ok(Self {
            schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
            source,
            attempt_id,
            base_logical_request_sha256,
            thread_id,
            turn_id,
            source_binding_sha256,
            content_sha256,
            content,
            claimed_token_count,
        })
    }

    pub fn schema_version(&self) -> u32 {
        self.schema_version
    }

    pub fn source(&self) -> &EphemeralModelInputSource {
        &self.source
    }

    pub fn attempt_id(&self) -> &str {
        &self.attempt_id
    }

    pub fn base_logical_request_sha256(&self) -> &ModelProviderSha256Digest {
        &self.base_logical_request_sha256
    }

    pub fn thread_id(&self) -> &str {
        &self.thread_id
    }

    pub fn turn_id(&self) -> &str {
        &self.turn_id
    }

    pub fn source_binding_sha256(&self) -> &ModelProviderSha256Digest {
        &self.source_binding_sha256
    }

    pub fn content_sha256(&self) -> &ModelProviderSha256Digest {
        &self.content_sha256
    }

    pub fn claimed_token_count(&self) -> u32 {
        self.claimed_token_count
    }

    /// Consumes the one-shot proposal and releases its raw content to Core.
    pub fn into_content(self) -> String {
        self.content
    }
}

/// Contributor for bounded input resolved afresh for one physical send.
///
/// Implementations must re-read or revalidate their source on every call and
/// return raw domain content, never a pre-rendered model message. Returning a
/// proposal does not authorize dispatch; Core must bind the finalized request
/// and obtain a real model-provider policy lease separately.
pub trait EphemeralModelInputContributor: Send + Sync {
    fn is_active(&self, _thread_store: &ExtensionData, _turn_store: &ExtensionData) -> bool {
        true
    }

    fn contribute<'a>(
        &'a self,
        _input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        Box::pin(std::future::ready(Ok(None)))
    }
}

fn invalid_source() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "ephemeral_model_input_source_invalid",
        "ephemeral model input source must match [a-z][a-z0-9_.-]{0,63}",
    )
}

fn invalid_proposal() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "ephemeral_model_input_proposal_invalid",
        "ephemeral model input requires non-empty scope, bounded content, and a bounded token claim",
    )
}
