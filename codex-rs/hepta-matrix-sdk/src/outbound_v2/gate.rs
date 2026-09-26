use std::future::poll_fn;
use std::task::Poll;

use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use tokio::time::Instant;

use super::*;

pub(super) struct FinalSendGate<'a, T: ?Sized, A: ?Sized> {
    pub(super) transport: &'a T,
    pub(super) authorizer: &'a A,
    pub(super) expected_identity: &'a MatrixOutboundIdentity,
    pub(super) record: &'a OutboxRecord,
    pub(super) cancel: &'a CancellationToken,
    pub(super) deadline: Instant,
}

pub(super) struct EnteredSend {
    pub(super) result: Result<MatrixEventId, MatrixTransportError>,
    // This is real, non-constructible kernel entry evidence, not a boolean
    // supplied by a caller. It stays alive until the outcome is processed.
    pub(super) _proof: EnteredUseToken,
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
        let mut token = Some(token);
        let mut proof = None;
        let mut send: Option<MatrixSendFuture<'_>> = None;
        let observed = {
            // Recheck before EVERY adapter poll, including a continuation after
            // Pending. A transport may do DNS, TLS, encryption or session work
            // before writing its request; its first poll is not a network write.
            // The kernel entry proof is consumed only once, never renewed here.
            let gated = poll_fn(|context| {
                if self.cancel.is_cancelled() {
                    return Poll::Ready(Err(OutboxDispatchError::Canceled));
                }
                if Instant::now() >= self.deadline {
                    return Poll::Ready(Err(OutboxDispatchError::LeaseExpired));
                }
                if self.authorizer.refresh_revocations().is_err() {
                    return Poll::Ready(Err(OutboxDispatchError::Authority));
                }
                let head = match self.authorizer.authority().revocation_head() {
                    Ok(head) => head,
                    Err(_) => return Poll::Ready(Err(OutboxDispatchError::Authority)),
                };
                // Fail closed on any head advance. Comparing the revocation
                // identity, rather than a state digest including claimed nonces,
                // avoids canceling an unrelated simultaneous nonce admission.
                if head.authority_epoch != claimed_epoch || head.revision != claimed_revision {
                    return Poll::Ready(Err(OutboxDispatchError::Authority));
                }
                match self.transport.identity() {
                    Ok(identity) if &identity == self.expected_identity => {}
                    _ => return Poll::Ready(Err(OutboxDispatchError::TransportIdentity)),
                }
                if send.is_none() {
                    let Some(token) = token.take() else {
                        return Poll::Ready(Err(OutboxDispatchError::Authority));
                    };
                    let entered = match self
                        .authorizer
                        .authority()
                        .enter_verified_use(token, binding)
                    {
                        Ok(entered) if entered.matches(binding) => entered,
                        _ => return Poll::Ready(Err(OutboxDispatchError::Authority)),
                    };
                    // Synchronous authority work does not renew the lease.
                    if self.cancel.is_cancelled() {
                        return Poll::Ready(Err(OutboxDispatchError::Canceled));
                    }
                    if Instant::now() >= self.deadline {
                        return Poll::Ready(Err(OutboxDispatchError::LeaseExpired));
                    }
                    proof = Some(entered);
                    send = Some(self.transport.send(self.record));
                }
                // Refresh/identity reads may block even on subsequent polls.
                if self.cancel.is_cancelled() {
                    return Poll::Ready(Err(OutboxDispatchError::Canceled));
                }
                if Instant::now() >= self.deadline {
                    return Poll::Ready(Err(OutboxDispatchError::LeaseExpired));
                }
                match send.as_mut() {
                    Some(send) => send.as_mut().poll(context).map(Ok),
                    None => Poll::Ready(Err(OutboxDispatchError::Invalid)),
                }
            });
            tokio::select! {
                biased;
                _ = self.cancel.cancelled() => Err(OutboxDispatchError::Canceled),
                result = tokio::time::timeout_at(self.deadline, gated) => {
                    result.unwrap_or(Err(OutboxDispatchError::LeaseExpired))
                }
            }
        };
        match proof {
            Some(proof) => Ok(EnteredSend {
                result: match observed {
                    Ok(result) => result,
                    Err(OutboxDispatchError::LeaseExpired) => Err(MatrixTransportError::ReadTimeout),
                    // Stopping polling cannot undo a request already written.
                    // Revocation, identity loss and cancellation after entry all
                    // preserve uncertainty and the existing transaction identity.
                    Err(_) => Err(MatrixTransportError::ResponseLost),
                },
                _proof: proof,
            }),
            None => match observed {
                Err(error) => Err(error),
                Ok(_) => Err(OutboxDispatchError::Invalid),
            },
        }
    }
}
