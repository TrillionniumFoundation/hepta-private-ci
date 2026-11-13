//! The two actual bootstrap FinalUse consumer tasks, retained outside the
//! receiving future. A cancelled receive cannot discard either real handle
//! or an owner which the closure has opened but not yet delivered.

use super::refused;
use futures::FutureExt;
use futures::future::BoxFuture;
use futures::future::Shared;
use crate::AgentdError;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use codex_hepta_contracts::FinalUseAuthority;
use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use tokio::task::JoinHandle;

#[derive(Clone, Copy)]
pub(crate) enum OriginalBootstrapConsumerKind {
    Device,
    Notes,
}

struct ConsumersState {
    claimed: u8,
    closed: bool,
    jobs: Vec<Arc<OriginalBootstrapConsumerJob>>,
}

pub(super) struct OriginalBootstrapConsumers {
    state: Mutex<ConsumersState>,
}

pub(crate) struct OriginalBootstrapConsumerAdmission<'a> {
    state: MutexGuard<'a, ConsumersState>,
    gate: Arc<SameActorPhaseGate>,
    armed: bool,
}

struct ConsumerJobState {
    output: Option<Result<FinalUseAuthority, AgentdError>>,
    joined: bool,
    receiving: bool,
    poisoned: bool,
}

pub(crate) struct OriginalBootstrapConsumerJob {
    state: Arc<Mutex<ConsumerJobState>>,
    completion: Shared<BoxFuture<'static, ()>>,
    gate: Arc<SameActorPhaseGate>,
}

impl OriginalBootstrapConsumers {
    pub(super) fn new() -> Self {
        Self {
            state: Mutex::new(ConsumersState {
                claimed: 0,
                closed: false,
                jobs: Vec::new(),
            }),
        }
    }

    pub(super) fn reserve(
        &self,
        kind: OriginalBootstrapConsumerKind,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<OriginalBootstrapConsumerAdmission<'_>, AgentdError> {
        let bit = match kind {
            OriginalBootstrapConsumerKind::Device => 1,
            OriginalBootstrapConsumerKind::Notes => 2,
        };
        let mut state = self.state.lock().map_err(|_| {
            gate.close();
            refused("original bootstrap consumer custody poisoned")
        })?;
        gate.require_open()?;
        if state.closed || state.claimed & bit != 0 {
            gate.close();
            return Err(refused("original bootstrap consumer cannot be reopened"));
        }
        // Claim before the one actual spawn. Failure never re-arms this bit.
        state.claimed |= bit;
        Ok(OriginalBootstrapConsumerAdmission {
            state,
            gate: Arc::clone(gate),
            armed: true,
        })
    }

    pub(super) fn close(&self) {
        let mut state = self.state.lock().unwrap_or_else(|error| error.into_inner());
        state.closed = true;
        for job in &state.jobs {
            job.gate.close();
        }
    }

    pub(super) async fn join_and_release(&self) -> Result<(), AgentdError> {
        let (jobs, poisoned) = {
            let (mut state, poisoned) = match self.state.lock() {
                Ok(state) => (state, false),
                Err(error) => (error.into_inner(), true),
            };
            state.closed = true;
            (state.jobs.clone(), poisoned)
        };
        let mut failure = poisoned.then(|| refused("original bootstrap consumer custody poisoned"));
        for job in jobs {
            job.gate.close();
            job.completion.clone().await;
            let (output, joined, poisoned) = {
                let mut state = job.lock_original_bootstrap_result();
                (state.output.take(), state.joined, state.poisoned)
            };
            if let Some(result) = output {
                // Undelivered owner is released only AFTER its actual task
                // joined. An undelivered original error remains observable.
                match result {
                    Ok(owner) => drop(owner),
                    Err(error) => super::save_original_failure(&mut failure, error),
                }
            }
            if !joined || poisoned {
                super::save_original_failure(
                    &mut failure,
                    refused("original bootstrap consumer terminal custody unavailable"),
                );
            }
        }
        failure.map_or(Ok(()), Err)
    }
}

impl OriginalBootstrapConsumerAdmission<'_> {
    pub(crate) fn retain_original_bootstrap_consumer_handle(
        mut self,
        handle: JoinHandle<Result<FinalUseAuthority, AgentdError>>,
    ) -> Arc<OriginalBootstrapConsumerJob> {
        let state = Arc::new(Mutex::new(ConsumerJobState {
            output: None,
            joined: false,
            receiving: false,
            poisoned: false,
        }));
        let recorded = Arc::clone(&state);
        let gate = Arc::clone(&self.gate);
        // Only this retained Shared future owns and awaits the actual handle.
        // Its unit result is cloneable; the original authority/error is not.
        let completion = async move {
            let result = match handle.await {
                Ok(result) => result,
                Err(error) => Err(AgentdError::Protocol(format!(
                    "original Root production inputs: {error}"
                ))),
            };
            let mut state = recorded.lock().unwrap_or_else(|error| {
                gate.close();
                let mut state = error.into_inner();
                state.poisoned = true;
                state
            });
            // No await separates the actual join and the unique result write.
            state.output = Some(result);
            state.joined = true;
        }
        .boxed()
        .shared();
        let job = Arc::new(OriginalBootstrapConsumerJob {
            state,
            completion,
            gate: Arc::clone(&self.gate),
        });
        self.state.jobs.push(Arc::clone(&job));
        self.armed = false;
        job
    }
}
impl Drop for OriginalBootstrapConsumerAdmission<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.state.closed = true;
            self.gate.close();
        }
    }
}

impl OriginalBootstrapConsumerJob {
    fn lock_original_bootstrap_result(&self) -> MutexGuard<'_, ConsumerJobState> {
        self.state.lock().unwrap_or_else(|error| {
            self.gate.close();
            let mut state = error.into_inner();
            state.poisoned = true;
            state
        })
    }

    pub(crate) fn receive_original(
        self: &Arc<Self>,
    ) -> impl Future<Output = Result<FinalUseAuthority, AgentdError>> + Send + 'static {
        let job = Arc::clone(self);
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        async move {
            {
                let mut state = job.lock_original_bootstrap_result();
                if state.receiving {
                    return Err(refused(
                        "original bootstrap consumer result was already received",
                    ));
                }
                state.receiving = true;
            }
            job.completion.clone().await;
            let output = {
                let mut state = job.lock_original_bootstrap_result();
                if !state.joined {
                    return Err(refused("actual bootstrap consumer join missing"));
                }
                state
                    .output
                    .take()
                    .ok_or_else(|| refused("original bootstrap consumer output missing"))?
            };
            let owner = output?;
            job.gate.require_open()?;
            closing.disarm();
            Ok(owner)
        }
    }
}

#[cfg(test)]
#[path = "production_launcher_same_actor_consumer_custody_tests.rs"]
mod tests;
