use super::gate::EnteredSend;
use super::*;

/// Only the admission phase may ask the caller to release an unentered claim.
/// An entered result owns its proof and borrows its exact fenced claim.
pub(super) enum Admission<'claim> {
    AlreadyTerminal,
    Entered(EnteredSend<'claim>),
}

pub(super) async fn admit_claim<
    'claim,
    T: MatrixOutboundTransport + ?Sized,
    A: MatrixOutboundAuthorizer + ?Sized,
>(
    store: &MatrixDurableStore,
    transport: &T,
    authorizer: &A,
    claim: &'claim MatrixFencedOutboxClaim,
    clock: &DispatchClock,
    cancel: &CancellationToken,
    stats: &mut OutboxDispatchStats,
) -> Result<Admission<'claim>, OutboxDispatchError> {
    if cancel.is_cancelled() {
        return Err(OutboxDispatchError::Canceled);
    }
    let record = claim.record();
    let deadline = clock.deadline(claim.lease_until_ms())?;
    let prepared_at_ms = clock.now_ms()?;
    let prepared = timed_sqlite(stats, store.prepare_outbox_dispatch(record, prepared_at_ms))
        .await
        .map_err(store_error)?;
    if prepared.state.is_terminal() {
        close_observed_terminal(store, claim, &prepared, clock, stats).await?;
        return Ok(Admission::AlreadyTerminal);
    }
    timed_sqlite(
        stats,
        store.record_outbox_prepared(claim, clock.now_ms()?),
    )
    .await
    .map_err(store_error)?;
    let identity = transport
        .identity()
        .map_err(|_| OutboxDispatchError::TransportIdentity)?;
    let request = build_matrix_final_use_request(
        store.owner_agent_id().as_str(),
        &prepared,
        record,
        &identity,
    )
    .map_err(authority_error)?;
    timed_sqlite(
        stats,
        store.pin_outbox_content(
            claim,
            &request.payload_digest,
            &request.scope_digest,
            clock.now_ms()?,
        ),
    )
    .await
    .map_err(store_error)?;
    let broker_started = std::time::Instant::now();
    let signed = tokio::select! {
        biased;
        _ = cancel.cancelled() => Err(OutboxDispatchError::Canceled),
        result = tokio::time::timeout_at(deadline, authorizer.signed_grant(&request)) => {
            result
                .map_err(|_| OutboxDispatchError::LeaseExpired)
                .and_then(|result| result.map_err(authority_error))
        }
    };
    stats.broker_latency.observe_duration(broker_started.elapsed());
    let signed = signed?;
    let revocation_started = std::time::Instant::now();
    let revocation = authorizer.refresh_revocations().map_err(authority_error);
    stats
        .revocation_latency
        .observe_duration(revocation_started.elapsed());
    revocation?;
    let token = authorizer
        .authority()
        .claim(&signed, &request.binding)
        .map_err(|_| OutboxDispatchError::Authority)?;
    let claimed_authority_epoch = token.claimed_authority_epoch();
    let claimed_revocation_revision = token.claimed_revocation_revision();
    if claimed_authority_epoch != signed.grant.authority_epoch {
        return Err(OutboxDispatchError::Authority);
    }
    let witness = MatrixOutboxAuthorityWitness {
        authority_epoch: claimed_authority_epoch,
        revocation_revision: claimed_revocation_revision,
        grant_id: signed.grant.grant_id.clone(),
        verified_use_witness_sha256: hex_digest(token.witness_sha256()),
        revocation_head_sha256: hex_digest(token.claimed_revocation_head_sha256()),
    };
    timed_sqlite(
        stats,
        store.record_outbox_authorized(claim, &witness, clock.now_ms()?),
    )
    .await
    .map_err(store_error)?;
    timed_sqlite(
        stats,
        store.record_dispatch_authority_claim(
            &record.stable_txn_id,
            &MatrixDispatchAuthorityClaim {
                operation_id: request.operation_id.clone(),
                subject_id: request.subject_id.clone(),
                destination_id: request.destination_id.clone(),
                homeserver_id: request.homeserver_id.clone(),
                matrix_user_id: request.matrix_user_id.clone(),
                device_id: request.device_id.clone(),
                session_generation: request.session_generation,
                authority_epoch: claimed_authority_epoch,
                revocation_revision: claimed_revocation_revision,
                grant_id: signed.grant.grant_id.clone(),
                request_digest: request.request_digest.clone(),
                scope_digest: request.scope_digest.clone(),
                // Preserve migration-6 digest semantics. The canonical signed
                // content is separately retained by migration 8.
                payload_digest: prepared.payload_digest.clone(),
                attempt: record.attempts,
                expires_at_ms: signed.grant.expires_at_unix_ms,
                claimed_at_ms: system_time_ms()?,
            },
        ),
    )
    .await
    .map_err(store_error)?;
    if cancel.is_cancelled() {
        return Err(OutboxDispatchError::Canceled);
    }
    timed_sqlite(
        stats,
        store.record_outbox_dispatching(claim, clock.now_ms()?),
    )
    .await
    .map_err(store_error)?;
    clock.deadline(claim.lease_until_ms())?;
    let gate = FinalSendGate {
        store,
        claim,
        clock,
        transport,
        authorizer,
        expected_identity: &identity,
        record,
        cancel,
        deadline,
    };
    gate.enter_verified_use(token, &request.binding, stats)
        .await
        .map(Admission::Entered)
}
