//! Shadow-only learning.operator owner-port coordinator.
//!
//! This generic coordinator has no production owner wiring and owns no ledger,
//! evaluator, selector, store, registry, deployment, or release authority. It
//! exposes no publish, canary, activation, or promotion port. A verified persisted
//! candidate is loaded, shadowed, revalidated, and cleaned up to its exact
//! predecessor before a terminal outcome can be returned. An unknown persistence
//! result is a recovery obligation, never a completed run or a safe retry.

use codex_hepta_types::Digest32;

#[path = "learning_operator_coordinator_rollback.rs"]
mod rollback;
#[path = "learning_operator_coordinator_types.rs"]
mod types;
#[path = "learning_operator_coordinator_validation.rs"]
mod validation;

use rollback::rollback_outcome;
pub use types::AuditableLearningOperatorSelectionReasonV1;
pub use types::DerivedOperatorTrainingInputV1;
pub use types::FittedOperatorCandidateV1;
pub use types::FreshProcessLoadedOperatorV1;
pub use types::FrozenOperatorDatasetV1;
pub use types::IndependentOperatorEvaluationV1;
pub use types::LearningOperatorCurrentnessStateV1;
pub use types::LearningOperatorPersistenceRecoveryV1;
pub use types::LearningOperatorSelectionReasonCodeV1;
pub use types::LearningOperatorShadowErrorV1;
pub use types::LearningOperatorShadowOutcomeV1;
pub use types::LearningOperatorShadowPortsV1;
pub use types::LearningOperatorShadowRequestV1;
pub use types::LearningOperatorShadowRollbackTriggerV1;
pub use types::LearningOperatorShadowStageV1;
pub use types::LearningOperatorShadowTerminalV1;
pub use types::OperatorCurrentnessReceiptV1;
pub use types::OperatorShadowReceiptV1;
pub use types::PersistedOperatorCandidateV1;
pub use types::RolledBackOperatorCandidateV1;
pub use types::SelectedOperatorCandidateV1;
use validation::ShadowHostClockV1;
use validation::checked_port;
use validation::invariant;
use validation::valid_currentness;
use validation::valid_fresh_load;
use validation::valid_shadow;
use validation::valid_window;
use validation::validate_frozen;
use validation::validate_request;

