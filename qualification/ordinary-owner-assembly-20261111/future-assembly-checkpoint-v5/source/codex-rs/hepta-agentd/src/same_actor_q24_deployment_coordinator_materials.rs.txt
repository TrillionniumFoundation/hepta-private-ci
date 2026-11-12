//! Actual external material handoffs at the original Prepared, Training,
//! decision and selected-C boundaries. A ready response is only data; Root,
//! original Artifact, Selector and Evaluation owners still authenticate it.

use std::sync::Arc;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Serialize;

use super::OriginalDeploymentCoordinator;
use crate::{
    AgentdError, CellQ24PreparedLearningV1, HostAuthorityLearningProfileV1,
    OriginalCellQ24TrainingMaterialV1, OriginalCellQ24TrainingReadbackV1,
};
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentProgress;
use crate::same_actor_q24_phase::OriginalSameActorPhaseCommandV1 as Command;

use super::super::data::{
    OriginalArtifactResponse, OriginalEvaluationResponse, OriginalMaterialReady,
    OriginalSelectionResponse,
};
use super::super::evaluation::OriginalExecutedEvaluation;
use super::super::exchange::{OriginalActorExchange, OriginalActorWait};
use super::super::observation_data::{OriginalDecisionNotice, OriginalTrainingNotice};
use super::super::{deployment_error, deployment_refused};

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalPreparedMaterialNotice<'a> {
    schema_version: u32,
    purpose: &'static str,
    phase: &'a str,
    material_digest: [u8; 32],
    actual_profile: &'a HostAuthorityLearningProfileV1,
}
#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalSelectionMaterialNotice<'a> {
    schema_version: u32,
    purpose: &'static str,
    phase: &'a str,
    material_digest: [u8; 32],
    canonical_material: &'a str,
}
#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalArtifactNotice<'a> {
    schema_version: u32,
    purpose: &'static str,
    phase: &'a str,
    original_decision_head: [u8; 32],
}

impl OriginalDeploymentCoordinator {
    pub(super) fn receive_prepared_original(
        &mut self,
        prepared: Arc<CellQ24PreparedLearningV1>,
        profile: HostAuthorityLearningProfileV1,
    ) -> Result<(), AgentdError> {
        if self.prepared.is_some() {
            return Err(deployment_refused("actual Prepared was already consumed"));
        }
        let proof = self.context.bootstrap().writer_proof.sha256()?
            .as_str().parse::<Digest32>().map_err(deployment_error)?.into_array();
        let expected = CellQ24PreparedLearningV1::root_profile(
            &prepared, self.context.identity(), proof,
        ).map_err(deployment_error)?;
        if expected != profile {
            return Err(deployment_refused("APrepared profile differs from the original producer"));
        }
        let mut wait = OriginalActorWait::for_original_prepared(
            Arc::clone(&self.context), &prepared,
        )?;
        let encoded = serde_json::to_vec(&profile).map_err(deployment_error)?;
        let material_digest = Digest32::of_bytes(&encoded);
        let notice = OriginalPreparedMaterialNotice {
            schema_version: 1,
            purpose: "hepta.same-actor-q24-deployment.prepared-material.v1",
            phase: &self.context.descriptor().phase,
            material_digest: material_digest.into_array(), actual_profile: &profile,
        };
        let (request, response) = OriginalActorExchange::new(
            self.data.scoped_material_ready.clone(),
        )?.exchange_original(&notice, &mut self.files, &mut wait)?;
        require_original_material_ready(&response, request, material_digest)?;
        wait.require_original_live()?;
        // This data-only signal is BEFORE A captures its original first
        // request_started. It grants no Root permission and proves no ACK.
        self.send_original(Command::OriginalPreparedMaterialsReady)?;
        // The actual A controller concurrently performs its two original
        // ACKs, drops A's original owners and receives the scoped rights.
        // This synchronous frame has its OWN unchanged original 500 ms end.
        super::super::client::OriginalDeploymentClient::exchange_original(
            self.original_client_mut()?, OriginalDeploymentProgress::OriginalAPrepared { profile },
        )?;
        wait.require_original_live()?;
        let inputs = self.learning.open_original_scoped_inputs(
            Arc::clone(&prepared), &mut self.files, wait.require_original_live()?,
        )?;
        self.prepared = Some(prepared);
        self.send_original(Command::Learning(Box::new(inputs)))
    }

