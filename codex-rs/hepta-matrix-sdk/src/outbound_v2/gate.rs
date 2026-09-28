use std::future::poll_fn;
use std::sync::Arc;
use std::task::Poll;

use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use tokio::time::Instant;

use super::*;
use crate::content::outbound_payload_digest;

pub(super) struct FinalSendGate<'gate, 'claim, T: ?Sized, A: ?Sized> {
    pub(super) store: &'gate MatrixDurableStore,
    pub(super) claim: &'claim MatrixFencedOutboxClaim,
    pub(super) clock: &'gate DispatchClock,
    pub(super) transport: &'gate T,
    pub(super) authorizer: &'gate A,
    pub(super) expected_identity: &'gate MatrixOutboundIdentity,
    pub(super) record: &'gate OutboxRecord,
    pub(super) cancel: &'gate CancellationToken,
    pub(super) deadline: Instant,
}

/// Once constructed, this value cannot be converted into a pre-entry failure.
/// The exact claim and real kernel proof live through all outcome persistence.
#[must_use]
pub(super) struct EnteredSend<'claim> {
    pub(super) result: Result<MatrixEventId, MatrixTransportError>,
    claim: &'claim MatrixFencedOutboxClaim,
    proof: Arc<EnteredUseToken>,
}

impl<'claim> EnteredSend<'claim> {
    pub(super) fn claim(&self) -> &'claim MatrixFencedOutboxClaim {
        self.claim
    }
}

#[derive(Clone, Copy)]
struct LiveGrant {
    epoch: u64,
    revision: u64,
    expires_at_ms: u64,
}

