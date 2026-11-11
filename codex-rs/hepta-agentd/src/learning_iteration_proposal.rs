//! Bind frozen work to the existing authenticated, anchored proposal owner.

use codex_hepta_intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;

use crate::AgentdState;
use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationProposalPayloadV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::learning_iteration::require_ready;

pub(super) async fn submit_iteration_proposal_v1(
    state: &AgentdState,
    ports: &dyn LearningIterationOwnerPortsV1,
    coordinator: &LearningIterationCoordinatorV1,
    clock: &(impl Fn() -> Result<u64, LearningIterationRuntimeErrorV1> + Send + Sync),
) -> Result<LearningIterationReceiptV1, LearningIterationRuntimeErrorV1> {
    let snapshot = coordinator.snapshot();
    let context = &snapshot.request;
    let mismatch =
        || LearningIterationRuntimeErrorV1::Validation(LearningIterationError::ContextMismatch);
    let candidate = coordinator.candidate().ok_or_else(mismatch)?;
    let candidate_bundle = candidate.digest().map_err(LearningIterationError::from)?;
    let lineage = candidate.training_lineage.as_ref().ok_or_else(mismatch)?;
    let evaluation = snapshot.receipts.last().ok_or_else(mismatch)?;
    let prepared = ports.prepare_proposal(snapshot).await?;
    if prepared.iteration_head != snapshot.head_digest
        || prepared.candidate_bundle != candidate_bundle
        || prepared.evaluation_evidence != evaluation.evidence_digest
    {
        return Err(mismatch());
    }
    require_ready(state)?;
    let now = clock()?;
    if now >= context.envelope.expiry_unix_seconds {
        return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
    }
    let (composition_digest, disposition) = match prepared.payload {
        LearningIterationProposalPayloadV1::Parameter(request) => {
            if request.proposal_id != context.operation_id
                || request.admission.baseline_id != context.selected_bundle.artifact_id
                || request.admission.objective_digest != context.envelope.objective_digest
                || request.admission.selected_artifact_digest != context.selected_artifact_digest
                || request.admission.baseline_generation != context.selected_bundle.generation
                || request.admission.candidate_generation != candidate.generation
                || request.admission.window.window_id != context.envelope.envelope_id
                || request.admission.dataset_digest != lineage.dataset
                || request.admission.update_rule_digest != lineage.update_rule
                || request
                    .generator_profile
                    .mutation_policy
                    .mutation_grammar_digest
                    != context.envelope.grammar_digest
                || request.generated.candidates.len()
                    > usize::from(context.envelope.maximum_candidates)
                || request.generator_attestation.principal_id != snapshot.owners.trainer
                || request.evaluations.iter().any(|evaluation| {
                    evaluation.bundle.evaluator.principal_id != snapshot.owners.evaluator
                })
                || request
                    .no_change_attestation
                    .as_ref()
                    .is_some_and(|attestation| {
                        attestation.principal_id != snapshot.owners.evaluator
                    })
            {
                return Err(mismatch());
            }
            let receipt = state
                .submit_parameter_plasticity_v1(*request, now)
                .await
                .map_err(LearningIterationRuntimeErrorV1::Proposal)?;
            let disposition = match receipt.disposition {
                ParameterPlasticityDispositionV1::UpdateCandidates => {
                    LearningProposalDispositionV1::UpdateCandidates
                }
                ParameterPlasticityDispositionV1::NoAdmissibleUpdate => {
                    LearningProposalDispositionV1::NoAdmissibleUpdate
                }
            };
            (receipt.composition_digest, disposition)
        }
        LearningIterationProposalPayloadV1::Topology(request) => {
            if request.proposal_id != context.operation_id
                || request.admission.baseline_id != context.selected_bundle.artifact_id
                || request.admission.objective_digest != context.envelope.objective_digest
                || request.selected_artifact_digest != context.selected_artifact_digest
                || request.baseline_generation != context.selected_bundle.generation
                || request.candidate_generation != candidate.generation
                || request.window.window_id != context.envelope.envelope_id
                || request.admission.evaluation_receipt_digest != evaluation.evidence_digest
                || request.generator_attestation.principal_id != snapshot.owners.trainer
                || request.evaluator_attestation.principal_id != snapshot.owners.evaluator
            {
                return Err(mismatch());
            }
            let receipt = state
                .submit_topology_plasticity_v1(*request, now)
                .await
                .map_err(LearningIterationRuntimeErrorV1::Proposal)?;
            (
                receipt.composition_digest,
                LearningProposalDispositionV1::UpdateCandidates,
            )
        }
    };
    Ok(LearningIterationReceiptV1 {
        operation_id: context.operation_id.clone(),
        predecessor: snapshot.head_digest,
        actor_id: snapshot.owners.proposal.clone(),
        evidence_digest: composition_digest,
        observed_unix_seconds: clock()?,
        observation: LearningIterationObservationV1::Proposal {
            candidate_bundle,
            proposal_id: context.operation_id.clone(),
            composition_digest,
            disposition,
        },
    })
}
