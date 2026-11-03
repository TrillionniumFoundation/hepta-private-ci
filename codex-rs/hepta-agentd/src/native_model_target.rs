//! Responses transport attached to the existing production operation writer.
//!
//! Admission and grants stay with the Agentd owner. This destination consumes
//! its one-shot handoff, returns the actual provider stream, and observes only
//! an original retained response. It owns no operation map or outbox.

use std::time::Duration;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_NAMESPACE;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionEffectEntry;
use codex_hepta_memory::ProductionEntryCurrentness;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTargetOutcome;
use codex_hepta_memory::ProductionTerminalObservation;
use codex_hepta_memory::ProductionTerminalObservationFuture;
use codex_hepta_native_agent::ModelRequest;
use codex_hepta_native_agent::ObservedModelCompletion;
use codex_hepta_native_agent::ResponsesModel;
use codex_hepta_native_agent::ResponsesStream;
use codex_http_client::HttpClientFactory;

pub const NATIVE_MODEL_TOPIC_V1: &str = "hepta.native.model.responses.v1";

/// Host-owned immutable transport settings, not model-supplied authority.
/// Credentials are intentionally not Debug or serialized with operation data.
pub struct NativeResponsesTargetConfig {
    pub responses_url: String,
    pub bearer: Option<String>,
    pub idle_timeout: Duration,
    pub max_request_bytes: usize,
    pub max_stream_bytes: usize,
}

pub struct NativeResponsesTarget {
    destination_id: String,
    responses_url: String,
    max_request_bytes: usize,
    transport: ResponsesModel,
}

impl NativeResponsesTarget {
    pub fn new(
        config: NativeResponsesTargetConfig,
        http_client_factory: &HttpClientFactory,
    ) -> Result<Self> {
        ensure!(config.max_request_bytes > 0, "model request byte limit is required");
        let transport = ResponsesModel::new(
            http_client_factory,
            config.responses_url.clone(),
            config.bearer,
            config.idle_timeout,
            config.max_stream_bytes,
        )?;
        // A restart with another endpoint cannot retain this destination's
        // authority even if a caller reuses the original operation/body.
        let endpoint_digest = Sha256Digest::for_bytes(config.responses_url.as_bytes());
        Ok(Self {
            destination_id: format!("destination:native-responses:{}", endpoint_digest.as_str()),
            responses_url: config.responses_url,
            max_request_bytes: config.max_request_bytes,
            transport,
        })
    }

    pub fn destination_id(&self) -> &str {
        &self.destination_id
    }

    /// Return the original body and operation only after validating the exact
    /// durable request. This method never admits a missing operation.
    pub(crate) fn original_request(
        &self,
        request: &ProductionDispatchRequest,
    ) -> Result<ModelRequest> {
        ensure!(
            request.schema_version == PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
                && request.namespace == PRODUCTION_DURABLE_WRITER_NAMESPACE,
            "unexpected production model request schema"
        );
        ensure!(request.topic == NATIVE_MODEL_TOPIC_V1, "unexpected model operation topic");
        ensure!(
            request.operation_destination_id == self.destination_id,
            "model destination changed after admission"
        );
        ensure!(
            request.idempotency_key == request.occurrence_key && !request.occurrence_key.is_empty(),
            "model request changed its original operation identity"
        );
        ensure!(
            request.expected_predecessor_sha256.is_none(),
            "Responses does not implement destination predecessor CAS"
        );
        ensure!(request.operation_policy_generation > 0, "missing model policy generation");
        let body = request.payload_json.as_bytes();
        ensure!(
            !body.is_empty() && body.len() <= self.max_request_bytes,
            "model body exceeds the admitted transport budget"
        );
        ensure!(
            request.payload_sha256 == Sha256Digest::for_bytes(body),
            "model body differs from its durable payload digest"
        );
        let value: serde_json::Value = serde_json::from_slice(body)?;
        ensure!(
            value["stream"] == true
                && value["model"].as_str().is_some_and(|model| !model.is_empty()),
            "model payload is not a streaming Responses request"
        );
        Ok(ModelRequest {
            operation_id: request.occurrence_key.clone(),
            body: body.to_vec(),
        })
    }

    /// Consume the existing writer's checked entry; headers are nonterminal.
    /// The caller must retain provider identity through the real ThreadStore
    /// and settle the same writer only from an actual terminal observation.
    pub(crate) async fn open_effect_entry(
        &self,
        entry: ProductionEffectEntry,
        currentness: &dyn ProductionEntryCurrentness,
    ) -> Result<ResponsesStream> {
        let original = self.original_request(entry.request())?;
        let ready = entry.revalidate().await?;
        self.transport
            .open_with_entry(&original, |endpoint, actual| {
                ensure!(endpoint == self.responses_url, "model endpoint changed at entry");
                ensure!(
                    actual.operation_id == original.operation_id && actual.body == original.body,
                    "model request changed at physical entry"
                );
                Ok(ready.enter(currentness)?)
            })
            .await
    }

    /// Query only the originally observed provider response, with no new POST
    /// and no new grant. Missing evidence remains pending at the owner.
    pub(crate) async fn reconcile_original(
        &self,
        request: &ProductionDispatchRequest,
        response_id: &str,
    ) -> Result<Option<ObservedModelCompletion>> {
        let original = self.original_request(request)?;
        self.transport.reconcile(&original, response_id).await
    }
}

impl ProductionOutboxTarget for NativeResponsesTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async {
            ProductionTargetOutcome::Rejected {
                reason: "native Responses requires the original writer's checked entry".to_string(),
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for NativeResponsesTarget {
    fn destination_id(&self) -> &str {
        &self.destination_id
    }

    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async {
            ProductionTerminalObservation::Unavailable {
                reason: "original provider response identity is held by the ThreadStore turn owner"
                    .to_string(),
            }
        })
    }
}

#[cfg(test)]
#[path = "native_model_target_tests.rs"]
mod tests;
