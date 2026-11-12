//! Binding checks before any preparation and on the actual published owner.

use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;

use super::OriginalCircuitRetainedPublicationContextV1;
use super::OriginalCircuitRetainedPublicationErrorV1;
use super::OriginalCircuitRetainedPublicationInputsV1;
use super::context::PublicationAccess;
use super::now;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::circuit_feature_current::Publication;

pub(super) fn require_inputs<Old: AnchorWitnessStore, New: AnchorWitnessStore>(
    context: &OriginalCircuitRetainedPublicationContextV1,
    inputs: &OriginalCircuitRetainedPublicationInputsV1<Old, New>,
) -> Result<(), OriginalCircuitRetainedPublicationErrorV1> {
    context.authenticate(now()?, PublicationAccess::NewWork)?;
    require_previous(context, &inputs.completed)?;
    let expected = CellGenerationOwnerBindingV1::new(
        &inputs.predecessor.config,
        inputs.predecessor.max_records,
    )
    .map_err(|_| {
        OriginalCircuitRetainedPublicationErrorV1::Binding("original predecessor config")
    })?;
    let next = &inputs.target.config;
    let source = &inputs.source;
    let definition = &inputs.definition;
    if inputs.completed.binding != expected
        || inputs.completed.manifest != inputs.predecessor.config.manifest
        || next.manifest != inputs.predecessor.config.manifest
        || source.scope.run_id == inputs.completed.source.input().scope.run_id
        || source.observation == inputs.completed.source.input().observation
        || source.scope.agent_id != context.training.request.agent_id
        || source.scope.cell_id != context.training.request.cell_id
        || source.scope.principal_digest.to_string()
            != context.training.request.principal_id.as_str()
        || next.initial.scope.agent_id != source.scope.agent_id.as_str()
        || next.initial.scope.cell_id != source.scope.cell_id.as_str()
        || next.initial.scope.run_id != source.scope.run_id.as_str()
        || next.initial.scope.principal_digest != source.scope.principal_digest.into_array()
        || next.task_digest
            != crate::circuit_feature_task_digest_v1(definition, source)?.into_array()
        || next.source_frontier != source.source_frontier.into_array()
        || next.manifest.bundle_digest != definition.bundle_digest.into_array()
        || next.manifest.state_schema != definition.state_schema_digest.into_array()
        || next.manifest.encoder != Some(definition.runtime.encoder_digest.into_array())
        || next.manifest.head != Some(definition.runtime.head_digest.into_array())
    {
        return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "exact drained A and distinct retained-model C",
        ));
    }
    crate::cell_composed_q24::validate_manifest(
        &context.training.request.selected_bundle,
        &next.manifest,
    )
    .map_err(|_| {
        OriginalCircuitRetainedPublicationErrorV1::Binding("complete retained Q24 manifest")
    })?;
    Ok(())
}

fn require_previous(
    context: &OriginalCircuitRetainedPublicationContextV1,
    previous: &PublishedCircuitFeatureCompletionV1,
) -> Result<(), OriginalCircuitRetainedPublicationErrorV1> {
    let request = &context.training.request;
    let input = previous.source.input();
    if previous.source.history_digest().as_str() != request.completed_task_receipt.to_string()
        || input.scope.run_id != request.source_run_id
        || input.scope.agent_id != request.agent_id
        || input.scope.cell_id != request.cell_id
        || input.scope.principal_digest.to_string() != request.principal_id.as_str()
        || previous.source.bundle_digest()
            != request
                .selected_bundle
                .digest()
                .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?
        || previous.receipt.checkpoint_after != previous.source.checkpoint_digest()
    {
        return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "actual completed A differs from original Training request",
        ));
    }
    crate::cell_composed_q24::validate_manifest(&request.selected_bundle, &previous.manifest)
        .map_err(|_| {
            OriginalCircuitRetainedPublicationErrorV1::Binding("complete original A model")
        })?;
    Ok(())
}

/// Read the actual original version publication, without opening a Cell writer
/// or fabricating a Selector receipt. The separate Selector must still attest.
pub(super) fn require_published(
    context: &OriginalCircuitRetainedPublicationContextV1,
    task: &PublishedCircuitFeatureTaskV1,
    access: PublicationAccess,
) -> Result<(), OriginalCircuitRetainedPublicationErrorV1> {
    let started = now()?;
    let coordinator = context.authenticate(started, access)?;
    task.require_current()?;
    let Publication::Update { original, previous } = &task.0.publication else {
        return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "retained task requires actual update publication",
        ));
    };
    require_previous(context, previous)?;
    let selected = task
        .0
        .original
        .lock()
        .map_err(|_| {
            OriginalCircuitRetainedPublicationErrorV1::Binding("original version owner lock")
        })?
        .selection(original, &coordinator, &previous.manifest)?;
    if !matches!(selected, LearningIterationObservationV1::Selection { candidate_bundle, .. }
        if candidate_bundle == context.training.request.selected_bundle.digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?)
    {
        return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "original retained version selection",
        ));
    }
    task.require_bundle(&context.training.request.selected_bundle)?;
    let finished = now()?;
    if finished < started {
        return Err(OriginalCircuitRetainedPublicationErrorV1::Clock);
    }
    context.authenticate(finished, access)?;
    Ok(())
}
