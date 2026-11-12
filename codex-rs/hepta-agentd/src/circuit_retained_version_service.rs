//! Fixed-purpose command serving. The Root frame carries only correlation
//! and Prepare/Readback; FinalUse, files and C task inputs stay in this host.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostIssuerTransportError;

use super::super::super::context::PublicationAccess;
use super::super::Error;
use super::super::RetainedVersionOriginV1;
use super::super::RetainedVersionPurposeV1;
use super::super::wire;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionFinalUseOutcomeV1;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl OriginalCircuitRetainedVersionHostV1 {
    pub async fn serve_commands(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        self.require_lifetime()?;
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let lifetime = self.remaining_lifetime(lifetime)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream,
                consumer,
                consumer_uid,
                original_consumer_pidfd,
                timeout,
                lifetime,
            )?;
            for request_id in 1..=128_u64 {
                self.require_lifetime()?;
                let mut failure = None;
                let exchanged = channel.exchange(|bytes| {
                    self.command_response(bytes, request_id).map_err(|error| {
                        failure = Some(error);
                        HostIssuerTransportError::InvalidRequest
                    })
                });
                match exchanged {
                    Ok(true) => {}
                    Ok(false) => return Ok(request_id - 1),
                    Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
                }
            }
            Err(Error::Unavailable)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    /// Original deployment entry: serve this purpose and, only after separate
    /// successful FinalUse, enter the existing ordinary C runtime. No protocol
    /// frame starts C or supplies its RunStart/deployment permission.
    pub async fn serve_original_ordinary(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
        arg0_paths: codex_arg0::Arg0DispatchPaths,
    ) -> Result<u64, Error> {
        let (served, (), ()) = tokio::try_join!(
            Arc::clone(&self).serve_commands(
                stream,
                consumer,
                consumer_uid,
                original_consumer_pidfd,
                timeout,
                lifetime,
            ),
            OriginalCircuitRetainedVersionHostV1::run_original_c(Arc::clone(&self), arg0_paths),
            OriginalCircuitRetainedVersionHostV1::serve_original_final_use(Arc::clone(&self)),
        )?;
        Ok(served)
    }

    /// Selection's already delivered original read socket is held from now,
    /// even though T/publication arrive later. No new deadline is created at
    /// readiness. The existing read protocol stays <=500 ms and read-only.
    pub async fn serve_original_selection_readback(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        if timeout.is_zero() || timeout > Duration::from_millis(500) {
            return Err(Error::Binding("same original published read bound"));
        }
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let lifetime = self.remaining_lifetime(lifetime)?;
        let channel = original_owner_command_channel_v1(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )?;
        self.serve_original_selection_channel(channel, permit).await
    }

    async fn serve_original_selection_channel(
        self: Arc<Self>,
        mut channel: codex_hepta_contracts::HostAuthorityPeerChannel,
        permit: tokio::sync::OwnedSemaphorePermit,
    ) -> Result<u64, Error> {
        loop {
            let changed = self.installed.notified();
            self.require_lifetime()?;
            channel.check_peer_lifetime()?;
            let reader = {
                match self.state.try_lock() {
                    Ok(state) if self.original_final_use_outcome() == RetainedVersionFinalUseOutcomeV1::Published => {
                        if let Some(reader) = state.selection_reader.as_ref() {
                            // Admission of this connection still requires the
                            // held full Material/D/T/B windows. A task reader's
                            // own T/B pins do not replace the Material freeze.
                            state.cut.as_ref().ok_or(Error::Unavailable)?
                                .require_fresh(super::super::now()?, PublicationAccess::Readback)?;
                            Some(Arc::clone(reader))
                        } else {
                            None
                        }
                    },
                    Ok(_) => None,
                    Err(std::sync::TryLockError::WouldBlock) => None,
                    Err(std::sync::TryLockError::Poisoned(_)) => return Err(Error::Unavailable),
                }
            };
            if let Some(reader) = reader {
                let purpose = self.purpose;
                return tokio::task::spawn_blocking(move || {
                    let _permit = permit;
                    match purpose {
                        RetainedVersionPurposeV1::TrainingNoUpdate =>
                            OriginalCircuitLearningReadOwnerV1::serve_original_retained_channel(reader.as_ref(), &mut channel),
                        RetainedVersionPurposeV1::EvaluatedNoUpdate =>
                            OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_retained_channel(reader.as_ref(), &mut channel),
                    }
                    .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))
                })
                .await
                .map_err(|_| Error::CommitUncertain)?;
            }
            tokio::select! {
                _ = changed => {},
                _ = tokio::time::sleep(Duration::from_millis(100)) => {},
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(self.end)) =>
                    return Err(Error::Unavailable),
            }
        }
    }

    fn remaining_lifetime(&self, requested: Duration) -> Result<Duration, Error> {
        if requested.is_zero() || requested > Duration::from_secs(300) {
            return Err(Error::Binding("original fixed Version session bound"));
        }
        let remaining = self
            .end
            .checked_duration_since(Instant::now())
            .ok_or(Error::Unavailable)?;
        Ok(requested.min(remaining))
    }

    fn command_response(&self, bytes: &[u8], request_id: u64) -> Result<Vec<u8>, Error> {
        let started = super::super::now()?;
        self.require_lifetime()?;
        let request: wire::Request = serde_json::from_slice(bytes)?;
        if request.schema != 1
            || request.purpose != self.purpose.operation()
            || request.request_id != request_id
            || !(1..=128).contains(&request_id)
            || request.initial_binding != self.initial_binding.to_string()
            || request.operation_id != self.material.initial.request.operation_id.to_string()
        {
            return Err(Error::Binding(
                "same original Version initial purpose and operation",
            ));
        }
        wire::digest(&request.binding)?;
        wire::digest(&request.training_head)?;
        let (current, fresh) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        if current != self.initial_binding || fresh < started {
            return Err(Error::Binding("same original Version material clock"));
        }
        let (result, pin) = {
            let mut state = match self.state.try_lock() {
                Ok(state) => state,
                Err(std::sync::TryLockError::WouldBlock) => {
                    return self.encode_response(
                        request,
                        wire::OriginalResult::Busy,
                        started,
                        None,
                    );
                }
                Err(std::sync::TryLockError::Poisoned(_)) => return Err(Error::Unavailable),
            };
            if self.bind_original_predecessor(&mut state).is_err() {
                if self.origin == RetainedVersionOriginV1::Recovered {
                    // A formerly admitted cold reader cannot admit another
                    // connection after its held original cut fails a live read.
                    // Already handed-out read-only connections are not revoked.
                    state.selection_reader = None;
                }
                // No complete original predecessor was authenticated. This
                // is readback uncertainty, not an accepted prepare dispatch.
                // In particular, a wrong external cut cannot spend another
                // operation's host admission slot.
                (wire::OriginalResult::Uncertain, None)
            } else {
                request.require_cut(state.cut.as_ref().ok_or(Error::Unavailable)?, request_id)?;
                let original = match request.action {
                    wire::Action::Prepare => self.prepare_original(&mut state),
                    wire::Action::Readback => {
                        self.preparation_requested.store(true, Ordering::Release);
                        self.read_original_recovery(&mut state)
                    }
                };
                state
                    .cut
                    .as_ref()
                    .ok_or(Error::Unavailable)?
                    .require_fresh(started, PublicationAccess::Readback)?;
                let result = match original {
                    Ok(value) => wire::OriginalResult::from_original(value),
                    Err(Error::Busy) => wire::OriginalResult::Busy,
                    Err(Error::ReadbackRequired) => wire::OriginalResult::ReadbackRequired,
                    Err(_) => wire::OriginalResult::Uncertain,
                };
                let result = match (&result, self.original_final_use_outcome()) {
                    (
                        wire::OriginalResult::Prepared { .. },
                        RetainedVersionFinalUseOutcomeV1::Denied,
                    ) => wire::OriginalResult::FinalUseDenied,
                    (
                        wire::OriginalResult::Prepared { .. },
                        RetainedVersionFinalUseOutcomeV1::Requested
                        | RetainedVersionFinalUseOutcomeV1::Uncertain,
                    ) => wire::OriginalResult::Uncertain,
                    _ => result,
                };
                (
                    result,
                    Some(
                        state
                            .cut
                            .as_ref()
                            .ok_or(Error::Unavailable)?
                            .duplicate_response_pin(),
                    ),
                )
            }
        };
        // The original host state guard is released before encoding/writing.
        self.encode_response(request, result, started, pin)
    }

    fn encode_response(
        &self,
        request: wire::Request,
        result: wire::OriginalResult,
        started: u64,
        pin: Option<super::super::context::OriginalVersionCut>,
    ) -> Result<Vec<u8>, Error> {
        let (binding, fresh) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        if binding != self.initial_binding || fresh < started {
            return Err(Error::Binding("original Version final clock"));
        }
        self.require_lifetime()?;
        let bytes = serde_json::to_vec(&wire::Response { request, result })?;
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded original Version response"));
        }
        if let Some(pin) = pin {
            pin.require_fresh(started, PublicationAccess::Readback)?;
        }
        Ok(bytes)
    }
}

#[cfg(test)]
#[path = "circuit_retained_version_issuer_host_tests.rs"]
mod issuer_fixture;

#[cfg(test)]
#[path = "circuit_evaluated_version_readiness_support_tests.rs"]
mod evaluated_reader_fixture;
