//! Consume the actual post-A Root rights, then supervise concrete Learning,
//! retained delivery and C. A completed host step is never a worker join.

use std::os::unix::net::UnixDatagram;
use std::sync::Arc;
use std::time::Duration;

use super::OriginalPhaseExecution;
use super::original_a::JoinedOriginalA;
use crate::AgentdError;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::circuit_task::SameActorTaskRoute;
use crate::root_production_learning_inputs::same_actor_phase::receive_original_same_actor_scoped_owners;
use crate::same_actor_q24_phase::OriginalSameActorPhaseCommandV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseHostV1;
use crate::same_actor_q24_phase::phase_owner_error;
use crate::same_actor_q24_phase::phase_refused;
use crate::same_actor_q24_phase_join_client::OriginalJoinedSameActorA;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningCleanup;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWorker;
use crate::same_actor_q24_phase_learning::PreparedLearningActivation;
use crate::same_actor_q24_phase_learning::PreparedLearningBuilder;

#[path = "same_actor_q24_phase_publish.rs"]
mod publish;
use publish::OriginalCFlow;

enum OriginalScopedExit {
    Progress(Result<(), AgentdError>),
    Worker(Result<(), AgentdError>),
    Cancelled,
    Closed,
}

impl OriginalPhaseExecution {
    pub(super) async fn run_original_scoped(
        &self,
        original: JoinedOriginalA,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        socket: UnixDatagram,
        host: &mut OriginalSameActorPhaseHostV1,
    ) -> Result<(), AgentdError> {
        self.require_original_execution()?;
        let prepared = Arc::clone(OriginalJoinedSameActorA::prepared(&original.joined));
        let scoped = {
            let receive = receive_original_same_actor_scoped_owners(
                socket,
                original.joined,
                Duration::from_millis(500),
            );
            tokio::pin!(receive);
            tokio::select! {
                result = &mut receive => result,
                _ = self.cancellation.cancelled() => {
                    self.close_original_execution();
                    Err(phase_refused("scoped original owner receive was cancelled"))
                }
                _ = self.context.gate().cancelled() => {
                    self.close_original_execution();
                    Err(phase_refused("scoped original owner receive is closed"))
                }
            }
        }?;
        self.require_original_execution()?;
        let OriginalSameActorPhaseCommandV1::Learning(inputs) =
            host.receive_original(&self.context).await?
        else {
            return Err(phase_refused(
                "original scoped owners require actual Learning materials",
            ));
        };
        if !Arc::ptr_eq(&inputs.original.prepared, &prepared) {
            return Err(phase_refused(
                "Learning materials differ from the actual joined Prepared",
            ));
        }
        let capacity = inputs.successor_queue_capacity;
        let builder = PreparedLearningBuilder::new(scoped, inputs.original)?;
        // These capabilities exist before any assembly future is polled.
        // The task route counts real retained jobs, not a worker-present flag.
        let cleanup = builder.cleanup();
        let result = SameActorTaskRoute::attach_original_learning_work(
            self.route.as_ref(),
            Arc::clone(cleanup.work()),
        );
        if let Err(error) = result {
            self.close_original_execution();
            drop(builder);
            let joined = cleanup.close_and_join_original_work().await;
            return preserve_scoped_result(Err(error), joined, "unstarted assembly custody");
        }
        let assembled = {
            let assemble = builder.assemble(capacity);
            tokio::pin!(assemble);
            tokio::select! {
                result = &mut assemble => result,
                _ = self.cancellation.cancelled() => {
                    self.close_original_execution();
                    Err(phase_refused("original Learning assembly was cancelled"))
                }
                _ = self.context.gate().cancelled() => {
                    self.close_original_execution();
                    Err(phase_refused("original Learning assembly is closed"))
                }
            }
            // Leaving this block actually drops the waiting process future;
            // original cancellation/fence guards run before terminal cleanup.
        };
        let activation = match assembled {
            Ok(activation) => activation,
            Err(error) => {
                self.close_original_execution();
                let joined = cleanup.close_and_join_original_work().await;
                return preserve_scoped_result(Err(error), joined, "assembly blocking work");
            }
        };
        let result = self
            .run_original_activated(activation, &cleanup, original.completion, authorities, host)
            .await;
        self.close_original_execution();
        // The concrete lane worker and the publication future have both ended
        // before this final cleanup can wait for their last retained job Arc.
        let joined = cleanup.close_and_join_original_work().await;
        preserve_scoped_result(result, joined, "retained Learning blocking work")
    }

