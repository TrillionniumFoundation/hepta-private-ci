//! Explicit operator recovery of an unresolved task-boundary update.
//!
//! This replaces only an actual retained Prepared intent. The successor files,
//! exact selection and predecessor cut cannot change. The new operation has a
//! different FinalUse binding; an earlier consumed or expired grant cannot
//! publish it. Ordinary recovery remains read-only.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::NeuronGenerationUpdateReadbackV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update::PreparedAgentdGenerationUpdateV1;
use crate::neuron_generation_update::validate_reset;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

pub struct AgentdGenerationForwardRecoveryV1 {
    pub original_operation_id: String,
    pub original_intent_digest: Digest32,
    pub new_operation_id: String,
}

/// Returns only an explicitly prepared new binding for the existing issuer.
/// It neither signs that binding nor claims an old or new FinalUse grant.
pub fn prepare_agentd_generation_forward_recovery_v1<Old, New>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    old: CellGenerationJournalV2<Old>,
    mut selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<New>,
    request: AgentdGenerationForwardRecoveryV1,
) -> Result<PreparedAgentdGenerationUpdateV1<Old, New>, AgentdError>
where
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
{
    StableId::new(&request.new_operation_id).map_err(invalid)?;
    if request.new_operation_id == request.original_operation_id {
        return Err(invalid(
            "forward recovery needs a different operation identity",
        ));
    }
    let original = current.recover_operation(
        &request.original_operation_id,
        request.original_intent_digest,
    )?;
    if !matches!(
        current.read_operation(&original)?,
        NeuronGenerationUpdateReadbackV1::Prepared
    ) {
        return Err(invalid("published updates use read-only recovery"));
    }
    let binding = validate_reset(&old, &selected, &target, original.completion())?;
    if &binding != original.target()
        || selected.observation().digest() != original.selection_observation_digest()
    {
        return Err(invalid(
            "forward recovery cannot change the original target or selection",
        ));
    }
    let metadata = target.file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err(invalid(
            "forward recovery needs the actual existing genesis",
        ));
    }
    let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
    let old = old.rebind_current(guard).map_err(invalid)?;
    let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
    let new = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        guard,
    )
    .map_err(invalid)?;
    new.prepared_checkpoint().map_err(invalid)?;
    let artifacts = authorities.artifacts.lock().map_err(invalid)?;
    selected.revalidate(&artifacts, authorities.now()?)?;
    let prepared =
        current.prepare_forward_recovery(&original, &old, &new, request.new_operation_id)?;
    drop(artifacts);
    Ok(PreparedAgentdGenerationUpdateV1::from_parts(
        current,
        authorities,
        prepared,
        old,
        new,
        selected,
    ))
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
