//! Learning readback of an actual task-boundary model replacement.
//! This supports the generation owner's published reset only. It neither
//! executes a generic CellBundleCutoverPlan nor claims preserved/migrated state.

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::GenerationLearningReadbackV1;
use super::ReadyAgentdGenerationUpdateV1;
use crate::AgentdError;
use crate::NeuronGenerationPredecessorCompletionV1;

/// Bind the original replacement operation to the complete qualified proposal
/// cut. This identity is not an authorization; the existing issuer must still
/// authenticate the decision before granting the exact replacement intent.
pub fn learning_updated_task_operation_id_v1(
    coordinator: &LearningIterationCoordinatorV1,
) -> Result<StableId, AgentdError> {
    let snapshot = coordinator.snapshot();
    let candidate = coordinator
        .next_task_bundle()
        .ok_or_else(|| invalid("updated task has no selected candidate"))?;
    if candidate == &snapshot.request.selected_bundle || coordinator.candidate() != Some(candidate)
    {
        return Err(invalid(
            "updated task requires the qualified proposed candidate",
        ));
    }
    let decision_head = match coordinator.next_stage() {
        Some(LearningIterationStageV1::Selection) => snapshot.head_digest,
        Some(LearningIterationStageV1::NextUse) => {
            snapshot
                .receipts
                .last()
                .ok_or_else(|| invalid("updated task selection is missing"))?
                .predecessor
        }
        None if matches!(
            snapshot.receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::NextUse { .. })
        ) =>
        {
            snapshot
                .receipts
                .iter()
                .find(|receipt| receipt.observation.stage() == LearningIterationStageV1::Selection)
                .ok_or_else(|| invalid("completed updated task selection is missing"))?
                .predecessor
        }
        _ => {
            return Err(invalid(
                "updated task decision is not awaiting or completing use",
            ));
        }
    };
    let digest = Digest32::of_parts(&[
        b"hepta.agentd.learning-updated-task-operation.v1\0",
        snapshot.request.operation_id.as_str().as_bytes(),
        decision_head.as_array(),
    ]);
    StableId::new(format!("learning-updated-task:{digest}")).map_err(invalid)
}

/// A read-only projection of the existing CURRENT owner's durable model-reset
/// publication, produced only after matching both complete manifests and the
/// original learning decision. Its receipt binds the actual consumed grant,
/// witness, old checkpoint, new initialized genesis and both owner identities.
/// It is not caller-supplied evidence, a new owner or a learning attestation.
struct PublishedLearningGenerationResetV1 {
    candidate_bundle: Digest32,
    state_partition: CellStatePartitionV1,
    receipt: Digest32,
}

impl<W: AnchorWitnessStore> ReadyAgentdGenerationUpdateV1<W> {
    /// Observe a selected candidate from this original publication.
    /// The old manifest is data: its complete digest must match the published
    /// predecessor, and its bundle must be the learning request's baseline.
    pub fn read_learning_updated_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: &CellBackendManifestV2,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        GenerationLearningReadbackV1 {
            journal: &self.journal,
            publication: &self.publication,
        }
        .read_updated_selection(coordinator, previous_manifest)
    }

    /// Read actual successful use after a model reset by the same journal.
    /// This accepts no use/cutover digest and creates no selection or writer.
    pub fn read_learning_updated_next_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: &CellBackendManifestV2,
        intent: &CellGenerationIntentV2,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        GenerationLearningReadbackV1 {
            journal: &self.journal,
            publication: &self.publication,
        }
        .read_updated_next_use(coordinator, previous_manifest, intent)
    }
}

