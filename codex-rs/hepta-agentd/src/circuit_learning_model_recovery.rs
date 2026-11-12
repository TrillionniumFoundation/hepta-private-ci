//! Read only the original published Model operation after loss or cold restart.
//! The original Model/E peers and original CURRENT, files and witnesses are
//! required again. This path cannot prepare, publish, sign or repair a cut.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitModelPublicationPredecessorsV1;
use super::OriginalCircuitModelPublicationSelectionV1;
use super::OriginalCircuitModelPublicationV1;
use super::binding;
use super::load_original_selection;
use super::now;
use super::uncertain;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateTargetV1;
use crate::AgentdIdentity;
use crate::CircuitFeaturePredecessorFilesV1;
use crate::CircuitTaskSourceInputV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalCellQ24ModelCommandClientV1;

pub struct OriginalCircuitModelPublicationRecoveryV1<New, Cell, Source>
where
    New: AnchorWitnessStore,
    Cell: AnchorWitnessStore,
    Source: AnchorWitnessStore,
{
    pub intent_digest: Digest32,
    pub current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub authorities: AgentdGenerationUpdateAuthoritiesV1,
    pub selection: OriginalCircuitModelPublicationSelectionV1,
    pub target: AgentdGenerationUpdateTargetV1<New>,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub predecessor: CircuitFeaturePredecessorFilesV1<Cell>,
    pub original_source: Arc<CircuitTaskSourceReadbackV1<Source>>,
    pub original_identity: AgentdIdentity,
}

pub async fn recover_original_circuit_model_publication_v1<New, Cell, Source>(
    predecessors: OriginalCircuitModelPublicationPredecessorsV1,
    model: &OriginalCellQ24ModelCommandClientV1,
    original: OriginalCircuitModelPublicationRecoveryV1<New, Cell, Source>,
) -> Result<OriginalCircuitModelPublicationV1, Error>
where
    New: AnchorWitnessStore + Send + 'static,
    Cell: AnchorWitnessStore + Send + 'static,
    Source: AnchorWitnessStore + Send + 'static,
{
    if original.intent_digest.is_zero() {
        return Err(Error::Binding("original Model publication intent"));
    }
    let started = now()?;
    let observation = model.begin_original_model_read().await?;
    let context = predecessors.with_original_model(observation.model().clone())?;
    observation.require_current(started)?;
    context.authenticate_material(observation.material(), started, /*new_work*/ false)?;
    let (context, task) = tokio::task::spawn_blocking(move || {
        let coordinator = context.authenticate(started, /*new_work*/ false)?;
        let operation = crate::learning_updated_task_operation_id_v1(&coordinator)?;
        let selected = load_original_selection(&original.authorities, original.selection)?;
        let ready = crate::recover_agentd_generation_update_v1(
            original.current,
            original.authorities,
            selected,
            original.target,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation.to_string(),
                intent_digest: original.intent_digest,
            },
        )?;
        let task = ready.recover_circuit_feature_task(
            original.definition,
            original.source,
            original.predecessor,
            original.original_source.as_ref(),
            &original.original_identity,
        )?;
        binding::require_published(&context, &task, /*new_work*/ false)?;
        Ok::<_, Error>((context, task))
    }).await.map_err(uncertain)??;
    let completed = observation.finish().await?;
    if completed.model() != context.model() {
        return Err(Error::Binding("same complete original Model during recovery"));
    }
    let (context, task) = tokio::task::spawn_blocking(move || {
        binding::require_published(&context, &task, /*new_work*/ false)?;
        Ok::<_, Error>((context, task))
    }).await.map_err(uncertain)??;
    context.authenticate_material(completed.material(), started, /*new_work*/ false)?;
    Ok(OriginalCircuitModelPublicationV1 { context, task })
}
