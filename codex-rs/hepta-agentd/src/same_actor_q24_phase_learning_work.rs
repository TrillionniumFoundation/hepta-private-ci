//! Custody of actual original blocking work for one closed same-actor phase.
//! A waiting future never owns the only JoinHandle. Terminal cleanup also
//! discards original owner results which were never delivered to their caller.

use futures::FutureExt;
use futures::future::BoxFuture;
use futures::future::Shared;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use tokio::sync::Notify;
use tokio::task::JoinHandle;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CellQ24PreparedLearningV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

#[path = "same_actor_q24_phase_learning_evaluation.rs"]
mod evaluation;
#[path = "same_actor_q24_phase_learning_retirement.rs"]
mod retirement;
pub(crate) use retirement::OriginalLearningStop;
pub(crate) use retirement::OriginalLearningWorkJoined;

/// Only the actual scoped assembly constructs this capability. It is neither
/// a replacement stage owner nor an independent source of learning evidence.
pub(crate) struct OriginalSameActorLearningWork {
    context: Arc<OriginalSameActorRootContext>,
    prepared: Arc<CellQ24PreparedLearningV1>,
    jobs: Arc<OriginalLearningJobs>,
    evaluation: evaluation::OriginalEvaluationExchange,
    retirement: retirement::OriginalLearningRetirement,
}

pub(crate) struct OriginalSameActorLearningCleanup {
    work: Arc<OriginalSameActorLearningWork>,
}

struct OriginalLearningJobs {
    gate: Arc<SameActorPhaseGate>,
    retained: Mutex<Vec<Arc<dyn OriginalJobCustody>>>,
    normal_closed: AtomicBool,
    pending: Arc<AtomicUsize>,
    join_failed: Arc<AtomicBool>,
    changed: Arc<Notify>,
}

trait OriginalJobCustody: Send + Sync {
    fn join_and_discard(&self) -> Pin<Box<dyn Future<Output = bool> + Send + '_>>;
    fn join_for_normal_retirement(&self) -> Pin<Box<dyn Future<Output = bool> + Send + '_>>;
}

struct OriginalJobState<T, E> {
    joined: bool,
    join_failed: bool,
    join_error: Option<tokio::task::JoinError>,
    output: Option<Result<T, E>>,
}

/// The original blocking JoinError is retained, not reconstructed from a
/// boolean or mapped into an unrelated owner result. Existing receivers keep
/// their original CommitUncertain mapping.
#[derive(Debug)]
pub(crate) enum OriginalJobReceiveError {
    Join(tokio::task::JoinError),
    Phase(std::io::Error),
    Custody(Error),
    WrongOriginalJob,
    ResultUnavailable,
    Release {
        original: Box<OriginalJobReceiveError>,
        custody: Error,
    },
}

impl std::fmt::Display for OriginalJobReceiveError {
    fn fmt(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Join(error) => write!(output, "original blocking join: {error}"),
            Self::Phase(error) => write!(output, "original phase refused result: {error}"),
            Self::Custody(error) => write!(output, "original job custody: {error}"),
            Self::WrongOriginalJob => write!(output, "job belongs to another original Work"),
            Self::ResultUnavailable => write!(output, "original joined result is unavailable"),
            Self::Release { original, custody } => {
                write!(output, "{original}; original job release: {custody}")
            }
        }
    }
}

impl std::error::Error for OriginalJobReceiveError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Join(error) => Some(error),
            Self::Phase(error) => Some(error),
            Self::Custody(error) => Some(error),
            Self::Release { original, .. } => Some(original.as_ref()),
            Self::WrongOriginalJob | Self::ResultUnavailable => None,
        }
    }
}

/// The registry retains the one Shared future which owns the actual handle.
/// Its unit completion is cloneable; the original result and JoinError are not.
pub(crate) struct OriginalLearningJob<T, E> {
    state: Arc<Mutex<OriginalJobState<T, E>>>,
    completion: Shared<BoxFuture<'static, ()>>,
    gate: Arc<SameActorPhaseGate>,
    pending: Arc<AtomicUsize>,
    join_failed: Arc<AtomicBool>,
    changed: Arc<Notify>,
}

