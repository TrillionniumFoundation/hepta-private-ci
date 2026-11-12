//! Unique preparation and separate original FinalUse publication.
//! Dropped/unknown effects leave the consumed phase unavailable. No recovery
//! constructor, command retry or Root resident grant can recreate it.
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;

use super::super::super::context::PublicationAccess;
use super::super::Error;
use super::super::OriginalCircuitRetainedVersionReadbackV1;
use super::super::RetainedVersionOriginV1;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionFinalUseOutcomeV1;
use super::RetainedVersionHostPhaseV1;
use super::RetainedVersionHostStateV1;
use super::RetainedVersionPreparedV1;

impl OriginalCircuitRetainedVersionHostV1 {
    pub(super) fn prepare_original(
        &self,
        state: &mut RetainedVersionHostStateV1,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        if self.origin != RetainedVersionOriginV1::Fresh
            || self.preparation_requested.swap(true, Ordering::AcqRel)
        {
            return Err(Error::ReadbackRequired);
        }
        let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
        cut.require_fresh(super::super::now()?, PublicationAccess::NewWork)?;
        state.require_cut_current(&self.runtime)?;
        state.artifacts.read_current()?;
        let Some(RetainedVersionHostPhaseV1::Awaiting { inputs, task }) = state.phase.take() else {
            return Err(Error::CommitUncertain);
        };
        task.require_completed_a(&inputs.completed)?;
        cut.require_fresh(super::super::now()?, PublicationAccess::NewWork)?;
        let trainer = state.trainer.take().ok_or(Error::CommitUncertain)?;
        let prepared = match &cut.evaluated {
            None => RetainedVersionPreparedV1::TrainingNoUpdate(self.runtime.block_on(
                crate::prepare_original_circuit_retained_publication_v1(
                    cut.original_context(), trainer, *inputs)).map_err(|_| Error::CommitUncertain)?),
            Some(context) => {
                let evaluator = state.evaluator.take().ok_or(Error::CommitUncertain)?;
                RetainedVersionPreparedV1::EvaluatedNoUpdate(self.runtime.block_on(
                    crate::prepare_original_circuit_evaluated_retention_v1(
                        context.clone_for_original_receipt(), trainer, evaluator, *inputs))
                    .map_err(|_| Error::CommitUncertain)?)
            }
        };
        state.phase = Some(RetainedVersionHostPhaseV1::Prepared {
            original: Box::new(prepared),
            task,
        });
        let actual = self
            .read_original(state)
            .map_err(|_| Error::CommitUncertain)?;
        state
            .cut
            .as_ref()
            .ok_or(Error::CommitUncertain)?
            .require_fresh(super::super::now()?, PublicationAccess::NewWork)?;
        self.prepared.notify_waiters();
        Ok(actual)
    }

