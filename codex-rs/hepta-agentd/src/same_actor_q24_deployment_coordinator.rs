//! The concrete ordinary coordinator consumes every real phase event and
//! supplies authenticated, deployment-owned material through the original
//! typed commands. It never submits directly to a task queue or makes Ready.

use std::sync::Arc;

use codex_hepta_intelligence_eval::LockedFileProductQualificationEvidenceSinkV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_types::Digest32;
use tokio::sync::mpsc;

use crate::AgentdError;
use crate::AuthBusObjectiveIngress;
use crate::CellQ24PreparedLearningV1;
use crate::LoadedCellQ24ModelV1;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentProgress;
use crate::same_actor_q24_phase::OriginalSameActorCOutcomeInputsV1;
use crate::same_actor_q24_phase::OriginalSameActorCompletedAInputsV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseCommandV1 as Command;
use crate::same_actor_q24_phase::OriginalSameActorPhaseEventV1 as Event;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

use super::artifacts::OriginalDeploymentArtifacts;
use super::artifacts::OriginalSelectionData;
use super::c::OriginalCResources;
use super::client::OriginalDeploymentClient;
use super::data::OriginalACompletionData;
use super::data::OriginalCOutcomeData;
use super::data::OriginalDeploymentData;
use super::deployment_refused;
use super::exchange::OriginalActorWait;
use super::factory::OriginalCoordinatorMaterials;
use super::files::OriginalDeploymentFiles;
use super::files::OriginalPinnedRead;
use super::ingress::OriginalOrdinaryTaskIngress;
use super::ingress::OriginalOrdinaryTaskStage;
use super::learning::OriginalDeploymentLearning;
use super::outcome_data::OriginalSignedOutcomeData;
use super::task::OriginalInitialPredecessorFiles;

#[path = "same_actor_q24_deployment_coordinator_materials.rs"]
mod materials;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Expected {
    Inputs,
    AInstalled,
    APrepared,
    TrainingOrDecision,
    Decision,
    Artifact,
    Selection,
    CInstalled,
    COutcome,
}

pub(super) struct OriginalDeploymentCoordinator {
    context: Arc<OriginalSameActorRootContext>,
    client: Option<OriginalDeploymentClient>,
    ingress: OriginalOrdinaryTaskIngress,
    commands: mpsc::Sender<Command>,
    events: mpsc::Receiver<Event>,
    data: OriginalDeploymentData,
    files: OriginalDeploymentFiles,
    artifacts: OriginalDeploymentArtifacts,
    learning: OriginalDeploymentLearning,
    initial_model: Arc<LoadedCellQ24ModelV1>,
    initial_bundle: CellCompatibilityBundleV1,
    predecessor: Option<OriginalInitialPredecessorFiles>,
    objective_a: Option<AuthBusObjectiveIngress>,
    objective_c: Option<AuthBusObjectiveIngress>,
    prepared: Option<Arc<CellQ24PreparedLearningV1>>,
    trained_model: Option<Arc<LoadedCellQ24ModelV1>>,
    original_selection: Option<(OriginalSelectionData, Digest32)>,
    evidence_owner: Option<LockedFileProductQualificationEvidenceSinkV1>,
    decision_head: Option<Digest32>,
    pins: Vec<OriginalPinnedRead>,
    expected: Expected,
}

/// A data-stage handoff, not C completion or a normal-retirement grant.
/// Only the real event loop can return it, retaining every actual material
/// owner and its original common-close guard.
pub(super) struct OriginalCoordinatorAtCOutcome {
    _closing: CloseSameActorPhaseOnDrop,
    coordinator: OriginalDeploymentCoordinator,
}

impl OriginalCoordinatorAtCOutcome {
    pub(super) fn require_original_retirement_origin(
        &self,
        identity: &crate::AgentdIdentity,
        gate: &Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        if self.coordinator.context.identity() != identity
            || !Arc::ptr_eq(self.coordinator.context.gate(), gate)
            || self.coordinator.expected != Expected::COutcome
        {
            self.coordinator.context.gate().close();
            return Err(deployment_refused("retained coordinator origin differs"));
        }
        gate.require_open()?;
        Ok(())
    }

    pub(super) fn take_original_retirement_client(
        &mut self,
    ) -> Result<OriginalDeploymentClient, AgentdError> {
        self.coordinator
            .client
            .take()
            .ok_or_else(|| deployment_refused("original progress client was already transferred"))
    }
}

