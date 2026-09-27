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
            // Recheck every continuation poll: DNS, TLS and encryption may
            // yield before the transport ever writes its request.
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
                if head.authority_epoch != claimed_epoch || head.revision != claimed_revision {
                    return Poll::Ready(Err(OutboxDispatchError::Authority));
                }
                match self.transport.identity() {
                    Ok(identity) if &identity == self.expected_identity => {}
                    _ => return Poll::Ready(Err(OutboxDispatchError::TransportIdentity)),
                }
                match outbound_payload_digest(self.record) {
                    Ok(digest) if digest.as_str() == hex_digest(binding.payload_sha256) => {}
                    _ => return Poll::Ready(Err(OutboxDispatchError::Authority)),
                }
                if send.is_none() {
                    let Some(token) = token.take() else {
                        return Poll::Ready(Err(OutboxDispatchError::Authority));
                    };
                    let entered = match self.authorizer.authority().enter_verified_use(token, binding) {
                        Ok(entered) if entered.matches(binding) => Arc::new(entered),
                        _ => return Poll::Ready(Err(OutboxDispatchError::Authority)),
                    };
                    let permit = match MatrixSendPermit::new(
                        Arc::clone(&entered), binding, self.expected_identity, self.record,
                    ) {
                        Ok(permit) => permit,
                        Err(_) => return Poll::Ready(Err(OutboxDispatchError::Authority)),
                    };
                    if self.cancel.is_cancelled() {
                        return Poll::Ready(Err(OutboxDispatchError::Canceled));
                    }
                    if Instant::now() >= self.deadline {
                        return Poll::Ready(Err(OutboxDispatchError::LeaseExpired));
                    }
                    proof = Some(entered);
                    send = Some(self.transport.send_authorized(self.record, permit));
                }
                // Synchronous refresh, digest work or future construction must
                // never extend the lease or delay cancellation past this poll.
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
                    // Dropping an entered future cannot undo already-written bytes.
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
