//! Durable Objective outbox worker. The AuthBus evidence owner persists signed
//! intent/replay identity; the learning.ledger owner persists RunStart. Retries
//! reuse both identities and never create a second Objective writer.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_evidence::AuthBusClaimRequest;
use codex_hepta_evidence::AuthBusDelivery;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;
use crate::authbus_ingress;
use crate::objective_ingress;
use crate::objective_ingress::objective_invalid;

pub(crate) async fn run(
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    if state.objective_ingress.get().is_none() {
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
                    eprintln!("Objective durable ingress unavailable: {error}");
                }
                reported_failure = true;
            }
        }
    }
}

pub(crate) async fn tick(state: &AgentdState) -> Result<(), AgentdError> {
    authbus_ingress::require_ready(state)?;
    let objective = objective_ingress::attached(state)?;
    let authbus = authbus_ingress::attached(state)?;
    let trust = authbus.trust(state)?;
    let issuer = trust.issuer()?;
    if issuer.revoked {
        authbus
            .evidence
            .quarantine_authbus_issuer(&issuer)
            .await
            .map_err(|error| objective_invalid(&error.to_string()))?;
        return Ok(());
    }
    if !objective.permits_issuer(&issuer.issuer_id) {
        return Ok(());
    }

    let pending = authbus
        .evidence
        .pending_authbus_deliveries_for_issuer(
            objective.subject(),
            objective.scope(),
            &issuer,
            /*limit*/ 16,
        )
        .await
        .map_err(|error| objective_invalid(&error.to_string()))?;
    let Some(status) = pending
        .into_iter()
        .find(|row| row.issuer_id == issuer.issuer_id && row.key_epoch == issuer.key_epoch)
    else {
        return Ok(());
    };

    let worker = StableId::new(format!(
        "agentd-objective:{}",
        state.identity().spawn_generation
    ))
    .map_err(|error| objective_invalid(&error.to_string()))?;
    let delivery = authbus
        .evidence
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: status.delivery_id,
                subject_id: objective.subject(),
                scope_digest: objective.scope(),
                worker_id: &worker,
                lease_ms: 30_000,
            },
        )
        .await
        .map_err(|error| objective_invalid(&error.to_string()))?;
    deliver(state, &objective, delivery).await
}

async fn deliver(
    state: &AgentdState,
    objective: &objective_ingress::ObjectiveIngressHost,
    delivery: AuthBusDelivery,
) -> Result<(), AgentdError> {
    let authbus = authbus_ingress::attached(state)?;
    let trust = authbus.trust(state)?;
    let issuer = trust.issuer()?;
    if issuer.revoked || !objective.permits_issuer(&issuer.issuer_id) {
        return authbus
            .evidence
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await
            .map_err(|error| objective_invalid(&error.to_string()));
    }

    let body = serde_json::from_slice::<crate::AuthBusObjectiveBody>(&delivery.payload);
    let Ok(body) = body else {
        return authbus
            .evidence
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await
            .map_err(|error| objective_invalid(&error.to_string()));
    };
    if !objective_ingress::objective_payload(state.identity(), &body)
        .is_ok_and(|bytes| bytes == delivery.payload)
    {
        return authbus
            .evidence
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await
            .map_err(|error| objective_invalid(&error.to_string()));
    }

    authbus_ingress::require_ready(state)?;
    delivery
        .message
        .authenticate(
            &issuer,
            objective.scope(),
            Digest32::of_bytes(&delivery.payload),
            authbus_ingress::now_ms()?,
        )
        .map_err(|error| objective_invalid(&format!("signature revalidation: {error}")))?;

    let lease = authbus
        .evidence
        .renew_authbus_delivery(&issuer, &delivery.lease, /*lease_ms*/ 30_000)
        .await
        .map_err(|error| objective_invalid(&error.to_string()))?;
    authbus_ingress::require_ready(state)?;

    let fresh = authbus.trust(state)?;
    let fresh_issuer = fresh.issuer()?;
    if fresh_issuer.revoked || !objective.permits_issuer(&fresh_issuer.issuer_id) {
        return authbus
            .evidence
            .quarantine_authbus_delivery(&fresh_issuer, &lease)
            .await
            .map_err(|error| objective_invalid(&error.to_string()));
    }
    delivery
        .message
        .authenticate(
            &fresh_issuer,
            objective.scope(),
            Digest32::of_bytes(&delivery.payload),
            authbus_ingress::now_ms()?,
        )
        .map_err(|error| objective_invalid(&format!("signature revalidation: {error}")))?;

    let result = objective.process_delivery(state, &delivery, authbus_ingress::now_ms()?);
    match result {
        Ok(digest) => {
            authbus_ingress::require_ready(state)?;
            let current = authbus.trust(state)?;
            let current_issuer = current.issuer()?;
            if current_issuer.revoked || !objective.permits_issuer(&current_issuer.issuer_id) {
                return authbus
                    .evidence
                    .quarantine_authbus_delivery(&current_issuer, &lease)
                    .await
                    .map_err(|error| objective_invalid(&error.to_string()));
            }
            delivery
                .message
                .authenticate(
                    &current_issuer,
                    objective.scope(),
                    Digest32::of_bytes(&delivery.payload),
                    authbus_ingress::now_ms()?,
                )
                .map_err(|error| objective_invalid(&format!("final signature fence: {error}")))?;
            authbus
                .evidence
                .ack_authbus_delivery(&current_issuer, &lease, digest)
                .await
                .map_err(|error| objective_invalid(&error.to_string()))
        }
        Err(AgentdError::Invalid(message))
            if message.contains("source envelope:")
                || message.contains("revision:")
                || message.contains("run id:")
                || message.contains("canonical publication: objective admission") =>
        {
            authbus
                .evidence
                .quarantine_authbus_delivery(&fresh_issuer, &lease)
                .await
                .map_err(|error| objective_invalid(&error.to_string()))
        }
        Err(error) => {
            authbus
                .evidence
                .retry_authbus_delivery(&fresh_issuer, &lease, /*delay_ms*/ 1_000)
                .await
                .map_err(|retry| objective_invalid(&format!("{error}; retry scheduling: {retry}")))
        }
    }
}

#[cfg(test)]
fn _assert_digest_is_send(value: Digest32) -> Digest32 {
    value
}