pub fn coordinate_learning_operator_shadow_v1<P: LearningOperatorShadowPortsV1>(
    ports: &mut P,
    request: LearningOperatorShadowRequestV1,
) -> Result<LearningOperatorShadowOutcomeV1, LearningOperatorShadowErrorV1> {
    validate_request(&request)?;
    let mut clock = ShadowHostClockV1::new(request.now_unix_micros);

    let training = checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::FreezeTraining,
        request.deadline_unix_micros,
        |ports| ports.freeze_training(&request),
    )?;
    validate_frozen(
        &request,
        &training,
        request.training_source_digest,
        request.now_unix_micros,
        clock.observed_at,
        LearningOperatorShadowStageV1::FreezeTraining,
    )?;

    let input = checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::Derive,
        training.expires_at,
        |ports| ports.derive(&request, &training),
    )?;
    if input.training_receipt_id != training.receipt_id
        || input.dataset_digest != training.dataset_digest
        || input.row_commitment_digest != training.row_commitment_digest
        || input.input_digest.is_zero()
    {
        return invariant(
            LearningOperatorShadowStageV1::Derive,
            "derived input is not bound to the frozen training receipt",
        );
    }

    let candidate = checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::Fit,
        training.expires_at,
        |ports| ports.fit(&request, &input),
    )?;
    let fitted_at = clock.observed_at;
    let expected_generation = request
        .predecessor_generation
        .next()
        .map_err(|_| LearningOperatorShadowErrorV1::InvalidRequest("generation overflow"))?;
    if candidate.producer_id != request.producer_id
        || candidate.generation != expected_generation
        || candidate.objective_digest != request.objective_digest
        || candidate.training_receipt_id != training.receipt_id
        || candidate.dataset_digest != training.dataset_digest
        || candidate.row_commitment_digest != training.row_commitment_digest
        || candidate.artifact_digest.is_zero()
        || candidate.payload_digest.is_zero()
    {
        return invariant(
            LearningOperatorShadowStageV1::Fit,
            "candidate identity, source, generation, or payload binding drifted",
        );
    }

    let evaluation_dataset = checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::FreezeEvaluation,
        request.deadline_unix_micros,
        |ports| ports.freeze_evaluation(&request, &candidate),
    )?;
    validate_frozen(
        &request,
        &evaluation_dataset,
        request.evaluation_source_digest,
        fitted_at,
        clock.observed_at,
        LearningOperatorShadowStageV1::FreezeEvaluation,
    )?;
    if evaluation_dataset.frozen_at <= fitted_at
        || evaluation_dataset.receipt_id == training.receipt_id
        || evaluation_dataset.dataset_digest == training.dataset_digest
        || evaluation_dataset.row_commitment_digest == training.row_commitment_digest
    {
        return invariant(
            LearningOperatorShadowStageV1::FreezeEvaluation,
            "evaluation must use an independently frozen future-window dataset",
        );
    }

    let evaluation = checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::Evaluate,
        evaluation_dataset.expires_at,
        |ports| ports.evaluate(&request, &candidate, &evaluation_dataset),
    )?;
    if evaluation.dataset_receipt_id != evaluation_dataset.receipt_id
        || evaluation.dataset_digest != evaluation_dataset.dataset_digest
        || evaluation.candidate_artifact_digest != candidate.artifact_digest
        || evaluation.evaluator_id == candidate.producer_id
        || evaluation.evidence_digest.is_zero()
        || evaluation.trust_digest.is_zero()
        || evaluation.authority_epoch != request.expected_authority_epoch
        || evaluation.stop_epoch != request.expected_stop_epoch
        || !valid_window(
            &request,
            evaluation.observed_at,
            evaluation.expires_at,
            evaluation_dataset.frozen_at,
            clock.observed_at,
        )
    {
        return invariant(
            LearningOperatorShadowStageV1::Evaluate,
            "independent evaluation identity, clock, trust, or authority drifted",
        );
    }

    let selection = checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::Select,
        evaluation.expires_at,
        |ports| ports.select(&request, &candidate, &evaluation),
    )?;
    if selection.candidate_artifact_digest != candidate.artifact_digest
        || selection.evaluation_evidence_digest != evaluation.evidence_digest
        || selection.selector_id == candidate.producer_id
        || selection.selector_id == evaluation.evaluator_id
        || selection.selection_digest.is_zero()
        || selection.reason.policy_digest.is_zero()
        || selection.reason.evidence_digest != evaluation.evidence_digest
    {
        return invariant(
            LearningOperatorShadowStageV1::Select,
            "selection is not independently bound to future-window evidence",
        );
    }

    clock.check(
        ports,
        &request,
        LearningOperatorShadowStageV1::Persist,
        evaluation.expires_at,
    )?;
    let persisted = ports
        .persist(&request, &candidate, &selection)
        .map_err(
            |message| LearningOperatorShadowErrorV1::PersistenceOutcomeUnknown {
                recovery: Box::new(LearningOperatorPersistenceRecoveryV1 {
                    run_id: request.run_id.clone(),
                    candidate_artifact_digest: candidate.artifact_digest,
                    selection_digest: selection.selection_digest,
                    reported: None,
                }),
                message,
            },
        )?;
    if persisted.artifact_digest != candidate.artifact_digest
        || persisted.payload_digest != candidate.payload_digest
        || persisted.selection_digest != selection.selection_digest
        || persisted.storage_receipt_digest.is_zero()
    {
        return Err(LearningOperatorShadowErrorV1::PersistenceOutcomeUnknown {
            recovery: Box::new(LearningOperatorPersistenceRecoveryV1 {
                run_id: request.run_id.clone(),
                candidate_artifact_digest: candidate.artifact_digest,
                selection_digest: selection.selection_digest,
                reported: Some(persisted),
            }),
            message: "persistence receipt does not verify the selected candidate; reconcile before loading or cleanup".to_owned(),
        });
    }
    if let Err(error) = clock.check(
        ports,
        &request,
        LearningOperatorShadowStageV1::Persist,
        evaluation.expires_at,
    ) {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            &selection,
            &persisted,
            LearningOperatorShadowRollbackTriggerV1::PersistDeadlineExceeded,
            None,
            None,
            Some(error.to_string()),
        );
    }

    let loaded = match checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::FreshProcessLoad,
        evaluation.expires_at,
        |ports| ports.fresh_process_load(&request, &persisted),
    ) {
        Ok(value) => value,
        Err(message) => {
            return rollback_outcome(
                ports,
                &request,
                &candidate,
                &selection,
                &persisted,
                LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch,
                None,
                None,
                Some(message.to_string()),
            );
        }
    };
    if !valid_fresh_load(
        &request,
        &persisted,
        &loaded,
        evaluation.observed_at,
        clock.observed_at,
    ) {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            &selection,
            &persisted,
            LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch,
            None,
            None,
            None,
        );
    }

    let shadow = match checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::Shadow,
        loaded.expires_at,
        |ports| ports.shadow(&request, &loaded),
    ) {
        Ok(value) => value,
        Err(message) => {
            return rollback_outcome(
                ports,
                &request,
                &candidate,
                &selection,
                &persisted,
                LearningOperatorShadowRollbackTriggerV1::ShadowRejected,
                None,
                None,
                Some(message.to_string()),
            );
        }
    };
    if !valid_shadow(
        &request,
        &candidate,
        &selection,
        &loaded,
        &shadow,
        loaded.loaded_at,
        clock.observed_at,
    ) || !shadow.passed
    {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            &selection,
            &persisted,
            LearningOperatorShadowRollbackTriggerV1::ShadowRejected,
            Some(shadow.shadow_digest),
            None,
            None,
        );
    }

    let currentness = match checked_port(
        ports,
        &request,
        &mut clock,
        LearningOperatorShadowStageV1::Revalidate,
        shadow.expires_at,
        |ports| ports.revalidate(&request, &candidate, &selection, &shadow),
    ) {
        Ok(value) => value,
        Err(message) => {
            return rollback_outcome(
                ports,
                &request,
                &candidate,
                &selection,
                &persisted,
                LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch,
                Some(shadow.shadow_digest),
                None,
                Some(message.to_string()),
            );
        }
    };
    if !valid_currentness(
        &request,
        &candidate,
        &selection,
        &currentness,
        shadow.observed_at,
        clock.observed_at,
    ) {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            &selection,
            &persisted,
            LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch,
            Some(shadow.shadow_digest),
            Some(currentness.currentness_digest),
            None,
        );
    }

    let trigger = match currentness.state {
        LearningOperatorCurrentnessStateV1::Current => {
            LearningOperatorShadowRollbackTriggerV1::ShadowCompleted
        }
        LearningOperatorCurrentnessStateV1::Revoked => {
            LearningOperatorShadowRollbackTriggerV1::CandidateRevoked
        }
    };
    rollback_outcome(
        ports,
        &request,
        &candidate,
        &selection,
        &persisted,
        trigger,
        Some(shadow.shadow_digest),
        Some(currentness.currentness_digest),
        None,
    )
}

#[cfg(test)]
#[path = "learning_operator_coordinator_tests.rs"]
mod tests;
