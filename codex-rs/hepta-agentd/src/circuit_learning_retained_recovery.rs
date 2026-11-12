//! Read-only recovery of one original retained publication after lost ACK.
//! No preparation, publication retry, forward grant or missing-file creation.

use std::sync::Arc;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;

use super::OriginalCircuitRetainedPublicationContextV1;
use super::OriginalCircuitRetainedPublicationErrorV1;
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
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::PublishedCircuitFeatureTaskV1;

/// The original checkpoint and complete original Training attestation are cold
/// expected bytes only. This type is accepted solely by read-only recovery;
/// it cannot create a fresh context or return a prepared publication.
pub struct OriginalCircuitRetainedPublicationRecoveryV1<New, Cell, Source>
where
    New: AnchorWitnessStore,
    Cell: AnchorWitnessStore,
    Source: AnchorWitnessStore,
{
    pub training: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub verifier: LearningEvidenceVerifierV1,
    pub training_evidence: SignedLearningEvidenceV1,
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

pub async fn recover_original_circuit_retained_publication_v1<New, Cell, Source>(
    trainer: OriginalCellQ24TrainingCommandClientV1,
    original: OriginalCircuitRetainedPublicationRecoveryV1<New, Cell, Source>,
) -> Result<PublishedCircuitFeatureTaskV1, OriginalCircuitRetainedPublicationErrorV1>
where
    New: AnchorWitnessStore + Send + 'static,
    Cell: AnchorWitnessStore + Send + 'static,
    Source: AnchorWitnessStore + Send + 'static,
{
    let OriginalCircuitRetainedPublicationRecoveryV1 {
        training, scope, verifier, training_evidence, intent_digest, current,
        authorities, selection, target, definition, source, predecessor,
        original_source, original_identity,
    } = original;
    if intent_digest.is_zero() {
        return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
            "original retained publication intent",
        ));
    }
    let context = OriginalCircuitRetainedPublicationContextV1 {
        training, scope, verifier, training_evidence,
    };
    context.require_training_current(&trainer, PublicationAccess::Readback).await?;
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
            definition, source, predecessor, original_source.as_ref(), &original_identity,
        )?;
        binding::require_published(&context, &task, PublicationAccess::Readback)?;
        if now()? < started {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Clock);
        }
        Ok::<_, OriginalCircuitRetainedPublicationErrorV1>((context, task))
    }).await.map_err(uncertain)??;
    context.require_training_current(&trainer, PublicationAccess::Readback).await?;
    tokio::task::spawn_blocking(move || {
        binding::require_published(&context, &task, PublicationAccess::Readback)?;
        Ok::<_, OriginalCircuitRetainedPublicationErrorV1>(task)
    }).await.map_err(uncertain)?
}
