//! One original Root issuer request for the actual prepared intent. Denied,
//! dropped and uncertain requests retain only original-operation readback.
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::FinalUseBinding;

use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionFinalUseOutcomeV1;
use super::RetainedVersionHostPhaseV1;
use super::super::Error;
use super::super::RetainedVersionOriginV1;
use super::super::super::context::PublicationAccess;
use crate::AgentdFinalUseIssuerError;
use crate::OriginalRootRetainedVersionIssuerV1;

impl OriginalCircuitRetainedVersionHostV1 {
    pub(super) async fn serve_original_final_use(self: Arc<Self>) -> Result<(), Error> {
        if self.origin != RetainedVersionOriginV1::Fresh
            || self.issuer_worker_started.swap(true, Ordering::AcqRel)
        {
            return Err(Error::ReadbackRequired);
        }
        let queued = QueuedOriginalVersionIssuerV1::new();
        let cancellation = Arc::clone(&queued.cancelled);
        loop {
            let changed = self.prepared.notified();
            self.require_lifetime()?;
            let owner = Arc::clone(&self);
            let cancelled = Arc::clone(&cancellation);
            let claim = tokio::task::spawn_blocking(move || {
                owner.claim_original_final_use(&cancelled)
            }).await.map_err(|_| Error::CommitUncertain)?;
            let claimed = match claim {
                Ok(claimed) => claimed,
                Err(_) => {
                    self.final_use_outcome.store(
                        RetainedVersionFinalUseOutcomeV1::Uncertain as u8, Ordering::Release,
                    );
                    return Ok(());
                }
            };
            if let Some((mut issuer, binding)) = claimed {
                let owner = Arc::clone(&self);
                let cancelled = Arc::clone(&cancellation);
                let response = tokio::task::spawn_blocking(move || {
                    require_not_cancelled(&cancelled)?;
                    let started = super::super::now()?;
                    {
                        let state = owner.state.try_lock().map_err(|_| Error::Busy)?;
                        owner.read_original(&state)?;
                        let Some(RetainedVersionHostPhaseV1::Prepared { original, .. }) = state.phase.as_ref() else {
                            return Err(Error::CommitUncertain);
                        };
                        if original.final_use_binding() != &binding {
                            return Err(Error::Binding("same actual prepared FinalUse binding"));
                        }
                        state.cut.as_ref().ok_or(Error::Unavailable)?
                            .require_fresh(started, PublicationAccess::NewWork)?;
                    }
                    // The Version mutex is released before Root network I/O.
                    // A dropped queued future does not send its first frame.
                    require_not_cancelled(&cancelled)?;
                    OriginalRootRetainedVersionIssuerV1::request_for_original_retained_version(
                        &mut issuer, &binding,
                    ).map_err(Error::Issuer)
                }).await;
                match response {
                    Ok(Ok(signed)) => {
                        if OriginalCircuitRetainedVersionHostV1::publish_original_final_use(
                            Arc::clone(&self), signed,
                        ).await.is_err() {
                            self.final_use_outcome.store(
                                RetainedVersionFinalUseOutcomeV1::Uncertain as u8, Ordering::Release,
                            );
                        }
                    }
                    Ok(Err(Error::Issuer(AgentdFinalUseIssuerError::Denied))) => {
                        self.final_use_outcome.store(
                            RetainedVersionFinalUseOutcomeV1::Denied as u8, Ordering::Release,
                        );
                    }
                    _ => {
                        self.final_use_outcome.store(
                            RetainedVersionFinalUseOutcomeV1::Uncertain as u8, Ordering::Release,
                        );
                    }
                }
                // The moved issuer is never returned. A legal denial may keep
                // the old provider's transport usable in other APIs, but this
                // host cannot reuse it, reconnect or create another request.
                drop(queued);
                return Ok(());
            }
            tokio::select! {
                _ = changed => {},
                _ = tokio::time::sleep(Duration::from_millis(100)) => {},
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(self.end)) =>
                    return Err(Error::Unavailable),
            }
        }
    }

    fn claim_original_final_use(
        &self,
        cancelled: &AtomicBool,
    ) -> Result<Option<(OriginalRootRetainedVersionIssuerV1, FinalUseBinding)>, Error> {
        require_not_cancelled(cancelled)?;
        let started = super::super::now()?;
        self.require_lifetime()?;
        if self.origin != RetainedVersionOriginV1::Fresh
            || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Awaiting
        {
            return Err(Error::ReadbackRequired);
        }
        let mut state = match self.state.try_lock() {
            Ok(state) => state,
            Err(std::sync::TryLockError::WouldBlock) => return Ok(None),
            Err(std::sync::TryLockError::Poisoned(_)) => return Err(Error::Unavailable),
        };
        match state.phase.as_ref() {
            Some(RetainedVersionHostPhaseV1::Awaiting { .. }) => return Ok(None),
            Some(RetainedVersionHostPhaseV1::Prepared { .. }) => {},
            _ => return Err(Error::CommitUncertain),
        }
        if !self.preparation_requested.load(Ordering::Acquire) {
            return Err(Error::ReadbackRequired);
        }
        self.read_original(&state)?;
        let Some(RetainedVersionHostPhaseV1::Prepared { original, .. }) = state.phase.as_ref() else {
            return Err(Error::CommitUncertain);
        };
        let binding = original.final_use_binding().clone();
        state.cut.as_ref().ok_or(Error::Unavailable)?
            .require_fresh(started, PublicationAccess::NewWork)?;
        require_not_cancelled(cancelled)?;
        let issuer = state.final_use_issuer.take().ok_or(Error::ReadbackRequired)?;
        self.final_use_outcome.store(
            RetainedVersionFinalUseOutcomeV1::Requested as u8, Ordering::Release,
        );
        Ok(Some((issuer, binding)))
    }
}

struct QueuedOriginalVersionIssuerV1 { cancelled: Arc<AtomicBool> }
impl QueuedOriginalVersionIssuerV1 {
    fn new() -> Self { Self { cancelled: Arc::new(AtomicBool::new(false)) } }
}
impl Drop for QueuedOriginalVersionIssuerV1 {
    fn drop(&mut self) { self.cancelled.store(true, Ordering::Release); }
}
fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) { return Err(Error::Cancelled); }
    Ok(())
}
