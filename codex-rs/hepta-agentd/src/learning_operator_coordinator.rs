//! Default shadow-only learning.operator coordination.
//!
//! This coordinator composes existing owners but owns no ledger, evaluator,
//! selector, artifact store, registry, deployment, or release authority.  It
//! deliberately has no publish, canary, activation, or promotion port.  Every
//! persisted candidate is loaded in a fresh process, observed in shadow mode,
//! revalidated for currentness/revocation, and then rolled back to the exact
//! predecessor before the run can terminate.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowStageV1 {
    FreezeTraining,
    Derive,
    Fit,
    FreezeEvaluation,
    Evaluate,
    Select,
    Persist,
    FreshProcessLoad,
    Shadow,
    Revalidate,
    Rollback,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowRollbackTriggerV1 {
    ShadowCompleted,
    ShadowRejected,
    CandidateRevoked,
    CurrentnessMismatch,
    FreshProcessLoadMismatch,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorCurrentnessStateV1 {
    Current,
    Revoked,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorSelectionReasonCodeV1 {
    IndependentFutureWindowSuperiority,
    SafetyEquivalentLowerResourceCost,
    IndependentlyVerifiedRollback,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuditableLearningOperatorSelectionReasonV1 {
    pub code: LearningOperatorSelectionReasonCodeV1,
    pub policy_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorShadowRequestV1 {
    pub run_id: StableId,
    pub owner_id: StableId,
    pub producer_id: StableId,
    pub objective_digest: Digest32,
    pub training_source_digest: Digest32,
    pub evaluation_source_digest: Digest32,
    pub predecessor_artifact_digest: Digest32,
    pub predecessor_generation: Generation,
    pub expected_authority_epoch: u64,
    pub expected_stop_epoch: u64,
    pub now_unix_micros: u64,
    pub deadline_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenOperatorDatasetV1 {
    pub receipt_id: StableId,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub source_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub dataset_digest: Digest32,
    pub row_commitment_digest: Digest32,
    pub frozen_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DerivedOperatorTrainingInputV1 {
    pub training_receipt_id: StableId,
    pub dataset_digest: Digest32,
    pub row_commitment_digest: Digest32,
    pub input_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FittedOperatorCandidateV1 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub generation: Generation,
    pub objective_digest: Digest32,
    pub training_receipt_id: StableId,
    pub dataset_digest: Digest32,
    pub row_commitment_digest: Digest32,
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentOperatorEvaluationV1 {
    pub evaluation_id: StableId,
    pub evaluator_id: StableId,
    pub dataset_receipt_id: StableId,
    pub dataset_digest: Digest32,
    pub candidate_artifact_digest: Digest32,
    pub evidence_digest: Digest32,
    pub trust_digest: Digest32,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub observed_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedOperatorCandidateV1 {
    pub selection_id: StableId,
    pub selector_id: StableId,
    pub candidate_artifact_digest: Digest32,
    pub evaluation_evidence_digest: Digest32,
    pub selection_digest: Digest32,
    pub reason: AuditableLearningOperatorSelectionReasonV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedOperatorCandidateV1 {
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
    pub selection_digest: Digest32,
    pub storage_receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FreshProcessLoadedOperatorV1 {
    pub process_id: StableId,
    pub boot_nonce_digest: Digest32,
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
    pub selection_digest: Digest32,
    pub storage_receipt_digest: Digest32,
    pub loaded_digest: Digest32,
    pub loaded_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorShadowReceiptV1 {
    pub process_id: StableId,
    pub loaded_digest: Digest32,
    pub artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub shadow_digest: Digest32,
    pub passed: bool,
    pub observation_count: u32,
    pub observed_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorCurrentnessReceiptV1 {
    pub artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub state: LearningOperatorCurrentnessStateV1,
    pub observed_at: u64,
    pub expires_at: u64,
    pub currentness_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RolledBackOperatorCandidateV1 {
    pub failed_artifact_digest: Digest32,
    pub failed_selection_digest: Digest32,
    pub restored_artifact_digest: Digest32,
    pub restored_generation: Generation,
    pub rollback_digest: Digest32,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub trigger: LearningOperatorShadowRollbackTriggerV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowTerminalV1 {
    QualifiedAndRolledBack(RolledBackOperatorCandidateV1),
    RevokedAndRolledBack(RolledBackOperatorCandidateV1),
    RejectedAndRolledBack(RolledBackOperatorCandidateV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorShadowOutcomeV1 {
    pub run_id: StableId,
    pub candidate_artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub shadow_digest: Option<Digest32>,
    pub currentness_digest: Option<Digest32>,
    pub terminal: LearningOperatorShadowTerminalV1,
    pub audit_digest: Digest32,
}

pub trait LearningOperatorShadowPortsV1 {
    fn freeze_training(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
    ) -> Result<FrozenOperatorDatasetV1, String>;

    fn derive(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        training: &FrozenOperatorDatasetV1,
    ) -> Result<DerivedOperatorTrainingInputV1, String>;

    fn fit(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        input: &DerivedOperatorTrainingInputV1,
    ) -> Result<FittedOperatorCandidateV1, String>;

    fn freeze_evaluation(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
    ) -> Result<FrozenOperatorDatasetV1, String>;

    fn evaluate(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        evaluation_dataset: &FrozenOperatorDatasetV1,
    ) -> Result<IndependentOperatorEvaluationV1, String>;

    fn select(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        evaluation: &IndependentOperatorEvaluationV1,
    ) -> Result<SelectedOperatorCandidateV1, String>;

    fn persist(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
    ) -> Result<PersistedOperatorCandidateV1, String>;

    fn fresh_process_load(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        persisted: &PersistedOperatorCandidateV1,
    ) -> Result<FreshProcessLoadedOperatorV1, String>;

    fn shadow(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        loaded: &FreshProcessLoadedOperatorV1,
    ) -> Result<OperatorShadowReceiptV1, String>;

    fn revalidate(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
        shadow: &OperatorShadowReceiptV1,
    ) -> Result<OperatorCurrentnessReceiptV1, String>;

    fn rollback(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
        persisted: &PersistedOperatorCandidateV1,
        trigger: LearningOperatorShadowRollbackTriggerV1,
    ) -> Result<RolledBackOperatorCandidateV1, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowErrorV1 {
    InvalidRequest(&'static str),
    Port {
        stage: LearningOperatorShadowStageV1,
        message: String,
    },
    Invariant {
        stage: LearningOperatorShadowStageV1,
        message: &'static str,
    },
    RollbackFailed {
        trigger: LearningOperatorShadowRollbackTriggerV1,
        message: String,
    },
}

impl fmt::Display for LearningOperatorShadowErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRequest(message) => {
                write!(formatter, "invalid shadow coordinator request: {message}")
            }
            Self::Port { stage, message } => {
                write!(formatter, "learning.operator shadow port failure at {stage:?}: {message}")
            }
            Self::Invariant { stage, message } => {
                write!(formatter, "learning.operator shadow invariant at {stage:?}: {message}")
            }
            Self::RollbackFailed { trigger, message } => {
                write!(formatter, "learning.operator rollback failed after {trigger:?}: {message}")
            }
        }
    }
}

impl StdError for LearningOperatorShadowErrorV1 {}

pub fn coordinate_learning_operator_shadow_v1<P: LearningOperatorShadowPortsV1>(
    ports: &mut P,
    request: LearningOperatorShadowRequestV1,
) -> Result<LearningOperatorShadowOutcomeV1, LearningOperatorShadowErrorV1> {
    validate_request(&request)?;

    let training = port(
        LearningOperatorShadowStageV1::FreezeTraining,
        ports.freeze_training(&request),
    )?;
    validate_frozen(
        &request,
        &training,
        request.training_source_digest,
        LearningOperatorShadowStageV1::FreezeTraining,
    )?;

    let input = port(
        LearningOperatorShadowStageV1::Derive,
        ports.derive(&request, &training),
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

    let candidate = port(
        LearningOperatorShadowStageV1::Fit,
        ports.fit(&request, &input),
    )?;
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

    let evaluation_dataset = port(
        LearningOperatorShadowStageV1::FreezeEvaluation,
        ports.freeze_evaluation(&request, &candidate),
    )?;
    validate_frozen(
        &request,
        &evaluation_dataset,
        request.evaluation_source_digest,
        LearningOperatorShadowStageV1::FreezeEvaluation,
    )?;
    if evaluation_dataset.receipt_id == training.receipt_id
        || evaluation_dataset.dataset_digest == training.dataset_digest
        || evaluation_dataset.row_commitment_digest == training.row_commitment_digest
    {
        return invariant(
            LearningOperatorShadowStageV1::FreezeEvaluation,
            "evaluation must use an independently frozen future-window dataset",
        );
    }

    let evaluation = port(
        LearningOperatorShadowStageV1::Evaluate,
        ports.evaluate(&request, &candidate, &evaluation_dataset),
    )?;
    if evaluation.dataset_receipt_id != evaluation_dataset.receipt_id
        || evaluation.dataset_digest != evaluation_dataset.dataset_digest
        || evaluation.candidate_artifact_digest != candidate.artifact_digest
        || evaluation.evaluator_id == candidate.producer_id
        || evaluation.evidence_digest.is_zero()
        || evaluation.trust_digest.is_zero()
        || evaluation.authority_epoch != request.expected_authority_epoch
        || evaluation.stop_epoch != request.expected_stop_epoch
        || !valid_window(&request, evaluation.observed_at, evaluation.expires_at)
    {
        return invariant(
            LearningOperatorShadowStageV1::Evaluate,
            "independent evaluation identity, clock, trust, or authority drifted",
        );
    }

    let selection = port(
        LearningOperatorShadowStageV1::Select,
        ports.select(&request, &candidate, &evaluation),
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

    let persisted = port(
        LearningOperatorShadowStageV1::Persist,
        ports.persist(&request, &candidate, &selection),
    )?;
    if persisted.artifact_digest != candidate.artifact_digest
        || persisted.payload_digest != candidate.payload_digest
        || persisted.selection_digest != selection.selection_digest
        || persisted.storage_receipt_digest.is_zero()
    {
        return invariant(
            LearningOperatorShadowStageV1::Persist,
            "persisted candidate differs from the independently selected candidate",
        );
    }

    let loaded = match ports.fresh_process_load(&request, &persisted) {
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
                Some(message),
            );
        }
    };
    if !valid_fresh_load(&request, &persisted, &loaded) {
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

    let shadow = match ports.shadow(&request, &loaded) {
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
                Some(message),
            );
        }
    };
    if !valid_shadow(&request, &candidate, &selection, &loaded, &shadow) || !shadow.passed {
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

    let currentness = match ports.revalidate(&request, &candidate, &selection, &shadow) {
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
                Some(message),
            );
        }
    };
    if !valid_currentness(&request, &candidate, &selection, &currentness) {
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

#[allow(clippy::too_many_arguments)]
fn rollback_outcome<P: LearningOperatorShadowPortsV1>(
    ports: &mut P,
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    persisted: &PersistedOperatorCandidateV1,
    trigger: LearningOperatorShadowRollbackTriggerV1,
    shadow_digest: Option<Digest32>,
    currentness_digest: Option<Digest32>,
    port_message: Option<String>,
) -> Result<LearningOperatorShadowOutcomeV1, LearningOperatorShadowErrorV1> {
    let rollback = ports
        .rollback(request, candidate, selection, persisted, trigger)
        .map_err(|message| LearningOperatorShadowErrorV1::RollbackFailed { trigger, message })?;
    if rollback.failed_artifact_digest != candidate.artifact_digest
        || rollback.failed_selection_digest != selection.selection_digest
        || rollback.restored_artifact_digest != request.predecessor_artifact_digest
        || rollback.restored_generation != request.predecessor_generation
        || rollback.rollback_digest.is_zero()
        || rollback.owner_id != request.owner_id
        || rollback.authority_epoch != request.expected_authority_epoch
        || rollback.stop_epoch != request.expected_stop_epoch
        || rollback.trigger != trigger
    {
        return invariant(
            LearningOperatorShadowStageV1::Rollback,
            "rollback did not restore the exact predecessor under the current epochs",
        );
    }
    let terminal = match trigger {
        LearningOperatorShadowRollbackTriggerV1::ShadowCompleted => {
            LearningOperatorShadowTerminalV1::QualifiedAndRolledBack(rollback)
        }
        LearningOperatorShadowRollbackTriggerV1::CandidateRevoked => {
            LearningOperatorShadowTerminalV1::RevokedAndRolledBack(rollback)
        }
        LearningOperatorShadowRollbackTriggerV1::ShadowRejected
        | LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch
        | LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch => {
            LearningOperatorShadowTerminalV1::RejectedAndRolledBack(rollback)
        }
    };
    let audit_digest = audit_digest(
        request,
        candidate,
        selection,
        persisted,
        trigger,
        shadow_digest,
        currentness_digest,
        port_message.as_deref(),
    );
    Ok(LearningOperatorShadowOutcomeV1 {
        run_id: request.run_id.clone(),
        candidate_artifact_digest: candidate.artifact_digest,
        selection_digest: selection.selection_digest,
        shadow_digest,
        currentness_digest,
        terminal,
        audit_digest,
    })
}

fn validate_request(
    request: &LearningOperatorShadowRequestV1,
) -> Result<(), LearningOperatorShadowErrorV1> {
    if [
        request.objective_digest,
        request.training_source_digest,
        request.evaluation_source_digest,
        request.predecessor_artifact_digest,
    ]
    .into_iter()
    .any(Digest32::is_zero)
    {
        return Err(LearningOperatorShadowErrorV1::InvalidRequest(
            "all objective, source, and predecessor digests must be nonzero",
        ));
    }
    if request.training_source_digest == request.evaluation_source_digest {
        return Err(LearningOperatorShadowErrorV1::InvalidRequest(
            "training and independent evaluation sources must differ",
        ));
    }
    if request.expected_authority_epoch == 0
        || request.expected_stop_epoch == 0
        || request.now_unix_micros == 0
        || request.now_unix_micros >= request.deadline_unix_micros
    {
        return Err(LearningOperatorShadowErrorV1::InvalidRequest(
            "trusted epochs and an unexpired absolute deadline are mandatory",
        ));
    }
    Ok(())
}

fn validate_frozen(
    request: &LearningOperatorShadowRequestV1,
    value: &FrozenOperatorDatasetV1,
    expected_source: Digest32,
    stage: LearningOperatorShadowStageV1,
) -> Result<(), LearningOperatorShadowErrorV1> {
    if value.owner_id != request.owner_id
        || value.authority_epoch != request.expected_authority_epoch
        || value.stop_epoch != request.expected_stop_epoch
        || value.source_digest != expected_source
        || value.ledger_head_digest.is_zero()
        || value.dataset_digest.is_zero()
        || value.row_commitment_digest.is_zero()
        || !valid_window(request, value.frozen_at, value.expires_at)
    {
        return invariant(
            stage,
            "frozen dataset is stale or not bound to owner, epochs, source, and rows",
        );
    }
    Ok(())
}

fn valid_fresh_load(
    request: &LearningOperatorShadowRequestV1,
    persisted: &PersistedOperatorCandidateV1,
    loaded: &FreshProcessLoadedOperatorV1,
) -> bool {
    loaded.artifact_digest == persisted.artifact_digest
        && loaded.payload_digest == persisted.payload_digest
        && loaded.selection_digest == persisted.selection_digest
        && loaded.storage_receipt_digest == persisted.storage_receipt_digest
        && !loaded.boot_nonce_digest.is_zero()
        && !loaded.loaded_digest.is_zero()
        && valid_window(request, loaded.loaded_at, loaded.expires_at)
}

fn valid_shadow(
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    loaded: &FreshProcessLoadedOperatorV1,
    shadow: &OperatorShadowReceiptV1,
) -> bool {
    shadow.process_id == loaded.process_id
        && shadow.loaded_digest == loaded.loaded_digest
        && shadow.artifact_digest == candidate.artifact_digest
        && shadow.selection_digest == selection.selection_digest
        && !shadow.shadow_digest.is_zero()
        && shadow.observation_count > 0
        && valid_window(request, shadow.observed_at, shadow.expires_at)
}

fn valid_currentness(
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    currentness: &OperatorCurrentnessReceiptV1,
) -> bool {
    currentness.artifact_digest == candidate.artifact_digest
        && currentness.selection_digest == selection.selection_digest
        && !currentness.ledger_head_digest.is_zero()
        && !currentness.registry_head_digest.is_zero()
        && currentness.authority_epoch == request.expected_authority_epoch
        && currentness.stop_epoch == request.expected_stop_epoch
        && !currentness.currentness_digest.is_zero()
        && valid_window(request, currentness.observed_at, currentness.expires_at)
}

fn valid_window(request: &LearningOperatorShadowRequestV1, issued_at: u64, expires_at: u64) -> bool {
    issued_at != 0
        && issued_at <= request.now_unix_micros
        && request.now_unix_micros < expires_at
        && request.now_unix_micros < request.deadline_unix_micros
}

fn port<T>(
    stage: LearningOperatorShadowStageV1,
    result: Result<T, String>,
) -> Result<T, LearningOperatorShadowErrorV1> {
    result.map_err(|message| LearningOperatorShadowErrorV1::Port { stage, message })
}

fn invariant<T>(
    stage: LearningOperatorShadowStageV1,
    message: &'static str,
) -> Result<T, LearningOperatorShadowErrorV1> {
    Err(LearningOperatorShadowErrorV1::Invariant { stage, message })
}

#[allow(clippy::too_many_arguments)]
fn audit_digest(
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    persisted: &PersistedOperatorCandidateV1,
    trigger: LearningOperatorShadowRollbackTriggerV1,
    shadow_digest: Option<Digest32>,
    currentness_digest: Option<Digest32>,
    port_message: Option<&str>,
) -> Digest32 {
    let mut bytes = b"hepta.learning-operator.shadow-audit.v1\0".to_vec();
    push_id(&mut bytes, &request.run_id);
    push_id(&mut bytes, &request.owner_id);
    push_id(&mut bytes, &candidate.artifact_id);
    for digest in [
        request.objective_digest,
        request.training_source_digest,
        request.evaluation_source_digest,
        request.predecessor_artifact_digest,
        candidate.artifact_digest,
        candidate.payload_digest,
        selection.selection_digest,
        selection.reason.policy_digest,
        persisted.storage_receipt_digest,
        shadow_digest.unwrap_or(Digest32::ZERO),
        currentness_digest.unwrap_or(Digest32::ZERO),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.expected_authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&request.expected_stop_epoch.to_be_bytes());
    bytes.push(rollback_trigger_code(trigger));
    if let Some(message) = port_message {
        bytes.extend_from_slice(Digest32::of_bytes(message.as_bytes()).as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn rollback_trigger_code(value: LearningOperatorShadowRollbackTriggerV1) -> u8 {
    match value {
        LearningOperatorShadowRollbackTriggerV1::ShadowCompleted => 1,
        LearningOperatorShadowRollbackTriggerV1::ShadowRejected => 2,
        LearningOperatorShadowRollbackTriggerV1::CandidateRevoked => 3,
        LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch => 4,
        LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch => 5,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let length = u64::try_from(raw.len()).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    enum Fault {
        None,
        LoadPayloadMismatch,
        ShadowRejected,
    }

    struct Fixture {
        fault: Fault,
        currentness: LearningOperatorCurrentnessStateV1,
        last_trigger: Option<LearningOperatorShadowRollbackTriggerV1>,
    }

    impl Fixture {
        fn new() -> Self {
            Self {
                fault: Fault::None,
                currentness: LearningOperatorCurrentnessStateV1::Current,
                last_trigger: None,
            }
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn request() -> LearningOperatorShadowRequestV1 {
        LearningOperatorShadowRequestV1 {
            run_id: id("run"),
            owner_id: id("owner"),
            producer_id: id("producer"),
            objective_digest: digest("objective"),
            training_source_digest: digest("training-source"),
            evaluation_source_digest: digest("evaluation-source"),
            predecessor_artifact_digest: digest("predecessor"),
            predecessor_generation: Generation::new(1).unwrap(),
            expected_authority_epoch: 7,
            expected_stop_epoch: 11,
            now_unix_micros: 100,
            deadline_unix_micros: 1_000,
        }
    }

    fn frozen(
        request: &LearningOperatorShadowRequestV1,
        name: &str,
        source: Digest32,
    ) -> FrozenOperatorDatasetV1 {
        FrozenOperatorDatasetV1 {
            receipt_id: id(&format!("{name}-receipt")),
            owner_id: request.owner_id.clone(),
            authority_epoch: request.expected_authority_epoch,
            stop_epoch: request.expected_stop_epoch,
            source_digest: source,
            ledger_head_digest: digest(&format!("{name}-ledger")),
            dataset_digest: digest(&format!("{name}-dataset")),
            row_commitment_digest: digest(&format!("{name}-rows")),
            frozen_at: request.now_unix_micros,
            expires_at: request.deadline_unix_micros,
        }
    }

    impl LearningOperatorShadowPortsV1 for Fixture {
        fn freeze_training(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
        ) -> Result<FrozenOperatorDatasetV1, String> {
            Ok(frozen(request, "training", request.training_source_digest))
        }

        fn derive(
            &mut self,
            _request: &LearningOperatorShadowRequestV1,
            training: &FrozenOperatorDatasetV1,
        ) -> Result<DerivedOperatorTrainingInputV1, String> {
            Ok(DerivedOperatorTrainingInputV1 {
                training_receipt_id: training.receipt_id.clone(),
                dataset_digest: training.dataset_digest,
                row_commitment_digest: training.row_commitment_digest,
                input_digest: digest("input"),
            })
        }

        fn fit(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
            input: &DerivedOperatorTrainingInputV1,
        ) -> Result<FittedOperatorCandidateV1, String> {
            Ok(FittedOperatorCandidateV1 {
                artifact_id: id("candidate"),
                producer_id: request.producer_id.clone(),
                generation: request.predecessor_generation.next().unwrap(),
                objective_digest: request.objective_digest,
                training_receipt_id: input.training_receipt_id.clone(),
                dataset_digest: input.dataset_digest,
                row_commitment_digest: input.row_commitment_digest,
                artifact_digest: digest("artifact"),
                payload_digest: digest("payload"),
            })
        }

        fn freeze_evaluation(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
            _candidate: &FittedOperatorCandidateV1,
        ) -> Result<FrozenOperatorDatasetV1, String> {
            Ok(frozen(
                request,
                "evaluation",
                request.evaluation_source_digest,
            ))
        }

        fn evaluate(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
            candidate: &FittedOperatorCandidateV1,
            dataset: &FrozenOperatorDatasetV1,
        ) -> Result<IndependentOperatorEvaluationV1, String> {
            Ok(IndependentOperatorEvaluationV1 {
                evaluation_id: id("evaluation"),
                evaluator_id: id("evaluator"),
                dataset_receipt_id: dataset.receipt_id.clone(),
                dataset_digest: dataset.dataset_digest,
                candidate_artifact_digest: candidate.artifact_digest,
                evidence_digest: digest("evaluation-evidence"),
                trust_digest: digest("evaluation-trust"),
                authority_epoch: request.expected_authority_epoch,
                stop_epoch: request.expected_stop_epoch,
                observed_at: request.now_unix_micros,
                expires_at: request.deadline_unix_micros,
            })
        }

        fn select(
            &mut self,
            _request: &LearningOperatorShadowRequestV1,
            candidate: &FittedOperatorCandidateV1,
            evaluation: &IndependentOperatorEvaluationV1,
        ) -> Result<SelectedOperatorCandidateV1, String> {
            Ok(SelectedOperatorCandidateV1 {
                selection_id: id("selection"),
                selector_id: id("selector"),
                candidate_artifact_digest: candidate.artifact_digest,
                evaluation_evidence_digest: evaluation.evidence_digest,
                selection_digest: digest("selection"),
                reason: AuditableLearningOperatorSelectionReasonV1 {
                    code: LearningOperatorSelectionReasonCodeV1::IndependentFutureWindowSuperiority,
                    policy_digest: digest("selection-policy"),
                    evidence_digest: evaluation.evidence_digest,
                },
            })
        }

        fn persist(
            &mut self,
            _request: &LearningOperatorShadowRequestV1,
            candidate: &FittedOperatorCandidateV1,
            selection: &SelectedOperatorCandidateV1,
        ) -> Result<PersistedOperatorCandidateV1, String> {
            Ok(PersistedOperatorCandidateV1 {
                artifact_digest: candidate.artifact_digest,
                payload_digest: candidate.payload_digest,
                selection_digest: selection.selection_digest,
                storage_receipt_digest: digest("storage"),
            })
        }

        fn fresh_process_load(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
            persisted: &PersistedOperatorCandidateV1,
        ) -> Result<FreshProcessLoadedOperatorV1, String> {
            let payload_digest = if self.fault == Fault::LoadPayloadMismatch {
                digest("wrong-payload")
            } else {
                persisted.payload_digest
            };
            Ok(FreshProcessLoadedOperatorV1 {
                process_id: id("fresh-process"),
                boot_nonce_digest: digest("boot-nonce"),
                artifact_digest: persisted.artifact_digest,
                payload_digest,
                selection_digest: persisted.selection_digest,
                storage_receipt_digest: persisted.storage_receipt_digest,
                loaded_digest: digest("loaded"),
                loaded_at: request.now_unix_micros,
                expires_at: request.deadline_unix_micros,
            })
        }

        fn shadow(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
            loaded: &FreshProcessLoadedOperatorV1,
        ) -> Result<OperatorShadowReceiptV1, String> {
            Ok(OperatorShadowReceiptV1 {
                process_id: loaded.process_id.clone(),
                loaded_digest: loaded.loaded_digest,
                artifact_digest: loaded.artifact_digest,
                selection_digest: loaded.selection_digest,
                shadow_digest: digest("shadow"),
                passed: self.fault != Fault::ShadowRejected,
                observation_count: 64,
                observed_at: request.now_unix_micros,
                expires_at: request.deadline_unix_micros,
            })
        }

        fn revalidate(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
            candidate: &FittedOperatorCandidateV1,
            selection: &SelectedOperatorCandidateV1,
            _shadow: &OperatorShadowReceiptV1,
        ) -> Result<OperatorCurrentnessReceiptV1, String> {
            Ok(OperatorCurrentnessReceiptV1 {
                artifact_digest: candidate.artifact_digest,
                selection_digest: selection.selection_digest,
                ledger_head_digest: digest("current-ledger"),
                registry_head_digest: digest("current-registry"),
                authority_epoch: request.expected_authority_epoch,
                stop_epoch: request.expected_stop_epoch,
                state: self.currentness,
                observed_at: request.now_unix_micros,
                expires_at: request.deadline_unix_micros,
                currentness_digest: digest("currentness"),
            })
        }

        fn rollback(
            &mut self,
            request: &LearningOperatorShadowRequestV1,
            candidate: &FittedOperatorCandidateV1,
            selection: &SelectedOperatorCandidateV1,
            _persisted: &PersistedOperatorCandidateV1,
            trigger: LearningOperatorShadowRollbackTriggerV1,
        ) -> Result<RolledBackOperatorCandidateV1, String> {
            self.last_trigger = Some(trigger);
            Ok(RolledBackOperatorCandidateV1 {
                failed_artifact_digest: candidate.artifact_digest,
                failed_selection_digest: selection.selection_digest,
                restored_artifact_digest: request.predecessor_artifact_digest,
                restored_generation: request.predecessor_generation,
                rollback_digest: digest("rollback"),
                owner_id: request.owner_id.clone(),
                authority_epoch: request.expected_authority_epoch,
                stop_epoch: request.expected_stop_epoch,
                trigger,
            })
        }
    }

    #[test]
    fn current_shadow_candidate_is_qualified_then_rolled_back() {
        let mut fixture = Fixture::new();
        let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorShadowTerminalV1::QualifiedAndRolledBack(_)
        ));
        assert_eq!(
            fixture.last_trigger,
            Some(LearningOperatorShadowRollbackTriggerV1::ShadowCompleted)
        );
    }

    #[test]
    fn revoked_candidate_is_observed_and_rolled_back_without_activation() {
        let mut fixture = Fixture::new();
        fixture.currentness = LearningOperatorCurrentnessStateV1::Revoked;
        let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorShadowTerminalV1::RevokedAndRolledBack(_)
        ));
        assert_eq!(
            fixture.last_trigger,
            Some(LearningOperatorShadowRollbackTriggerV1::CandidateRevoked)
        );
    }

    #[test]
    fn fresh_process_payload_mismatch_rolls_back_before_shadow() {
        let mut fixture = Fixture::new();
        fixture.fault = Fault::LoadPayloadMismatch;
        let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorShadowTerminalV1::RejectedAndRolledBack(_)
        ));
        assert_eq!(outcome.shadow_digest, None);
        assert_eq!(
            fixture.last_trigger,
            Some(LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch)
        );
    }

    #[test]
    fn shadow_rejection_rolls_back_and_never_reaches_currentness() {
        let mut fixture = Fixture::new();
        fixture.fault = Fault::ShadowRejected;
        let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorShadowTerminalV1::RejectedAndRolledBack(_)
        ));
        assert_eq!(
            fixture.last_trigger,
            Some(LearningOperatorShadowRollbackTriggerV1::ShadowRejected)
        );
    }
}
