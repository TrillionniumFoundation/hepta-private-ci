use std::fmt;
use std::future::Future;
use std::pin::Pin;

use crate::ExtensionData;

/// Schema version for [`ModelProviderInvocationInput`].
pub const MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION: u32 = 1;

/// Future returned by one model-provider policy callback.
pub type ModelProviderPolicyFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, ModelProviderPolicyError>> + Send + 'a>>;

/// Stable error returned by model-provider policy infrastructure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelProviderPolicyError {
    reason_code: String,
    detail: String,
}

impl ModelProviderPolicyError {
    pub fn new(reason_code: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            reason_code: reason_code.into(),
            detail: detail.into(),
        }
    }

    pub fn reason_code(&self) -> &str {
        &self.reason_code
    }

    pub fn detail(&self) -> &str {
        &self.detail
    }
}

/// Canonical lowercase SHA-256 digest exposed across the provider policy seam.
///
/// The host must digest semantic provider material before constructing this
/// value. Raw prompts, request bodies, authentication headers, provider tokens,
/// and response text must never cross this API.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ModelProviderSha256Digest(String);

impl ModelProviderSha256Digest {
    pub fn parse(value: impl Into<String>) -> Result<Self, ModelProviderPolicyError> {
        let value = value.into();
        if value.len() != 64
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
        {
            return Err(ModelProviderPolicyError::new(
                "invalid_sha256_digest",
                "provider policy digests must contain exactly 64 lowercase hexadecimal characters",
            ));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Host-owned purpose of one model-provider request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelProviderRequestKind {
    Turn,
    Prewarm,
    Compaction,
    Memory,
}

/// Transport used for one provider send attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelProviderTransport {
    Http,
    WebSocket,
}

/// Secret-free semantic binding for one provider send attempt.
///
/// Payload-bearing fields are represented only by SHA-256 digests. Stable
/// provider and model selectors are exposed so a contributor can select policy;
/// endpoint contents remain digested because provider URLs may contain secrets.
pub struct ModelProviderInvocationInput<'a> {
    pub schema_version: u32,
    pub session_store: &'a ExtensionData,
    pub thread_store: &'a ExtensionData,
    pub turn_store: &'a ExtensionData,
    /// Opaque identity unique to this physical send attempt.
    pub attempt_id: &'a str,
    /// Stable identity shared by retries of the same logical request binding.
    pub request_binding_id: &'a str,
    pub thread_id: &'a str,
    pub turn_id: &'a str,
    pub request_kind: ModelProviderRequestKind,
    pub provider_id: &'a str,
    /// Compatibility-named digest of the host's versioned, secret-free
    /// provider selector. Hosts must not derive this from credentials, raw
    /// provider configuration, headers, endpoint query values, or retry state.
    pub provider_config_sha256: &'a ModelProviderSha256Digest,
    pub model: &'a str,
    pub transport: ModelProviderTransport,
    pub endpoint_sha256: &'a ModelProviderSha256Digest,
    pub logical_request_sha256: &'a ModelProviderSha256Digest,
    pub wire_semantic_sha256: &'a ModelProviderSha256Digest,
    /// Digest of host-rendered input that exists only for this physical send.
    ///
    /// This and `ephemeral_input_witness_sha256` must either both be present or
    /// both be absent. Raw input must never cross this policy seam.
    pub ephemeral_input_sha256: Option<&'a ModelProviderSha256Digest>,
    /// Host witness binding the ephemeral input to this exact physical send.
    pub ephemeral_input_witness_sha256: Option<&'a ModelProviderSha256Digest>,
    pub previous_response_id_sha256: Option<&'a ModelProviderSha256Digest>,
    pub generate: bool,
}

/// Terminal observation for one physical provider send attempt.
///
/// `Completed` proves only that the host observed the provider's response
/// completion signal. It is not an effect acknowledgement and does not prove
/// exactly-once execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ModelProviderTerminal {
    Completed {
        response_id_sha256: ModelProviderSha256Digest,
        response_items_sha256: ModelProviderSha256Digest,
        token_usage_sha256: ModelProviderSha256Digest,
        /// Exact provider observation. `None` means the provider omitted the field.
        end_turn: Option<bool>,
    },
    /// Successful unary provider operation with no response id or token usage.
    ///
    /// This is used by endpoints such as remote compaction that return only
    /// response items. Missing fields must not be replaced with synthetic digests.
    CompletedUnary {
        response_items_sha256: ModelProviderSha256Digest,
    },
    Rejected {
        reason_code: String,
    },
    NotDispatched {
        reason_code: String,
    },
    Indeterminate {
        reason_code: String,
        partial_response_sha256: Option<ModelProviderSha256Digest>,
    },
}

/// Opaque, single-use capability for completing one admitted provider attempt.
///
/// The consuming receiver ensures the host cannot finish the same lease twice.
pub trait ModelProviderAttemptLease: Send {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()>;
}

/// Decision returned before a physical provider send.
pub enum ModelProviderPolicyDecision {
    Allow {
        lease: Box<dyn ModelProviderAttemptLease>,
    },
    Block {
        reason_code: String,
        message: String,
    },
}

impl fmt::Debug for ModelProviderPolicyDecision {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Allow { .. } => formatter
                .debug_struct("Allow")
                .field("lease", &"<opaque>")
                .finish(),
            Self::Block {
                reason_code,
                message,
            } => formatter
                .debug_struct("Block")
                .field("reason_code", reason_code)
                .field("message", message)
                .finish(),
        }
    }
}

pub(crate) struct NoopModelProviderAttemptLease;

impl ModelProviderAttemptLease for NoopModelProviderAttemptLease {
    fn finish(
        self: Box<Self>,
        _terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(std::future::ready(Ok(())))
    }
}