/// Held only across the original spawn and immediate handle registration.
/// No owner lock, I/O, await or user callback is executed under this guard.
pub(crate) struct OriginalBlockingAdmission<'a> {
    retained: MutexGuard<'a, Vec<Arc<dyn OriginalJobCustody>>>,
    gate: Arc<SameActorPhaseGate>,
    pending: Arc<AtomicUsize>,
    join_failed: Arc<AtomicBool>,
    changed: Arc<Notify>,
    armed: bool,
}

impl OriginalSameActorLearningWork {
    pub(super) fn from_original_scope(
        context: Arc<OriginalSameActorRootContext>,
        prepared: Arc<CellQ24PreparedLearningV1>,
    ) -> Result<Arc<Self>, AgentdError> {
        OriginalSameActorRootContext::require_current(&context)?;
        CellQ24PreparedLearningV1::revalidate_source(&prepared)
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        let jobs = Arc::new(OriginalLearningJobs {
            gate: Arc::clone(context.gate()),
            retained: Mutex::new(Vec::new()),
            normal_closed: AtomicBool::new(false),
            pending: Arc::new(AtomicUsize::new(0)),
            join_failed: Arc::new(AtomicBool::new(false)),
            changed: Arc::new(Notify::new()),
        });
        let evaluation = evaluation::OriginalEvaluationExchange::new(Arc::clone(context.gate()));
        Ok(Arc::new(Self {
            context,
            prepared,
            jobs,
            evaluation,
            retirement: retirement::OriginalLearningRetirement::new(),
        }))
    }

    pub(super) fn cleanup(self: &Arc<Self>) -> OriginalSameActorLearningCleanup {
        OriginalSameActorLearningCleanup {
            work: Arc::clone(self),
        }
    }

    pub(crate) fn gate(&self) -> &Arc<SameActorPhaseGate> {
        &self.jobs.gate
    }

    pub(crate) fn pending_count(&self) -> usize {
        self.jobs.pending.load(Ordering::Acquire)
    }

    pub(crate) fn require_identity_and_gate(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        if self.context.identity() != identity || !Arc::ptr_eq(self.gate(), gate) {
            self.gate().close();
            return Err(AgentdError::GenerationFenced(
                "learning work differs from its original phase and full identity".into(),
            ));
        }
        OriginalSameActorRootContext::require_current(&self.context)
    }

    pub(crate) fn require_original_prepared(
        &self,
        prepared: &Arc<CellQ24PreparedLearningV1>,
    ) -> Result<(), Error> {
        if !Arc::ptr_eq(&self.prepared, prepared) {
            self.gate().close();
            return Err(Error::WrongScope);
        }
        self.require_original_work_entry()
    }

    pub(crate) fn require_training_context(
        &self,
        dataset: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        if dataset.request != self.prepared.initial().request
            || dataset.owners != self.prepared.initial().owners
            || scope != self.prepared.scope()
        {
            self.gate().close();
            return Err(Error::WrongScope);
        }
        scope
            .validate_snapshot(dataset)
            .map_err(|_| Error::WrongScope)?;
        self.require_original_work_entry()
    }

    pub(crate) fn require_original_work_entry(&self) -> Result<(), Error> {
        self.gate()
            .require_open()
            .map(|_| ())
            .map_err(|_| Error::CommitUncertain)
    }

    pub(crate) fn original_failure_scope(&self) -> CloseSameActorPhaseOnDrop {
        CloseSameActorPhaseOnDrop::new(self.gate())
    }

