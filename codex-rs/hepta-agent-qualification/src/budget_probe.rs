use crate::Args;
use crate::evidence::ContinuationEvidence;
use crate::evidence::Evidence;
use crate::evidence::ExactBodyObserver;
use crate::request_wire::PreparedOrdinaryWire;
use anyhow::Result;
use anyhow::anyhow;
use codex_api::RequestedOutputLimit;
use codex_api::ResponsesOptions;
use codex_api::encode_request_with_requested_output_limit;
use codex_core::config::ConfigBuilder;
use codex_features::Feature;
use codex_hepta_agent_loop::ManagedResponsesAttempt;
use codex_hepta_agent_loop::ManagedResponsesClient;
use codex_hepta_agent_loop::ModelEvent;
use codex_hepta_agent_loop::ModelRequest;
use codex_hepta_agent_loop::ResponsesBridgeLimits;
use codex_hepta_agent_loop::TurnBinding;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_login::AgentIdentityAuthPolicy;
use codex_login::AuthManager;
use codex_model_provider::AgentIdentitySessionFallback;
use codex_model_provider::ProviderAuthScope;
use codex_model_provider::create_model_provider;
use codex_protocol::protocol::SessionSource;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

#[path = "budget_request.rs"]
mod request_template;
#[path = "probe_settings.rs"]
mod settings;

#[path = "budget_report.rs"]
mod report;
const MAXIMUM_VISIBLE_BYTES: usize = 8_192;
const MAXIMUM_RETAINED_BYTES: usize = 262_144;

// Error strings can contain provider bodies, URLs or credentials. Only the
// typed allowlist above the HTTP/stream boundary may enter retained evidence.
fn failure_diagnostic(error: &codex_hepta_agent_loop::Error) -> Value {
    use codex_hepta_agent_loop::Error as LoopError;
    match error {
        LoopError::Responses(failure) => json!({
            "stage":failure.stage.as_str(), "category":failure.category.as_str(),
            "http_status":failure.http_status,
            "provider_error":failure.provider_error.map(|details| json!({
                "type":details.error_type.map(codex_hepta_agent_loop::ResponsesProviderErrorType::as_str),
                "code":details.code.map(codex_hepta_agent_loop::ResponsesProviderErrorCode::as_str),
                "param":details.parameter.map(codex_hepta_agent_loop::ResponsesProviderErrorParam::as_str),
            })),
        }),
        LoopError::Limit(_) => json!({"stage":"native", "category":"limit", "http_status":null}),
        LoopError::Contract(_) => {
            json!({"stage":"native", "category":"contract", "http_status":null})
        }
        LoopError::Owner(_) => json!({"stage":"native", "category":"owner", "http_status":null}),
    }
}

struct Observation {
    text: String,
    first_visible_ms: Option<u128>,
    completed: bool,
    unexpected_tool: bool,
}

async fn collect(
    mut events: mpsc::Receiver<codex_hepta_agent_loop::Result<ModelEvent>>,
    cancellation: CancellationToken,
    started: Instant,
) -> Observation {
    let mut observed = Observation {
        text: String::new(),
        first_visible_ms: None,
        completed: false,
        unexpected_tool: false,
    };
    while let Some(event) = events.recv().await {
        match event {
            Ok(ModelEvent::TextDelta(text)) => {
                if observed.text.len().saturating_add(text.len()) > MAXIMUM_VISIBLE_BYTES {
                    cancellation.cancel();
                    break;
                }
                observed
                    .first_visible_ms
                    .get_or_insert_with(|| started.elapsed().as_millis());
                observed.text.push_str(&text);
            }
            Ok(ModelEvent::Completed { .. }) => observed.completed = true,
            Ok(ModelEvent::ToolCall(_)) => {
                observed.unexpected_tool = true;
                cancellation.cancel();
            }
            Err(_) => cancellation.cancel(),
        }
    }
    observed
}

#[cfg(test)]
#[path = "probe_diagnostics_tests.rs"]
mod diagnostics_tests;
