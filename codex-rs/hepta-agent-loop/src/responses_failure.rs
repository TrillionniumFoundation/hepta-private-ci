//! Allowlisted diagnostics from the existing API error type.
//!
//! No upstream message, URL, header, body or error source is retained. These
//! fields describe an observed error category; they do not establish provider
//! acceptance, rejection, absence of effects, retry authority or a terminal ACK.

use codex_api::ApiError;
use codex_api::TransportError;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponsesFailureStage {
    Request,
    Stream,
}

impl ResponsesFailureStage {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Request => "request",
            Self::Stream => "stream",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponsesFailureCategory {
    TransportHttp,
    TransportRetryLimit,
    TransportTimeout,
    TransportConnection,
    TransportNetwork,
    TransportBuild,
    ApiStatus,
    ApiStream,
    ContextWindowExceeded,
    QuotaExceeded,
    UsageNotIncluded,
    ApiRetryable,
    RateLimit,
    InvalidRequest,
    CyberPolicy,
    MisalignmentPolicy,
    ServerOverloaded,
}

impl ResponsesFailureCategory {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::TransportHttp => "transport_http",
            Self::TransportRetryLimit => "transport_retry_limit",
            Self::TransportTimeout => "transport_timeout",
            Self::TransportConnection => "transport_connection",
            Self::TransportNetwork => "transport_network",
            Self::TransportBuild => "transport_build",
            Self::ApiStatus => "api_status",
            Self::ApiStream => "api_stream",
            Self::ContextWindowExceeded => "context_window_exceeded",
            Self::QuotaExceeded => "quota_exceeded",
            Self::UsageNotIncluded => "usage_not_included",
            Self::ApiRetryable => "api_retryable",
            Self::RateLimit => "rate_limit",
            Self::InvalidRequest => "invalid_request",
            Self::CyberPolicy => "cyber_policy",
            Self::MisalignmentPolicy => "misalignment_policy",
            Self::ServerOverloaded => "server_overloaded",
        }
    }
}

/// Safe to display or serialize by field. An upstream "retryable" category is
/// only its label; the existing owner must authorize every physical attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ResponsesFailure {
    pub stage: ResponsesFailureStage,
    pub category: ResponsesFailureCategory,
    pub http_status: Option<u16>,
}

impl ResponsesFailure {
    pub(crate) fn from_api(stage: ResponsesFailureStage, error: &ApiError) -> Self {
        use ResponsesFailureCategory as Category;
        let (category, http_status) = match error {
            ApiError::Transport(error) => match error {
                TransportError::Http { status, .. } => {
                    (Category::TransportHttp, Some(status.as_u16()))
                }
                TransportError::RetryLimit => (Category::TransportRetryLimit, None),
                TransportError::Timeout => (Category::TransportTimeout, None),
                TransportError::Connection(_) => (Category::TransportConnection, None),
                TransportError::Network(_) => (Category::TransportNetwork, None),
                TransportError::Build(_) => (Category::TransportBuild, None),
            },
            ApiError::Api { status, .. } => (Category::ApiStatus, Some(status.as_u16())),
            ApiError::Stream(_) => (Category::ApiStream, None),
            ApiError::ContextWindowExceeded => (Category::ContextWindowExceeded, None),
            ApiError::QuotaExceeded => (Category::QuotaExceeded, None),
            ApiError::UsageNotIncluded => (Category::UsageNotIncluded, None),
            ApiError::Retryable { .. } => (Category::ApiRetryable, None),
            ApiError::RateLimit(_) => (Category::RateLimit, None),
            ApiError::InvalidRequest { .. } => (Category::InvalidRequest, None),
            ApiError::CyberPolicy { .. } => (Category::CyberPolicy, None),
            ApiError::MisalignmentPolicyViolation { .. } => (Category::MisalignmentPolicy, None),
            ApiError::ServerOverloaded => (Category::ServerOverloaded, None),
        };
        Self {
            stage,
            category,
            http_status,
        }
    }
}

impl fmt::Display for ResponsesFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{}:{}",
            self.stage.as_str(),
            self.category.as_str()
        )?;
        if let Some(status) = self.http_status {
            write!(formatter, " (HTTP {status})")?;
        }
        Ok(())
    }
}
