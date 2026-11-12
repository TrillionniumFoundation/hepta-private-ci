//! Actual decision, Artifact/Selection, CURRENT, FinalUse, C source and
//! independent C Outcome. A system error never selects the retention branch.

use std::sync::Arc;
use std::time::Duration;

use super::OriginalPhaseExecution;
use crate::AgentdError;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::CircuitQ24TaskOpenModeV1;
use crate::OriginalCellQ24ArtifactPublicationDriverV1;
use crate::OriginalCellQ24FeatureTargetV1;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::OriginalCellQ24PublicationErrorV1;
use crate::OriginalCellQ24PublishedArtifactForRootV1;
use crate::OriginalCellQ24RetainedArtifactForRootV1;
use crate::OriginalCellQ24RootPublicationDriverV1;
use crate::OriginalCellQ24SelectedArtifactForRootV1;
use crate::OriginalCellQ24TaskLedgerProducerV1;
use crate::OriginalCellQ24TaskLedgerStatusV1;
use crate::OriginalQ24SuccessorFeedbackV1;
use crate::OriginalQ24SuccessorHandoffV1;
use crate::OriginalQ24PreparedSuccessorV1;
use crate::OriginalQ24InstalledSuccessorV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::root_production_learning_inputs::same_actor_phase::OriginalScopedPublicationTicket;
use crate::same_actor_q24_phase::OriginalSameActorArtifactInputsV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseCommandV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseEventV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseHostV1;
use crate::same_actor_q24_phase::phase_owner_error;
use crate::same_actor_q24_phase::phase_refused;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

pub(super) struct OriginalCFlow {
    pub(super) owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
    pub(super) publication: OriginalScopedPublicationTicket,
    pub(super) handoff: OriginalQ24SuccessorHandoffV1,
    pub(super) completion: PublishedCircuitFeatureCompletionV1,
    pub(super) authorities: AgentdGenerationUpdateAuthoritiesV1,
    pub(super) work: Arc<OriginalSameActorLearningWork>,
}

enum OriginalArtifact {
    Published(OriginalCellQ24PublishedArtifactForRootV1),
    Retained(OriginalCellQ24RetainedArtifactForRootV1),
}

