//! Static labels projected from an existing HTTP error body.
//!
//! These are provider-reported labels, not validation findings, retry advice or
//! evidence of acceptance, absence of effects or a terminal acknowledgement.

use serde::Deserialize;
use serde::Deserializer;
use serde::de::MapAccess;
use serde::de::Visitor;
use serde::de::value::MapAccessDeserializer;
use serde_json::Value;
use std::fmt;
use std::marker::PhantomData;

const MAXIMUM_DIAGNOSTIC_BODY_BYTES: usize = 16 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponsesProviderErrorType {
    InvalidRequest,
    Authentication,
    Permission,
    RateLimit,
    Server,
    Api,
}

impl ResponsesProviderErrorType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::InvalidRequest => "invalid_request_error",
            Self::Authentication => "authentication_error",
            Self::Permission => "permission_error",
            Self::RateLimit => "rate_limit_error",
            Self::Server => "server_error",
            Self::Api => "api_error",
        }
    }

    fn from_allowlisted_str(value: &str) -> Option<Self> {
        match value {
            "invalid_request_error" => Some(Self::InvalidRequest),
            "authentication_error" => Some(Self::Authentication),
            "permission_error" => Some(Self::Permission),
            "rate_limit_error" => Some(Self::RateLimit),
            "server_error" => Some(Self::Server),
            "api_error" => Some(Self::Api),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponsesProviderErrorCode {
    InvalidRequestError,
    InvalidRequest,
    UnsupportedParameter,
    UnsupportedValue,
    MissingRequiredParameter,
    InvalidValue,
    ModelNotFound,
    ContextLengthExceeded,
    InsufficientQuota,
    RateLimitExceeded,
    InvalidApiKey,
    PermissionDenied,
    ServerError,
    UsageNotIncluded,
    MisalignmentPolicyViolation,
    ServerOverloaded,
}

impl ResponsesProviderErrorCode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::InvalidRequestError => "invalid_request_error",
            Self::InvalidRequest => "invalid_request",
            Self::UnsupportedParameter => "unsupported_parameter",
            Self::UnsupportedValue => "unsupported_value",
            Self::MissingRequiredParameter => "missing_required_parameter",
            Self::InvalidValue => "invalid_value",
            Self::ModelNotFound => "model_not_found",
            Self::ContextLengthExceeded => "context_length_exceeded",
            Self::InsufficientQuota => "insufficient_quota",
            Self::RateLimitExceeded => "rate_limit_exceeded",
            Self::InvalidApiKey => "invalid_api_key",
            Self::PermissionDenied => "permission_denied",
            Self::ServerError => "server_error",
            Self::UsageNotIncluded => "usage_not_included",
            Self::MisalignmentPolicyViolation => "misalignment_policy_violation",
            Self::ServerOverloaded => "server_overloaded",
        }
    }

    fn from_allowlisted_str(value: &str) -> Option<Self> {
        match value {
            "invalid_request_error" => Some(Self::InvalidRequestError),
            "invalid_request" => Some(Self::InvalidRequest),
            "unsupported_parameter" => Some(Self::UnsupportedParameter),
            "unsupported_value" => Some(Self::UnsupportedValue),
            "missing_required_parameter" => Some(Self::MissingRequiredParameter),
            "invalid_value" => Some(Self::InvalidValue),
            "model_not_found" => Some(Self::ModelNotFound),
            "context_length_exceeded" => Some(Self::ContextLengthExceeded),
            "insufficient_quota" => Some(Self::InsufficientQuota),
            "rate_limit_exceeded" => Some(Self::RateLimitExceeded),
            "invalid_api_key" => Some(Self::InvalidApiKey),
            "permission_denied" => Some(Self::PermissionDenied),
            "server_error" => Some(Self::ServerError),
            "usage_not_included" => Some(Self::UsageNotIncluded),
            "misalignment_policy_violation" => Some(Self::MisalignmentPolicyViolation),
            "server_overloaded" => Some(Self::ServerOverloaded),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponsesProviderErrorParam {
    Model,
    Instructions,
    Input,
    Tools,
    ToolChoice,
    ParallelToolCalls,
    Reasoning,
    ReasoningEffort,
    ReasoningSummary,
    ReasoningContext,
    Store,
    Stream,
    StreamOptions,
    Include,
    ServiceTier,
    PromptCacheKey,
    Text,
    TextFormat,
    TextVerbosity,
    ClientMetadata,
    MaxOutputTokens,
}

impl ResponsesProviderErrorParam {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Model => "model",
            Self::Instructions => "instructions",
            Self::Input => "input",
            Self::Tools => "tools",
            Self::ToolChoice => "tool_choice",
            Self::ParallelToolCalls => "parallel_tool_calls",
            Self::Reasoning => "reasoning",
            Self::ReasoningEffort => "reasoning.effort",
            Self::ReasoningSummary => "reasoning.summary",
            Self::ReasoningContext => "reasoning.context",
            Self::Store => "store",
            Self::Stream => "stream",
            Self::StreamOptions => "stream_options",
            Self::Include => "include",
            Self::ServiceTier => "service_tier",
            Self::PromptCacheKey => "prompt_cache_key",
            Self::Text => "text",
            Self::TextFormat => "text.format",
            Self::TextVerbosity => "text.verbosity",
            Self::ClientMetadata => "client_metadata",
            Self::MaxOutputTokens => "max_output_tokens",
        }
    }

    fn from_allowlisted_str(value: &str) -> Option<Self> {
        match value {
            "model" => Some(Self::Model),
            "instructions" => Some(Self::Instructions),
            "input" => Some(Self::Input),
            "tools" => Some(Self::Tools),
            "tool_choice" => Some(Self::ToolChoice),
            "parallel_tool_calls" => Some(Self::ParallelToolCalls),
            "reasoning" => Some(Self::Reasoning),
            "reasoning.effort" => Some(Self::ReasoningEffort),
            "reasoning.summary" => Some(Self::ReasoningSummary),
            "reasoning.context" => Some(Self::ReasoningContext),
            "store" => Some(Self::Store),
            "stream" => Some(Self::Stream),
            "stream_options" => Some(Self::StreamOptions),
            "include" => Some(Self::Include),
            "service_tier" => Some(Self::ServiceTier),
            "prompt_cache_key" => Some(Self::PromptCacheKey),
            "text" => Some(Self::Text),
            "text.format" => Some(Self::TextFormat),
            "text.verbosity" => Some(Self::TextVerbosity),
            "client_metadata" => Some(Self::ClientMetadata),
            "max_output_tokens" => Some(Self::MaxOutputTokens),
            _ => None,
        }
    }
}