    /// This returns only the exact actual prepared binding. The external
    /// original FinalUse issuer must independently authorize it; Root does not
    /// receive this binding through the Version wire.
    pub async fn read_original_final_use_binding(
        self: Arc<Self>,
    ) -> Result<FinalUseBinding, Error> {
        tokio::task::spawn_blocking(move || {
            let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
            self.bind_original_predecessor(&mut state)?;
            self.read_original(&state)?;
            let Some(RetainedVersionHostPhaseV1::Prepared { original, .. }) = state.phase.as_ref()
            else {
                return Err(Error::ReadbackRequired);
            };
            state
                .cut
                .as_ref()
                .ok_or(Error::Unavailable)?
                .require_fresh(super::super::now()?, PublicationAccess::NewWork)?;
            Ok(original.final_use_binding().clone())
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    /// Called only after this host's one original issuer request, never by the
    /// Root command or a caller-supplied future grant.
    /// Exact binding is checked before custody is consumed. Any effect failure
    /// permanently removes this prepared instance; only original readback may
    /// establish what happened. This does not issue or renew a grant.
    pub(super) async fn publish_original_final_use(
        self: Arc<Self>,
        signed: SignedFinalUseGrant,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        if self.origin != RetainedVersionOriginV1::Fresh {
            return Err(Error::ReadbackRequired);
        }
        {
            let state = self.state.try_lock().map_err(|_| Error::Busy)?;
            if self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Requested
                || state.final_use_issuer.is_some()
            {
                return Err(Error::ReadbackRequired);
            }
            let Some(RetainedVersionHostPhaseV1::Prepared { original, .. }) = state.phase.as_ref()
            else {
                return Err(Error::ReadbackRequired);
            };
            if &signed.grant.binding != original.final_use_binding() {
                return Err(Error::Binding(
                    "same independently authorized original FinalUse",
                ));
            }
        }
        if self.publication_requested.swap(true, Ordering::AcqRel) {
            return Err(Error::ReadbackRequired);
        }
        let queued = QueuedFinalUseFence::new();
        let cancellation = Arc::clone(&queued.cancelled);
        let result = tokio::task::spawn_blocking(move || {
            require_not_cancelled(&cancellation)?;
            self.require_lifetime()?;
            let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
            self.bind_original_predecessor(&mut state)?;
            self.read_original(&state)?;
            let Some(RetainedVersionHostPhaseV1::Prepared { original, .. }) = state.phase.as_ref()
            else {
                return Err(Error::ReadbackRequired);
            };
            if &signed.grant.binding != original.final_use_binding() {
                return Err(Error::Binding(
                    "same independently authorized original FinalUse",
                ));
            }
            state
                .cut
                .as_ref()
                .ok_or(Error::Unavailable)?
                .require_fresh(super::super::now()?, PublicationAccess::NewWork)?;
            require_not_cancelled(&cancellation)?;
            let Some(RetainedVersionHostPhaseV1::Prepared { original, task }) = state.phase.take()
            else {
                return Err(Error::CommitUncertain);
            };
            task.require_completed_a(original.completed())?;
            require_not_cancelled(&cancellation)?;
            let (published, trainer, evaluator) = self.runtime.block_on(
                (*original).publish(signed),
            ).map_err(|_| Error::CommitUncertain)?;
            let cut = state.cut.as_ref().ok_or(Error::CommitUncertain)?;
            let intent = match &published.0.publication {
                crate::circuit_feature_current::Publication::Update { original, .. } => {
                    original.intent_digest()
                }
                _ => return Err(Error::CommitUncertain),
            };
            // A real existing product factory consumes the C config/files.
            // No RunStart is synthesized; ordinary ingress still needs its
            // separately authorized original deployment and task request.
            let (installed, config) = task
                .install_original(published, cut, intent)
                .map_err(|_| Error::CommitUncertain)?;
            state.trainer = Some(trainer);
            state.evaluator = evaluator;
            state.phase = Some(RetainedVersionHostPhaseV1::Installed {
                original: installed,
                config: Some(config),
            });
            state
                .install_original_selection_reader()
                .map_err(|_| Error::CommitUncertain)?;
            let actual = self
                .read_original(&state)
                .map_err(|_| Error::CommitUncertain)?;
            state
                .cut
                .as_ref()
                .ok_or(Error::CommitUncertain)?
                .require_fresh(super::super::now()?, PublicationAccess::NewWork)?;
            self.final_use_outcome.store(
                RetainedVersionFinalUseOutcomeV1::Published as u8,
                Ordering::Release,
            );
            self.installed.notify_waiters();
            Ok(actual)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }

    /// Actual ordinary C runtime entry for the original Version host. It waits
    /// for the separate successful FinalUse publication, consumes the existing
    /// factory's config once, and calls the original Agentd runtime. Starting
    /// the daemon does not invent an authenticated RunStart or a C completion.
    pub async fn run_original_c(
        self: Arc<Self>,
        arg0_paths: codex_arg0::Arg0DispatchPaths,
    ) -> Result<(), Error> {
        if self.origin != RetainedVersionOriginV1::Fresh
            || self.runtime_started.swap(true, Ordering::AcqRel)
        {
            return Err(Error::ReadbackRequired);
        }
        loop {
            let changed = self.installed.notified();
            self.require_lifetime()?;
            let owner = Arc::clone(&self);
            let config = tokio::task::spawn_blocking(move || {
                let mut state = match owner.state.try_lock() {
                    Ok(state) => state,
                    Err(std::sync::TryLockError::WouldBlock) => return Ok(None),
                    Err(std::sync::TryLockError::Poisoned(_)) => return Err(Error::Unavailable),
                };
                match state.phase.as_ref() {
                    Some(RetainedVersionHostPhaseV1::Installed { .. }) => {}
                    Some(
                        RetainedVersionHostPhaseV1::Awaiting { .. }
                        | RetainedVersionHostPhaseV1::Prepared { .. },
                    ) => return Ok(None),
                    _ => return Err(Error::CommitUncertain),
                }
                owner.read_original(&state)?;
                if owner.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
                {
                    return Err(Error::CommitUncertain);
                }
                state
                    .cut
                    .as_ref()
                    .ok_or(Error::Unavailable)?
                    .require_fresh(super::super::now()?, PublicationAccess::NewWork)?;
                let Some(RetainedVersionHostPhaseV1::Installed { config, .. }) =
                    state.phase.as_mut()
                else {
                    return Err(Error::CommitUncertain);
                };
                Ok::<_, Error>(Some(config.take().ok_or(Error::ReadbackRequired)?))
            })
            .await
            .map_err(|_| Error::CommitUncertain)??;
            if let Some(config) = config {
                return crate::run(config, arg0_paths).await.map_err(Error::Owner);
            }
            tokio::select! {
                _ = changed => {},
                _ = tokio::time::sleep(std::time::Duration::from_millis(100)) => {},
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(self.end)) =>
                    return Err(Error::Unavailable),
            }
        }
    }
}

struct QueuedFinalUseFence {
    cancelled: Arc<AtomicBool>,
}
impl QueuedFinalUseFence {
    fn new() -> Self {
        Self {
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }
}
impl Drop for QueuedFinalUseFence {
    fn drop(&mut self) {
        self.cancelled.store(true, Ordering::Release);
    }
}
fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) {
        return Err(Error::Cancelled);
    }
    Ok(())
}
