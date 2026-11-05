use super::ConnectionSessionState;
use super::MessageProcessor;
use crate::outgoing_message::ConnectionRequestId;
use crate::outgoing_message::RequestContext;
use crate::request_serialization::QueuedInitializedRequest;
use crate::request_serialization::RequestSerializationAccess;
use crate::request_serialization::RequestSerializationQueueKey;
use crate::termination_observation;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedParams;
use std::sync::Arc;
use tokio::time::Instant;
use tokio::time::timeout_at;
use tracing::Instrument;

impl MessageProcessor {
    pub(super) async fn enqueue_observed_termination(
        self: &Arc<Self>,
        request_id: ConnectionRequestId,
        params: ThreadBackgroundTerminalsTerminateObservedParams,
        session: Arc<ConnectionSessionState>,
        request_context: RequestContext,
        admitted_at: Instant,
    ) -> Result<(), JSONRPCErrorError> {
        let (operation, reply) =
            termination_observation::admit(admitted_at, params.observation_timeout_ms)?;
        let end = operation.end();
        let key = RequestSerializationQueueKey::Thread {
            thread_id: params.thread_id.clone(),
        };
        let span = request_context.span();
        let outgoing = Arc::clone(&self.outgoing);
        // This one response owner starts before enqueue can await the queue mutex.
        // Outbound transport backpressure does not renew the operation's budget.
        tokio::spawn(
            async move {
                match reply.wait().await {
                    Ok(response) => outgoing.send_response(request_id, response).await,
                    Err(error) => outgoing.send_error(request_id, error).await,
                }
                drop(request_context);
            }
            .instrument(span.clone()),
        );
        let processor = Arc::clone(self);
        let request = QueuedInitializedRequest::new(
            Arc::clone(&session.rpc_gate),
            operation
                .run(move |end| async move {
                    processor
                        .thread_processor
                        .thread_background_terminals_terminate_observed(params, end)
                        .await
                })
                .instrument(span),
        );
        // Dropping enqueue before insertion drops the original queue entry. An
        // already-inserted entry retains the same guard and can never start late.
        let _ = timeout_at(
            end,
            self.request_serialization_queues.enqueue(
                key,
                RequestSerializationAccess::Exclusive,
                request,
            ),
        )
        .await;
        Ok(())
    }
}
