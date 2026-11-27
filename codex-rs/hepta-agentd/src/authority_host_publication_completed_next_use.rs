//! Join the complete terminal NextUse to actual original A and retired C DATA.
//! The retained-model branch still publishes the new C task owner; retaining
//! weights does not invent a CURRENT transition or replace a missing one.

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_types::StableId;

use super::*;
use crate::NeuronGenerationPredecessorCompletionV1;
use crate::circuit_task::RootHistoricalTaskPublicationDataV1;

impl OriginalCompletedPublicationReadV1<'_> {
    pub(super) fn require_original_next_use(
        &self,
        context: &OriginalCompletedLearningContextV1<'_>,
        data: &RootCompletedSuccessorDataV1,
    ) -> io::Result<()> {
        let terminal = context.terminal();
        let completed = LearningIterationCoordinatorV1::from_snapshot(terminal.clone())
            .map_err(io::Error::other)?;
        if completed.next_stage().is_some() || terminal.training_no_update_v2().is_some() {
            return Err(io::Error::other(
                "actual evaluated terminal history required",
            ));
        }
        let selected = completed
            .next_task_bundle()
            .ok_or_else(|| io::Error::other("original selected bundle missing"))?;
        let selected_bundle = selected.digest().map_err(io::Error::other)?;
        let original = self.proof.original_profile()?;
        let published = self
            .proof
            .original_current()
            .published
            .as_ref()
            .ok_or_else(|| io::Error::other("first original publication missing"))?;
        let original_a = context.original_task_publication();
        let (a, _) =
            RootHistoricalTaskPublicationDataV1::decode_original_successor_data(&original_a)
                .map_err(io::Error::other)?;
        let (c, cell) = RootHistoricalTaskPublicationDataV1::decode_original_successor_data(
            &data.cut.publication,
        )
        .map_err(io::Error::other)?;
        let target = original.intent.target.scope();
        let scope = &cell.scope;
        let definition = canonical_digest(&data.cut.definition)?;
        canonical_digest(&data.cut.configuration)?;
        canonical_digest(&data.cut.source_checkpoint)?;
        canonical_digest(&data.cut.cell_checkpoint)?;
        if data.cut.source_sequence == 0
            || data.cut.cell_sequence == 0
            || data.cut.writer_epoch != original.intent.target.writer_epoch()
            || a.input().scope.run_id != terminal.request.source_run_id
            || a.input().scope.run_id == c.input().scope.run_id
            || c.bundle_digest() != selected_bundle
            || cell.bundle_digest != selected_bundle
            || cell.checkpoint_after != c.checkpoint_digest()
            || scope.principal_digest.into_array() != target.principal_digest
            || scope.agent_id.as_str() != target.agent_id
            || scope.cell_id.as_str() != target.cell_id
            || scope.run_id.as_str() != target.run_id
            || published.intent != original.intent
        {
            return Err(io::Error::other(
                "original A/C publication and full cut differ",
            ));
        }
        c.require_decision(&cell).map_err(io::Error::other)?;
        let partition = CellStatePartitionV1 {
            principal_id: StableId::new(scope.principal_digest.to_string())
                .map_err(io::Error::other)?,
            agent_id: scope.agent_id.clone(),
            cell_id: scope.cell_id.clone(),
            run_id: scope.run_id.clone(),
        };
        let selection_digest = Digest32::from_array(original.intent.selection);
        let publication_digest = Digest32::of_parts(&[
            b"hepta.agentd.generation-publication.v1\0",
            &serde_json::to_vec(published).map_err(io::Error::other)?,
        ]);
        let committed = Digest32::of_parts(&[
            b"hepta.agentd.learning-circuit-feature-use.v1\0",
            c.publication_digest().as_array(),
            &crate::circuit_cell_output::encode_receipt(&cell).map_err(io::Error::other)?,
        ]);
        let expected = if selected == &terminal.request.selected_bundle {
            if original.intent.completion
                != NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
            {
                return Err(io::Error::other(
                    "retained model requires its original C task publication",
                ));
            }
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle: selected_bundle,
                state_partition: partition,
                checkpoint_digest: cell.checkpoint_after,
                selection_digest,
                committed_step_receipt: committed,
                task_owner_publication: publication_digest,
            }
        } else {
            if original.intent.completion != NeuronGenerationPredecessorCompletionV1::OwnerDrained {
                return Err(io::Error::other(
                    "adopted C requires original model cutover",
                ));
            }
            let reset = Digest32::of_parts(&[
                b"hepta.agentd.learning-published-feature-reset.v1\0",
                publication_digest.as_array(),
                &original
                    .intent
                    .previous
                    .digest()
                    .map_err(io::Error::other)?,
                &original.intent.target.digest().map_err(io::Error::other)?,
                a.publication_digest().as_array(),
                a.checkpoint_digest().as_array(),
                cell.checkpoint_before.as_array(),
                definition.as_array(),
                partition.digest().as_array(),
            ]);
            LearningIterationObservationV1::NextUse {
                candidate_bundle: selected_bundle,
                state_partition: partition,
                checkpoint_digest: cell.checkpoint_after,
                selection_digest,
                committed_step_receipt: committed,
                state_cutover_receipt: reset,
            }
        };
        if terminal.receipts.last().map(|receipt| &receipt.observation) != Some(&expected) {
            return Err(io::Error::other("full original terminal NextUse differs"));
        }
        Ok(())
    }
}

fn canonical_digest(value: &str) -> io::Result<Digest32> {
    let digest = value.parse::<Digest32>().map_err(io::Error::other)?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(io::Error::other("canonical original cut digest required"));
    }
    Ok(digest)
}
