//! Match completed A, the changed Model, distinct C and actual CURRENT.

use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;

use super::Error;
use super::OriginalCircuitModelPublicationContextV1;
use super::OriginalCircuitModelPublicationInputsV1;
use super::now;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::circuit_feature_current::Publication;

pub(super) fn require_inputs<Old: AnchorWitnessStore, New: AnchorWitnessStore>(
    context: &OriginalCircuitModelPublicationContextV1,
    inputs: &OriginalCircuitModelPublicationInputsV1<Old, New>,
) -> Result<(), Error> {
    let coordinator = OriginalCircuitModelPublicationContextV1::authenticate(
        context, now()?, /*new_work*/ true,
    )?;
    require_previous(context, &inputs.completed)?;
    let expected = CellGenerationOwnerBindingV1::new(
        &inputs.predecessor.config,
        inputs.predecessor.max_records,
    ).map_err(|_| Error::Binding("original Model predecessor config"))?;
    let next = &inputs.target.config;
    let source = &inputs.source;
    let definition = &inputs.definition;
    let candidate = coordinator.candidate().ok_or(Error::Binding("actual proposed candidate"))?;
    if inputs.completed.binding != expected
        || inputs.completed.manifest != inputs.predecessor.config.manifest
        || next.manifest == inputs.predecessor.config.manifest
        || source.scope.run_id == inputs.completed.source.input().scope.run_id
        || source.observation == inputs.completed.source.input().observation
        || source.scope.agent_id != context.decision().request.agent_id
        || source.scope.cell_id != context.decision().request.cell_id
        || source.scope.principal_digest.to_string() != context.decision().request.principal_id.as_str()
        || next.initial.scope.agent_id != source.scope.agent_id.as_str()
        || next.initial.scope.cell_id != source.scope.cell_id.as_str()
        || next.initial.scope.run_id != source.scope.run_id.as_str()
        || next.initial.scope.principal_digest != source.scope.principal_digest.into_array()
        || next.task_digest != crate::circuit_feature_task_digest_v1(definition, source)?.into_array()
        || next.source_frontier != source.source_frontier.into_array()
        || next.manifest.bundle_digest != definition.bundle_digest.into_array()
        || next.manifest.state_schema != definition.state_schema_digest.into_array()
        || next.manifest.encoder != Some(definition.runtime.encoder_digest.into_array())
        || next.manifest.head != Some(definition.runtime.head_digest.into_array())
    {
        return Err(Error::Binding("exact drained A and distinct changed-model C"));
    }
    crate::cell_composed_q24::validate_manifest(candidate, &next.manifest)
        .map_err(|_| Error::Binding("complete original candidate Q24 manifest"))?;
    Ok(())
}

fn require_previous(
    context: &OriginalCircuitModelPublicationContextV1,
    previous: &PublishedCircuitFeatureCompletionV1,
) -> Result<(), Error> {
    let request = &context.decision().request;
    let input = previous.source.input();
    if previous.source.history_digest().as_str() != request.completed_task_receipt.to_string()
        || input.scope.run_id != request.source_run_id
        || input.scope.agent_id != request.agent_id
        || input.scope.cell_id != request.cell_id
        || input.scope.principal_digest.to_string() != request.principal_id.as_str()
        || previous.source.bundle_digest() != request.selected_bundle.digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?
        || previous.receipt.checkpoint_after != previous.source.checkpoint_digest()
    {
        return Err(Error::Binding("actual completed A differs from original Model decision"));
    }
    crate::cell_composed_q24::validate_manifest(&request.selected_bundle, &previous.manifest)
        .map_err(|_| Error::Binding("complete original A model"))?;
    Ok(())
}

pub(super) fn require_published(
    context: &OriginalCircuitModelPublicationContextV1,
    task: &PublishedCircuitFeatureTaskV1,
    new_work: bool,
) -> Result<(), Error> {
    let started = now()?;
    let coordinator = context.authenticate(started, new_work)?;
    task.require_current()?;
    let Publication::Update { original, previous } = &task.0.publication else {
        return Err(Error::Binding("changed Model requires an actual update publication"));
    };
    require_previous(context, previous)?;
    let candidate = coordinator.candidate().ok_or(Error::Binding("actual proposed candidate"))?;
    if task.source().scope.run_id == previous.source.input().scope.run_id
        || task.source().observation == previous.source.input().observation
    {
        return Err(Error::Binding("new Model task requires distinct C session and input"));
    }
    let selected = task.0.original.lock()
        .map_err(|_| Error::Binding("original version owner lock"))?
        .selection(original, &coordinator, &previous.manifest)?;
    if !matches!(selected, LearningIterationObservationV1::Selection { candidate_bundle, .. }
        if candidate_bundle == candidate.digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?)
    {
        return Err(Error::Binding("actual published changed-model selection"));
    }
    task.require_bundle(candidate)?;
    context.authenticate(started, new_work)?;
    Ok(())
}
