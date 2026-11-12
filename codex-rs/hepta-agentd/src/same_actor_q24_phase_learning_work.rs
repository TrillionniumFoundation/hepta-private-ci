//! Custody of actual original blocking work for one closed same-actor phase.
//! A waiting future never owns the only JoinHandle. Terminal cleanup also
//! discards original owner results which were never delivered to their caller.

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

/// Only the actual scoped assembly constructs this capability. It is neither
/// a replacement stage owner nor an independent source of learning evidence.
pub(crate) struct OriginalSameActorLearningWork {
    context: Arc<OriginalSameActorRootContext>,
    prepared: Arc<CellQ24PreparedLearningV1>,
    jobs: Arc<OriginalLearningJobs>,
    evaluation: evaluation::OriginalEvaluationExchange,
}

pub(crate) struct OriginalSameActorLearningCleanup {
    work: Arc<OriginalSameActorLearningWork>,
}

struct OriginalLearningJobs {
    gate: Arc<SameActorPhaseGate>,
    retained: Mutex<Vec<Arc<dyn OriginalJobCustody>>>,
    pending: Arc<AtomicUsize>,
    join_failed: Arc<AtomicBool>,
    changed: Arc<Notify>,
}

trait OriginalJobCustody: Send + Sync {
    fn join_and_discard(&self) -> Pin<Box<dyn Future<Output = bool> + Send + '_>>;
}

struct OriginalJobState<T, E> {
    handle: Option<JoinHandle<Result<T, E>>>,
    joined: bool,
    join_failed: bool,
    output: Option<Result<T, E>>,
}

/// This object holds the real handle, even while another future borrows it
/// through an async mutex and is subsequently cancelled.
pub(crate) struct OriginalLearningJob<T, E> {
    state: tokio::sync::Mutex<OriginalJobState<T, E>>,
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

    pub(crate) async fn close_and_join_original_work(&self) -> Result<(), AgentdError> {
        self.jobs.close_and_join().await.map_err(|_| {
            AgentdError::GenerationFenced("original learning work join failed".into())
        })
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

    fn reserve(&self) -> Result<OriginalBlockingAdmission<'_>, Error> {
        let retained = self.retained.lock().map_err(|_| {
            self.gate.close();
            Error::CommitUncertain
        })?;
        self.gate.require_open().map_err(|_| Error::CommitUncertain)?;
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

    async fn close_and_join(&self) -> Result<(), ()> {
        self.gate.close();
        loop {
            // Poison recovery is terminal custody only. It never admits work,
            // returns an owner result, or restores permission to this phase.
            let jobs = self
                .retained
                .lock()
                .unwrap_or_else(|error| error.into_inner())
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
                    .unwrap_or_else(|error| error.into_inner())
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
        let job = Arc::new(OriginalLearningJob {
            state: tokio::sync::Mutex::new(OriginalJobState {
                handle: Some(handle),
                joined: false,
                join_failed: false,
                output: None,
            }),
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
    async fn join_locked(&self, state: &mut OriginalJobState<T, E>) {
        if state.joined {
            return;
        }
        let result = match state.handle.as_mut() {
            Some(handle) => handle.await,
            None => {
                state.join_failed = true;
                self.join_failed.store(true, Ordering::Release);
                state.joined = true;
                return;
            }
        };
        // No await separates completion from this terminal state transition.
        // A later cleanup observes joined and never polls this handle again.
        state.joined = true;
        state.handle = None;
        match result {
            Ok(output) => state.output = Some(output),
            Err(_) => {
                state.join_failed = true;
                self.join_failed.store(true, Ordering::Release);
            }
        }
    }

    async fn receive(&self) -> Result<Result<T, E>, ()> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        let mut state = self.state.lock().await;
        self.join_locked(&mut state).await;
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
    fn join_and_discard(&self) -> Pin<Box<dyn Future<Output = bool> + Send + '_>> {
        Box::pin(async move {
            let mut state = self.state.lock().await;
            self.join_locked(&mut state).await;
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
        let state = self.state.get_mut();
        if !state.joined {
            // Losing all supervision is not a completed join. Never advertise
            // it as drained merely because a holder was dropped.
            self.gate.close();
            return;
        }
        drop(state.output.take());
        self.pending.fetch_sub(1, Ordering::AcqRel);
        self.changed.notify_waiters();
        self.gate.notify_original_waiters();
    }
}

#[cfg(test)]
#[path = "same_actor_q24_phase_learning_work_tests.rs"]
mod tests;
