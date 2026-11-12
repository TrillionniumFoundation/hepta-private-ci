//! Original Model purpose only; old Training/Evidence protocols are untouched.
//! All connections retain the one original host state and bounded framing.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use super::*;
use super::super::super::model_command::wire;
use crate::AgentdRootAuthorityPeer;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl OriginalCellQ24ModelCommandHostV1 {
    pub async fn serve_commands(
        self: Arc<Self>, stream: UnixStream, consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32, original_consumer_pidfd: OwnedFd, timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        // Bind the original descriptor/pidfd and absolute end before this
        // service can queue. The worker cannot restart that original budget.
        let mut channel = original_owner_command_channel_v1(stream, consumer, consumer_uid,
            original_consumer_pidfd, timeout, lifetime)?;
        let queued = QueuedModelServiceV1::new();
        let cancellation = Arc::clone(&queued.cancelled);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            // A service dropped while it was queued never enters the original
            // frame reader. Cancellation after dispatch remains uncertain.
            if cancellation.load(Ordering::Acquire) { return Err(Error::Cancelled); }
            channel.check_peer_lifetime()?;
            if cancellation.load(Ordering::Acquire) { return Err(Error::Cancelled); }
            self.serve_original_channel(&mut channel)
        }).await.map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }
    fn serve_original_channel(&self, channel: &mut HostAuthorityPeerChannel) -> Result<u64, Error> {
        for nonce in 1..=128 {
            if !channel.exchange(|bytes| {
                self.command_response(bytes, nonce).map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? { return Ok(nonce - 1); }
        }
        Err(Error::Unavailable)
    }
    fn command_response(&self, bytes: &[u8], nonce: u64) -> Result<Vec<u8>, Error> {
        if bytes.len() > 16_384 { return Err(Error::Binding("bounded original Model command")); }
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_initial(&self.bootstrap.config.material, nonce)?;
        let outcome = match self.original_response(&request) {
            Ok(outcome) => outcome,
            Err(Error::Busy) => wire::Outcome::Busy,
            Err(Error::ReadbackRequired) => wire::Outcome::ReadbackRequired,
            Err(Error::Ineligible) => wire::Outcome::Ineligible,
            Err(Error::DeadlineExceeded) => wire::Outcome::Expired,
            Err(Error::Unavailable) => wire::Outcome::Unavailable,
            // Never turn a transport, CURRENT, source or owner error into a
            // proven missing Model. The original operation remains unresolved.
            Err(_) => wire::Outcome::Uncertain,
        };
        let response = serde_json::to_vec(&wire::Response { request, outcome })?;
        if response.len() > 16_384 { return Err(Error::Binding("bounded original Model response")); }
        Ok(response)
    }
}

struct QueuedModelServiceV1 { cancelled: Arc<AtomicBool> }
impl QueuedModelServiceV1 {
    fn new() -> Self { Self { cancelled: Arc::new(AtomicBool::new(false)) } }
}
impl Drop for QueuedModelServiceV1 {
    fn drop(&mut self) { self.cancelled.store(true, Ordering::Release); }
}