    async fn run_original_activated(
        &self,
        activation: PreparedLearningActivation,
        cleanup: &OriginalSameActorLearningCleanup,
        completion: PublishedCircuitFeatureCompletionV1,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        host: &mut OriginalSameActorPhaseHostV1,
    ) -> Result<(), AgentdError> {
        self.require_original_execution()?;
        let (_handle, owners, publication, handoff, successor, worker) =
            activation.into_original_parts()?;
        SameActorTaskRoute::install_original_c(self.route.as_ref(), successor)?;
        self.require_original_execution()?;
        let stop = self.cancellation.child_token();
        let _cancel_on_drop = stop.clone().drop_guard();
        let mut work = Box::pin(OriginalSameActorLearningWorker::run(
            worker,
            self.store.clone(),
            Arc::clone(&self.state),
            stop.clone(),
        ));
        let flow = OriginalCFlow {
            owners,
            publication,
            handoff,
            completion,
            authorities,
            work: Arc::clone(cleanup.work()),
        };
        let first = {
            let progress = self.publish_and_observe_original_c(flow, host);
            tokio::pin!(progress);
            tokio::select! {
                result = work.as_mut() => OriginalScopedExit::Worker(result),
                result = &mut progress => OriginalScopedExit::Progress(result),
                _ = self.cancellation.cancelled() => OriginalScopedExit::Cancelled,
                _ = self.context.gate().cancelled() => OriginalScopedExit::Closed,
            }
            // Do not retain an unpolled publication/process future while
            // waiting for the Work registry to release its actual owner result.
        };
        let exit = match first {
            OriginalScopedExit::Progress(Ok(())) => {
                // C really ran and its independent Outcome was accepted.
                // Keep serving under the same original deadlines. This is no
                // new phase, rearm, Root shutdown ACK, or successful EOF proof.
                tokio::select! {
                    result = work.as_mut() => OriginalScopedExit::Worker(result),
                    _ = self.cancellation.cancelled() => OriginalScopedExit::Cancelled,
                    _ = self.context.gate().cancelled() => OriginalScopedExit::Closed,
                }
            }
            other => other,
        };
        self.close_original_execution();
        stop.cancel();
        let result = match exit {
            OriginalScopedExit::Worker(result) => {
                // Already completed and internally joined by the concrete
                // worker. Never poll its future a second time.
                drop(work);
                return result
                    .and_then(|()| Err(phase_refused("original required C worker stopped")));
            }
            OriginalScopedExit::Progress(result) => result,
            OriginalScopedExit::Cancelled => Err(phase_refused("original C phase was cancelled")),
            OriginalScopedExit::Closed => Err(phase_refused("original C phase is closed")),
        };
        let joined = work.as_mut().await;
        drop(work);
        preserve_scoped_result(result, joined, "concrete Learning/delivery/C worker")
    }
}

fn preserve_scoped_result(
    original: Result<(), AgentdError>,
    cleanup: Result<(), AgentdError>,
    stage: &'static str,
) -> Result<(), AgentdError> {
    match (original, cleanup) {
        (Ok(()), result) => result,
        (Err(error), Ok(())) => Err(error),
        (Err(original), Err(cleanup)) => Err(phase_owner_error(OriginalScopedCleanupFailure {
            stage,
            original,
            cleanup,
        })),
    }
}

#[derive(Debug, thiserror::Error)]
#[error("original phase failed: {original}; actual {stage} cleanup also failed: {cleanup}")]
struct OriginalScopedCleanupFailure {
    stage: &'static str,
    #[source]
    original: AgentdError,
    cleanup: AgentdError,
}
