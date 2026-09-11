//! Bounded relay to the existing durable Core queue, not a provider dispatcher.

use std::sync::Arc;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::UserInput;
use codex_hepta_evidence::AuthBusClaimRequest;
use codex_hepta_evidence::AuthBusDelivery;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;
use crate::AuthBusTextBody;
use crate::authbus_ingress::TextIngress;
use crate::authbus_ingress::attached;
use crate::authbus_ingress::now_ms;
use crate::authbus_ingress::payload;
use crate::authbus_ingress::require_ready;
use crate::authbus_trust::invalid;

pub(crate) async fn run(
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    if state.authbus.get().is_none() {
        cancellation.cancelled().await;
        return Ok(());
    }
    let mut reported_failure = false;
    loop {
        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(Duration::from_millis(250)) => {}
        }
        let result = tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            result = tick(&state) => result,
        };
        match result {
            Ok(()) => reported_failure = false,
            Err(error) => {
                if !reported_failure {
                    eprintln!("AuthBus text relay unavailable: {error}");
                }
                reported_failure = true;
            }
        }
    }
}

// One message per tick. The queue's own manifest capacity remains authoritative.
pub(crate) async fn tick(state: &AgentdState) -> Result<(), AgentdError> {
    require_ready(state)?;
    let host = attached(state)?;
    let trust = host.trust(state)?;
    let issuer = trust.issuer()?;
    if issuer.revoked {
        host.evidence
            .quarantine_authbus_issuer(&issuer)
            .await
            .map_err(|error| invalid(&error.to_string()))?;
        return Ok(());
    }
    let pending = host
        .evidence
        .pending_authbus_deliveries_for_issuer(
            &host.subject,
            host.scope,
            &issuer,
            /*limit*/ 16,
        )
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    let Some(status) = pending
        .into_iter()
        .find(|row| row.issuer_id == issuer.issuer_id && row.key_epoch == issuer.key_epoch)
    else {
        return Ok(());
    };
    let client = connect(state).await?;
    require_ready(state)?;
    let issuer = host.trust(state)?.issuer()?;
    let worker = StableId::new(format!("agentd:{}", state.identity().spawn_generation))
        .map_err(|error| invalid(&error.to_string()))?;
    let delivery = host
        .evidence
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: status.delivery_id,
                subject_id: &host.subject,
                scope_digest: host.scope,
                worker_id: &worker,
                lease_ms: 30_000,
            },
        )
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    let result = deliver(state, &host, &client, delivery).await;
    let _ = client.shutdown().await;
    result
}

async fn connect(state: &AgentdState) -> Result<RemoteAppServerClient, AgentdError> {
    let identity = state.identity();
    let connect = RemoteAppServerClient::connect_with_bounded_events(
        RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::UnixSocket {
                socket_path: AbsolutePathBuf::from_absolute_path(&identity.app_server_socket)?,
            },
            client_name: "hepta-agentd-authbus-text".into(),
            client_version: env!("CARGO_PKG_VERSION").into(),
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: 8,
        },
        /*event_channel_capacity*/ 16,
    );
    let client = timeout(Duration::from_secs(2), connect)
        .await
        .map_err(|_| invalid("App Server connection timed out"))??;
    if client.codex_home() != Some(identity.home_root.to_string_lossy().as_ref()) {
        state.mark_fenced();
        let _ = client.shutdown().await;
        return Err(invalid(
            "App Server home differs from the owning Agent home",
        ));
    }
    Ok(client)
}

