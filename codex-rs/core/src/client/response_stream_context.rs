//! Attempt-scoped state retained while a provider response stream is mapped.

use std::sync::Arc;

use codex_model_provider::SharedModelProvider;
use codex_otel::SessionTelemetry;
use codex_rollout_trace::InferenceTraceAttempt;

use crate::model_provider_policy::ProviderAttemptOwner;

pub(super) struct ResponseStreamContext {
    pub(super) upstream_request_id: Option<String>,
    pub(super) session_telemetry: SessionTelemetry,
    pub(super) inference_trace_attempt: InferenceTraceAttempt,
    pub(super) provider: SharedModelProvider,
    pub(super) provider_attempt: Option<ProviderAttemptOwner>,
    pub(super) redact_provider_errors: bool,
    pub(super) encoded_request_observer: Option<Arc<dyn codex_api::EncodedRequestBodyObserver>>,
}