    pub(super) fn execute_original_b(
        &mut self,
        snapshot: LearningIterationSnapshotV1,
        material: OriginalCellQ24TrainingMaterialV1,
        readback: OriginalCellQ24TrainingReadbackV1,
    ) -> Result<(), AgentdError> {
        let prepared = self.prepared()?;
        prepared.scope().validate_snapshot(&snapshot).map_err(deployment_error)?;
        if snapshot.request != prepared.initial().request
            || material.scope() != prepared.scope() || material.training() != &snapshot
            || self.trained_model.is_some() || self.evidence_owner.is_some()
        {
            return Err(deployment_refused("independent B differs from the actual single Training cut"));
        }
        let mut wait = OriginalActorWait::for_original_prepared(
            Arc::clone(&self.context), &prepared,
        )?;
        let (notice, model) = OriginalTrainingNotice::from_original(
            &self.context.descriptor().phase, &snapshot, material,
        )?;
        let (digest, response) = OriginalActorExchange::new(
            self.data.independent_training.clone(),
        )?.exchange_original(&notice, &mut self.files, &mut wait)?;
        let data: OriginalEvaluationResponse = response.parse_original()?;
        if data.schema_version != 1 || data.request_digest != digest.into_array() {
            return Err(deployment_refused("independent B input does not bind this actual Training"));
        }
        response.require_original_pin()?;
        wait.require_original_live()?;
        let OriginalExecutedEvaluation { inputs, evidence_owner } =
            data.original.execute_original(
                &self.context, &prepared, readback, &self.learning, &mut self.files,
            )?;
        // These are the actual retained model and sink, not reconstructed
        // capabilities from the external notification or private receipt bytes.
        self.trained_model = Some(model);
        self.evidence_owner = Some(evidence_owner);
        self.send_original(Command::Evaluation(Box::new(inputs)))
    }

    pub(super) fn receive_original_decision(
        &mut self, snapshot: LearningIterationSnapshotV1,
    ) -> Result<(), AgentdError> {
        let prepared = self.prepared()?;
        prepared.scope().validate_snapshot(&snapshot).map_err(deployment_error)?;
        if snapshot.request != prepared.initial().request || self.decision_head.is_some() {
            return Err(deployment_refused("actual decision belongs to another original request"));
        }
        let mut wait = OriginalActorWait::for_original_prepared(
            Arc::clone(&self.context), &prepared,
        )?;
        let notice = OriginalDecisionNotice::from_original(
            &self.context.descriptor().phase, &snapshot,
        )?;
        let (digest, response) = OriginalActorExchange::new(self.data.artifact_decision.clone())?
            .exchange_original(&notice, &mut self.files, &mut wait)?;
        let data: OriginalArtifactResponse = response.parse_original()?;
        if data.schema_version != 1 || data.request_digest != digest.into_array() {
            return Err(deployment_refused("Artifact input differs from the actual decision"));
        }
        let command = self.artifacts.original_artifact_command(
            &data.original, &mut self.files, wait.require_original_live()?,
        )?;
        response.require_original_pin()?;
        self.decision_head = Some(snapshot.head_digest);
        self.send_original(Command::Artifact(command))
    }

    pub(super) fn receive_original_artifact(&mut self) -> Result<(), AgentdError> {
        let prepared = self.prepared()?;
        let head = self.decision_head
            .ok_or_else(|| deployment_refused("original Artifact has no observed decision"))?;
        let mut wait = OriginalActorWait::for_original_prepared(
            Arc::clone(&self.context), &prepared,
        )?;
        let notice = OriginalArtifactNotice {
            schema_version: 1,
            purpose: "hepta.same-actor-q24-deployment.artifact-available.v1",
            phase: &self.context.descriptor().phase, original_decision_head: head.into_array(),
        };
        let (digest, response) = OriginalActorExchange::new(self.data.independent_selection.clone())?
            .exchange_original(&notice, &mut self.files, &mut wait)?;
        let data: OriginalSelectionResponse = response.parse_original()?;
        if data.schema_version != 1 || data.request_digest != digest.into_array() {
            return Err(deployment_refused("independent Selection response differs"));
        }
        let (selection, digest) = self.artifacts.open_original_selection(
            &data.original, &mut self.files, wait.require_original_live()?,
        )?;
        response.require_original_pin()?;
        self.original_selection = Some((data.original, digest));
        self.send_original(Command::Selection(Box::new(selection)))
    }

    pub(super) fn await_original_current_material(
        &mut self, canonical: &str, wait: &mut OriginalActorWait,
    ) -> Result<(), AgentdError> {
        let material = Digest32::of_bytes(canonical.as_bytes());
        let notice = OriginalSelectionMaterialNotice {
            schema_version: 1,
            purpose: "hepta.same-actor-q24-deployment.selected-current-material.v1",
            phase: &self.context.descriptor().phase, material_digest: material.into_array(),
            canonical_material: canonical,
        };
        let (request, response) = OriginalActorExchange::new(
            self.data.current_material_ready.clone(),
        )?.exchange_original(&notice, &mut self.files, wait)?;
        require_original_material_ready(&response, request, material)?;
        wait.require_original_live()?;
        OriginalSameActorRootContext::require_current(&self.context)
    }
}

fn require_original_material_ready(
    response: &super::super::files::OriginalPinnedRead,
    request: Digest32, material: Digest32,
) -> Result<(), AgentdError> {
    let ready: OriginalMaterialReady = response.parse_original()?;
    if ready.schema_version != 1 || ready.request_digest != request.into_array()
        || ready.material_digest != material.into_array()
    {
        return Err(deployment_refused("external material-ready data differs"));
    }
    // This authenticates no approval. Root's actual finite-purpose handler
    // separately opens and authenticates its original 0600 approval material.
    response.require_original_pin()
}
