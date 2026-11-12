//! Read only an original evaluated-retention publication after lost ACK.
//! This path has no fresh writer factory, prepare call or FinalUse grant.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;

use super::OriginalCircuitEvaluatedRetentionContextV1;
use super::OriginalCircuitRetainedPublicationErrorV1 as Error;
use super::OriginalCircuitRetainedPublicationSelectionV1;
use super::binding;
use super::context::PublicationAccess;
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
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::PublishedCircuitFeatureTaskV1;

/// These are existing original owners and the exact retained Control intent.
/// The complete original B cut remains in context; it is not reconstructed as
/// TrainingNoUpdate and no caller supplies a replacement completed receipt.
pub struct OriginalCircuitEvaluatedRetentionRecoveryV1<New, Cell, Source>
where
    New: AnchorWitnessStore,
    Cell: AnchorWitnessStore,
    Source: AnchorWitnessStore,
{
    pub context: OriginalCircuitEvaluatedRetentionContextV1,
    pub intent_digest: Digest32,
    pub current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub authorities: AgentdGenerationUpdateAuthoritiesV1,
    pub selection: OriginalCircuitRetainedPublicationSelectionV1,
    pub target: AgentdGenerationUpdateTargetV1<New>,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub predecessor: CircuitFeaturePredecessorFilesV1<Cell>,
    pub original_source: Arc<CircuitTaskSourceReadbackV1<Source>>,
    pub original_identity: AgentdIdentity,
}

pub async fn recover_original_circuit_evaluated_retention_v1<New, Cell, Source>(
    trainer: OriginalCellQ24TrainingCommandClientV1,
    evaluator: OriginalCellEvaluationCommandClientV1,
    original: OriginalCircuitEvaluatedRetentionRecoveryV1<New, Cell, Source>,
) -> Result<PublishedCircuitFeatureTaskV1, Error>
where
    New: AnchorWitnessStore + Send + 'static,
    Cell: AnchorWitnessStore + Send + 'static,
    Source: AnchorWitnessStore + Send + 'static,
{
    let OriginalCircuitEvaluatedRetentionRecoveryV1 {
        context,
        intent_digest,
        current,
        authorities,
        selection,
        target,
        definition,
        source,
        predecessor,
        original_source,
        original_identity,
    } = original;
    if intent_digest.is_zero() {
        return Err(Error::Binding(
            "original evaluated-retention publication intent",
        ));
    }
    context
        .require_current(&trainer, &evaluator, PublicationAccess::Readback)
        .await?;
    let (context, task) = tokio::task::spawn_blocking(move || {
        let started = now()?;
        let coordinator = context.authenticate(started, PublicationAccess::Readback)?;
        let operation = crate::learning_retained_task_operation_id_v1(&coordinator)?;
        let selected = load_original_selection(&authorities, selection)?;
        let ready = crate::recover_agentd_generation_update_v1(
            current,
            authorities,
            selected,
            target,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation.to_string(),
                intent_digest,
            },
        )?;
        let task = ready.recover_circuit_feature_task(
            definition,
            source,
            predecessor,
            original_source.as_ref(),
            &original_identity,
        )?;
        binding::require_published_decision(&coordinator, &task)?;
        let finished = now()?;
        if finished < started {
            return Err(Error::Clock);
        }
        context.authenticate(finished, PublicationAccess::Readback)?;
        Ok::<_, Error>((context, task))
    })
    .await
    .map_err(uncertain)??;
    context
        .require_current(&trainer, &evaluator, PublicationAccess::Readback)
        .await?;
    tokio::task::spawn_blocking(move || {
        let started = now()?;
        let coordinator = context.authenticate(started, PublicationAccess::Readback)?;
        binding::require_published_decision(&coordinator, &task)?;
        let finished = now()?;
        if finished < started {
            return Err(Error::Clock);
        }
        context.authenticate(finished, PublicationAccess::Readback)?;
        Ok::<_, Error>(task)
    })
    .await
    .map_err(uncertain)?
}
