use crate::ExtensionData;

use super::ModelProviderPolicyError;
use super::ModelProviderPolicyFuture;
use super::ModelProviderRequestKind;
use super::ModelProviderSha256Digest;
use super::ModelProviderTransport;

/// Schema shared by one context final-use request and its digest-only proposal.
pub const MODEL_PROVIDER_CONTEXT_SCHEMA_VERSION: u32 = 1;

/// Stable host facts available immediately before the final provider request is
/// frozen. Raw prompt/context bytes never cross this API.
pub struct ModelProviderContextFinalUseInput<'a> {
    pub schema_version: u32,
    pub session_store: &'a ExtensionData,
    pub thread_store: &'a ExtensionData,
    pub turn_store: &'a ExtensionData,
    pub attempt_id: &'a str,
    pub base_logical_request_sha256: &'a ModelProviderSha256Digest,
    pub thread_id: &'a str,
    pub turn_id: &'a str,
    pub request_kind: ModelProviderRequestKind,
    pub provider_id: &'a str,
    pub model: &'a str,
    pub transport: ModelProviderTransport,
    pub generate: bool,
}

/// Digest-only proof that a previously injected context bundle was revalidated
/// against its authoritative owner immediately before this physical send.
///
/// This value deliberately carries no raw prompt or provider request data. The
/// constructor binds all identities so Core can reject a replay into another
/// attempt, thread, turn, provider, model, or request baseline.
pub struct ModelProviderContextFinalUseProposal {
    schema_version: u32,
    attempt_id: String,
    base_logical_request_sha256: ModelProviderSha256Digest,
    thread_id: String,
    turn_id: String,
    provider_id: String,
    model: String,
    context_payload_sha256: ModelProviderSha256Digest,
    authority_sha256: ModelProviderSha256Digest,
    source_binding_sha256: ModelProviderSha256Digest,
    execution_profile_sha256: ModelProviderSha256Digest,
    tokenization_proof_sha256: ModelProviderSha256Digest,
    serialized_token_count: u64,
}

impl ModelProviderContextFinalUseProposal {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        attempt_id: impl Into<String>,
        base_logical_request_sha256: ModelProviderSha256Digest,
        thread_id: impl Into<String>,
        turn_id: impl Into<String>,
        provider_id: impl Into<String>,
        model: impl Into<String>,
        context_payload_sha256: ModelProviderSha256Digest,
        authority_sha256: ModelProviderSha256Digest,
        source_binding_sha256: ModelProviderSha256Digest,
        execution_profile_sha256: ModelProviderSha256Digest,
        tokenization_proof_sha256: ModelProviderSha256Digest,
        serialized_token_count: u64,
    ) -> Result<Self, ModelProviderPolicyError> {
        let value = Self {
            schema_version: MODEL_PROVIDER_CONTEXT_SCHEMA_VERSION,
            attempt_id: attempt_id.into(),
            base_logical_request_sha256,
            thread_id: thread_id.into(),
            turn_id: turn_id.into(),
            provider_id: provider_id.into(),
            model: model.into(),
            context_payload_sha256,
            authority_sha256,
            source_binding_sha256,
            execution_profile_sha256,
            tokenization_proof_sha256,
            serialized_token_count,
        };
        value.validate_shape()?;
        Ok(value)
    }

    pub fn schema_version(&self) -> u32 {
        self.schema_version
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

    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub fn model(&self) -> &str {
        &self.model
    }

    pub fn context_payload_sha256(&self) -> &ModelProviderSha256Digest {
        &self.context_payload_sha256
    }

    pub fn authority_sha256(&self) -> &ModelProviderSha256Digest {
        &self.authority_sha256
    }

    pub fn source_binding_sha256(&self) -> &ModelProviderSha256Digest {
        &self.source_binding_sha256
    }

    pub fn execution_profile_sha256(&self) -> &ModelProviderSha256Digest {
        &self.execution_profile_sha256
    }

    pub fn tokenization_proof_sha256(&self) -> &ModelProviderSha256Digest {
        &self.tokenization_proof_sha256
    }

    pub fn serialized_token_count(&self) -> u64 {
        self.serialized_token_count
    }

    fn validate_shape(&self) -> Result<(), ModelProviderPolicyError> {
        if self.attempt_id.trim().is_empty()
            || self.thread_id.trim().is_empty()
            || self.turn_id.trim().is_empty()
            || self.provider_id.trim().is_empty()
            || self.model.trim().is_empty()
            || self.serialized_token_count == 0
        {
            return Err(invalid_context_proposal());
        }
        Ok(())
    }
}

/// Contributor that revalidates one already-injected context bundle at the
/// physical provider boundary. Implementations may read authoritative stores
/// and construct a preparation proof, but cannot add or alter request content.
pub trait ModelProviderContextFinalUseContributor: Send + Sync {
    fn is_active(&self, _thread_store: &ExtensionData, _turn_store: &ExtensionData) -> bool {
        true
    }

    fn prepare<'a>(
        &'a self,
        _input: ModelProviderContextFinalUseInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<ModelProviderContextFinalUseProposal>> {
        Box::pin(std::future::ready(Ok(None)))
    }
}

fn invalid_context_proposal() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_context_proposal_invalid",
        "provider context final-use proof requires non-empty exact scope and positive token count",
    )
}
