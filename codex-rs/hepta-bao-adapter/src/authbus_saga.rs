//! Registered-product AuthBus saga. Error variants carry execution stage rather
//! than asking the caller to infer stage from a provider error category.
use codex_hepta_authbus::{AuthBusAuthorityHost, QuotaReservation, ReservationRequest, SettlementStatus};
use codex_hepta_types::{Digest32, StableId};
use crate::{BaoAuthBusError, BaoAuthBusEvidenceProvider, BaoAuthorizedReadV1, BaoClient, BaoClientError, BaoSecretReceipt};

pub(crate) enum BaoSagaError {
    /// No provider invocation by this call. A reservation/fence may still need reconciliation.
    BeforeDispatch(BaoAuthBusError),
    /// A fence exists. Neither a refund nor redispatch may be inferred from the error.
    AfterDispatch(BaoAuthBusError),
    /// Immutable provider-failure evidence AND its settlement are durable.
    ProviderTerminal,
}

pub(crate) struct BaoSagaHooks<R, D, T, P, C> {
    pub reserved: R,
    pub dispatch_fenced: D,
    pub provider_terminal: T,
    pub prepare_delivery: P,
    pub consumer: C,
}

pub(crate) async fn consume_kv_v2_with_authbus_saga<E, R, D, T, P, C>(
    client: &BaoClient,
    authbus: &AuthBusAuthorityHost,
    read: BaoAuthorizedReadV1<'_>,
    evidence: &mut E,
    hooks: BaoSagaHooks<R, D, T, P, C>,
) -> Result<BaoSecretReceipt, BaoSagaError>
where
    E: BaoAuthBusEvidenceProvider,
    R: FnMut(&QuotaReservation) -> Result<(), BaoAuthBusError>,
    D: FnMut(&QuotaReservation) -> Result<(), BaoAuthBusError>,
    T: FnOnce(BaoClientError, Digest32) -> Result<(), BaoAuthBusError>,
    P: FnOnce(&BaoSecretReceipt) -> Result<(), ()>,
    C: FnOnce(&[u8], &BaoSecretReceipt) -> Result<(), ()>,
{
    let BaoAuthorizedReadV1 { admission, authority, grant, request } = read;
    let BaoSagaHooks { mut reserved, mut dispatch_fenced, provider_terminal, prepare_delivery, consumer } = hooks;
    let before = BaoSagaError::BeforeDispatch;
    let after = BaoSagaError::AfterDispatch;
    admission.validate().map_err(|error| before(error.into()))?;
    let binding = client.binding(request).map_err(|error| before(error.into()))?;
    let principal = StableId::new(binding.subject_id.clone())
        .map_err(|_| before(BaoClientError::InvalidRequest.into()))?;
    let action = StableId::new("action:bao-read")
        .map_err(|_| before(BaoClientError::InvalidRequest.into()))?;
    let scope = Digest32::from_array(binding.scope_sha256);
    let effect_digest = client.authbus_effect_digest(request, &admission.operation_id)
        .map_err(|error| before(error.into()))?;
    let observed = evidence.trusted_time().map_err(before)?;
    let time = authbus.observe_trusted_time_attestation(&observed).await.map_err(|error| before(error.into()))?;
    let decision = authbus.authorize(&principal, &action, scope, admission.policy_revision, time.clone())
        .await.map_err(|error| before(error.into()))?;
    let reservation = authbus.reserve(&decision, ReservationRequest {
        quota_key: admission.quota_key.clone(),
        operation_id: admission.operation_id.clone(),
        amount: admission.amount,
        effect_digest,
        expected_quota_revision: admission.expected_quota_revision,
        expires_at_ms: admission.expires_at_ms,
    }, time).await.map_err(|error| before(error.into()))?;
    reserved(&reservation).map_err(before)?;
    let dispatch_time = authbus.observe_trusted_time_attestation(&evidence.trusted_time().map_err(before)?)
        .await.map_err(|error| before(error.into()))?;
    let dispatched = authbus.mark_dispatch_attempted(&reservation.reservation_id, reservation.revision, effect_digest, dispatch_time)
        .await.map_err(|error| before(error.into()))?;
    dispatch_fenced(&dispatched).map_err(after)?;
    let provider = client.consume_kv_v2_guarded(authority, grant, request, prepare_delivery, consumer)
        .await.and_then(|result| result.map_err(|()| BaoClientError::ConsumerIndeterminate));
    match provider {
        Ok(receipt) => {
            let terminal = Digest32::of_bytes(&serde_json::to_vec(&receipt)
                .map_err(|_| after(BaoAuthBusError::Evidence("receipt encoding failed")))?);
            crate::https_consumer::settle_observed(authbus, evidence, &dispatched,
                SettlementStatus::Completed, admission.amount, terminal, Some(receipt)).await
                .map_err(after)?.ok_or_else(|| after(BaoAuthBusError::Evidence("successful settlement lost its receipt")))
        }
        Err(error) if ambiguous_after_dispatch(error) => {
            if let Ok(observation) = evidence.trusted_time()
                && let Ok(time) = authbus.observe_trusted_time_attestation(&observation).await
            {
                let _ = authbus.mark_indeterminate(&dispatched.reservation_id, dispatched.revision, time).await;
            }
            Err(after(BaoAuthBusError::Indeterminate { reservation_id: dispatched.reservation_id, provider_error: error }))
        }
        Err(error) => {
            let terminal = Digest32::of_bytes(format!("hepta.bao.terminal.v4:{error:?}").as_bytes());
            provider_terminal(error, terminal).map_err(after)?;
            match crate::https_consumer::settle_observed(authbus, evidence, &dispatched,
                SettlementStatus::Completed, admission.amount, terminal, None).await
            {
                Ok(None) => Err(BaoSagaError::ProviderTerminal),
                Ok(Some(_)) => Err(after(BaoAuthBusError::Evidence("terminal provider failure unexpectedly produced a receipt"))),
                Err(pending) => Err(after(pending)),
            }
        }
    }
}

fn ambiguous_after_dispatch(error: BaoClientError) -> bool {
    matches!(error, BaoClientError::TransportUnavailable | BaoClientError::TimedOut
        | BaoClientError::ConsumerIndeterminate | BaoClientError::Authority(_)
        | BaoClientError::InvalidConfiguration | BaoClientError::InvalidRequest)
}
