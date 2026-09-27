use std::future::poll_fn;
use std::sync::Arc;
use std::task::Poll;

use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use tokio::time::Instant;

use super::*;
use crate::content::outbound_payload_digest;

pub(super) struct FinalSendGate<'a, T: ?Sized, A: ?Sized> {
    pub(super) store: &'a MatrixDurableStore,
    pub(super) claim: &'a MatrixFencedOutboxClaim,
    pub(super) clock: &'a DispatchClock,
    pub(super) transport: &'a T,
    pub(super) authorizer: &'a A,
    pub(super) expected_identity: &'a MatrixOutboundIdentity,
    pub(super) record: &'a OutboxRecord,
    pub(super) cancel: &'a CancellationToken,
    pub(super) deadline: Instant,
}

pub(super) struct EnteredSend {
    pub(super) result: Result<MatrixEventId, MatrixTransportError>,
    // A real kernel proof remains alive through outcome processing. The only
    // additional reference belongs to the single-use, non-cloneable permit.
    pub(super) _proof: Arc<EnteredUseToken>,
}

impl EnteredSend {
    fn indeterminate(proof: Arc<EnteredUseToken>) -> Self {
        Self {
            // Once the kernel final-use boundary has been crossed, a later
            // persistence, freshness or adapter-construction fault must never
            // be returned as a pre-entry failure. Conservatively preserve the
            // same transaction as an unknown effect and reconcile it.
            result: Err(MatrixTransportError::ResponseLost),
            _proof: proof,
        }
    }
}

impl<T: MatrixOutboundTransport + ?Sized, A: MatrixOutboundAuthorizer + ?Sized>
    FinalSendGate<'_, T, A>
{
    pub(super) async fn enter_verified_use(
        &self,
        token: VerifiedUseToken,
        binding: &FinalUseBinding,
    ) -> Result<EnteredSend, OutboxDispatchError> {
        let claimed_epoch = token.claimed_authority_epoch();
        let claimed_revision = token.claimed_revocation_revision();
        // The durable authority claim is the only source for the grant's
        // absolute expiry after the kernel token becomes non-serializable.
        // Re-read the exact attempt before entry so an expired or mismatched
        // persisted claim cannot rely only on the outbox lease deadline.
        let authority_claim = self
            .store
            .dispatch_authority_claim(&self.record.stable_txn_id, self.record.attempts)
            .await
            .map_err(store_error)?
            .ok_or(OutboxDispatchError::Store)?;
        if authority_claim.authority_epoch != claimed_epoch
            || authority_claim.revocation_revision != claimed_revision
            || authority_claim.attempt != self.record.attempts
            || authority_claim.expires_at_ms <= authority_claim.claimed_at_ms
        {
            return Err(OutboxDispatchError::Authority);
        }
        let grant_expires_at_ms = authority_claim.expires_at_ms;
        self.preflight(
            claimed_epoch,
            claimed_revision,
            grant_expires_at_ms,
            binding,
        )?;

        let entered = self
            .authorizer
            .authority()
            .enter_verified_use(token, binding)
            .map_err(|_| OutboxDispatchError::Authority)?;
        if !entered.matches(binding) {
            return Err(OutboxDispatchError::Authority);
        }
        let proof = Arc::new(entered);

        // Crossing the kernel check is a monotone audit boundary. The network
        // has not necessarily been entered yet, but any result after this line
        // must carry the proof back to the caller so the claim cannot be
        // released as a pre-entry cancel/revoke. A timeout may also mean the
        // durable entered-use write committed while its acknowledgement was
        // lost, so that path is necessarily indeterminate.
        let persisted = tokio::time::timeout_at(
            self.deadline,
            self.store.record_outbox_entered_use(
                self.claim,
                proof.as_ref(),
                binding,
                self.clock.now_ms()?,
            ),
        )
        .await;
        match persisted {
            Ok(Ok(())) => {}
            Ok(Err(_)) | Err(_) => return Ok(EnteredSend::indeterminate(proof)),
        }
        if self
            .preflight(
                claimed_epoch,
                claimed_revision,
                grant_expires_at_ms,
                binding,
            )
            .is_err()
        {
            return Ok(EnteredSend::indeterminate(proof));
        }

        let permit = match MatrixSendPermit::new(
            Arc::clone(&proof),
            binding,
            self.expected_identity,
            self.record,
        ) {
            Ok(permit) => permit,
            Err(_) => return Ok(EnteredSend::indeterminate(proof)),
        };
        if self
            .preflight(
                claimed_epoch,
                claimed_revision,
                grant_expires_at_ms,
                binding,
            )
            .is_err()
        {
            return Ok(EnteredSend::indeterminate(proof));
        }
        let mut send = self.transport.send_authorized(self.record, permit);

        // Recheck every continuation poll: DNS, TLS and encryption may yield
        // before the transport ever writes its request. Once the future exists,
        // dropping it cannot prove that no bytes crossed the network boundary,
        // so every gate stop is returned as an indeterminate transport result.
        let gated = poll_fn(|context| {
            if self
                .preflight(
                    claimed_epoch,
                    claimed_revision,
                    grant_expires_at_ms,
                    binding,
                )
                .is_err()
            {
                return Poll::Ready(Err(OutboxDispatchError::Authority));
            }
            send.as_mut().poll(context).map(Ok)
        });
        let observed = tokio::select! {
            biased;
            _ = self.cancel.cancelled() => Err(OutboxDispatchError::Canceled),
            result = tokio::time::timeout_at(self.deadline, gated) => {
                result.unwrap_or(Err(OutboxDispatchError::LeaseExpired))
            }
        };
        Ok(EnteredSend {
            result: match observed {
                Ok(result) => result,
                Err(OutboxDispatchError::LeaseExpired) => Err(MatrixTransportError::ReadTimeout),
                Err(_) => Err(MatrixTransportError::ResponseLost),
            },
            _proof: proof,
        })
    }

    fn preflight(
        &self,
        claimed_epoch: u64,
        claimed_revision: u64,
        grant_expires_at_ms: u64,
        binding: &FinalUseBinding,
    ) -> Result<(), OutboxDispatchError> {
        if self.cancel.is_cancelled() {
            return Err(OutboxDispatchError::Canceled);
        }
        if Instant::now() >= self.deadline {
            return Err(OutboxDispatchError::LeaseExpired);
        }
        if !grant_is_live(self.clock.now_ms()?, grant_expires_at_ms) {
            return Err(OutboxDispatchError::Authority);
        }
        self.authorizer
            .refresh_revocations()
            .map_err(authority_error)?;
        let head = self
            .authorizer
            .authority()
            .revocation_head()
            .map_err(|_| OutboxDispatchError::Authority)?;
        if head.authority_epoch != claimed_epoch || head.revision != claimed_revision {
            return Err(OutboxDispatchError::Authority);
        }
        match self.transport.identity() {
            Ok(identity) if &identity == self.expected_identity => {}
            _ => return Err(OutboxDispatchError::TransportIdentity),
        }
        match outbound_payload_digest(self.record) {
            Ok(digest) if digest.as_str() == hex_digest(binding.payload_sha256) => {}
            _ => return Err(OutboxDispatchError::Authority),
        }
        Ok(())
    }
}

fn grant_is_live(now_ms: u64, expires_at_ms: u64) -> bool {
    now_ms < expires_at_ms
}

#[cfg(test)]
mod tests {
    use super::grant_is_live;

    #[test]
    fn grant_expiry_is_a_closed_entry_boundary() {
        assert!(grant_is_live(41, 42));
        assert!(!grant_is_live(42, 42));
        assert!(!grant_is_live(43, 42));
    }
}