impl OriginalDeploymentCoordinator {
    pub(super) fn new_original(
        context: Arc<OriginalSameActorRootContext>,
        client: OriginalDeploymentClient,
        ingress: OriginalOrdinaryTaskIngress,
        commands: mpsc::Sender<Command>,
        events: mpsc::Receiver<Event>,
        actual: OriginalCoordinatorMaterials,
    ) -> Result<Self, AgentdError> {
        OriginalSameActorRootContext::require_current(&context)?;
        let OriginalCoordinatorMaterials {
            data,
            files,
            artifacts,
            learning,
            initial_model,
            initial_bundle,
            predecessor,
            objective_a,
            objective_c,
            pins,
        } = actual;
        Ok(Self {
            context,
            client: Some(client),
            ingress,
            commands,
            events,
            data,
            files,
            artifacts,
            learning,
            initial_model,
            initial_bundle,
            predecessor: Some(predecessor),
            objective_a: Some(objective_a),
            objective_c: Some(objective_c),
            prepared: None,
            trained_model: None,
            original_selection: None,
            evidence_owner: None,
            decision_head: None,
            pins,
            expected: Expected::Inputs,
        })
    }

    pub(super) fn require_original_context(
        &self,
        context: &Arc<OriginalSameActorRootContext>,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(context, &self.context) {
            return Err(deployment_refused(
                "coordinator belongs to another actual Root context",
            ));
        }
        self.require_original_inputs()
    }

    fn require_original_inputs(&self) -> Result<(), AgentdError> {
        OriginalSameActorRootContext::require_current(&self.context)?;
        for pin in &self.pins {
            OriginalPinnedRead::require_original_pin(pin)?;
        }
        self.artifacts.require_original_paths()?;
        self.files.require_original_context()
    }

    fn send_original(&self, command: Command) -> Result<(), AgentdError> {
        self.require_original_inputs()?;
        self.commands
            .try_send(command)
            .map_err(|_| deployment_refused("actual coordinator command was not delivered"))?;
        self.require_original_inputs()
    }

    fn prepared(&self) -> Result<Arc<CellQ24PreparedLearningV1>, AgentdError> {
        self.prepared
            .as_ref()
            .cloned()
            .ok_or_else(|| deployment_refused("actual Prepared has not been received"))
    }

    fn original_client_mut(&mut self) -> Result<&mut OriginalDeploymentClient, AgentdError> {
        self.client.as_mut().ok_or_else(|| {
            deployment_refused("actual progress client is no longer in the event loop")
        })
    }