impl<'claim, T: MatrixOutboundTransport + ?Sized, A: MatrixOutboundAuthorizer + ?Sized>
    FinalSendGate<'_, 'claim, T, A>
{
    pub(super) async fn enter_verified_use(
        &self,
        token: VerifiedUseToken,
        binding: &FinalUseBinding,
        stats: &mut OutboxDispatchStats,
    ) -> Result<EnteredSend<'claim>, OutboxDispatchError> {
        let authority_claim = self
            .store
            .dispatch_authority_claim(&self.record.stable_txn_id, self.record.attempts)
            .await
            .map_err(store_error)?
            .ok_or(OutboxDispatchError::Store)?;
        let grant = LiveGrant {
            epoch: token.claimed_authority_epoch(),
            revision: token.claimed_revocation_revision(),
            expires_at_ms: authority_claim.expires_at_ms,
        };
        if authority_claim.authority_epoch != grant.epoch
            || authority_claim.revocation_revision != grant.revision
            || authority_claim.attempt != self.record.attempts
            || authority_claim.expires_at_ms <= authority_claim.claimed_at_ms
        {
            return Err(OutboxDispatchError::Authority);
        }

        // OutboxRecord owns its bytes, and both it and binding stay immutably
        // borrowed for this entire gate. Check canonical content once here;
        // the sealed permit independently validates it at the adapter boundary.
        // Only this immutable work is cached. No authority/session/time result is.
        let started = Instant::now();
        stats.payload_digest_checks = stats.payload_digest_checks.saturating_add(1);
        let digest = outbound_payload_digest(self.record);
        stats.payload_digest_ns = stats.payload_digest_ns.saturating_add(elapsed_ns(started));
        match digest {
            Ok(digest) if digest.as_str() == hex_digest(binding.payload_sha256) => {}
            _ => return Err(OutboxDispatchError::Authority),
        }
        self.preflight(grant, stats)?;
        let proof = self
            .authorizer
            .authority()
            .enter_verified_use(token, binding)
            .map_err(|_| OutboxDispatchError::Authority)?;

        // No fallible operation between successful kernel entry and building
        // the typed entered value. Only continue_entered may finish this value,
        // and its return type cannot represent a pre-entry failure.
        let entered = EnteredSend {
            result: Err(MatrixTransportError::ResponseLost),
            claim: self.claim,
            proof: Arc::new(proof),
        };
        stats.entered_attempts = stats.entered_attempts.saturating_add(1);
        Ok(self.continue_entered(entered, binding, grant, stats).await)
    }

    async fn continue_entered(
        &self,
        mut entered: EnteredSend<'claim>,
        binding: &FinalUseBinding,
        grant: LiveGrant,
        stats: &mut OutboxDispatchStats,
    ) -> EnteredSend<'claim> {
        // All uses of ? below are confined to this inner result. In particular,
        // a clock failure or mismatched kernel proof can NEVER escape as an
        // ordinary admission error, even before the first network poll.
        let observed: Result<Result<MatrixEventId, MatrixTransportError>, OutboxDispatchError> =
            async {
                if !entered.proof.matches(binding) {
                    return Err(OutboxDispatchError::Authority);
                }
                tokio::time::timeout_at(
                    self.deadline,
                    self.store.record_outbox_entered_use(
                        entered.claim,
                        entered.proof.as_ref(),
                        binding,
                        self.clock.now_ms()?,
                    ),
                )
                .await
                .map_err(|_| OutboxDispatchError::Store)?
                .map_err(store_error)?;
                self.preflight(grant, stats)?;
                let permit = MatrixSendPermit::new(
                    Arc::clone(&entered.proof),
                    binding,
                    self.expected_identity,
                    self.record,
                )
                .map_err(|_| OutboxDispatchError::Authority)?;
                self.preflight(grant, stats)?;

                // Keep permit validation and transport-future construction
                // inside the first live-gated poll. The public transport trait
                // has no overridable authorized method, and even synchronous
                // constructor work cannot happen before this preflight.
                let mut permit = Some(permit);
                let mut send: Option<MatrixSendFuture<'_>> = None;
                let mut first_poll = true;
                let gated = poll_fn(|context| {
                    if let Err(error) = self.preflight(grant, stats) {
                        return Poll::Ready(Err(error));
                    }
                    if send.is_none() {
                        let Some(permit) = permit.take() else {
                            return Poll::Ready(Err(OutboxDispatchError::Store));
                        };
                        let future = match self
                            .transport
                            .send_authorized(self.record, permit)
                        {
                            Ok(future) => future,
                            Err(error) => return Poll::Ready(Err(error)),
                        };
                        send = Some(future);
                        // Identity/permit validation and future construction are
                        // synchronous and may consume the remaining live window.
                        if let Err(error) = self.preflight(grant, stats) {
                            return Poll::Ready(Err(error));
                        }
                    }
                    if first_poll {
                        let now_ms = match self.clock.now_ms() {
                            Ok(now_ms) => now_ms,
                            Err(error) => return Poll::Ready(Err(error)),
                        };
                        let wait_ms = now_ms.saturating_sub(self.claim.claimed_at_ms());
                        stats.claim_to_first_poll_samples =
                            stats.claim_to_first_poll_samples.saturating_add(1);
                        stats.claim_to_first_poll_ms =
                            stats.claim_to_first_poll_ms.saturating_add(wait_ms);
                        stats.claim_to_first_poll_max_ms =
                            stats.claim_to_first_poll_max_ms.max(wait_ms);
                        first_poll = false;
                    }
                    let Some(send) = send.as_mut() else {
                        return Poll::Ready(Err(OutboxDispatchError::Store));
                    };
                    stats.transport_polls = stats.transport_polls.saturating_add(1);
                    send.as_mut().poll(context).map(Ok)
                });
                tokio::select! {
                    biased;
                    _ = self.cancel.cancelled() => Err(OutboxDispatchError::Canceled),
                    result = tokio::time::timeout_at(self.deadline, gated) => {
                        result.unwrap_or(Err(OutboxDispatchError::LeaseExpired))
                    }
                }
            }
            .await;
        entered.result = match observed {
            Ok(result) => result,
            Err(OutboxDispatchError::LeaseExpired) => Err(MatrixTransportError::ReadTimeout),
            Err(_) => Err(MatrixTransportError::ResponseLost),
        };
        entered
    }

    fn preflight(
        &self,
        grant: LiveGrant,
        stats: &mut OutboxDispatchStats,
    ) -> Result<(), OutboxDispatchError> {
        let started = Instant::now();
        stats.dynamic_checks = stats.dynamic_checks.saturating_add(1);
        let result = self.check_live_authority(grant);
        stats.dynamic_check_ns = stats.dynamic_check_ns.saturating_add(elapsed_ns(started));
        result
    }

    fn check_live_authority(&self, grant: LiveGrant) -> Result<(), OutboxDispatchError> {
        self.require_live_window(grant.expires_at_ms)?;
        self.authorizer
            .refresh_revocations()
            .map_err(authority_error)?;
        let head = self
            .authorizer
            .authority()
            .revocation_head()
            .map_err(|_| OutboxDispatchError::Authority)?;
        if head.authority_epoch != grant.epoch || head.revision != grant.revision {
            return Err(OutboxDispatchError::Authority);
        }
        match self.transport.identity() {
            Ok(identity) if &identity == self.expected_identity => {}
            _ => return Err(OutboxDispatchError::TransportIdentity),
        }
        // Synchronous revocation refresh and identity lookup may consume time.
        self.require_live_window(grant.expires_at_ms)
    }

    fn require_live_window(&self, grant_expires_at_ms: u64) -> Result<(), OutboxDispatchError> {
        if self.cancel.is_cancelled() {
            return Err(OutboxDispatchError::Canceled);
        }
        if Instant::now() >= self.deadline {
            return Err(OutboxDispatchError::LeaseExpired);
        }
        let now_ms = effective_grant_now(self.clock.now_ms()?, system_time_ms()?);
        if !grant_is_live(now_ms, grant_expires_at_ms) {
            return Err(OutboxDispatchError::Authority);
        }
        Ok(())
    }
}

fn elapsed_ns(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX)
}

fn effective_grant_now(monotonic_now_ms: u64, wall_now_ms: u64) -> u64 {
    monotonic_now_ms.max(wall_now_ms)
}

fn grant_is_live(now_ms: u64, expires_at_ms: u64) -> bool {
    now_ms < expires_at_ms
}

#[cfg(test)]
mod tests {
    use super::effective_grant_now;
    use super::grant_is_live;

    #[test]
    fn grant_expiry_is_a_closed_entry_boundary() {
        assert!(grant_is_live(41, 42));
        assert!(!grant_is_live(42, 42));
        assert!(!grant_is_live(43, 42));
    }

    #[test]
    fn stale_caller_epoch_cannot_extend_a_grant() {
        assert_eq!(effective_grant_now(10, 50), 50);
        assert_eq!(effective_grant_now(50, 10), 50);
    }
}