/// Only enum discriminants survive the projection. Unknown or absent fields
/// are indistinguishable; free-form messages and dynamic parameter paths are
/// never retained. Labels do not authorize a retry or a request mutation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ResponsesProviderError {
    pub error_type: Option<ResponsesProviderErrorType>,
    pub code: Option<ResponsesProviderErrorCode>,
    pub parameter: Option<ResponsesProviderErrorParam>,
}

// The typed envelope rejects duplicate recognized fields. Unknown fields are
// ignored, and only the three bounded transient Values are materialized.
// Neither wire type implements Debug or Serialize.
#[derive(Deserialize)]
struct ErrorEnvelope {
    #[serde(deserialize_with = "object_only")]
    error: ErrorFields,
}

#[derive(Deserialize)]
struct ErrorFields {
    #[serde(rename = "type")]
    error_type: Option<Value>,
    code: Option<Value>,
    param: Option<Value>,
}

// Derived structs can also accept positional sequences. Require a JSON object
// at both envelope levels while retaining Serde's duplicate-field rejection.
fn object_only<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    struct Object<T>(PhantomData<T>);

    impl<'de, T: Deserialize<'de>> Visitor<'de> for Object<T> {
        type Value = T;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("a JSON error object")
        }

        fn visit_map<A: MapAccess<'de>>(self, map: A) -> Result<T, A::Error> {
            T::deserialize(MapAccessDeserializer::new(map))
        }
    }

    deserializer.deserialize_map(Object(PhantomData))
}

impl ResponsesProviderError {
    pub(crate) fn from_http_body(body: &str) -> Option<Self> {
        // The original transport already owns its error body. This bound limits
        // additional diagnostic parsing; it is not a transport download limit.
        if body.len() > MAXIMUM_DIAGNOSTIC_BODY_BYTES {
            return None;
        }
        let mut decoder = serde_json::Deserializer::from_str(body);
        let envelope: ErrorEnvelope = object_only(&mut decoder).ok()?;
        decoder.end().ok()?;
        let error = envelope.error;
        let projected = Self {
            error_type: error
                .error_type
                .as_ref()
                .and_then(Value::as_str)
                .and_then(ResponsesProviderErrorType::from_allowlisted_str),
            code: error
                .code
                .as_ref()
                .and_then(Value::as_str)
                .and_then(ResponsesProviderErrorCode::from_allowlisted_str),
            parameter: error
                .param
                .as_ref()
                .and_then(Value::as_str)
                .and_then(ResponsesProviderErrorParam::from_allowlisted_str),
        };
        (projected.error_type.is_some()
            || projected.code.is_some()
            || projected.parameter.is_some())
        .then_some(projected)
    }
}

#[cfg(test)]
#[path = "responses_provider_error_tests.rs"]
mod tests;
