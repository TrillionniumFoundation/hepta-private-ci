//! Read-only C source capability from this exact recovered task and Root
//! connection. No old Source/Cell writer, raw identity or supplied completion
//! can construct it. Dataset authorization remains a separate complete join.

use super::*;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::authority_host_service::generation_publication::RootCompletedSuccessorDataV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use serde::Deserialize;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum OriginalSuccessorRecoveryModeV1 {
    CaptureRetired,
    ReadFinalized,
}

struct OriginalHistoricalCircuitFeatureSource {
    task: PublishedCircuitFeatureTaskV1,
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    original_a: Arc<OriginalHistoricalTaskReadReceiptV1>,
    data: RootCompletedSuccessorDataV1,
    failed: AtomicBool,
}

#[derive(Clone)]
pub(crate) struct OriginalHistoricalCircuitFeatureSourcesV1(
    Arc<OriginalHistoricalCircuitFeatureSource>,
);

impl PublishedCircuitFeatureTaskV1 {
    pub(crate) fn recover_original_completed_successor(
        &self,
        original_a: Arc<OriginalHistoricalTaskReadReceiptV1>,
        mode: OriginalSuccessorRecoveryModeV1,
    ) -> Result<OriginalHistoricalCircuitFeatureSourcesV1, AgentdError> {
        self.require_current()?;
        let current = LiveGenerationCurrent::original_historical_successor_current(
            &self.0.current,
            &original_a,
        )?;
        let data = NeuronGenerationCurrentOwnerV1::read_original_completed_successor(
            &current,
            &original_a,
            matches!(mode, OriginalSuccessorRecoveryModeV1::CaptureRetired),
        )?;
        let source = OriginalHistoricalCircuitFeatureSourcesV1(Arc::new(
            OriginalHistoricalCircuitFeatureSource {
                task: self.clone(),
                current,
                original_a,
                data,
                failed: AtomicBool::new(false),
            },
        ));
        source.read_original()?;
        self.require_current()?;
        Ok(source)
    }
}

impl OriginalHistoricalCircuitFeatureSourcesV1 {
    fn read_original(
        &self,
    ) -> Result<(CircuitTaskSourcePublicationV1, CellDecisionReceiptV1), AgentdError> {
        if self.0.failed.load(Ordering::Acquire) {
            return Err(invalid("historical successor reader is fenced"));
        }
        let result = (|| {
            let held = &self.0;
            held.task.require_current()?;
            NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(
                &held.current,
                &held.original_a,
            )?;
            let Publication::Update { original, previous } = &held.task.0.publication else {
                return Err(invalid(
                    "historical source has no original successor publication",
                ));
            };
            let actual_a =
                PublishedCircuitFeatureCompletionV1::read_original_historical_completion(
                    &held.original_a,
                    previous.manifest.clone(),
                )?;
            if actual_a.binding != previous.binding
                || actual_a.source != previous.source
                || actual_a.receipt != previous.receipt
            {
                return Err(invalid("historical A predecessor changed"));
            }
            let data = NeuronGenerationCurrentOwnerV1::read_original_completed_successor(
                &held.current,
                &held.original_a,
                /*capture_retired*/ false,
            )?;
            if data != held.data
                || data.cut.definition
                    != held
                        .task
                        .definition()
                        .semantic_digest()
                        .map_err(invalid)?
                        .to_string()
            {
                return Err(invalid("historical C differs from the original Root cut"));
            }
            let (source, decision) =
                crate::circuit_task::RootHistoricalTaskPublicationDataV1::decode_original_successor_data(
                    &data.cut.publication,
                )
                .map_err(invalid)?;
            let input = source.input();
            if input != &source_input(held.task.source(), input.operation_id.clone())
                || source.bundle_digest() != held.task.definition().bundle_digest
                || data.cut.writer_epoch != original.target().writer_epoch()
            {
                return Err(invalid("historical C differs from original published task"));
            }
            source.require_decision(&decision).map_err(invalid)?;
            held.task.require_current()?;
            NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(
                &held.current,
                &held.original_a,
            )?;
            Ok((source, decision))
        })();
        if result.is_err() {
            self.0.failed.store(true, Ordering::Release);
        }
        result
    }

