//! Original Evaluator command serving. Only one shared host admission exists;
//! cold state and any attempted dispatch never regain execution authority.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;

use super::Error;
use super::OriginalCellEvaluationHostV1;
use super::now;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellEvaluationReceiptErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

impl OriginalCellEvaluationHostV1 {
    /// Original connected stream and held consumer pidfd only. The original
    /// 30-second frame and 300-second session bounds are not extended. This
    /// service does not add a deeply nested 500-ms evidence endpoint.
    pub async fn serve_commands(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
            )?;
            self.serve_channel(&mut channel)
        }).await.map_err(|_| Error::CommitUncertain)?
    }

    fn serve_channel(&self, channel: &mut HostAuthorityPeerChannel) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.command_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? { return Ok(request_id - 1); }
        }
        Err(Error::Unavailable)
    }

    fn command_response(&self, bytes: &[u8], request_id: u64) -> Result<Vec<u8>, Error> {
        if bytes.len() > 16_384 { return Err(Error::Binding("bounded Evaluation request")); }
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, request_id)?;
        self.context.authenticate(now()?)?;
        let outcome = match request.action {
            wire::Action::Execute => {
                if self.execution_requested.swap(true, Ordering::AcqRel) {
                    wire::Outcome::ReadbackRequired
                } else if now()? >= self.context.training.request.envelope.expiry_unix_seconds {
                    wire::Outcome::Expired
                } else {
                    self.original_response(wire::Action::Execute)?
                }
            }
            wire::Action::Readback => self.original_response(wire::Action::Readback)?,
        };
        // No owner lock is held while encoding or writing a response. Every
        // successful result was read from the same original panel and journal.
        self.context.authenticate(now()?)?;
        let encoded = serde_json::to_vec(&wire::Response::new(request, outcome))?;
        if encoded.len() > 16_384 { return Err(Error::Binding("bounded Evaluation response")); }
        Ok(encoded)
    }

    fn original_response(&self, action: wire::Action) -> Result<wire::Outcome, Error> {
        let completed = {
            let mut owners = match self.owners.try_lock() {
                Ok(owners) => owners,
                Err(_) => return Ok(wire::Outcome::Busy),
            };
            self.runtime.block_on(owners.completion(&self.context, action))
        };
        match completed {
            Ok(original) => wire::encode_completed(&self.context, original, now()?),
            Err(error) => Ok(original_state(error)),
        }
    }
}

fn original_state(error: Error) -> wire::Outcome {
    use LearningOriginalOwnerErrorV1 as Journal;
    use OriginalCellEvaluationReceiptErrorV1 as Receipt;
    use ProductEvaluationExecutionStoreErrorV1 as Store;
    match error {
        Error::Receipt(Receipt::Owner(Journal::Pending)) => wire::Outcome::Pending,
        Error::Receipt(Receipt::Owner(Journal::Store(Store::Missing))) => wire::Outcome::Missing,
        Error::DeadlineExceeded => wire::Outcome::Expired,
        // Missing upstream B/retention/Qualification is not a statement about
        // this Evaluation journal's own Missing or Pending state.
        Error::Panel(_) | Error::Qualification(_) | Error::PredecessorUnavailable =>
            wire::Outcome::PredecessorUnavailable,
        _ => wire::Outcome::Uncertain,
    }
}
