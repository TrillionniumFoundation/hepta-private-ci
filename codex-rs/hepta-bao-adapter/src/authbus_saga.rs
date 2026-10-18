//! Registered-product AuthBus saga with explicit durable transition callbacks.
//!
//! The lower-level `BaoClient` API remains available for trusted adapters, but
//! the registered product host uses this sequence so local state never claims a
//! reservation or dispatch fence before AuthBus has committed it.

use std::future::Future;

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
use crate::https_consumer::BaoGuardedDeliveryError;

pub(crate) struct BaoAuthBusSagaHooks<
    Reserved,
    DispatchFenced,
    ProviderTerminal,
    PrepareDelivery,
    Consumer,
    ConsumerSucceeded,
> {
    pub(crate) reserved: Reserved,
    pub(crate) dispatch_fenced: DispatchFenced,
    pub(crate) provider_terminal: ProviderTerminal,
    pub(crate) prepare_delivery: PrepareDelivery,
    pub(crate) consumer: Consumer,
    pub(crate) consumer_succeeded: ConsumerSucceeded,
}

pub(crate) async fn consume_kv_v2_with_authbus_saga<
    E,
    Reserved,
    ReservedFuture,
    DispatchFenced,
    DispatchFencedFuture,
    ProviderTerminal,
    ProviderTerminalFuture,
    PrepareDelivery,
    PrepareDeliveryFuture,
    Consumer,
    ConsumerSucceeded,
    ConsumerSucceededFuture,
>(
    client: &BaoClient,
    authbus: &AuthBusAuthorityHost,
    read: BaoAuthorizedReadV1<'_>,
    evidence: &mut E,
    hooks: BaoAuthBusSagaHooks<
        Reserved,
        DispatchFenced,
        ProviderTerminal,
        PrepareDelivery,
        Consumer,
        ConsumerSucceeded,
    >,
) -> Result<BaoSecretReceipt, BaoAuthBusError>
where
    E: BaoAuthBusEvidenceProvider,
    Reserved: FnMut(&QuotaReservation) -> ReservedFuture,
    ReservedFuture: Future<Output = Result<(), BaoAuthBusError>>,
    DispatchFenced: FnMut(&QuotaReservation) -> DispatchFencedFuture,
    DispatchFencedFuture: Future<Output = Result<(), BaoAuthBusError>>,
    ProviderTerminal: FnOnce(BaoClientError, Digest32) -> ProviderTerminalFuture,
    ProviderTerminalFuture: Future<Output = Result<(), BaoAuthBusError>>,
    PrepareDelivery: FnOnce(&BaoSecretReceipt) -> PrepareDeliveryFuture,
    PrepareDeliveryFuture: Future<Output = Result<(), BaoAuthBusError>>,
    Consumer: FnOnce(&[u8], &BaoSecretReceipt) -> Result<(), ()>,
    ConsumerSucceeded: FnOnce(&BaoSecretReceipt) -> ConsumerSucceededFuture,
    ConsumerSucceededFuture: Future<Output = Result<(), BaoAuthBusError>>,
{
    let BaoAuthBusSagaHooks {
        mut reserved,
        mut dispatch_fenced,
        provider_terminal,
        prepare_delivery,
        consumer,
        consumer_succeeded,
    } = hooks;
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
    let principal =
        StableId::new(binding.subject_id.clone()).map_err(|_| BaoClientError::InvalidRequest)?;
    let action = StableId::new("action:bao-read").map_err(|_| BaoClientError::InvalidRequest)?;
    let scope = Digest32::from_array(binding.scope_sha256);
    let effect_digest = client.authbus_effect_digest(request, &admission.operation_id)?;

    #[cfg(all(test, unix))]
    crate::saga_crash::cut("trusted_time.before");
    let observed = evidence.trusted_time()?;
    let time = authbus.observe_trusted_time_attestation(&observed).await?;
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("trusted_time.after");
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("authorize.before");
    let decision = authbus
        .authorize(
            &principal,
            &action,
            scope,
            admission.policy_revision,
            time.clone(),
        )
        .await?;
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("authorize.after");
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("reserve.before");
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
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("reserve.after");
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("reservation_bind.before");
    reserved(&reservation).await?;
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("reservation_bind.after");

    let dispatch_time = authbus
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await?;
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("dispatch_fence.before");
    let dispatched = authbus
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            effect_digest,
            dispatch_time,
        )
        .await?;
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("dispatch_fence.after");
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("local_fence.before");
    dispatch_fenced(&dispatched).await?;
    #[cfg(all(test, unix))]
    crate::saga_crash::cut("local_fence.after");

    let provider = match client
        .consume_kv_v2_guarded_async(authority, grant, request, prepare_delivery, consumer)
        .await
    {
        Err(error) => Err(error),
        Ok(Ok(receipt)) => Ok(receipt),
        Ok(Err(BaoGuardedDeliveryError::Preparation(error))) => return Err(error),
        Ok(Err(BaoGuardedDeliveryError::Consumer(()))) => {
            Err(BaoClientError::ConsumerIndeterminate)
        }
    };
    match provider {
        Ok(receipt) => {
            #[cfg(all(test, unix))]
            crate::saga_crash::cut("consumer_ack.before");
            consumer_succeeded(&receipt).await?;
            #[cfg(all(test, unix))]
            crate::saga_crash::cut("consumer_ack.after");
            let terminal = receipt
                .evidence_digest()
                .map(Digest32::from_array)
                .map_err(|_| BaoAuthBusError::Evidence("receipt encoding failed"))?;
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
            // Updating AuthBus is best effort after an uncertain dispatch. A
            // time-service outage must preserve the original reservation and
            // uncertainty instead of replacing them with an admission error.
            let time = match evidence.trusted_time() {
                Ok(attestation) => authbus.observe_trusted_time_attestation(&attestation).await,
                Err(_) => {
                    return Err(BaoAuthBusError::Indeterminate {
                        reservation_id: dispatched.reservation_id,
                        provider_error: error,
                    });
                }
            };
            if let Ok(time) = time {
                let _ = authbus
                    .mark_indeterminate(&dispatched.reservation_id, dispatched.revision, time)
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
            provider_terminal(error, terminal).await?;
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