    pub(crate) fn require_original_feature_binding(
        &self,
        baseline: Digest32,
    ) -> Result<Digest32, AgentdError> {
        let (source, _) = self.read_original()?;
        let Publication::Update { original, previous } = &self.0.task.0.publication else {
            return Err(invalid("original historical successor required"));
        };
        if previous.manifest.bundle_digest != baseline.into_array() {
            return Err(invalid("original historical predecessor bundle differs"));
        }
        let binding = Digest32::of_parts(&[
            b"hepta.agentd.original-feature-learning-source.v1\0",
            original.publication_digest()?.as_array(),
            source.publication_digest().as_array(),
            &previous.manifest.digest().map_err(invalid)?,
        ]);
        self.read_original()?;
        Ok(binding)
    }

    pub(crate) fn read_original_feature_observation(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        role: crate::OriginalGenerationLearningRoleV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())
            .map_err(invalid)?;
        let (source, decision) = self.read_original()?;
        let result = match role {
            crate::OriginalGenerationLearningRoleV1::Selection => {
                self.read_selection(coordinator)?
            }
            crate::OriginalGenerationLearningRoleV1::NextUse => {
                self.read_next_use(coordinator, &source, &decision)?
            }
        };
        self.read_original()?;
        Ok(result)
    }

    fn read_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let Publication::Update { original, previous } = &self.0.task.0.publication else {
            return Err(invalid("original successor selection required"));
        };
        self.0.task.0.original.lock().map_err(invalid)?.selection(
            original,
            coordinator,
            &previous.manifest,
        )
    }

    fn read_next_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        source: &CircuitTaskSourcePublicationV1,
        decision: &CellDecisionReceiptV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        use codex_hepta_learning_artifacts::CellStatePartitionV1;
        use codex_hepta_learning_artifacts::LearningIterationStageV1;
        if coordinator.next_stage() != Some(LearningIterationStageV1::NextUse) {
            return Err(invalid(
                "historical successor is not the required NextUse stage",
            ));
        }
        let mut prefix = coordinator.snapshot().clone();
        let selection = prefix
            .receipts
            .pop()
            .ok_or_else(|| invalid("original selection missing"))?;
        prefix.head_digest = selection.predecessor;
        let prefix = LearningIterationCoordinatorV1::from_snapshot(prefix).map_err(invalid)?;
        let actual = self.read_selection(&prefix)?;
        if actual != selection.observation {
            return Err(invalid("original selection differs during historical read"));
        }
        let LearningIterationObservationV1::Selection {
            candidate_bundle,
            selection_digest,
        } = actual
        else {
            return Err(invalid("original historical selection required"));
        };
        let Publication::Update { original, previous } = &self.0.task.0.publication else {
            return Err(invalid("original historical successor required"));
        };
        if decision.bundle_digest != candidate_bundle
            || previous.source.input().scope.run_id != coordinator.snapshot().request.source_run_id
        {
            return Err(invalid("historical C differs from selected successor"));
        }
        let scope = &decision.scope;
        let state_partition = CellStatePartitionV1 {
            principal_id: StableId::new(scope.principal_digest.to_string()).map_err(invalid)?,
            agent_id: scope.agent_id.clone(),
            cell_id: scope.cell_id.clone(),
            run_id: scope.run_id.clone(),
        };
        let publication = original.publication_digest()?;
        let committed_step_receipt = Digest32::of_parts(&[
            b"hepta.agentd.learning-circuit-feature-use.v1\0",
            source.publication_digest().as_array(),
            &crate::circuit_cell_output::encode_receipt(decision).map_err(invalid)?,
        ]);
        let checkpoint_digest = decision.checkpoint_after;
        Ok(
            if coordinator.next_task_bundle()
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
                let state_cutover_receipt = Digest32::of_parts(&[
                    b"hepta.agentd.learning-published-feature-reset.v1\0",
                    publication.as_array(),
                    &previous.binding.digest().map_err(invalid)?,
                    &original.target().digest().map_err(invalid)?,
                    previous.source.publication_digest().as_array(),
                    previous.receipt.checkpoint_after.as_array(),
                    decision.checkpoint_before.as_array(),
                    self.0
                        .task
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
            },
        )
    }
}
