//! Independent positive Version purpose. One request may perform one original
//! prepare/issuer/publish invocation; readback never prepares or repairs it.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::sync::atomic::AtomicBool;
use std::time::Duration;
use std::time::Instant;
use codex_hepta_contracts::HostIssuerTransportError;
use super::super::Error;
use super::super::Origin;
use super::super::wire;
use super::OriginalCircuitModelVersionHostV1 as Host;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCircuitCandidateLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitCandidateLearningReadOwnerV1 as ReadOwner;
use crate::OriginalCircuitModelSelectionCommandReceiptV1 as Selection;
use crate::OriginalCircuitModelPublicationContextV1 as PublicationContext;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl Host {
    pub async fn serve_commands(
        self: Arc<Self>, stream: UnixStream, consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32, original_consumer_pidfd: OwnedFd,
        timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        let lifetime = self.remaining_lifetime(lifetime)?;
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        let queued = QueuedService(Arc::new(AtomicBool::new(/*v*/ false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            for request_id in 1..=128_u64 {
                if cancelled.load(Ordering::Acquire) { return Err(Error::Cancelled); }
                self.require_lifetime()?;
                if !channel.exchange(|bytes| self.command_response(bytes, request_id, &cancelled)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest))?
                {
                    return Ok(request_id - 1);
                }
            }
            Err(Error::Unavailable)
        }).await.map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }

    fn command_response(&self, bytes: &[u8], request_id: u64, cancelled: &AtomicBool) -> Result<Vec<u8>, Error> {
        require_not_cancelled(cancelled)?;
        self.require_lifetime()?;
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded positive Version command"));
        }
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_initial(self.initial_binding,
            &self.predecessors.material.initial.request.operation_id, request_id)?;
        let actual = match request.action {
            wire::Action::Publish => self.runtime.block_on(self.publish_original(&request, cancelled)),
            wire::Action::Readback => {
                self.requested.store(/*val*/ true, Ordering::Release);
                self.runtime.block_on(self.read_original(Some(&request)))
            }
        };
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        let result = match actual {
            Ok(read) => {
                // Only the finished operation can produce this response.
                let context = {
                    let state = self.state.try_lock().map_err(|_| Error::Busy)?;
                    Arc::clone(state.context.as_ref().ok_or(Error::CommitUncertain)?)
                };
                request.require_context(&context)?;
                wire::Outcome::from_original(read)
            }
            Err(Error::Busy) => wire::Outcome::Busy,
            Err(Error::ReadbackRequired) => wire::Outcome::ReadbackRequired,
            Err(Error::FinalUseDenied) => wire::Outcome::FinalUseDenied,
            Err(Error::Unavailable) => wire::Outcome::Unavailable,
            Err(_) => wire::Outcome::Uncertain,
        };
        self.require_lifetime()?;
        let encoded = serde_json::to_vec(&wire::Response { request, result })?;
        if encoded.is_empty() || encoded.len() > 16_384 {
            return Err(Error::Binding("bounded positive Version response"));
        }
        Ok(encoded)
    }

    /// Original ordinary deployment entry. Root's command does not contain
    /// C's authenticated RunStart; the unchanged runtime still requires it.
    pub async fn serve_original_ordinary(
        self: Arc<Self>, stream: UnixStream, consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32, original_consumer_pidfd: OwnedFd,
        timeout: Duration, lifetime: Duration, arg0_paths: codex_arg0::Arg0DispatchPaths,
    ) -> Result<u64, Error> {
        let (served, ()) = tokio::try_join!(
            Arc::clone(&self).serve_commands(stream, consumer, consumer_uid,
                original_consumer_pidfd, timeout, lifetime),
            Arc::clone(&self).run_original_c(arg0_paths),
        )?;
        Ok(served)
    }

    pub async fn run_original_c(
        self: Arc<Self>, arg0_paths: codex_arg0::Arg0DispatchPaths,
    ) -> Result<(), Error> {
        if self.origin != Origin::Fresh || self.runtime_started.swap(/*val*/ true, Ordering::AcqRel) {
            return Err(Error::ReadbackRequired);
        }
        self.wait_installed().await?;
        let owner = Arc::clone(&self);
        let queued = QueuedService(Arc::new(AtomicBool::new(/*v*/ false)));
        let cancelled = Arc::clone(&queued.0);
        let config = tokio::task::spawn_blocking(move || {
            require_not_cancelled(&cancelled)?;
            let current = owner.runtime.block_on(owner.read_original(None))?;
            if current.publication().is_none() { return Err(Error::CommitUncertain); }
            require_not_cancelled(&cancelled).map_err(|_| Error::CommitUncertain)?;
            let mut state = owner.state.try_lock().map_err(|_| Error::Busy)?;
            let context = state.context.as_ref().ok_or(Error::CommitUncertain)?;
            PublicationContext::authenticate(context.as_ref(), super::super::now()?, /*new_work*/ true)?;
            if state.intent != Some(current.intent_digest()) {
                return Err(Error::CommitUncertain);
            }
            state.config.take().ok_or(Error::ReadbackRequired)
        }).await.map_err(|_| Error::CommitUncertain)??;
        drop(queued);
        crate::run(config, arg0_paths).await.map_err(Error::Owner)
    }

    async fn wait_installed(&self) -> Result<(), Error> {
        loop {
            let changed = self.installed.notified();
            self.require_lifetime()?;
            match self.outcome.load(Ordering::Acquire) {
                4 => return Ok(()),
                2 => return Err(Error::FinalUseDenied),
                3 => return Err(Error::CommitUncertain),
                _ => {}
            }
            tokio::select! {
                _ = changed => {},
                _ = tokio::time::sleep(Duration::from_millis(100)) => {},
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(self.end)) =>
                    return Err(Error::Unavailable),
            }
        }
    }

    /// Pin the original Selector's read socket before waiting for publication.
    /// This is only the physical published-owner purpose; S separately brackets
    /// it with its actual full original Model/E operation.
    pub async fn serve_original_selection_readback(
        self: Arc<Self>, stream: UnixStream, consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32, original_consumer_pidfd: OwnedFd,
        timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        if timeout.is_zero() || timeout > Duration::from_millis(500) {
            return Err(Error::Binding("original published read exchange bound"));
        }
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        let lifetime = self.remaining_lifetime(lifetime)?;
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        self.wait_installed().await?;
        let queued = QueuedService(Arc::new(AtomicBool::new(/*v*/ false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            require_not_cancelled(&cancelled)?;
            channel.check_peer_lifetime()?;
            let (installed, context) = {
                let state = self.state.try_lock().map_err(|_| Error::Busy)?;
                (state.installed.clone().ok_or(Error::CommitUncertain)?,
                    Arc::clone(state.context.as_ref().ok_or(Error::CommitUncertain)?))
            };
            let context = ReadContext::from_original_model(context.duplicate_response_pin())?;
            let reader = ReadOwner::from_original_owners(installed.cell,
                installed.source.as_ref().clone(), installed.identity, context)?;
            ReadOwner::serve_original_candidate_channel(&reader, &mut channel).map_err(Error::Published)
        }).await.map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }

    /// The opaque actual S result extends this installed Model pin to C. The
    /// original C observer independently rereads S/T; this endpoint only reads
    /// the held C Cell/Source, never executes or signs C.
    pub async fn serve_original_next_use_readback(
        self: Arc<Self>, selection: Selection, stream: UnixStream,
        consumer: AgentdRootAuthorityPeer, consumer_uid: u32,
        original_consumer_pidfd: OwnedFd, timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        if timeout.is_zero() || timeout > Duration::from_millis(500) {
            return Err(Error::Binding("original published C exchange bound"));
        }
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        let lifetime = self.remaining_lifetime(lifetime)?;
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        let queued = QueuedService(Arc::new(AtomicBool::new(/*v*/ false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if cancelled.load(Ordering::Acquire) { return Err(Error::Cancelled); }
            channel.check_peer_lifetime()?;
            let reader = self.original_next_use_reader(&selection)?;
            ReadOwner::serve_original_next_use_channel(&reader, &mut channel).map_err(Error::Published)
        }).await.map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }
    pub async fn serve_original_completion_readiness(
        self: Arc<Self>, selection: Selection, stream: UnixStream,
        consumer: AgentdRootAuthorityPeer, consumer_uid: u32,
        original_consumer_pidfd: OwnedFd, timeout: Duration, lifetime: Duration,
    ) -> Result<u64, Error> {
        if timeout.is_zero() || timeout > Duration::from_millis(500) {
            return Err(Error::Binding("original published C exchange bound"));
        }
        let permit = Arc::clone(&self.connections).try_acquire_owned().map_err(|_| Error::Busy)?;
        let lifetime = self.remaining_lifetime(lifetime)?;
        let mut channel = original_owner_command_channel_v1(
            stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime,
        )?;
        let queued = QueuedService(Arc::new(AtomicBool::new(/*v*/ false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if cancelled.load(Ordering::Acquire) { return Err(Error::Cancelled); }
            channel.check_peer_lifetime()?;
            let reader = self.original_next_use_reader(&selection)?;
            ReadOwner::serve_original_readiness_channel(&reader, &mut channel).map_err(Error::Published)
        }).await.map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }
    fn original_next_use_reader(
        &self, selection: &Selection,
    ) -> Result<ReadOwner<codex_hepta_neuron::FileAnchorWitnessStore, codex_hepta_neuron::FileAnchorWitnessStore>, Error> {
        self.require_lifetime()?;
        if self.outcome.load(Ordering::Acquire) != 4 { return Err(Error::ReadbackRequired); }
        let (installed, original) = {
            let state = self.state.try_lock().map_err(|_| Error::Busy)?;
            (state.installed.clone().ok_or(Error::CommitUncertain)?,
                Arc::clone(state.context.as_ref().ok_or(Error::CommitUncertain)?))
        };
        let context = ReadContext::from_original_selection(selection)?;
        let current = super::super::now()?;
        if context.model() != original.model()
            || PublicationContext::original_version_binding(context.model_publication_context(), current)?
                != PublicationContext::original_version_binding(original.as_ref(), current)?
        {
            return Err(Error::Binding("same actual selected Model for C reader"));
        }
        ReadOwner::from_original_owners(installed.cell, installed.source.as_ref().clone(),
            installed.identity, context).map_err(Error::Published)
    }

    fn remaining_lifetime(&self, requested: Duration) -> Result<Duration, Error> {
        if requested.is_zero() || requested > Duration::from_secs(300) {
            return Err(Error::Binding("original Version session bound"));
        }
        Ok(requested.min(self.end.checked_duration_since(Instant::now()).ok_or(Error::Unavailable)?))
    }
}

struct QueuedService(Arc<AtomicBool>);
impl Drop for QueuedService {
    fn drop(&mut self) { self.0.store(/*val*/ true, Ordering::Release); }
}

fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) { return Err(Error::Cancelled); }
    Ok(())
}