async fn deliver<Q: TextQueueTransport>(
    state: &AgentdState,
    host: &TextIngress,
    client: &Q,
    delivery: AuthBusDelivery,
) -> Result<(), AgentdError> {
    let trust = host.trust(state)?;
    let issuer = trust.issuer()?;
    let body = serde_json::from_slice::<AuthBusTextBody>(&delivery.payload);
    let Ok(body) = body else {
        return host
            .evidence
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await
            .map_err(|error| invalid(&error.to_string()));
    };
    if !payload(&body).is_ok_and(|bytes| bytes == delivery.payload)
        || !trust.permits(&body.thread_id)
        || (body.spawn_generation != state.identity().spawn_generation && delivery.attempts == 1)
    {
        return host
            .evidence
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await
            .map_err(|error| invalid(&error.to_string()));
    }
    require_ready(state)?;
    delivery
        .message
        .authenticate(
            &issuer,
            host.scope,
            Digest32::of_bytes(&delivery.payload),
            now_ms()?,
        )
        .map_err(|error| invalid(&error.to_string()))?;
    // Renew immediately before the transport boundary to reject a stolen/expired
    // lease. A process crash after this point always recovers with lookup only.
    let lease = host
        .evidence
        .renew_authbus_delivery(&issuer, &delivery.lease, /*lease_ms*/ 30_000)
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    require_ready(state)?;
    let fresh = host.trust(state)?;
    let fresh_issuer = fresh.issuer()?;
    if !fresh.permits(&body.thread_id) {
        return host
            .evidence
            .quarantine_authbus_delivery(&fresh_issuer, &lease)
            .await
            .map_err(|error| invalid(&error.to_string()));
    }
    delivery
        .message
        .authenticate(
            &fresh_issuer,
            host.scope,
            Digest32::of_bytes(&delivery.payload),
            now_ms()?,
        )
        .map_err(|error| invalid(&error.to_string()))?;
    let mode = if delivery.attempts == 1 {
        ThreadQueueReconcileMode::AllowIfAbsent
    } else {
        ThreadQueueReconcileMode::ReconcileOnly
    };
    let client_id = format!("hepta.authbus:{}", lease.delivery_id());
    let input = vec![UserInput::Text {
        text: body.text,
        text_elements: Vec::new(),
    }];
    let expected = input_digest(&input)?;
    let response = timeout(
        Duration::from_secs(5),
        client.reconcile(ThreadQueueReconcileParams {
            thread_id: body.thread_id.clone(),
            input,
            client_user_message_id: client_id.clone(),
            expected_payload_sha256: expected.clone(),
            mode,
        }),
    )
    .await;
    require_ready(state)?;
    let current = host.trust(state)?;
    let issuer = current.issuer()?;
    if !current.permits(&body.thread_id) {
        return host
            .evidence
            .quarantine_authbus_delivery(&issuer, &lease)
            .await
            .map_err(|error| invalid(&error.to_string()));
    }
    match response {
        Ok(Ok(response)) => match receipt(&response, &client_id, &expected, mode) {
            Ok(digest) => host
                .evidence
                .ack_authbus_delivery(&issuer, &lease, digest)
                .await
                .map_err(|error| invalid(&error.to_string())),
            Err(_) => host
                .evidence
                .quarantine_authbus_delivery(&issuer, &lease)
                .await
                .map_err(|error| invalid(&error.to_string())),
        },
        // The request may have crossed the seam. Redelivery is a lookup using
        // the same client ID and payload; Missing/Cancelled never recreate it.
        Ok(Err(_)) | Err(_) => host
            .evidence
            .retry_authbus_delivery(&issuer, &lease, /*delay_ms*/ 1000)
            .await
            .map_err(|error| invalid(&error.to_string())),
    }
}

fn input_digest(input: &[UserInput]) -> Result<String, AgentdError> {
    user_input_payload_sha256(
        &input
            .iter()
            .cloned()
            .map(UserInput::into_core)
            .collect::<Vec<_>>(),
    )
    .map_err(Into::into)
}

fn receipt(
    response: &ThreadQueueReconcileResponse,
    client_id: &str,
    expected: &str,
    mode: ThreadQueueReconcileMode,
) -> Result<Digest32, AgentdError> {
    if response.client_user_message_id != client_id || response.payload_sha256 != expected {
        return Err(invalid("queue receipt identity or payload mismatch"));
    }
    match &response.outcome {
        ThreadQueueReconcileOutcome::Queued {
            queued_submission,
            created,
        } => {
            if queued_submission.client_user_message_id != client_id
                || queued_submission.id.is_empty()
                || input_digest(&queued_submission.input)? != expected
                || (mode == ThreadQueueReconcileMode::ReconcileOnly && *created)
            {
                return Err(invalid("queue submission does not match the signed input"));
            }
        }
        ThreadQueueReconcileOutcome::Persisted { turn_id } if !turn_id.is_empty() => {}
        ThreadQueueReconcileOutcome::Persisted { .. }
        | ThreadQueueReconcileOutcome::Missing
        | ThreadQueueReconcileOutcome::Cancelled => {
            return Err(invalid("queue has no matching durable admission"));
        }
    }
    Ok(Digest32::of_bytes(&serde_json::to_vec(response)?))
}

/// Private transport boundary used by the real App Server client. Fault tests
/// inject lost replies here while retaining the actual signed SQLite lifecycle.
trait TextQueueTransport {
    fn reconcile(
        &self,
        params: ThreadQueueReconcileParams,
    ) -> impl std::future::Future<Output = Result<ThreadQueueReconcileResponse, AgentdError>> + Send;
}

impl TextQueueTransport for RemoteAppServerClient {
    async fn reconcile(
        &self,
        params: ThreadQueueReconcileParams,
    ) -> Result<ThreadQueueReconcileResponse, AgentdError> {
        self.request_handle()
            .request_typed(ClientRequest::ThreadQueueReconcile {
                request_id: RequestId::Integer(1),
                params,
            })
            .await
            .map_err(|error| invalid(&error.to_string()))
    }
}
