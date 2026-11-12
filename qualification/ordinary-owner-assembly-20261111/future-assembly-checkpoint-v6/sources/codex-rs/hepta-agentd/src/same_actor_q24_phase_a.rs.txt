//! Join the real A owner before the second Root acknowledgement. Admission
//! drain, independent Outcome and a durable GenV2 drain are different facts.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_neuron::FileAnchorWitnessStore;

use super::OriginalPhaseExecution;
use crate::AgentdError;
use crate::CellQ24PreparedLearningV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitTaskRuntimeBootstrapV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::OriginalCellQ24TaskLedgerProducerV1;
use crate::OriginalCellQ24TaskLedgerStatusV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::circuit_task::SameActorTaskRoute;
use crate::same_actor_q24_phase::OriginalSameActorAOwners;
use crate::same_actor_q24_phase::OriginalSameActorPhaseCommandV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseEventV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseHostV1;
use crate::same_actor_q24_phase::phase_owner_error;
use crate::same_actor_q24_phase::phase_refused;
use crate::same_actor_q24_phase_join_client::OriginalDaemonPhaseRetirement;
use crate::same_actor_q24_phase_join_client::OriginalJoinedSameActorA;

struct OriginalAReadback {
    source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    ledger: Arc<OriginalCellQ24TaskLedgerProducerV1>,
    published: PublishedCircuitFeatureTaskV1,
}

struct PreparedOriginalA {
    retirement: OriginalDaemonPhaseRetirement,
    completion: PublishedCircuitFeatureCompletionV1,
}

pub(super) struct JoinedOriginalA {
    pub(super) joined: OriginalJoinedSameActorA,
    pub(super) completion: PublishedCircuitFeatureCompletionV1,
}

enum OriginalAExit {
    Prepared(Result<PreparedOriginalA, AgentdError>),
    Owner(Result<(), AgentdError>),
    Cancelled,
    Closed,
}

impl OriginalPhaseExecution {
    pub(super) async fn run_original_a(
        &self,
        owners: OriginalSameActorAOwners,
        host: &mut OriginalSameActorPhaseHostV1,
    ) -> Result<JoinedOriginalA, AgentdError> {
        self.require_original_execution()?;
        let OriginalSameActorAOwners {
            bootstrap,
            source,
            cell,
            ledger,
            published,
        } = owners;
        let readback = OriginalAReadback {
            source,
            cell,
            ledger,
            published,
        };
        host.notify_original(
            &self.context,
            OriginalSameActorPhaseEventV1::OriginalAOwnersInstalled,
        )?;
        let stop = self.cancellation.child_token();
        let _cancel_on_drop = stop.clone().drop_guard();
        // The outer original bootstrap already owns this required blocking
        // lane. Reuse the real Direct-owner loop and its exact store/identity
        // checks; do not spawn another discardable blocking handle for A.
        let mut work = Box::pin(
            CircuitTaskRuntimeBootstrapV1::run_in_original_successor_lane(
                bootstrap,
                self.store.clone(),
                Arc::clone(&self.state),
                stop.clone(),
            ),
        );
        let exit = {
            let prepare = self.prepare_original_a(&readback, host);
            tokio::pin!(prepare);
            tokio::select! {
                result = work.as_mut() => OriginalAExit::Owner(result),
                result = &mut prepare => OriginalAExit::Prepared(result),
                _ = self.cancellation.cancelled() => OriginalAExit::Cancelled,
                _ = self.context.gate().cancelled() => OriginalAExit::Closed,
            }
        };
        let result = match exit {
            OriginalAExit::Prepared(result) => result,
            OriginalAExit::Owner(result) => {
                self.close_original_execution();
                // This future has already returned; never poll it again.
                drop(work);
                drop(readback);
                return Err(result.err().unwrap_or_else(|| {
                    phase_refused("original A owner stopped before its acknowledged retirement")
                }));
            }
            OriginalAExit::Cancelled => Err(phase_refused("original A phase was cancelled")),
            OriginalAExit::Closed => Err(phase_refused("original A phase is closed")),
        };
        let prepared = match result {
            Ok(prepared) => prepared,
            Err(error) => {
                self.close_original_execution();
                stop.cancel();
                let joined = work.as_mut().await;
                drop(work);
                drop(readback);
                return preserve_original_failure(error, joined);
            }
        };
        // Only FIRST ACK success permits the intentional Initial disconnect.
        // Closing admission alone did not release or replace these owners.
        let released = SameActorTaskRoute::release_original_a(self.route.as_ref());
        if released.is_err() {
            self.close_original_execution();
        }
        stop.cancel();
        let joined = work.as_mut().await;
        // Both the actual loop and every controller-held Active producer,
        // Cell and PublishedTask are gone before sending the second ACK.
        drop(work);
        drop(readback);
        if let Err(error) = released {
            return preserve_original_failure(error, joined);
        }
        joined?;
        self.require_original_execution()?;
        let joined = prepared.retirement.join_after_original_a_drop().await?;
        self.require_original_execution()?;
        Ok(JoinedOriginalA {
            joined,
            completion: prepared.completion,
        })
    }

