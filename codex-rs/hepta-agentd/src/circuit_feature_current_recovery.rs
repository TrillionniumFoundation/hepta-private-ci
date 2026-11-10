//! Rebuild a historical Feature completion from original acknowledged files.
//! A live, authenticated successor publication permits only this scoped read.
//! It cannot reactivate the retired task, admit inference or repair its history.

use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationOpenModeV1;
use codex_hepta_neuron::CellOwnerJournalReadbackV1;
use codex_hepta_neuron::SparseCheckpoint;

use super::*;

pub struct CircuitFeaturePredecessorFilesV1<W: AnchorWitnessStore> {
    pub file: File,
    pub witness: W,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub manifest: CellBackendManifestV2,
    pub maximum_records: usize,
}

// Private and used only by the no-writer readback view. The original live
// successor still checks its actual artifact/FinalUse/Control owners twice.
struct HistoricalRead {
    successor: Arc<LiveGenerationCurrent>,
    publication: PublishedNeuronGenerationUpdateV1,
}
impl CellGenerationCurrentV1 for HistoricalRead {
    fn check_open(&self, binding: &CellGenerationOwnerBindingV1) -> Result<CellGenerationOpenModeV1, CellGenerationErrorV2> {
        self.check_current(binding)?;
        Ok(CellGenerationOpenModeV1::Active)
    }
    fn check_current(&self, binding: &CellGenerationOwnerBindingV1) -> Result<(), CellGenerationErrorV2> {
        if binding != self.publication.previous() { return Err(CellGenerationErrorV2::InvalidBinding); }
        self.successor.check_current(self.publication.target())
    }
}

pub(crate) fn recover_predecessor<CW: AnchorWitnessStore, SW: AnchorWitnessStore>(
    publication: &PublishedNeuronGenerationUpdateV1, current: &Arc<LiveGenerationCurrent>,
    files: CircuitFeaturePredecessorFilesV1<CW>, source: &CircuitTaskSourceReadbackV1<SW>, identity: &AgentdIdentity,
) -> Result<PublishedCircuitFeatureCompletionV1, AgentdError> {
    current.check_current(publication.target()).map_err(invalid)?;
    let previous = publication.previous();
    let scope = previous.scope();
    if !(3..=16).contains(&files.maximum_records)
        || !matches!(publication.completion(), crate::NeuronGenerationPredecessorCompletionV1::OwnerDrained
            | crate::NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel)
        || previous.task_digest() != circuit_feature_task_digest_v1(&files.definition, &files.source)?.into_array()
        || files.manifest.digest().map_err(invalid)? != previous.manifest_digest()
        || files.manifest.bundle_digest != files.definition.bundle_digest.into_array()
        || scope.agent_id != files.source.scope.agent_id.as_str() || scope.cell_id != files.source.scope.cell_id.as_str()
        || scope.run_id != files.source.scope.run_id.as_str() || scope.principal_digest != files.source.scope.principal_digest.into_array()
        || previous.source_frontier() != files.source.source_frontier.into_array()
    { return Err(invalid("cold Feature predecessor differs from original publication")); }
    let before = source.read_run_publication(identity, &files.source.scope.run_id).map_err(invalid)?;
    let input = before.input();
    if input != &source_input(&files.source, input.operation_id.clone()) || before.bundle_digest() != files.definition.bundle_digest {
        return Err(invalid("cold Feature source differs from original task"));
    }
    let digest = canonical_cell_step_request_digest_v1(&files.definition, input).map_err(invalid)?;
    let guard = Arc::new(HistoricalRead { successor: Arc::clone(current), publication: publication.clone() });
    let reader = CellOwnerJournalReadbackV1::open_guarded(files.file, files.witness,
        vec![CellJournalPartitionV1 { scope: files.source.scope.clone(), definition: files.definition,
            source_frontier: files.source.source_frontier, writer_epoch: previous.writer_epoch() }],
        files.maximum_records, previous.clone(), guard).map_err(invalid)?;
    if reader.pending_inference(&input.scope).map_err(invalid)?.is_some() { return Err(invalid("cold Feature predecessor remains pending")); }
    let receipt = reader.lookup(&input.scope, &input.operation_id, digest).map_err(invalid)?
        .ok_or_else(|| invalid("cold Feature predecessor has no committed result"))?;
    before.require_decision(&receipt).map_err(invalid)?;
    let snapshot = reader.snapshot(&input.scope).map_err(invalid)?;
    if snapshot.revision != 1 || snapshot.writer_epoch != previous.writer_epoch()
        || snapshot.checkpoint.as_ref().map(SparseCheckpoint::digest) != Some(receipt.checkpoint_after)
        || receipt.checkpoint_after != before.checkpoint_digest() {
        return Err(invalid("cold Feature predecessor checkpoint differs"));
    }
    if source.read_run_publication(identity, &files.source.scope.run_id).map_err(invalid)? != before {
        return Err(invalid("cold Feature source changed across history read"));
    }
    current.check_current(publication.target()).map_err(invalid)?;
    Ok(PublishedCircuitFeatureCompletionV1 { binding: previous.clone(), manifest: files.manifest, source: before, receipt })
}
