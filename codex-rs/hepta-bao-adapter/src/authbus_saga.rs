//! Registered-product AuthBus saga with explicit durable transition callbacks.
//!
//! The lower-level `BaoClient` API remains available for trusted adapters, but
//! the registered product host uses this sequence so local state never claims a
//! reservation or dispatch fence before AuthBus has committed it.

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::BaoAuthBusError;
use crate::BaoAuthBusEvidenceProvider;
use crate::BaoAuthorizedReadV1;
use crate::BaoClient;
use crate::BaoClientError;
use crate::BaoSecretReceipt;

pub(crate) async fn consume_kv_v2_with_authbus_saga<E: BaoAuthBusEvidenceProvider>(
    client: &BaoClient,
    authbus: &AuthBusAuthorityHost,
    read: BaoAuthorizedReadV1<'_>,
    evidence: &mut E,
    mut reserved: impl FnMut(&QuotaReservation) -> Result<(), BaoAuthBusError>,
    mut dispatch_fenced: impl FnMut(&QuotaReservation) -> Result<(), BaoAuthBusError>,
    provider_terminal: impl FnOnce(BaoClientError, Digest32) -> Result<(), BaoAuthBusError>,
    prepare_delivery: impl FnOnce(&BaoSecretReceipt) -> Result<(), ()>,
    consumer: impl FnOnce(&[u8], &BaoSecretReceipt) -> Result<(), ()>,
) -> Result<BaoSecretReceipt, BaoAuthBusError> {
    let BaoAuthorizedReadV1 {
        admission,
        authority,
        grant,
        request,
    } = read;
    if admission.policy_revision == 0
        || admission.expected_quota_revision == 0
        || admission.amount == 0
        || admission.expires_at_ms == 0
    {
        return Err(BaoClientError::InvalidRequest.into());
    }
    let binding = client.binding(request)?;
    let principal = StableId::new(binding.subject_id.clone())
        .map_err(|_| BaoClientError::InvalidRequest)?;
    let action = StableId::new("action:bao-read").map_err(|_| BaoClientError::InvalidRequest)?;
    let scope = Digest32::from_array(binding.scope_sha256);
    let effect_digest = client.authbus_effect_digest(request, &admission.operation_id)?;

    let observed = evidence.trusted_time()?;
    let time = authbus.observe_trusted_time_attestation(&observed).await?;
    let decision = authbus
        .authorize(
            &principal,
            &action,
            scope,
            admission.policy_revision,
            time.clone(),
        )
        .await?;
    let reservation = authbus
        .reserve(
            &decision,
            ReservationRequest {
                quota_key: admission.quota_key.clone(),
                operation_id: admission.operation_id.clone(),
                amount: admission.amount,
                effect_digest,
                expected_quota_revision: admission.expected_quota_revision,
                expires_at_ms: admission.expires_at_ms,
            },
            time,
        )
        .await?;
    reserved(&reservation)?;

    let dispatch_time = authbus
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await?;
    let dispatched = authbus
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            effect_digest,
            dispatch_time,
        )
        .await?;
    dispatch_fenced(&dispatched)?;

    let provider = client
        .consume_kv_v2_guarded(authority, grant, request, prepare_delivery, consumer)
        .await
        .and_then(|result| result.map_err(|()| BaoClientError::ConsumerIndeterminate));
    match provider {
        Ok(receipt) => {
            let terminal = Digest32::of_bytes(
                &serde_json::to_vec(&receipt)
                    .map_err(|_| BaoAuthBusError::Evidence("receipt encoding failed"))?,
            );
            crate::https_consumer::settle_observed(
                authbus,
                evidence,
                &dispatched,
                SettlementStatus::Completed,
                admission.amount,
                terminal,
                Some(receipt),
            )
            .await?
            .ok_or(BaoAuthBusError::Evidence(
                "successful settlement lost its receipt",
            ))
        }
        Err(error) if ambiguous_after_dispatch(error) => {
            let time = authbus
                .observe_trusted_time_attestation(&evidence.trusted_time()?)
                .await;
            if let Ok(time) = time {
                let _ = authbus
                    .mark_indeterminate(
                        &dispatched.reservation_id,
                        dispatched.revision,
                        time,
                    )
                    .await;
            }
            Err(BaoAuthBusError::Indeterminate {
                reservation_id: dispatched.reservation_id,
                provider_error: error,
            })
        }
        Err(error) => {
            let terminal =
                Digest32::of_bytes(format!("hepta.bao.terminal.v4:{error:?}").as_bytes());
            provider_terminal(error, terminal)?;
            match crate::https_consumer::settle_observed(
                authbus,
                evidence,
                &dispatched,
                SettlementStatus::Completed,
                admission.amount,
                terminal,
                None,
            )
            .await
            {
                Ok(None) => Err(BaoAuthBusError::Provider(error)),
                Ok(Some(_)) => Err(BaoAuthBusError::Evidence(
                    "terminal provider failure unexpectedly produced a receipt",
                )),
                Err(pending) => Err(pending),
            }
        }
    }
}

fn ambiguous_after_dispatch(error: BaoClientError) -> bool {
    matches!(
        error,
        BaoClientError::TransportUnavailable
            | BaoClientError::TimedOut
            | BaoClientError::ConsumerIndeterminate
            | BaoClientError::Authority(_)
            | BaoClientError::InvalidConfiguration
            | BaoClientError::InvalidRequest
    )
}
