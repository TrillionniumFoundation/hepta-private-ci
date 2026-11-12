//! Publish the unchanged model after a complete independent negative result.
//! The separate Artifact selector, CURRENT owner and exact FinalUse grant stay
//! mandatory. This stage does not attest Selection, execute C or enroll Root.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;

use super::OriginalCircuitEvaluatedRetentionContextV1;
use super::OriginalCircuitRetainedPublicationErrorV1 as Error;
use super::OriginalCircuitRetainedPublicationInputsV1;
use super::QueuedPublicationFence;
use super::binding;
use super::context::PublicationAccess;
use super::load_original_selection;
use super::now;
use super::require_not_cancelled;
use super::uncertain;
use crate::AgentdGenerationUpdateRequestV1;
use crate::CircuitTaskSourceInputV1;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::PreparedAgentdGenerationUpdateV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;

/// Non-Clone custody of one actual preparation. Both original readback clients
/// survive until publication. No getter supplies a role signer or retry right.
pub struct PreparedOriginalCircuitEvaluatedRetentionV1<
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
> {
    context: OriginalCircuitEvaluatedRetentionContextV1,
    trainer: OriginalCellQ24TrainingCommandClientV1,
    evaluator: OriginalCellEvaluationCommandClientV1,
    prepared: PreparedAgentdGenerationUpdateV1<Old, New>,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
    completed: PublishedCircuitFeatureCompletionV1,
}

/// Consume original owner capabilities only after actual Trainer and Evaluator
/// readback. A failure after preparation remains uncertain; callers retain the
/// original Control intent and must not repeat this as fresh work.
pub async fn prepare_original_circuit_evaluated_retention_v1<Old, New>(
    context: OriginalCircuitEvaluatedRetentionContextV1,
    trainer: OriginalCellQ24TrainingCommandClientV1,
    evaluator: OriginalCellEvaluationCommandClientV1,
    inputs: OriginalCircuitRetainedPublicationInputsV1<Old, New>,
) -> Result<PreparedOriginalCircuitEvaluatedRetentionV1<Old, New>, Error>
where
    Old: AnchorWitnessStore + Send + 'static,
    New: AnchorWitnessStore + Send + 'static,
{
    context
        .require_current(&trainer, &evaluator, PublicationAccess::NewWork)
        .await?;
    binding::require_inputs_for_request(&context.snapshot().request, &inputs)?;
    let queued = QueuedPublicationFence::new();
    let cancelled = Arc::clone(&queued.cancelled);
    let (context, prepared, definition, source, completed) =
        tokio::task::spawn_blocking(move || {
            let started = now()?;
            let coordinator = context.authenticate(started, PublicationAccess::NewWork)?;
            require_not_cancelled(&cancelled)?;
            binding::require_inputs_for_request(&coordinator.snapshot().request, &inputs)?;
            let operation = crate::learning_retained_task_operation_id_v1(&coordinator)?;
            let selected = load_original_selection(&inputs.authorities, inputs.selection)?;
            if selected.manifest() != &inputs.target.config.manifest {
                return Err(Error::Binding(
                    "selected original artifact differs from retained manifest",
                ));
            }
            let before = now()?;
            if before < started {
                return Err(Error::Clock);
            }
            context.authenticate(before, PublicationAccess::NewWork)?;
            require_not_cancelled(&cancelled)?;
            let prepared = crate::prepare_agentd_generation_cold_same_model_task_v1(
                inputs.current,
                inputs.authorities,
                inputs.predecessor,
                selected,
                inputs.target,
                AgentdGenerationUpdateRequestV1 {
                    operation_id: operation.to_string(),
                },
            )
            .map_err(uncertain)?;
            let after = now().map_err(uncertain)?;
            if after < before {
                return Err(uncertain(Error::Clock));
            }
            context
                .authenticate(after, PublicationAccess::NewWork)
                .map_err(uncertain)?;
            Ok::<_, Error>((
                context,
                prepared,
                inputs.definition,
                inputs.source,
                inputs.completed,
            ))
        })
        .await
        .map_err(uncertain)??;
    drop(queued);
    context
        .require_current(&trainer, &evaluator, PublicationAccess::NewWork)
        .await
        .map_err(uncertain)?;
    Ok(PreparedOriginalCircuitEvaluatedRetentionV1 {
        context,
        trainer,
        evaluator,
        prepared,
        definition,
        source,
        completed,
    })
}