    pub(crate) fn reserve_original_blocking(&self) -> Result<OriginalBlockingAdmission<'_>, Error> {
        self.jobs.reserve()
    }

    pub(crate) async fn receive_original_job<T: Send + 'static, E: Send + 'static>(
        &self,
        job: Arc<OriginalLearningJob<T, E>>,
    ) -> Result<Result<T, E>, Error> {
        self.jobs.receive_registered_job(job).await
    }

    pub(crate) async fn receive_original_job_with_join_cause<
        T: Send + 'static,
        E: Send + 'static,
    >(
        &self,
        job: Arc<OriginalLearningJob<T, E>>,
    ) -> Result<Result<T, E>, OriginalJobReceiveError> {
        self.jobs.receive_registered_job_with_join_cause(job).await
    }

    pub(crate) async fn close_and_join_original_work(&self) -> Result<(), AgentdError> {
        self.jobs
            .close_and_join()
            .await
            .map_err(|_| AgentdError::GenerationFenced("original learning work join failed".into()))
    }
}

impl OriginalSameActorLearningCleanup {
    pub(crate) fn work(&self) -> &Arc<OriginalSameActorLearningWork> {
        &self.work
    }

    pub(crate) async fn close_and_join_original_work(&self) -> Result<(), AgentdError> {
        self.work.close_and_join_original_work().await
    }
}

impl OriginalLearningJobs {
    async fn receive_registered_job<T: Send + 'static, E: Send + 'static>(
        &self,
        job: Arc<OriginalLearningJob<T, E>>,
    ) -> Result<Result<T, E>, Error> {
        let result = job.receive().await;
        self.release(&job)?;
        result.map_err(|_| Error::CommitUncertain)
    }

    async fn receive_registered_job_with_join_cause<T: Send + 'static, E: Send + 'static>(
        &self,
        job: Arc<OriginalLearningJob<T, E>>,
    ) -> Result<Result<T, E>, OriginalJobReceiveError> {
        if !Arc::ptr_eq(&self.gate, &job.gate) || !Arc::ptr_eq(&self.pending, &job.pending) {
            self.gate.close();
            job.gate.close();
            return Err(OriginalJobReceiveError::WrongOriginalJob);
        }
        let result = job.receive_with_join_cause().await;
        match self.release(&job) {
            Ok(()) => result,
            Err(custody) => match result {
                Err(original) => Err(OriginalJobReceiveError::Release {
                    original: Box::new(original),
                    custody,
                }),
                Ok(output) => {
                    drop(output);
                    Err(OriginalJobReceiveError::Custody(custody))
                }
            },
        }
    }