impl OriginalPhaseExecution {
    pub(super) async fn publish_and_observe_original_c(
        &self,
        flow: OriginalCFlow,
        host: &mut OriginalSameActorPhaseHostV1,
    ) -> Result<(), AgentdError> {
        self.require_original_execution()?;
        let OriginalCFlow { owners, publication, handoff, completion, authorities, work } = flow;
        owners.require_original_same_actor_work(&work).map_err(phase_owner_error)?;
        // The real retained-source delivery drives the original outbox row.
        // Calling handle.submit here too would duplicate that delivery.
        let snapshot = OriginalQ24SuccessorHandoffV1::decision_snapshot(&handoff)
            .await.map_err(phase_owner_error)?;
        self.require_original_execution()?;
        host.notify_original(
            &self.context, OriginalSameActorPhaseEventV1::OriginalDecision(Box::new(snapshot.clone())),
        )?;
        let OriginalSameActorPhaseCommandV1::Artifact(input) =
            host.receive_original(&self.context).await?
        else {
            return Err(phase_refused("actual learning decision requires an explicit Artifact input"));
        };
        let artifact = match input {
            OriginalSameActorArtifactInputsV1::PublishQualified(request) => {
                let driver: OriginalCellQ24ArtifactPublicationDriverV1 = OriginalCellQ24ArtifactPublicationDriverV1::for_qualified_adoption(
                    owners, snapshot, authorities,
                ).await.map_err(phase_owner_error)?;
                self.require_original_execution()?;
                OriginalArtifact::Published(driver.publish_original_same_actor_candidate(
                    *request, work,
                ).await.map_err(phase_owner_error)?)
            }
            OriginalSameActorArtifactInputsV1::RetainOriginal => {
                // This original method authenticates an actual Retain/Defer/
                // NoUpdate decision. No Err is converted into that decision.
                OriginalArtifact::Retained(
                    OriginalCellQ24RetainedArtifactForRootV1::from_original_result(
                        owners, snapshot, authorities,
                    ).await.map_err(phase_owner_error)?,
                )
            }
        };
        self.require_original_execution()?;
        host.notify_original(&self.context, OriginalSameActorPhaseEventV1::OriginalArtifactAvailable)?;
        let OriginalSameActorPhaseCommandV1::Selection(input) =
            host.receive_original(&self.context).await?
        else {
            return Err(phase_refused("Artifact requires its independent original Selection"));
        };
        let selected: OriginalCellQ24SelectedArtifactForRootV1 = match artifact {
            OriginalArtifact::Published(original) =>
                OriginalCellQ24PublishedArtifactForRootV1::accept_selection(original, *input)
                    .await.map_err(phase_owner_error)?,
            OriginalArtifact::Retained(original) =>
                OriginalCellQ24RetainedArtifactForRootV1::accept_selection(original, *input)
                    .await.map_err(phase_owner_error)?,
        };
        self.require_original_execution()?;
        host.notify_original(
            &self.context,
            OriginalSameActorPhaseEventV1::OriginalSelectionObserved {
                selection: selected.selection_observation().digest(),
            },
        )?;
        let OriginalSameActorPhaseCommandV1::PublishOriginalC(inputs) =
            host.receive_original(&self.context).await?
        else {
            return Err(phase_refused("original selected model requires its exact ordinary C inputs"));
        };
        if !matches!(&inputs.execution.source_mode, CircuitQ24TaskOpenModeV1::Create)
            || !matches!(
                &inputs.execution.feedback,
                OriginalQ24SuccessorFeedbackV1::OriginalLedger(ledger)
                    if ledger.open_mode == CircuitQ24TaskOpenModeV1::Create
            )
        {
            return Err(phase_refused("this phase requires fresh C Source and original Ledger feedback"));
        }
        self.require_original_execution()?;
        // The host notice is not a CURRENT capability. The one actual Root
        // ticket independently checks its enrolled decision/selection/session.
        let driver: OriginalCellQ24RootPublicationDriverV1 = selected.connect_original_same_actor_current(
            publication, Duration::from_millis(500),
        ).await.map_err(phase_owner_error)?;
        self.require_original_execution()?;
        let target = OriginalCellQ24FeatureTargetV1 {
            target: inputs.target, definition: inputs.definition, source: inputs.source,
            model: inputs.model, previous: completion,
        };
        let prepared: OriginalQ24PreparedSuccessorV1 = driver.prepare_original_successor(
            handoff, inputs.predecessor, target, inputs.execution,
        ).await.map_err(phase_owner_error)?;
        // From this point CURRENT may already be durably prepared. Any
        // subsequent failure retains the original uncertainty classification.
        self.require_original_execution().map_err(uncertain_original_c)?;
        let grants: Arc<AgentdUnixFinalUseGrantProvider> = self.context.grants();
        let signed = AgentdUnixFinalUseGrantProvider::request_grant(
            grants.as_ref(), OriginalQ24PreparedSuccessorV1::final_use_binding(&prepared),
        ).map_err(phase_owner_error).map_err(uncertain_original_c)?;
        self.require_original_execution().map_err(uncertain_original_c)?;
        let installed: OriginalQ24InstalledSuccessorV1 =
            OriginalQ24PreparedSuccessorV1::publish(prepared, signed).await.map_err(phase_owner_error)?;
        self.require_original_execution().map_err(uncertain_original_c)?;
        // Only the original worker installs the actual Source, Cell, Producer
        // and Ready slot. This controller never sets that state.
        host.notify_original(&self.context, OriginalSameActorPhaseEventV1::OriginalCOwnersInstalled)?;
        let OriginalSameActorPhaseCommandV1::ObserveOriginalC(input) =
            host.receive_original(&self.context).await?
        else {
            return Err(phase_refused("ordinary C requires its independent terminal business Outcome"));
        };
        self.require_original_execution()?;
        let ledger: Arc<OriginalCellQ24TaskLedgerProducerV1> =
            OriginalQ24InstalledSuccessorV1::original_task_ledger(&installed).ok_or_else(|| {
                phase_refused("original C was installed without its mandatory actual Ledger")
            })?;
        let status = OriginalCellQ24TaskLedgerProducerV1::submit_original_terminal_outcome(
            ledger.as_ref(), input.outcome, &input.signed,
        ).map_err(phase_owner_error)?;
        if !matches!(status, OriginalCellQ24TaskLedgerStatusV1::Complete { .. }) {
            return Err(phase_refused("independent original C Outcome is not complete"));
        }
        self.require_original_execution()?;
        host.notify_original(
            &self.context,
            OriginalSameActorPhaseEventV1::OriginalCOutcomeAccepted(Box::new(status)),
        )?;
        Ok(())
    }
}

fn uncertain_original_c(cause: AgentdError) -> AgentdError {
    phase_owner_error(crate::circuit_q24_successor::prepared_uncertain(
        OriginalCellQ24PublicationErrorV1::Owner(cause),
    ))
}
