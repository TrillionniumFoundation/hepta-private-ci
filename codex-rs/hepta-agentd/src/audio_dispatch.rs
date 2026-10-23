//! The existing Core queue receives only the final text; its original client ID
//! links back to the canonical signed source metadata in the AuthBus outbox.
use crate::AgentdError;
use crate::AgentdState;
use crate::audio_observation::AudioObservationBodyV1;
use crate::audio_observation::invalid;
use crate::audio_observation::payload;
use crate::audio_observation::scope;
use crate::audio_policy::AudioPolicy;
use crate::authbus_ingress::attached;
use crate::authbus_ingress::now_ms;
use crate::authbus_ingress::require_ready;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::UserInput;
use codex_hepta_evidence::AuthBusClaimRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

pub(crate) async fn run(
    state: Arc<AgentdState>,
    cancel: CancellationToken,
) -> Result<(), AgentdError> {
    let mut reported = false;
    loop {
        tokio::select! { _=cancel.cancelled()=>return Ok(()), _=tokio::time::sleep(Duration::from_millis(250))=>{} }
        let result =
            tokio::select! {_=cancel.cancelled()=>return Ok(()), result=tick(&state)=>result};
        match result {
            Ok(()) => reported = false,
            Err(error) => {
                if !reported {
                    eprintln!("Audio observation relay unavailable: {error}");
                }
                reported = true;
            }
        }
    }
}

pub(super) async fn tick(state: &AgentdState) -> Result<(), AgentdError> {
    require_ready(state)?;
    let host = attached(state)?;
    let policy = AudioPolicy::current(state)?;
    let route = scope(
        &state.identity().agent_id,
        &policy.stream(""),
        policy.capture_generation,
    )?;
    let issuer = host.trust(state)?.issuer()?;
    if issuer.revoked {
        host.evidence
            .quarantine_authbus_issuer(&issuer)
            .await
            .map_err(invalid)?;
        return Ok(());
    }
    let pending = host
        .evidence
        .pending_authbus_deliveries_for_issuer(&host.subject, route, &issuer, /*limit*/ 16)
        .await
        .map_err(invalid)?;
    let Some(status) = pending.into_iter().next() else {
        return Ok(());
    };
    // A failed connection is known not to have crossed the Core seam. Resolve it
    // before consuming a durable delivery attempt, as the original text relay does.
    let client=crate::authbus_dispatch::connect(state).await?;
    let result=async {
    require_ready(state)?;
    let issuer=host.trust(state)?.issuer()?;
    let worker = StableId::new(format!(
        "agentd:audio:{}",
        state.identity().spawn_generation
    ))
    .map_err(invalid)?;
    let delivery = host
        .evidence
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: status.delivery_id,
                subject_id: &host.subject,
                scope_digest: route,
                worker_id: &worker,
                lease_ms: 30_000,
            },
        )
        .await
        .map_err(invalid)?;
    let checked = async {
        let body: AudioObservationBodyV1 = serde_json::from_slice(&delivery.payload)?;
        if payload(&body)? != delivery.payload
            || delivery.message.claims.sequence != body.source.sequence
            || scope(
                &state.identity().agent_id,
                &body.source.stream,
                body.source.capture_generation,
            )? != route
            || (body.spawn_generation != state.identity().spawn_generation
                && delivery.attempts == 1)
        {
            return Err(invalid(
                "audio payload, capture route or Agentd generation drift",
            ));
        }
        policy.permits(
            delivery.message.claims.issuer_id.as_str(),
            delivery.message.claims.key_epoch.get(),
            &body,
        )?;
        if !host.trust(state)?.permits(&body.thread_id) {
            return Err(invalid("thread permission changed"));
        }
        policy.verify_media(state.identity(), &body.source).await?;
        Ok::<_, AgentdError>(body)
    }
    .await;
    let body = match checked {
        Ok(body) => body,
        Err(_) => {
            return host
                .evidence
                .quarantine_authbus_delivery(&host.trust(state)?.issuer()?, &delivery.lease)
                .await
                .map_err(invalid);
        }
    };
        require_ready(state)?;
        let issuer = host.trust(state)?.issuer()?;
        AudioPolicy::current(state)?.permits(
            delivery.message.claims.issuer_id.as_str(),
            delivery.message.claims.key_epoch.get(),
            &body,
        )?;
        if !host.trust(state)?.permits(&body.thread_id) {
            return Err(invalid("thread permission changed"));
        }
        delivery
            .message
            .authenticate(
                &issuer,
                route,
                Digest32::of_bytes(&delivery.payload),
                now_ms()?,
            )
            .map_err(invalid)?;
        let lease = host
            .evidence
            .renew_authbus_delivery(&issuer, &delivery.lease, /*lease_ms*/ 30_000)
            .await
            .map_err(invalid)?;
        let mode = if delivery.attempts == 1 {
            ThreadQueueReconcileMode::AllowIfAbsent
        } else {
            ThreadQueueReconcileMode::ReconcileOnly
        };
        let client_id = format!("hepta.authbus:{}", lease.delivery_id());
        let input = vec![UserInput::Text {
            text: body.text.clone(),
            text_elements: Vec::new(),
        }];
        let expected = crate::authbus_dispatch::input_digest(&input)?;
        let response = tokio::time::timeout(
            Duration::from_secs(5),
            client.request_typed::<ThreadQueueReconcileResponse>(
                ClientRequest::ThreadQueueReconcile {
                    request_id: RequestId::Integer(1),
                    params: ThreadQueueReconcileParams {
                        thread_id: body.thread_id.clone(),
                        input,
                        client_user_message_id: client_id.clone(),
                        expected_payload_sha256: expected.clone(),
                        mode,
                    },
                },
            ),
        )
        .await;
        require_ready(state)?;
        let trust = host.trust(state)?;
        let issuer = trust.issuer()?;
        if !trust.permits(&body.thread_id)
            || AudioPolicy::current(state)?
                .permits(
                    delivery.message.claims.issuer_id.as_str(),
                    delivery.message.claims.key_epoch.get(),
                    &body,
                )
                .is_err()
        {
            return host
                .evidence
                .quarantine_authbus_delivery(&issuer, &lease)
                .await
                .map_err(invalid);
        }
        match response {
            Ok(Ok(response)) => {
                match crate::authbus_dispatch::receipt(&response, &client_id, &expected, mode) {
                    Ok(digest) => host
                        .evidence
                        .ack_authbus_delivery(&issuer, &lease, digest)
                        .await
                        .map_err(invalid),
                    Err(_) => host
                        .evidence
                        .quarantine_authbus_delivery(&issuer, &lease)
                        .await
                        .map_err(invalid),
                }
            }
            Ok(Err(_)) | Err(_) => host
                .evidence
                .retry_authbus_delivery(&issuer, &lease, /*delay_ms*/ 1000)
                .await
                .map_err(invalid),
        }
    }
    .await;
    let shutdown = tokio::time::timeout(Duration::from_secs(3), client.shutdown()).await;
    result?;
    shutdown
        .map_err(|_| invalid("audio relay client cleanup timed out"))?
        .map_err(invalid)
}
