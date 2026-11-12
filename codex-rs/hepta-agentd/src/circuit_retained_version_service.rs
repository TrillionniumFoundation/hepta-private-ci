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
use super::super::evaluated_wire::EvaluatedProgressResult;
use super::super::evaluated_wire::VersionRequest;
use super::super::profile::VersionCut;
use super::super::profile::VersionPurpose;
use super::super::wire;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionFinalUseOutcomeV1;
use super::RetainedVersionHostPhaseV1;
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
        if self.purpose != VersionPurpose::TrainingNoUpdate {
            return Err(Error::Binding(
                "original three-cut Version Selection read purpose",
            ));
        }
        self.serve_selection_readback(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )
        .await
    }

    /// The independent four-cut purpose consumes the already-delivered S read
    /// stream before waiting for this same Version owner's actual C factory.
    pub async fn serve_original_evaluated_selection_readback(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        if self.purpose != VersionPurpose::Evaluated {
            return Err(Error::Binding(
                "original four-cut evaluated Version Selection read purpose",
            ));
        }
        self.serve_selection_readback(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )
        .await
    }

    async fn serve_selection_readback(
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
        let mut channel = original_owner_command_channel_v1(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )?;
        loop {
            let changed = self.installed.notified();
            self.require_lifetime()?;
            channel.check_peer_lifetime()?;
            let reader = {
                match self.state.try_lock() {
                    Ok(state) => state.selection_reader.as_ref().map(Arc::clone),
                    Err(std::sync::TryLockError::WouldBlock) => None,
                    Err(std::sync::TryLockError::Poisoned(_)) => return Err(Error::Unavailable),
                }
            };
            if let Some(reader) = reader {
                let purpose = self.purpose;
                return tokio::task::spawn_blocking(move || {
                    let _permit = permit;
                    let served = match purpose {
                        VersionPurpose::TrainingNoUpdate => OriginalCircuitLearningReadOwnerV1::serve_original_retained_channel(
                            reader.as_ref(), &mut channel,
                        ),
                        VersionPurpose::Evaluated => OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_retained_channel(
                            reader.as_ref(), &mut channel,
                        ),
                    };
                    served
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
        let request = VersionRequest::decode(bytes, self.purpose)?;
        request.require_initial(
            self.purpose,
            request_id,
            self.initial_binding,
            &self.material.initial,
        )?;
        let (current, fresh) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        if current != self.initial_binding || fresh < started {
            return Err(Error::Binding("same original Version material clock"));
        }
        if request.is_publication_progress() {
            return self.publication_progress_response(request, request_id, started);
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
                // No complete original predecessor was authenticated. This
                // is readback uncertainty, not an accepted prepare dispatch.
                // In particular, a wrong external cut cannot spend another
                // operation's host admission slot.
                (wire::OriginalResult::Uncertain, None)
            } else {
                request.require_cut(state.cut.as_ref().ok_or(Error::Unavailable)?, request_id)?;
                let original = match request.action()? {
                    wire::Action::Prepare => self.prepare_original(&mut state),
                    wire::Action::Readback => {
                        self.preparation_requested.store(true, Ordering::Release);
                        self.read_original(&state)
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

    fn publication_progress_response(
        &self,
        request: VersionRequest,
        request_id: u64,
        started: u64,
    ) -> Result<Vec<u8>, Error> {
        if self.purpose != VersionPurpose::Evaluated || !request.is_publication_progress() {
            return Err(Error::Binding("evaluated-only Version progress purpose"));
        }
        let (result, pin) = {
            match self.state.try_lock() {
                Ok(state) => match state.cut.as_ref() {
                    None => (EvaluatedProgressResult::ReadbackRequired, None),
                    Some(cut) => {
                        if !matches!(cut, VersionCut::Evaluated(_)) {
                            return Err(Error::Binding("original evaluated Version progress cut"));
                        }
                        request.require_cut(cut, request_id)?;
                        cut.require_fresh(started, PublicationAccess::Readback)?;
                        // This is only the private worker's scheduling state.
                        // No peer read, owner binding, CURRENT observation or
                        // phase/issuer mutation is performed by this action.
                        let result = match (self.original_final_use_outcome(), state.phase.as_ref())
                        {
                            (RetainedVersionFinalUseOutcomeV1::Denied, _) => {
                                EvaluatedProgressResult::FinalUseDenied
                            }
                            (RetainedVersionFinalUseOutcomeV1::Uncertain, _) | (_, None) => {
                                EvaluatedProgressResult::Uncertain
                            }
                            (
                                RetainedVersionFinalUseOutcomeV1::Awaiting,
                                Some(RetainedVersionHostPhaseV1::Awaiting { .. }),
                            ) => {
                                if self.preparation_requested.load(Ordering::Acquire) {
                                    // A failed admitted prepare is not a worker
                                    // still running behind this held mutex.
                                    EvaluatedProgressResult::Uncertain
                                } else {
                                    EvaluatedProgressResult::Pending
                                }
                            }
                            (
                                RetainedVersionFinalUseOutcomeV1::Awaiting
                                | RetainedVersionFinalUseOutcomeV1::Requested,
                                Some(RetainedVersionHostPhaseV1::Prepared { .. }),
                            ) => EvaluatedProgressResult::Pending,
                            (
                                RetainedVersionFinalUseOutcomeV1::Published,
                                Some(
                                    RetainedVersionHostPhaseV1::Installed { .. }
                                    | RetainedVersionHostPhaseV1::Recovered(_),
                                ),
                            ) => EvaluatedProgressResult::ReadbackAvailable,
                            _ => EvaluatedProgressResult::Uncertain,
                        };
                        (result, Some(cut.duplicate_response_pin()))
                    }
                },
                Err(std::sync::TryLockError::WouldBlock) => (EvaluatedProgressResult::Busy, None),
                Err(std::sync::TryLockError::Poisoned(_)) => return Err(Error::Unavailable),
            }
        };
        let (binding, fresh) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        if binding != self.initial_binding || fresh < started {
            return Err(Error::Binding("original Version progress final clock"));
        }
        self.require_lifetime()?;
        let bytes = request.encode_progress_response(result)?;
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded original Version progress response"));
        }
        if let Some(pin) = pin {
            pin.require_fresh(started, PublicationAccess::Readback)?;
        }
        Ok(bytes)
    }

    fn encode_response(
        &self,
        request: VersionRequest,
        result: wire::OriginalResult,
        started: u64,
        pin: Option<VersionCut>,
    ) -> Result<Vec<u8>, Error> {
        let (binding, fresh) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        if binding != self.initial_binding || fresh < started {
            return Err(Error::Binding("original Version final clock"));
        }
        self.require_lifetime()?;
        let bytes = request.encode_response(result)?;
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