    pub(super) async fn run_original(
        mut self,
    ) -> Result<OriginalCoordinatorAtCOutcome, AgentdError> {
        let closing = CloseSameActorPhaseOnDrop::new(self.context.gate());
        loop {
            self.require_original_inputs()?;
            let event = tokio::select! {
                _ = self.context.gate().cancelled() =>
                    return Err(deployment_refused("original deployment phase closed")),
                event = self.events.recv() => event,
            }
            .ok_or_else(|| deployment_refused("original phase event owner stopped"))?;
            self.require_original_inputs()?;
            match (self.expected, event) {
                (Expected::Inputs, Event::InputsOpened { identity, phase }) => {
                    if identity.as_ref() != self.context.identity()
                        || phase != self.context.descriptor().phase
                    {
                        return Err(deployment_refused(
                            "InputsOpened differs from sealed actual context",
                        ));
                    }
                    // This is the actual context-pinned peer. Public event
                    // fields were only compared; they created no capability.
                    OriginalDeploymentClient::exchange_original(
                        self.original_client_mut()?,
                        OriginalDeploymentProgress::InputsOpened,
                    )?;
                    self.send_original(Command::InitialRootEnrolled)?;
                    self.expected = Expected::AInstalled;
                }
                (Expected::AInstalled, Event::OriginalAOwnersInstalled) => {
                    let objective = self
                        .objective_a
                        .take()
                        .ok_or_else(|| deployment_refused("original A was already submitted"))?;
                    self.ingress
                        .submit_original_once(OriginalOrdinaryTaskStage::A, objective)
                        .await?;
                    let mut wait = OriginalActorWait::for_original_task(
                        Arc::clone(&self.context),
                        self.learning.original_a_claim_deadline(),
                    )?;
                    let completion = wait.wait_original_file(
                        &mut self.files,
                        &self.data.completion_a,
                        1024 * 1024,
                    )?;
                    let completed: OriginalACompletionData =
                        OriginalPinnedRead::parse_original(&completion)?;
                    if completed.schema_version != 1
                        || completed.phase != self.context.descriptor().phase
                    {
                        return Err(deployment_refused(
                            "actual A completion file belongs to another phase",
                        ));
                    }
                    let (outcome, signed) =
                        OriginalSignedOutcomeData::into_original(completed.outcome)?;
                    let preparation = completed
                        .preparation
                        .original(Arc::clone(&self.initial_model), &self.initial_bundle)?;
                    let now = wait.require_original_live()?;
                    let freeze = self.learning.open_original_freeze(&mut self.files, now)?;
                    OriginalPinnedRead::require_original_pin(&completion)?;
                    self.send_original(Command::CompleteOriginalA(Box::new(
                        OriginalSameActorCompletedAInputsV1 {
                            outcome,
                            signed,
                            preparation,
                            // This actual ledger was created fresh for A.
                            // The producer adds and authenticates A's own task.
                            history: Vec::new(),
                            freeze,
                        },
                    )))?;
                    self.expected = Expected::APrepared;
                }
                (Expected::APrepared, Event::OriginalAPrepared { prepared, profile }) => {
                    self.receive_prepared_original(prepared, *profile)?;
                    self.expected = Expected::TrainingOrDecision;
                }
                (
                    Expected::TrainingOrDecision,
                    Event::OriginalTraining {
                        snapshot,
                        material,
                        readback,
                    },
                ) => {
                    self.execute_original_b(*snapshot, *material, *readback)?;
                    self.expected = Expected::Decision;
                }
                (
                    Expected::TrainingOrDecision | Expected::Decision,
                    Event::OriginalDecision(snapshot),
                ) => {
                    self.receive_original_decision(*snapshot)?;
                    self.expected = Expected::Artifact;
                }
                (Expected::Artifact, Event::OriginalArtifactAvailable) => {
                    self.receive_original_artifact()?;
                    self.expected = Expected::Selection;
                }
                (Expected::Selection, Event::OriginalSelectionObserved { selection }) => {
                    let (data, expected) = self
                        .original_selection
                        .take()
                        .ok_or_else(|| deployment_refused("actual Selection was not supplied"))?;
                    if selection != expected {
                        return Err(deployment_refused("actual Selection observation differs"));
                    }
                    let prepared = self.prepared()?;
                    let mut wait = OriginalActorWait::for_original_prepared(
                        Arc::clone(&self.context),
                        &prepared,
                    )?;
                    let signed = data.original_signed()?;
                    let predecessor = self.predecessor.take().ok_or_else(|| {
                        deployment_refused("actual A predecessor already transferred")
                    })?;
                    let now = wait.require_original_live()?;
                    let actual = super::c::OriginalCData::open_original(
                        &self.data.original_c,
                        &self.context,
                        &mut self.files,
                        OriginalCResources {
                            initial_model: &self.initial_model,
                            trained_model: self.trained_model.as_ref(),
                            predecessor,
                            learning: &self.learning,
                            selection: &signed,
                            capacity: self.data.learning.owners.successor_queue_capacity,
                            now,
                        },
                    )?;
                    self.await_original_current_material(&actual.canonical_material, &mut wait)?;
                    OriginalDeploymentClient::exchange_original(
                        self.original_client_mut()?,
                        OriginalDeploymentProgress::OriginalSelectionReady {
                            canonical_material: actual.canonical_material,
                        },
                    )?;
                    wait.require_original_live()?;
                    self.send_original(Command::PublishOriginalC(Box::new(actual.inputs)))?;
                    self.expected = Expected::CInstalled;
                }
                (Expected::CInstalled, Event::OriginalCOwnersInstalled) => {
                    let objective = self
                        .objective_c
                        .take()
                        .ok_or_else(|| deployment_refused("original C was already submitted"))?;
                    self.ingress
                        .submit_original_once(OriginalOrdinaryTaskStage::C, objective)
                        .await?;
                    let mut wait = OriginalActorWait::for_original_task(
                        Arc::clone(&self.context),
                        self.learning.original_c_claim_deadline(),
                    )?;
                    let response = wait.wait_original_file(
                        &mut self.files,
                        &self.data.outcome_c,
                        1024 * 1024,
                    )?;
                    let data: OriginalCOutcomeData = OriginalPinnedRead::parse_original(&response)?;
                    if data.schema_version != 1 || data.phase != self.context.descriptor().phase {
                        return Err(deployment_refused(
                            "actual C Outcome belongs to another phase",
                        ));
                    }
                    let (outcome, signed) = OriginalSignedOutcomeData::into_original(data.outcome)?;
                    OriginalPinnedRead::require_original_pin(&response)?;
                    wait.require_original_live()?;
                    self.send_original(Command::ObserveOriginalC(Box::new(
                        OriginalSameActorCOutcomeInputsV1 { outcome, signed },
                    )))?;
                    self.expected = Expected::COutcome;
                }
                (Expected::COutcome, Event::OriginalCOutcomeAccepted(_actual_status)) => {
                    // This event hands custody back to the real joining
                    // owner; it is not C completion. The outer path must still
                    // obtain C/Learning/Circuit/Session caps before seq1.
                    // Keep the actual client, every material owner and both
                    // thread/event-loop failure guards alive across the join.
                    return Ok(OriginalCoordinatorAtCOutcome {
                        _closing: closing,
                        coordinator: self,
                    });
                }
                _ => {
                    return Err(deployment_refused(
                        "original deployment event arrived out of order",
                    ));
                }
            }
        }
    }
}