    fn reserve(&self) -> Result<OriginalBlockingAdmission<'_>, Error> {
        let retained = self.retained.lock().map_err(|_| {
            self.gate.close();
            Error::CommitUncertain
        })?;
        self.gate
            .require_open()
            .map_err(|_| Error::CommitUncertain)?;
        if self.normal_closed.load(Ordering::Acquire) {
            self.gate.close();
            return Err(Error::CommitUncertain);
        }
        self.pending
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| {
                self.gate.close();
                Error::CommitUncertain
            })?;
        Ok(OriginalBlockingAdmission {
            retained,
            gate: Arc::clone(&self.gate),
            pending: Arc::clone(&self.pending),
            join_failed: Arc::clone(&self.join_failed),
            changed: Arc::clone(&self.changed),
            armed: true,
        })
    }

    fn release<T: Send + 'static, E: Send + 'static>(
        &self,
        original: &Arc<OriginalLearningJob<T, E>>,
    ) -> Result<(), Error> {
        let original: Arc<dyn OriginalJobCustody> = original.clone();
        let mut retained = self.retained.lock().map_err(|_| {
            self.gate.close();
            Error::CommitUncertain
        })?;
        retained.retain(|entry| !Arc::ptr_eq(entry, &original));
        Ok(())
    }

    async fn join_original_normal(&self) -> Result<(), String> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        {
            let _retained = self.retained.lock().map_err(|error| {
                self.gate.close();
                error.to_string()
            })?;
            self.gate
                .require_open()
                .map_err(|error| error.to_string())?;
            if self.normal_closed.swap(true, Ordering::AcqRel) {
                return Err("original normal Work join was already requested".into());
            }
        }
        loop {
            self.gate
                .require_open()
                .map_err(|error| error.to_string())?;
            let jobs = self
                .retained
                .lock()
                .map_err(|error| {
                    self.gate.close();
                    error.to_string()
                })?
                .clone();
            if jobs.is_empty() {
                let notified = self.changed.notified();
                tokio::pin!(notified);
                notified.as_mut().enable();
                if self.pending.load(Ordering::Acquire) == 0 {
                    if self.join_failed.load(Ordering::Acquire) {
                        return Err("original blocking work failed before normal retirement".into());
                    }
                    self.gate
                        .require_open()
                        .map_err(|error| error.to_string())?;
                    closing.disarm();
                    return Ok(());
                }
                tokio::select! {
                    _ = notified => {},
                    _ = self.gate.cancelled() => {
                        return Err("original phase closed while joining actual Work".into());
                    }
                    _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                        self.gate.deadline().instant(),
                    )) => {
                        self.gate.close();
                        return Err("original phase ended while joining actual Work".into());
                    }
                }
                continue;
            }
            for job in jobs {
                let joined = tokio::select! {
                    result = job.join_for_normal_retirement() => result,
                    _ = self.gate.cancelled() => {
                        return Err("original phase closed while joining an actual handle".into());
                    }
                    _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                        self.gate.deadline().instant(),
                    )) => {
                        self.gate.close();
                        return Err("original phase ended while joining an actual handle".into());
                    }
                };
                self.retained
                    .lock()
                    .map_err(|error| {
                        self.gate.close();
                        error.to_string()
                    })?
                    .retain(|entry| !Arc::ptr_eq(entry, &job));
                if !joined {
                    self.join_failed.store(true, Ordering::Release);
                    return Err("original normal join found failed or undelivered work".into());
                }
            }
        }
    }

    async fn close_and_join(&self) -> Result<(), ()> {
        self.gate.close();
        loop {
            // Poison recovery is terminal custody only. It never admits work,
            // returns an owner result, or restores permission to this phase.
            let jobs = self
                .retained
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone();
            if jobs.is_empty() {
                let notified = self.changed.notified();
                tokio::pin!(notified);
                notified.as_mut().enable();
                if self.pending.load(Ordering::Acquire) == 0 {
                    return if self.join_failed.load(Ordering::Acquire) {
                        Err(())
                    } else {
                        Ok(())
                    };
                }
                // A cancelled or concurrent receiver may still own a job Arc
                // and its not-yet-delivered original owner value. Do not call
                // cleanup complete until that real custody has been released.
                notified.await;
                continue;
            }
            for job in jobs {
                if !job.join_and_discard().await {
                    self.join_failed.store(true, Ordering::Release);
                }
                self.retained
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .retain(|entry| !Arc::ptr_eq(entry, &job));
            }
        }
    }
}

impl OriginalBlockingAdmission<'_> {
    pub(crate) fn retain_original_handle<T: Send + 'static, E: Send + 'static>(
        mut self,
        handle: JoinHandle<Result<T, E>>,
    ) -> Arc<OriginalLearningJob<T, E>> {
        let state = Arc::new(Mutex::new(OriginalJobState::<T, E> {
            joined: false,
            join_failed: false,
            join_error: None,
            output: None,
        }));
        let recorded = Arc::clone(&state);
        let failed = Arc::clone(&self.join_failed);
        let gate = Arc::clone(&self.gate);
        // This future owns the one real handle before any waiter can poll it.
        // Registry custody of the job retains this Shared clone on cancellation.
        let completion = async move {
            let result = handle.await;
            let mut state = recorded.lock().unwrap_or_else(|error| {
                gate.close();
                failed.store(true, Ordering::Release);
                let mut state = error.into_inner();
                state.join_failed = true;
                state
            });
            // No await separates the actual join from its single terminal write.
            state.joined = true;
            match result {
                Ok(output) => state.output = Some(output),
                Err(error) => {
                    state.join_failed = true;
                    state.join_error = Some(error);
                    failed.store(true, Ordering::Release);
                }
            }
        }
        .boxed()
        .shared();
        let job = Arc::new(OriginalLearningJob {
            state,
            completion,
            gate: Arc::clone(&self.gate),
            pending: Arc::clone(&self.pending),
            join_failed: Arc::clone(&self.join_failed),
            changed: Arc::clone(&self.changed),
        });
        self.retained.push(job.clone());
        self.armed = false;
        job
    }
}