    async fn prepare_original_a(
        &self,
        original: &OriginalAReadback,
        host: &mut OriginalSameActorPhaseHostV1,
    ) -> Result<PreparedOriginalA, AgentdError> {
        let OriginalSameActorPhaseCommandV1::CompleteOriginalA(inputs) =
            host.receive_original(&self.context).await?
        else {
            return Err(phase_refused(
                "original A requires its independent terminal Outcome",
            ));
        };
        if !matches!(inputs.freeze.open_mode, CircuitQ24TaskOpenModeV1::Create) {
            return Err(phase_refused(
                "this fresh phase requires a new original Evaluator claim",
            ));
        }
        // Existing exact-A tickets may finish. No new request can be built or
        // queued, and no old ticket can later resolve to C.
        SameActorTaskRoute::begin_closing_original_a(self.route.as_ref())?;
        SameActorTaskRoute::wait_original_a_quiescent(self.route.as_ref()).await?;
        self.require_original_execution()?;
        let status = OriginalCellQ24TaskLedgerProducerV1::submit_original_terminal_outcome(
            &original.ledger,
            inputs.outcome,
            &inputs.signed,
        )
        .map_err(phase_owner_error)?;
        if !matches!(status, OriginalCellQ24TaskLedgerStatusV1::Complete { .. }) {
            return Err(phase_refused(
                "original independent Outcome is not complete",
            ));
        }
        self.require_original_execution()?;
        let prepared = Arc::new(
            OriginalCellQ24TaskLedgerProducerV1::prepare_learning(
                &original.ledger,
                inputs.preparation,
                inputs.history,
                inputs.freeze,
            )
            .map_err(phase_owner_error)?,
        );
        self.require_original_execution()?;
        let retained = OriginalCellQ24TaskLedgerProducerV1::retained_learning_source(
            &original.ledger,
            Arc::clone(&prepared),
            self.store.clone(),
        )
        .await?;
        self.require_original_execution()?;
        let completion = PublishedCircuitFeatureTaskV1::drain_completed_task(
            &original.published,
            &original.cell,
            original.source.as_ref(),
            self.context.identity(),
        )?;
        self.require_original_execution()?;
        let profile = CellQ24PreparedLearningV1::root_profile(
            &prepared,
            self.context.identity(),
            self.context
                .bootstrap()
                .writer_proof
                .sha256()?
                .as_str()
                .parse::<codex_hepta_types::Digest32>()
                .map_err(|error| phase_refused(&format!("original writer proof digest: {error}")))?
                .into_array(),
        )
        .map_err(phase_owner_error)?;
        host.notify_original(
            &self.context,
            OriginalSameActorPhaseEventV1::OriginalAPrepared {
                prepared: Arc::clone(&prepared),
                profile: Box::new(profile),
            },
        )?;
        // No original retirement frame or request_started has been created
        // yet. A remains owned by this actual controller until the concrete
        // host reports externally supplied material ready for Root to inspect.
        host.wait_original_deployment_materials(&self.context, &prepared).await?;
        self.require_original_execution()?;
        let retirement = OriginalDaemonPhaseRetirement::begin_original_retirement(
            Arc::clone(&self.context),
            prepared,
            retained,
            Duration::from_millis(500),
        )
        .await?;
        self.require_original_execution()?;
        Ok(PreparedOriginalA {
            retirement,
            completion,
        })
    }
}

fn preserve_original_failure(
    error: AgentdError,
    joined: Result<(), AgentdError>,
) -> Result<JoinedOriginalA, AgentdError> {
    match joined {
        Ok(()) => Err(error),
        Err(join) => Err(phase_owner_error(OriginalAJoinFailure {
            original: error,
            join,
        })),
    }
}

#[derive(Debug, thiserror::Error)]
#[error("original A phase failed: {original}; actual owner join also failed: {join}")]
struct OriginalAJoinFailure {
    #[source]
    original: AgentdError,
    join: AgentdError,
}
