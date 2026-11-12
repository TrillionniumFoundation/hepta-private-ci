//! The exact task ticket spans queue transfer and original result observation.
//! Cancelling either its submission or caller closes this one phase.

use codex_hepta_automation::CircuitCommittedTraceV2;

use super::*;
use crate::CircuitTaskLearningPendingV1;
use crate::CircuitTaskLearningReadinessV1;

impl AdmittedOriginalTask {
    pub(super) fn require_original_admission(&self) -> Result<(), Error> {
        let checked = (|| {
            let state = self.route.state.lock().map_err(|_| Error::Unavailable)?;
            self.route.require_ticket_locked(&state, self)
        })();
        if checked.is_err() {
            self.route.close();
        }
        checked
    }
}

impl SameActorTaskAdmission {
    pub(crate) fn build_original_task_request(
        &mut self,
    ) -> Result<CircuitTaskRequestV1, AgentdError> {
        self.original
            .require_original_admission()
            .map_err(task_error)?;
        if self.built.is_some() || self.submitted {
            self.original.route.close();
            return Err(task_error(Error::InvalidBinding));
        }
        let request = self
            .original
            .original
            .invocation
            .build(&self.original.route.identity, &self.original.record)
            .inspect_err(|_| self.original.route.close())?;
        request
            .validate_record(
                &self.original.record,
                self.original.original.handle.generation,
            )
            .map_err(|error| {
                self.original.route.close();
                task_error(error)
            })?;
        self.original
            .require_original_admission()
            .map_err(task_error)?;
        self.built = Some(request.clone());
        Ok(request)
    }

    pub(crate) async fn submit_original_task_request(
        &mut self,
        request: CircuitTaskRequestV1,
    ) -> Result<CircuitTaskReceiptV1, Error> {
        let mut close = CloseSameActorPhaseOnDrop::new(&self.original.route.gate);
        let queued: Result<_, Error> = (|| {
            let route = &self.original.route;
            let state = route.state.lock().map_err(|_| {
                route.gate.close();
                Error::Unavailable
            })?;
            route.require_ticket_locked(&state, &self.original)?;
            if self.submitted || self.built.as_ref() != Some(&request) {
                drop(state);
                route.close();
                return Err(Error::InvalidBinding);
            }
            let original = &self.original.original.handle;
            request.validate_record(&self.original.record, original.generation)?;
            let (response, receive) = oneshot::channel();
            // This same phase guard protects both the admission cut and the
            // transfer to the original queue. There is no uncounted interval.
            self.submitted = true;
            original.pending.fetch_add(1, Ordering::AcqRel);
            original
                .sender
                .try_send(Command {
                    request,
                    record: self.original.record.clone(),
                    mode: CircuitTaskModeV1::Drive,
                    response,
                    _pending: PendingWork(Arc::clone(&original.pending)),
                    phase: Some(SameActorQueuedTask {
                        original: Arc::clone(&self.original),
                    }),
                })
                .map_err(|error| match error {
                    mpsc::error::TrySendError::Full(_) => Error::QueueFull,
                    mpsc::error::TrySendError::Closed(_) => Error::Unavailable,
                })?;
            drop(state);
            Ok(receive)
        })();
        let receive = queued.inspect_err(|_| self.original.route.close())?;
        let result = receive.await.map_err(|_| {
            self.original.route.close();
            Error::CommitUncertain
        })?;
        if result.is_err() {
            self.original.route.close();
            return result;
        }
        self.original.require_original_admission().map_err(|_| {
            self.original.route.close();
            Error::CommitUncertain
        })?;
        close.disarm();
        result
    }

