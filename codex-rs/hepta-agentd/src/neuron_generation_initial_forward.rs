//! Explicit new-signature recovery of an unresolved initial publication.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;
use crate::neuron_generation_initial::PreparedAgentdGenerationInitialV1;
use crate::neuron_generation_initial::validate_initial_target;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_forward::AgentdGenerationForwardRecoveryV1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

/// Preserve the original files and selection while preparing a different
/// external FinalUse binding. This does not refund or reuse a consumed nonce.
pub fn prepare_agentd_generation_initial_forward_recovery_v1<W: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<W>,
    request: AgentdGenerationForwardRecoveryV1,
) -> Result<PreparedAgentdGenerationInitialV1<W>, AgentdError> {
    StableId::new(&request.new_operation_id).map_err(invalid)?;
    if request.new_operation_id == request.original_operation_id {
        return Err(invalid("initial forward recovery needs a new operation"));
    }
    let original = current.recover_initial_operation(
        &request.original_operation_id,
        request.original_intent_digest,
    )?;
    if !matches!(
        current.read_initial_operation(&original)?,
        NeuronGenerationInitialReadbackV1::Prepared
    ) {
        return Err(invalid("published initial owners use read-only recovery"));
    }
    if &validate_initial_target(&selected, &target)? != original.target()
        || selected.observation().digest() != original.selection_observation_digest()
    {
        return Err(invalid("initial forward target or selection differs"));
    }
    let metadata = target.file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err(invalid(
            "initial forward recovery requires retained genesis",
        ));
    }
    let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
    let journal = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        guard,
    )
    .map_err(invalid)?;
    journal.prepared_checkpoint().map_err(invalid)?;
    let artifacts = authorities.artifacts.lock().map_err(invalid)?;
    selected.revalidate(&artifacts, authorities.now()?)?;
    let prepared =
        current.prepare_initial_forward_recovery(&original, &journal, request.new_operation_id)?;
    drop(artifacts);
    Ok(PreparedAgentdGenerationInitialV1::from_parts(
        current,
        authorities,
        prepared,
        journal,
        selected,
    ))
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