impl<Old: AnchorWitnessStore + Send + 'static, New: AnchorWitnessStore + Send + 'static>
    PreparedOriginalCircuitEvaluatedRetentionV1<Old, New>
{
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.prepared.final_use_binding()
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.prepared.intent_digest()
    }

    /// Only the independent original grant may publish this exact intent.
    /// Lost ACK, cancellation or a changed owner never becomes another prepare.
    pub async fn publish_original_retained_task(
        self,
        signed: SignedFinalUseGrant,
    ) -> Result<PublishedCircuitFeatureTaskV1, Error> {
        self.publish_and_retain_original_evidence(signed)
            .await
            .map(|(task, _trainer, _evaluator)| task)
    }

    /// Internal continuation custody of the same finite original connections.
    /// This consumes the preparation; it cannot clone, reconnect, renew or
    /// replace either original owner or turn a failed publication into a retry.
    pub(crate) async fn publish_and_retain_original_evidence(
        self,
        signed: SignedFinalUseGrant,
    ) -> Result<
        (
            PublishedCircuitFeatureTaskV1,
            OriginalCellQ24TrainingCommandClientV1,
            OriginalCellEvaluationCommandClientV1,
        ),
        Error,
    > {
        self.context
            .require_current(&self.trainer, &self.evaluator, PublicationAccess::NewWork)
            .await
            .map_err(uncertain)?;
        let queued = QueuedPublicationFence::new();
        let cancelled = Arc::clone(&queued.cancelled);
        let Self {
            context,
            trainer,
            evaluator,
            prepared,
            definition,
            source,
            completed,
        } = self;
        let (context, task) = tokio::task::spawn_blocking(move || {
            // The original preparation already has a durable intent. Even a
            // pre-publication refusal must preserve same-operation recovery.
            let started = now().map_err(uncertain)?;
            context
                .authenticate(started, PublicationAccess::NewWork)
                .map_err(uncertain)?;
            require_not_cancelled(&cancelled).map_err(uncertain)?;
            let ready =
                PreparedAgentdGenerationUpdateV1::publish(prepared, &signed).map_err(uncertain)?;
            let task = ready
                .into_circuit_feature_task(definition, source, completed)
                .map_err(uncertain)?;
            let coordinator = context
                .authenticate(now().map_err(uncertain)?, PublicationAccess::NewWork)
                .map_err(uncertain)?;
            binding::require_published_decision(&coordinator, &task).map_err(uncertain)?;
            if now().map_err(uncertain)? < started {
                return Err(uncertain(Error::Clock));
            }
            Ok::<_, Error>((context, task))
        })
        .await
        .map_err(uncertain)??;
        drop(queued);
        context
            .require_current(&trainer, &evaluator, PublicationAccess::NewWork)
            .await
            .map_err(uncertain)?;
        let task = tokio::task::spawn_blocking(move || {
            let started = now().map_err(uncertain)?;
            let coordinator = context
                .authenticate(started, PublicationAccess::NewWork)
                .map_err(uncertain)?;
            binding::require_published_decision(&coordinator, &task).map_err(uncertain)?;
            let finished = now().map_err(uncertain)?;
            if finished < started {
                return Err(uncertain(Error::Clock));
            }
            context
                .authenticate(finished, PublicationAccess::NewWork)
                .map_err(uncertain)?;
            Ok::<_, Error>(task)
        })
        .await
        .map_err(uncertain)??;
        Ok((task, trainer, evaluator))
    }
}