impl<W: AnchorWitnessStore> GenerationLearningReadbackV1<'_, W> {
    pub(crate) fn read_updated_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: &CellBackendManifestV2,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let reset = self.published_learning_reset(
            coordinator,
            previous_manifest,
            LearningIterationStageV1::Selection,
        )?;
        Ok(LearningIterationObservationV1::Selection {
            candidate_bundle: reset.candidate_bundle,
            selection_digest: self.publication.selection_observation_digest(),
        })
    }

    pub(crate) fn read_updated_next_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: &CellBackendManifestV2,
        intent: &CellGenerationIntentV2,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let reset = self.published_learning_reset(
            coordinator,
            previous_manifest,
            LearningIterationStageV1::NextUse,
        )?;
        let selection_digest = self.publication.selection_observation_digest();
        if !matches!(coordinator.snapshot().receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::Selection { selection_digest: expected, .. })
                if *expected == selection_digest)
        {
            return Err(invalid(
                "updated learning selection differs from its published owner",
            ));
        }
        let receipt = self
            .journal
            .receipt_for_intent(intent)
            .map_err(invalid)?
            .ok_or_else(|| invalid("updated learning next-task use is not committed"))?;
        if !matches!(
            receipt.disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        ) {
            return Err(invalid(
                "updated learning next-task result did not adopt work",
            ));
        }
        let observed = self.journal.observe_generation().map_err(invalid)?;
        if intent.task_digest != self.publication.target().task_digest()
            || intent.source_frontier != observed.source_frontier()
        {
            return Err(invalid(
                "updated learning intent differs from the actual owner",
            ));
        }
        let bytes = serde_json::to_vec(&receipt).map_err(invalid)?;
        let observation = LearningIterationObservationV1::NextUse {
            candidate_bundle: reset.candidate_bundle,
            state_partition: reset.state_partition,
            checkpoint_digest: observed.owner_checkpoint(),
            selection_digest,
            committed_step_receipt: Digest32::of_parts(&[
                b"hepta.agentd.learning-next-use-receipt.v1\0",
                &bytes,
            ]),
            state_cutover_receipt: reset.receipt,
        };
        self.journal.require_current().map_err(invalid)?;
        Ok(observation)
    }

    fn published_learning_reset(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: &CellBackendManifestV2,
        stage: LearningIterationStageV1,
    ) -> Result<PublishedLearningGenerationResetV1, AgentdError> {
        if coordinator.next_stage() != Some(stage) {
            return Err(invalid(
                "updated learning observation is not the next required stage",
            ));
        }
        let operation = learning_updated_task_operation_id_v1(coordinator)?;
        let request = &coordinator.snapshot().request;
        let bundle = coordinator
            .next_task_bundle()
            .ok_or_else(|| invalid("updated learning decision has no candidate"))?
            .digest()
            .map_err(invalid)?;
        let previous = self.publication.previous();
        let target = self.publication.target();
        let scope = target.scope();
        if self.publication.operation_id() != operation.as_str()
            || self.journal.owner_binding() != Some(target)
            || previous_manifest.bundle_digest
                != request
                    .selected_bundle
                    .digest()
                    .map_err(invalid)?
                    .into_array()
            || previous_manifest.digest().map_err(invalid)? != previous.manifest_digest()
            || self.journal.manifest().bundle_digest != bundle.into_array()
            || self.journal.manifest().digest().map_err(invalid)? != target.manifest_digest()
            || scope.principal_digest != previous.scope().principal_digest
            || Digest32::from_array(scope.principal_digest).to_string()
                != request.principal_id.as_str()
            || scope.agent_id != request.agent_id.as_str()
            || scope.agent_id != previous.scope().agent_id
            || scope.cell_id != request.cell_id.as_str()
            || scope.cell_id != previous.scope().cell_id
            || previous.scope().run_id != request.source_run_id.as_str()
            || scope.run_id == previous.scope().run_id
            || target.task_digest() == previous.task_digest()
            || target.manifest_digest() == previous.manifest_digest()
            || previous.generation().checked_add(1) != Some(target.generation())
            || previous.writer_epoch().checked_add(1) != Some(target.writer_epoch())
            || !matches!(
                self.publication.completion(),
                NeuronGenerationPredecessorCompletionV1::ModelStopped
                    | NeuronGenerationPredecessorCompletionV1::OwnerDrained
            )
        {
            return Err(invalid(
                "learning candidate differs from the published model replacement",
            ));
        }
        // Ready creation/recovery authenticates the original durable publication
        // and exclusively held initialized journal. Publication required the old
        // ACK/drain and fences it. This final live check also rejects withdrawal,
        // revoked use and a newer CURRENT before deriving any reset evidence.
        self.journal.snapshot().map_err(invalid)?;
        let receipt = Digest32::of_parts(&[
            b"hepta.agentd.learning-published-model-reset.v1\0",
            operation.as_str().as_bytes(),
            &previous.digest().map_err(invalid)?,
            &target.digest().map_err(invalid)?,
            &previous_manifest.digest().map_err(invalid)?,
            bundle.as_array(),
            &target.initial_snapshot_digest(),
            target.genesis_checkpoint().as_array(),
            self.publication.publication_digest()?.as_array(),
        ]);
        Ok(PublishedLearningGenerationResetV1 {
            candidate_bundle: bundle,
            state_partition: CellStatePartitionV1 {
                principal_id: StableId::new(
                    Digest32::from_array(scope.principal_digest).to_string(),
                )
                .map_err(invalid)?,
                agent_id: StableId::new(&scope.agent_id).map_err(invalid)?,
                cell_id: StableId::new(&scope.cell_id).map_err(invalid)?,
                run_id: StableId::new(&scope.run_id).map_err(invalid)?,
            },
            receipt,
        })
    }
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