impl Drop for OriginalBlockingAdmission<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.gate.close();
            self.pending.fetch_sub(1, Ordering::AcqRel);
            self.changed.notify_waiters();
            self.gate.notify_original_waiters();
        }
    }
}

impl<T: Send + 'static, E: Send + 'static> OriginalLearningJob<T, E> {
    fn lock_original_learning_result(&self) -> MutexGuard<'_, OriginalJobState<T, E>> {
        self.state.lock().unwrap_or_else(|error| {
            self.gate.close();
            self.join_failed.store(true, Ordering::Release);
            let mut state = error.into_inner();
            state.join_failed = true;
            state
        })
    }

    async fn receive_with_join_cause(&self) -> Result<Result<T, E>, OriginalJobReceiveError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.completion.clone().await;
        let mut state = self.lock_original_learning_result();
        let failed = state.join_failed;
        let join_error = state.join_error.take();
        let output = state.output.take();
        drop(state);
        if let Some(error) = join_error {
            drop(output);
            return Err(OriginalJobReceiveError::Join(error));
        }
        if failed {
            drop(output);
            return Err(OriginalJobReceiveError::ResultUnavailable);
        }
        let output = output.ok_or(OriginalJobReceiveError::ResultUnavailable)?;
        if output.is_err() {
            self.gate.close();
            return Ok(output);
        }
        if let Err(error) = self.gate.require_open() {
            drop(output);
            return Err(OriginalJobReceiveError::Phase(error));
        }
        closing.disarm();
        Ok(output)
    }

    async fn receive(&self) -> Result<Result<T, E>, ()> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.completion.clone().await;
        let mut state = self.lock_original_learning_result();
        let failed = state.join_failed;
        let output = state.output.take();
        drop(state);
        if failed {
            drop(output);
            return Err(());
        }
        let output = output.ok_or(())?;
        if output.is_err() {
            self.gate.close();
            return Ok(output);
        }
        if self.gate.require_open().is_err() {
            drop(output);
            return Err(());
        }
        closing.disarm();
        Ok(output)
    }
}

impl<T: Send + 'static, E: Send + 'static> OriginalJobCustody for OriginalLearningJob<T, E> {
    fn join_for_normal_retirement(&self) -> Pin<Box<dyn Future<Output = bool> + Send + '_>> {
        Box::pin(async move {
            self.completion.clone().await;
            let mut state = self.lock_original_learning_result();
            let output = state.output.take();
            let succeeded = !state.join_failed && output.is_none();
            drop(state);
            // A completed but never-delivered owner cannot become normal
            // completion. Release it, retain failure, then fault cleanup joins
            // every remaining original handle.
            drop(output);
            if !succeeded {
                self.join_failed.store(true, Ordering::Release);
                self.gate.close();
            }
            succeeded
        })
    }

    fn join_and_discard(&self) -> Pin<Box<dyn Future<Output = bool> + Send + '_>> {
        Box::pin(async move {
            self.completion.clone().await;
            let mut state = self.lock_original_learning_result();
            let succeeded = !state.join_failed;
            let output = state.output.take();
            drop(state);
            // This may release original Files and owner capabilities. It is
            // complete before the registry entry and its pending count fall.
            drop(output);
            succeeded
        })
    }
}

impl<T, E> Drop for OriginalLearningJob<T, E> {
    fn drop(&mut self) {
        let mut state = self.state.lock().unwrap_or_else(|error| {
            self.gate.close();
            self.join_failed.store(true, Ordering::Release);
            error.into_inner()
        });
        if !state.joined {
            // Losing all supervision is not a completed join. Never advertise
            // it as drained merely because a holder was dropped.
            self.gate.close();
            return;
        }
        let output = state.output.take();
        drop(state);
        drop(output);
        self.pending.fetch_sub(1, Ordering::AcqRel);
        self.changed.notify_waiters();
        self.gate.notify_original_waiters();
    }
}

#[cfg(test)]
#[path = "same_actor_q24_phase_learning_work_tests.rs"]
mod tests;