    pub(crate) fn publish_original_task_result(
        &self,
        receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError> {
        self.require_original_phase_execution()?;
        self.original
            .original
            .invocation
            .publish_result(&self.original.route.identity, &self.original.record, receipt)
            .map_err(|error| {
                self.original.route.close();
                AgentdError::Protocol(format!(
                    "same-actor task executed; original source acknowledgement is uncertain: {error}"
                ))
            })?;
        self.require_original_phase_execution()
    }

    pub(crate) async fn observe_original_task_learning(
        &self,
        trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        if self.original.phase == TaskPhase::C {
            return self.observe_original_c_learning(trace).await;
        }
        // The blocking callback retains this same ticket. Dropping its awaiting
        // caller cannot make original source/ledger work invisible to drain.
        let original = Arc::clone(&self.original);
        let trace = trace.clone();
        match tokio::task::spawn_blocking(move || {
            if original.require_original_admission().is_err() {
                return CircuitTaskLearningReadinessV1::Pending(
                    CircuitTaskLearningPendingV1::OwnerUnavailable,
                );
            }
            let invocation: &Arc<dyn AgentdCircuitTaskInvocationProviderV1> =
                &original.original.invocation;
            let ready =
                invocation.observe_learning(&original.route.identity, &original.record, &trace);
            if original.require_original_admission().is_err() {
                CircuitTaskLearningReadinessV1::Pending(
                    CircuitTaskLearningPendingV1::OwnerUnavailable,
                )
            } else {
                ready
            }
        })
        .await
        {
            Ok(ready) => ready,
            Err(error) => {
                // A stopped callback has an unknown effect/acknowledgement
                // state. This differs from a live owner awaiting an Outcome.
                self.original.route.close();
                CircuitTaskLearningReadinessV1::Pending(CircuitTaskLearningPendingV1::Refused(
                    format!("original learning owner observation stopped: {error}"),
                ))
            }
        }
    }

    async fn observe_original_c_learning(
        &self,
        trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.original.route.gate);
        let work = match self.original.route.original_learning_work() {
            Ok(work) => work,
            Err(error) => {
                self.original.route.close();
                return CircuitTaskLearningReadinessV1::Pending(
                    CircuitTaskLearningPendingV1::Refused(error.to_string()),
                );
            }
        };
        let job = {
            let admission = match work.reserve_original_blocking() {
                Ok(admission) => admission,
                Err(error) => {
                    self.original.route.close();
                    return CircuitTaskLearningReadinessV1::Pending(
                        CircuitTaskLearningPendingV1::Refused(error.to_string()),
                    );
                }
            };
            let original = Arc::clone(&self.original);
            let trace = trace.clone();
            let handle = tokio::task::spawn_blocking(move || {
                if original.require_original_admission().is_err() {
                    return Ok::<_, std::convert::Infallible>(
                        CircuitTaskLearningReadinessV1::Pending(
                            CircuitTaskLearningPendingV1::OwnerUnavailable,
                        ),
                    );
                }
                let invocation: &Arc<dyn AgentdCircuitTaskInvocationProviderV1> =
                    &original.original.invocation;
                let ready = invocation.observe_learning(
                    &original.route.identity,
                    &original.record,
                    &trace,
                );
                Ok(if original.require_original_admission().is_err() {
                    CircuitTaskLearningReadinessV1::Pending(
                        CircuitTaskLearningPendingV1::OwnerUnavailable,
                    )
                } else {
                    ready
                })
            });
            // The same actual handle enters the already bound Work registry
            // before any await. A cancelled receiver never detaches that job.
            admission.retain_original_handle(handle)
        };
        match crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork::receive_original_job_with_join_cause(
            &work,
            job,
        )
        .await
        {
            Ok(Ok(ready)) => {
                if self.original.require_original_admission().is_err() {
                    self.original.route.close();
                    return CircuitTaskLearningReadinessV1::Pending(
                        CircuitTaskLearningPendingV1::OwnerUnavailable,
                    );
                }
                // This fact is set only after that actual handle was joined.
                // A C ticket cannot finish from a pending count or task result.
                self.observation_joined.store(true, Ordering::Release);
                closing.disarm();
                ready
            }
            Ok(Err(never)) => match never {},
            Err(error) => {
                self.original.route.close();
                CircuitTaskLearningReadinessV1::Pending(
                    CircuitTaskLearningPendingV1::Refused(format!(
                        "original learning owner observation stopped: {error}"
                    )),
                )
            }
        }
    }

    pub(crate) fn require_original_phase_execution(&self) -> Result<(), AgentdError> {
        if !self.submitted || self.original.require_original_admission().is_err() {
            self.original.route.close();
            return Err(task_error(Error::CommitUncertain));
        }
        Ok(())
    }

    pub(crate) fn finish_original_task(mut self) -> Result<(), AgentdError> {
        self.require_original_phase_execution()?;
        if self.original.phase == TaskPhase::C
            && !self.observation_joined.load(Ordering::Acquire)
        {
            self.original.route.close();
            return Err(task_error(Error::CommitUncertain));
        }
        self.completed = true;
        Ok(())
    }
}

impl Drop for SameActorTaskAdmission {
    fn drop(&mut self) {
        if !self.completed {
            self.original.route.close();
        }
    }
}

impl Drop for AdmittedOriginalTask {
    fn drop(&mut self) {
        let valid = match self.route.state.lock() {
            Ok(mut state) => match state.tickets.checked_sub(1) {
                Some(tickets) => {
                    state.tickets = tickets;
                    true
                }
                None => false,
            },
            Err(_) => false,
        };
        if !valid {
            self.route.close();
        }
        self.route.changed.send_replace(());
        self.route.gate.notify_original_waiters();
    }
}

impl AgentdCircuitTaskInvocationProviderV1 for PhaseInvocation {
    fn build(
        &self,
        _identity: &AgentdIdentity,
        _record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, AgentdError> {
        // The normal signed ingress must obtain the route's exact ticket first.
        self.route.gate.require_open().map_err(phase_error)?;
        Err(task_error(Error::Unavailable))
    }

    fn publish_result(
        &self,
        _identity: &AgentdIdentity,
        _record: &RunStartRecordV1,
        _receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError> {
        self.route.gate.require_open().map_err(phase_error)?;
        Err(task_error(Error::Unavailable))
    }

    fn observe_learning(
        &self,
        _identity: &AgentdIdentity,
        _record: &RunStartRecordV1,
        _trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        // Historical A uses the separate retained-source owner. Current task
        // learning uses its ticket; a fresh route lookup cannot replace either.
        CircuitTaskLearningReadinessV1::Pending(CircuitTaskLearningPendingV1::OwnerUnavailable)
    }
}
