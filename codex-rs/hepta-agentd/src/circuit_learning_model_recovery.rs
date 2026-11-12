//! Read only the original published Model operation after loss or cold restart.
//! The original Model/E peers and original CURRENT, files and witnesses are
//! required again. This path cannot prepare, publish, sign or repair a cut.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitModelPublicationContextV1;
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
use crate::OriginalCellEvaluationModelMaterialClientV1;
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
    context: OriginalCircuitModelPublicationContextV1,
    model: OriginalCellQ24ModelCommandClientV1,
    evaluator: OriginalCellEvaluationModelMaterialClientV1,
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
    let observation = evaluator.begin_model_read().await?;
    context.authenticate_material(observation.material(), started, false)?;
    context.require_model_current(&model, false).await?;
    let (context, task) = tokio::task::spawn_blocking(move || {
        let coordinator = context.authenticate(started, false)?;
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
        binding::require_published(&context, &task, false)?;
        Ok::<_, Error>((context, task))
    }).await.map_err(uncertain)??;
    context.require_model_current(&model, false).await?;
    let material = observation.finish().await?;
    context.authenticate_material(&material, started, false)?;
    Ok(OriginalCircuitModelPublicationV1 { context, task })
}
