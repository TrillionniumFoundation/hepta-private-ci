//! Unsigned read-only translation from actual source, private Cell and original
//! version owners. The separately enrolled Observer still authenticates and
//! checkpoints this observation; this adapter issues no role attestation.

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;

use super::current_read::OriginalPublishedReadCurrent;
use super::*;

impl<W: AnchorWitnessStore> PublishedCircuitCellOwnerV1<W> {
    pub fn read_learning_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let mut current = OriginalPublishedReadCurrent::individual(self);
        self.read_learning_selection_with_current(coordinator, &mut current)
    }

    pub(super) fn read_learning_selection_with_current(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        current: &mut OriginalPublishedReadCurrent<'_, W>,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())
            .map_err(invalid)?;
        OriginalPublishedReadCurrent::require(current, self)?;
        let Publication::Update { original, previous } = &self.task.0.publication else {
            return Err(invalid("initial Feature task is not a learning selection"));
        };
        if previous.source.history_digest().as_str()
            != coordinator
                .snapshot()
                .request
                .completed_task_receipt
                .to_string()
        {
            return Err(invalid(
                "learning selection differs from original completed source",
            ));
        }
        let result = self.task.0.original.lock().map_err(invalid)?.selection(
            original,
            coordinator,
            &previous.manifest,
        )?;
        OriginalPublishedReadCurrent::require(current, self)?;
        Ok(result)
    }

    /// Re-read the still-held original source around actual Cell lookup. A
    /// cloned historical publication cannot bypass current source withdrawal.
    pub fn read_learning_next_use<SW: AnchorWitnessStore>(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let mut current = OriginalPublishedReadCurrent::individual(self);
        self.read_learning_next_use_with_current(coordinator, source, identity, &mut current)
    }

    pub(super) fn read_learning_next_use_with_current<SW: AnchorWitnessStore>(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
        current: &mut OriginalPublishedReadCurrent<'_, W>,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())
            .map_err(invalid)?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::NextUse) {
            return Err(invalid(
                "Feature observation is not the next required stage",
            ));
        }
        let mut prefix = coordinator.snapshot().clone();
        let selection = prefix
            .receipts
            .pop()
            .ok_or_else(|| invalid("Feature selection missing"))?;
        prefix.head_digest = selection.predecessor;
        let prefix = LearningIterationCoordinatorV1::from_snapshot(prefix).map_err(invalid)?;
        let actual_selection = self.read_learning_selection_with_current(&prefix, current)?;
        if actual_selection != selection.observation {
            return Err(invalid(
                "Feature selection differs from original version owner",
            ));
        }
        let LearningIterationObservationV1::Selection {
            candidate_bundle,
            selection_digest,
        } = actual_selection
        else {
            return Err(invalid("original version observation is not selection"));
        };
        let before = source
            .read_run_publication(identity, &self.task.source().scope.run_id)
            .map_err(invalid)?;
        let receipt = PublishedCircuitCellOwnerV1::committed_with_current(self, &before, current)?;
        let Publication::Update { original, previous } = &self.task.0.publication else {
            return Err(invalid("Feature successor lacks original publication"));
        };
        if receipt.bundle_digest != candidate_bundle
            || previous.source.input().scope.run_id != coordinator.snapshot().request.source_run_id
        {
            return Err(invalid(
                "Feature computation differs from selected successor",
            ));
        }
        let scope = &receipt.scope;
        let state_partition = CellStatePartitionV1 {
            principal_id: StableId::new(scope.principal_digest.to_string()).map_err(invalid)?,
            agent_id: scope.agent_id.clone(),
            cell_id: scope.cell_id.clone(),
            run_id: scope.run_id.clone(),
        };
        let publication = original.publication_digest()?;
        let committed_step_receipt = Digest32::of_parts(&[
            b"hepta.agentd.learning-circuit-feature-use.v1\0",
            before.publication_digest().as_array(),
            &crate::circuit_cell_output::encode_receipt(&receipt).map_err(invalid)?,
        ]);
        let checkpoint_digest = receipt.checkpoint_after;
        let result = if coordinator.next_task_bundle()
            == Some(&coordinator.snapshot().request.selected_bundle)
        {
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle: candidate_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                task_owner_publication: publication,
            }
        } else {
            // These are the actual Feature private reset/commit checkpoints,
            // not the unused GenerationV2 journal's placeholder state bytes.
            let state_cutover_receipt = Digest32::of_parts(&[
                b"hepta.agentd.learning-published-feature-reset.v1\0",
                publication.as_array(),
                &previous.binding.digest().map_err(invalid)?,
                &original.target().digest().map_err(invalid)?,
                previous.source.publication_digest().as_array(),
                previous.receipt.checkpoint_after.as_array(),
                receipt.checkpoint_before.as_array(),
                self.task
                    .definition()
                    .semantic_digest()
                    .map_err(invalid)?
                    .as_array(),
                state_partition.digest().as_array(),
            ]);
            LearningIterationObservationV1::NextUse {
                candidate_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                state_cutover_receipt,
            }
        };
        if source
            .read_run_publication(identity, &self.task.source().scope.run_id)
            .map_err(invalid)?
            != before
        {
            return Err(invalid(
                "original Feature source changed across observation",
            ));
        }
        OriginalPublishedReadCurrent::require(current, self)?;
        Ok(result)
    }
}
