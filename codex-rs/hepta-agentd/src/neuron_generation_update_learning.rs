//! Learning observations from the original published generation owner.
//!
//! These reads create no selection, signature, checkpoint or Chain record.
//! The host must still attest and durably checkpoint the complete iteration.
//! Cold recovery uses recover_agentd_generation_update_v1 with the original
//! operation and intent; neither read admits work or consumes another nonce.

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ReadyAgentdGenerationUpdateV1;
use crate::AgentdError;
use crate::NeuronGenerationPredecessorCompletionV1;
use crate::PublishedNeuronGenerationUpdateV1;

/// Deterministic identity for the original same-model task operation. This
/// binds the complete evaluated decision cut without changing CURRENT's wire
/// schema or authorizing a grant. The issuer still authenticates that cut.
/// Completed retained-use snapshots recover the same decision predecessor;
/// this identity read cannot reopen a completed iteration stage.
pub fn learning_retained_task_operation_id_v1(
    coordinator: &LearningIterationCoordinatorV1,
) -> Result<StableId, AgentdError> {
    let snapshot = coordinator.snapshot();
    if coordinator.next_task_bundle() != Some(&snapshot.request.selected_bundle) {
        return Err(invalid(
            "retained task requires an evaluated baseline decision",
        ));
    }
    let decision_head = match coordinator.next_stage() {
        Some(LearningIterationStageV1::Selection) => snapshot.head_digest,
        Some(LearningIterationStageV1::NextUse) => {
            snapshot
                .receipts
                .last()
                .ok_or_else(|| invalid("retained task selection is missing"))?
                .predecessor
        }
        None if matches!(
            snapshot.receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::RetainedModelNextUse { .. })
        ) =>
        {
            snapshot
                .receipts
                .iter()
                .find(|receipt| receipt.observation.stage() == LearningIterationStageV1::Selection)
                .ok_or_else(|| invalid("completed retained task selection is missing"))?
                .predecessor
        }
        _ => {
            return Err(invalid(
                "retained task decision is not awaiting or completing baseline use",
            ));
        }
    };
    let digest = Digest32::of_parts(&[
        b"hepta.agentd.learning-retained-task-operation.v1\0",
        snapshot.request.operation_id.as_str().as_bytes(),
        decision_head.as_array(),
    ]);
    StableId::new(format!("learning-retained-task:{digest}")).map_err(invalid)
}

impl<W: AnchorWitnessStore> ReadyAgentdGenerationUpdateV1<W> {
    /// Read the independently signed selection retained by this original
    /// publication, with live CURRENT, withdrawal and retained-use checks.
    /// A learning-role attestation remains separate from this observation.
    /// The request principal ID must be the Cell principal digest's canonical
    /// lowercase hexadecimal StableId, as used by the existing control codec.
    pub fn read_learning_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        GenerationLearningReadbackV1 {
            journal: &self.journal,
            publication: &self.publication,
        }
        .read_selection(coordinator)
    }

    /// Resolve an exact retained intent in this same exclusively held journal.
    /// Pending, failed and cancelled work cannot stand in for actual use. The
    /// caller supplies no purported use, checkpoint or cutover receipt hash.
    pub fn read_learning_next_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        intent: &CellGenerationIntentV2,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        GenerationLearningReadbackV1 {
            journal: &self.journal,
            publication: &self.publication,
        }
        .read_next_use(coordinator, intent)
    }
}

/// Borrow the same guarded journal before or after its ordinary actor handoff.
/// This view neither opens another writer nor authenticates a learning role.
pub(crate) struct GenerationLearningReadbackV1<'a, W: AnchorWitnessStore> {
    pub(crate) journal: &'a CellGenerationJournalV2<W>,
    pub(crate) publication: &'a PublishedNeuronGenerationUpdateV1,
}

impl<W: AnchorWitnessStore> GenerationLearningReadbackV1<'_, W> {
    pub(crate) fn read_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let candidate_bundle =
            self.learning_bundle(coordinator, LearningIterationStageV1::Selection)?;
        Ok(LearningIterationObservationV1::Selection {
            candidate_bundle,
            selection_digest: self.publication.selection_observation_digest(),
        })
    }

    pub(crate) fn read_next_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        intent: &CellGenerationIntentV2,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let candidate_bundle =
            self.learning_bundle(coordinator, LearningIterationStageV1::NextUse)?;
        let selection_digest = self.publication.selection_observation_digest();
        if !matches!(coordinator.snapshot().receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::Selection { selection_digest: expected, .. })
                if *expected == selection_digest)
        {
            return Err(invalid(
                "learning selection differs from the published owner",
            ));
        }
        let receipt = self
            .journal
            .receipt_for_intent(intent)
            .map_err(invalid)?
            .ok_or_else(|| invalid("learning next-task use is not committed"))?;
        if !matches!(
            receipt.disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        ) {
            return Err(invalid("learning next-task result did not adopt work"));
        }
        let observed = self.journal.observe_generation().map_err(invalid)?;
        if intent.task_digest != self.publication.target().task_digest()
            || intent.source_frontier != observed.source_frontier()
        {
            return Err(invalid(
                "learning next-task intent differs from the actual owner",
            ));
        }
        let scope = &observed.snapshot().scope;
        let bytes = serde_json::to_vec(&receipt).map_err(invalid)?;
        let observation = LearningIterationObservationV1::RetainedModelNextUse {
            retained_bundle: candidate_bundle,
            state_partition: CellStatePartitionV1 {
                principal_id: StableId::new(
                    Digest32::from_array(scope.principal_digest).to_string(),
                )
                .map_err(invalid)?,
                agent_id: StableId::new(&scope.agent_id).map_err(invalid)?,
                cell_id: StableId::new(&scope.cell_id).map_err(invalid)?,
                run_id: StableId::new(&scope.run_id).map_err(invalid)?,
            },
            checkpoint_digest: observed.owner_checkpoint(),
            selection_digest,
            committed_step_receipt: Digest32::of_parts(&[
                b"hepta.agentd.learning-next-use-receipt.v1\0",
                &bytes,
            ]),
            task_owner_publication: self.publication.publication_digest()?,
        };
        self.journal.require_current().map_err(invalid)?;
        Ok(observation)
    }

    fn learning_bundle(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        stage: LearningIterationStageV1,
    ) -> Result<Digest32, AgentdError> {
        if coordinator.next_stage() != Some(stage) {
            return Err(invalid(
                "learning observation is not the next required stage",
            ));
        }
        let request = &coordinator.snapshot().request;
        let bundle = coordinator
            .next_task_bundle()
            .ok_or_else(|| invalid("learning decision has no next-task bundle"))?
            .digest()
            .map_err(invalid)?;
        let previous = self.publication.previous();
        let target = self.publication.target();
        let scope = target.scope();
        let operation = learning_retained_task_operation_id_v1(coordinator)?;
        if self.publication.operation_id() != operation.as_str()
            || self.journal.owner_binding() != Some(target)
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
            || target.manifest_digest() != previous.manifest_digest()
            || previous.generation().checked_add(1) != Some(target.generation())
            || previous.writer_epoch().checked_add(1) != Some(target.writer_epoch())
            || self.publication.completion()
                != NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
        {
            return Err(invalid(
                "learning decision differs from the original published task owner",
            ));
        }
        // A healthy journal read checks LiveGenerationCurrent installed by
        // real publish/recover assembly with the same concrete authority owners.
        self.journal.snapshot().map_err(invalid)?;
        Ok(bundle)
    }
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

#[cfg(test)]
#[path = "neuron_generation_update_learning_tests.rs"]
pub(super) mod tests;
