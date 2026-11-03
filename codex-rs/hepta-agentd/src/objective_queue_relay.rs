//! Relay a signed canonical input to the original Core QueueStore. The
//! RunStart journal owns retry identity; this module owns no queue or outbox.

use std::future::Future;
use std::pin::Pin;
use std::time::Duration;

use codex_app_server_protocol::{ThreadQueueReconcileMode, ThreadQueueReconcileParams, ThreadQueueReconcileResponse, UserInput};
use codex_hepta_learning_ledger::RunStartRecordV1;

use crate::{AgentdError, AgentdState};
use crate::authbus_dispatch::{TextQueueTransport, connect, input_digest, receipt};
use crate::authbus_ingress::require_ready;
use crate::authbus_trust::invalid;

pub(crate) type ObjectiveQueueFuture<'a> = Pin<Box<dyn Future<Output = Result<ThreadQueueReconcileResponse, AgentdError>> + Send + 'a>>;

/// The original QueueStore transport boundary. Implementations send the exact
/// signed route and must revalidate its owner after connecting, before sending.
/// Fault fixtures replace transport only; they retain Core's actual queue.
pub(crate) trait ObjectiveQueueTransport: Send + Sync {
    fn reconcile<'a>(&'a self, state: &'a AgentdState, record: &'a RunStartRecordV1,
        params: ThreadQueueReconcileParams) -> ObjectiveQueueFuture<'a>;
}

pub(crate) struct OriginalObjectiveQueueTransport;

impl ObjectiveQueueTransport for OriginalObjectiveQueueTransport {
    fn reconcile<'a>(&'a self, state: &'a AgentdState, record: &'a RunStartRecordV1,
        params: ThreadQueueReconcileParams) -> ObjectiveQueueFuture<'a> {
        Box::pin(async move {
            let client = connect(state).await?;
            let response = async {
                require_current_route(state, record, &params)?;
                client.reconcile(params).await
            }.await;
            let _ = client.shutdown().await;
            response
        })
    }
}

pub(crate) fn require_current_route(state: &AgentdState, record: &RunStartRecordV1,
    params: &ThreadQueueReconcileParams) -> Result<(), AgentdError> {
    require_observed_route(state, record, params)?;
    if params.mode == ThreadQueueReconcileMode::AllowIfAbsent {
        state.with_fresh_original_run(record.snapshot.run_id.as_str(), || Ok(()))?;
    }
    Ok(())
}

// A reply to an already sent admission may arrive after that same run closes.
// Validate the exact route/trust/generation without asking for fresh permission.
fn require_observed_route(state: &AgentdState, record: &RunStartRecordV1,
    params: &ThreadQueueReconcileParams) -> Result<(), AgentdError> {
    require_ready(state)?;
    if state.native_objective_executor.get().is_none() {
        return Err(invalid("signed queued objective requires the installed original native executor"));
    }
    let current = state.canonical_queued_input(record)?;
    if params.thread_id != current.thread_id
        || params.client_user_message_id != current.client_user_message_id
        || params.expected_payload_sha256 != current.input_payload_sha256
        || input_digest(&params.input)? != current.input_payload_sha256 {
        return Err(invalid("original queued objective route or payload changed"));
    }
    Ok(())
}

pub(crate) async fn relay(state: &AgentdState, record: &RunStartRecordV1,
    mode: ThreadQueueReconcileMode, transport: &dyn ObjectiveQueueTransport) -> Result<(), AgentdError> {
    let input = state.canonical_queued_input(record)?;
    let params = ThreadQueueReconcileParams {
        thread_id: input.thread_id,
        client_user_message_id: input.client_user_message_id,
        input: vec![UserInput::Text { text: input.text, text_elements: Vec::new() }],
        expected_payload_sha256: input.input_payload_sha256,
        mode,
    };
    require_current_route(state, record, &params)?;
    let response = tokio::time::timeout(Duration::from_secs(5),
        transport.reconcile(state, record, params.clone())).await
        .map_err(|_| invalid("original objective queue reply is unknown after timeout"))??;
    require_observed_route(state, record, &params)?;
    receipt(&response, &params.client_user_message_id, &params.expected_payload_sha256, mode)?;
    Ok(())
}
