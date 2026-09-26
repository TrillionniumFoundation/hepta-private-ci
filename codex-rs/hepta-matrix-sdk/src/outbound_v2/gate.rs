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
        let mut token = Some(token);
        let mut proof = None;
        let mut send: Option<MatrixSendFuture<'_>> = None;
        let observed = {
            // The final check runs in the SAME poll as adapter entry. Merely
            // constructing or awaiting this future does not consume authority.
            let gated = poll_fn(|context| {
                if send.is_none() {
                    if self.cancel.is_cancelled() {
                        return Poll::Ready(Err(OutboxDispatchError::Canceled));
                    }
                    if Instant::now() >= self.deadline {
                        return Poll::Ready(Err(OutboxDispatchError::LeaseExpired));
                    }
                    if self.authorizer.refresh_revocations().is_err() {
                        return Poll::Ready(Err(OutboxDispatchError::Authority));
                    }
                    match self.transport.identity() {
                        Ok(identity) if &identity == self.expected_identity => {}
                        _ => return Poll::Ready(Err(OutboxDispatchError::TransportIdentity)),
                    }
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
                    // Refresh and the protected-clock check may do synchronous
                    // I/O. They do not renew the durable claim's deadline.
                    if self.cancel.is_cancelled() {
                        return Poll::Ready(Err(OutboxDispatchError::Canceled));
                    }
                    if Instant::now() >= self.deadline {
                        return Poll::Ready(Err(OutboxDispatchError::LeaseExpired));
                    }
                    proof = Some(entered);
                    send = Some(self.transport.send(self.record));
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
                    // Cancellation after entry cannot prove a negative effect.
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
