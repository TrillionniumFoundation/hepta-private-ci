//! Bounded learning.operator production coordination.
//!
//! This host-side coordinator sequences existing owner capabilities. It owns no
//! ledger, artifact, evaluation, signing, deployment, or release authority.
//! Every port returns an immutable receipt, and the coordinator rejects any
//! cross-stage identity, lineage, clock, owner, or authority-epoch drift.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorStageV1 {
    FreezeTraining,
    Derive,
    Fit,
    FreezeEvaluation,
    Evaluate,
    Select,
    Certify,
    Persist,
    Publish,
    Canary,
    Activate,
    Rollback,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorRollbackTriggerV1 {
    PublicationBindingMismatch,
    CanaryUnavailable,
    CanaryRejected,
    CanaryBindingMismatch,
    ActivationUnavailable,
    ActivationBindingMismatch,
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
pub struct LearningOperatorRunRequestV1 {
    pub run_id: StableId,
    pub owner_id: StableId,
    pub producer_id: StableId,
    pub objective_digest: Digest32,
    pub training_source_digest: Digest32,
    pub evaluation_source_digest: Digest32,
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub predecessor_artifact_digest: Digest32,
    pub expected_authority_epoch: u64,
    pub now_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenOperatorDatasetV1 {
    pub receipt_id: StableId,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub source_digest: Digest32,
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
    pub dataset_digest: Digest32,
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
pub struct CertifiedOperatorCandidateV1 {
    pub certificate_digest: Digest32,
    pub artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedOperatorCandidateV1 {
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
    pub storage_receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedOperatorCandidateV1 {
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub certificate_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub publication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorCanaryReceiptV1 {
    pub publication_digest: Digest32,
    pub canary_digest: Digest32,
    pub passed: bool,
    pub observation_count: u32,
    pub started_at: u64,
    pub completed_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActivatedOperatorCandidateV1 {
    pub publication_digest: Digest32,
    pub activation_digest: Digest32,
    pub owner_id: StableId,
    pub authority_epoch: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RolledBackOperatorCandidateV1 {
    pub failed_publication_digest: Digest32,
    pub restored_artifact_digest: Digest32,
    pub restored_generation: Generation,
    pub rollback_digest: Digest32,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub trigger: LearningOperatorRollbackTriggerV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningOperatorTerminalV1 {
    Activated(ActivatedOperatorCandidateV1),
    RolledBack(RolledBackOperatorCandidateV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorRunOutcomeV1 {
    pub run_id: StableId,
    pub candidate_artifact_digest: Digest32,
    pub publication_digest: Digest32,
    pub terminal: LearningOperatorTerminalV1,
    pub audit_digest: Digest32,
}

pub trait LearningOperatorCoordinatorPortsV1 {
    fn freeze_training(
        &mut self,
        request: &LearningOperatorRunRequestV1,
    ) -> Result<FrozenOperatorDatasetV1, String>;

    fn derive(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        training: &FrozenOperatorDatasetV1,
    ) -> Result<DerivedOperatorTrainingInputV1, String>;

    fn fit(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        input: &DerivedOperatorTrainingInputV1,
    ) -> Result<FittedOperatorCandidateV1, String>;

    fn freeze_evaluation(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        candidate: &FittedOperatorCandidateV1,
    ) -> Result<FrozenOperatorDatasetV1, String>;

    fn evaluate(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        candidate: &FittedOperatorCandidateV1,
        evaluation_dataset: &FrozenOperatorDatasetV1,
    ) -> Result<IndependentOperatorEvaluationV1, String>;

    fn select(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        candidate: &FittedOperatorCandidateV1,
        evaluation: &IndependentOperatorEvaluationV1,
    ) -> Result<SelectedOperatorCandidateV1, String>;

    fn certify(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
    ) -> Result<CertifiedOperatorCandidateV1, String>;

    fn persist(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        candidate: &FittedOperatorCandidateV1,
        certificate: &CertifiedOperatorCandidateV1,
    ) -> Result<PersistedOperatorCandidateV1, String>;

    fn publish(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        candidate: &FittedOperatorCandidateV1,
        certificate: &CertifiedOperatorCandidateV1,
        persisted: &PersistedOperatorCandidateV1,
    ) -> Result<PublishedOperatorCandidateV1, String>;

    fn canary(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        published: &PublishedOperatorCandidateV1,
    ) -> Result<OperatorCanaryReceiptV1, String>;

    fn activate(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        published: &PublishedOperatorCandidateV1,
        canary: &OperatorCanaryReceiptV1,
    ) -> Result<ActivatedOperatorCandidateV1, String>;

    fn rollback(
        &mut self,
        request: &LearningOperatorRunRequestV1,
        published: &PublishedOperatorCandidateV1,
        trigger: LearningOperatorRollbackTriggerV1,
    ) -> Result<RolledBackOperatorCandidateV1, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningOperatorCoordinatorErrorV1 {
    InvalidRequest(&'static str),
    Port {
        stage: LearningOperatorStageV1,
        message: String,
    },
    Invariant {
        stage: LearningOperatorStageV1,
        message: &'static str,
    },
    RollbackFailed {
        trigger: LearningOperatorRollbackTriggerV1,
        message: String,
    },
}

impl fmt::Display for LearningOperatorCoordinatorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRequest(message) => write!(formatter, "invalid coordinator request: {message}"),
            Self::Port { stage, message } => {
                write!(formatter, "learning.operator port failure at {stage:?}: {message}")
            }
            Self::Invariant { stage, message } => {
                write!(formatter, "learning.operator invariant failure at {stage:?}: {message}")
            }
            Self::RollbackFailed { trigger, message } => {
                write!(formatter, "learning.operator rollback failed after {trigger:?}: {message}")
            }
        }
    }
}

impl StdError for LearningOperatorCoordinatorErrorV1 {}

pub fn coordinate_learning_operator_run_v1<P: LearningOperatorCoordinatorPortsV1>(
    ports: &mut P,
    request: LearningOperatorRunRequestV1,
) -> Result<LearningOperatorRunOutcomeV1, LearningOperatorCoordinatorErrorV1> {
    validate_request(&request)?;

    let training = port(
        LearningOperatorStageV1::FreezeTraining,
        ports.freeze_training(&request),
    )?;
    validate_frozen(
        &request,
        &training,
        request.training_source_digest,
        LearningOperatorStageV1::FreezeTraining,
    )?;

    let input = port(
        LearningOperatorStageV1::Derive,
        ports.derive(&request, &training),
    )?;
    if input.training_receipt_id != training.receipt_id
        || input.dataset_digest != training.dataset_digest
        || input.row_commitment_digest != training.row_commitment_digest
        || input.input_digest.is_zero()
    {
        return invariant(
            LearningOperatorStageV1::Derive,
            "derived input is not exactly bound to the frozen training receipt",
        );
    }

    let candidate = port(LearningOperatorStageV1::Fit, ports.fit(&request, &input))?;
    let expected_generation = request
        .predecessor_generation
        .next()
        .map_err(|_| LearningOperatorCoordinatorErrorV1::InvalidRequest("generation overflow"))?;
    if candidate.producer_id != request.producer_id
        || candidate.generation != expected_generation
        || candidate.objective_digest != request.objective_digest
        || candidate.dataset_digest != training.dataset_digest
        || candidate.artifact_digest.is_zero()
        || candidate.payload_digest.is_zero()
    {
        return invariant(
            LearningOperatorStageV1::Fit,
            "candidate identity, generation, objective, dataset, or payload binding drifted",
        );
    }

    let evaluation_dataset = port(
        LearningOperatorStageV1::FreezeEvaluation,
        ports.freeze_evaluation(&request, &candidate),
    )?;
    validate_frozen(
        &request,
        &evaluation_dataset,
        request.evaluation_source_digest,
        LearningOperatorStageV1::FreezeEvaluation,
    )?;
    if evaluation_dataset.receipt_id == training.receipt_id
        || evaluation_dataset.dataset_digest == training.dataset_digest
        || evaluation_dataset.row_commitment_digest == training.row_commitment_digest
    {
        return invariant(
            LearningOperatorStageV1::FreezeEvaluation,
            "evaluation must use an independently frozen receipt and row commitment",
        );
    }

    let evaluation = port(
        LearningOperatorStageV1::Evaluate,
        ports.evaluate(&request, &candidate, &evaluation_dataset),
    )?;
    if evaluation.dataset_receipt_id != evaluation_dataset.receipt_id
        || evaluation.dataset_digest != evaluation_dataset.dataset_digest
        || evaluation.candidate_artifact_digest != candidate.artifact_digest
        || evaluation.evaluator_id == candidate.producer_id
        || evaluation.evidence_digest.is_zero()
        || evaluation.trust_digest.is_zero()
        || evaluation.authority_epoch != request.expected_authority_epoch
        || !valid_window(
            request.now_unix_micros,
            evaluation.observed_at,
            evaluation.expires_at,
        )
    {
        return invariant(
            LearningOperatorStageV1::Evaluate,
            "independent evaluation identity, evidence, clock, or authority binding drifted",
        );
    }

    let selection = port(
        LearningOperatorStageV1::Select,
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
            LearningOperatorStageV1::Select,
            "selection is not independently and audibly bound to evaluation evidence",
        );
    }

    let certificate = port(
        LearningOperatorStageV1::Certify,
        ports.certify(&request, &candidate, &selection),
    )?;
    if certificate.artifact_digest != candidate.artifact_digest
        || certificate.selection_digest != selection.selection_digest
        || certificate.owner_id != request.owner_id
        || certificate.authority_epoch != request.expected_authority_epoch
        || certificate.certificate_digest.is_zero()
        || !valid_window(
            request.now_unix_micros,
            certificate.issued_at,
            certificate.expires_at,
        )
    {
        return invariant(
            LearningOperatorStageV1::Certify,
            "certificate is stale or not bound to owner, authority epoch, artifact, and selection",
        );
    }

    let persisted = port(
        LearningOperatorStageV1::Persist,
        ports.persist(&request, &candidate, &certificate),
    )?;
    if persisted.artifact_digest != candidate.artifact_digest
        || persisted.payload_digest != candidate.payload_digest
        || persisted.storage_receipt_digest.is_zero()
    {
        return invariant(
            LearningOperatorStageV1::Persist,
            "persisted payload identity differs from the selected immutable candidate",
        );
    }

    let published = port(
        LearningOperatorStageV1::Publish,
        ports.publish(&request, &candidate, &certificate, &persisted),
    )?;
    if !valid_publication(&request, &candidate, &certificate, &published) {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            published,
            LearningOperatorRollbackTriggerV1::PublicationBindingMismatch,
        );
    }

    let canary = match ports.canary(&request, &published) {
        Ok(value) => value,
        Err(_) => {
            return rollback_outcome(
                ports,
                &request,
                &candidate,
                published,
                LearningOperatorRollbackTriggerV1::CanaryUnavailable,
            );
        }
    };
    if canary.publication_digest != published.publication_digest
        || canary.canary_digest.is_zero()
        || canary.observation_count == 0
        || canary.started_at < request.now_unix_micros
        || canary.completed_at < canary.started_at
    {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            published,
            LearningOperatorRollbackTriggerV1::CanaryBindingMismatch,
        );
    }
    if !canary.passed {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            published,
            LearningOperatorRollbackTriggerV1::CanaryRejected,
        );
    }

    let activated = match ports.activate(&request, &published, &canary) {
        Ok(value) => value,
        Err(_) => {
            return rollback_outcome(
                ports,
                &request,
                &candidate,
                published,
                LearningOperatorRollbackTriggerV1::ActivationUnavailable,
            );
        }
    };
    if activated.publication_digest != published.publication_digest
        || activated.activation_digest.is_zero()
        || activated.owner_id != request.owner_id
        || activated.authority_epoch != request.expected_authority_epoch
    {
        return rollback_outcome(
            ports,
            &request,
            &candidate,
            published,
            LearningOperatorRollbackTriggerV1::ActivationBindingMismatch,
        );
    }

    let audit_digest = audit_digest(
        &request,
        &candidate,
        &evaluation,
        &selection,
        &certificate,
        &published,
        canary.canary_digest,
        activated.activation_digest,
    );
    Ok(LearningOperatorRunOutcomeV1 {
        run_id: request.run_id,
        candidate_artifact_digest: candidate.artifact_digest,
        publication_digest: published.publication_digest,
        terminal: LearningOperatorTerminalV1::Activated(activated),
        audit_digest,
    })
}

fn rollback_outcome<P: LearningOperatorCoordinatorPortsV1>(
    ports: &mut P,
    request: &LearningOperatorRunRequestV1,
    candidate: &FittedOperatorCandidateV1,
    published: PublishedOperatorCandidateV1,
    trigger: LearningOperatorRollbackTriggerV1,
) -> Result<LearningOperatorRunOutcomeV1, LearningOperatorCoordinatorErrorV1> {
    let rollback = ports
        .rollback(request, &published, trigger)
        .map_err(|message| LearningOperatorCoordinatorErrorV1::RollbackFailed {
            trigger,
            message,
        })?;
    if rollback.failed_publication_digest != published.publication_digest
        || rollback.restored_artifact_digest != request.predecessor_artifact_digest
        || rollback.restored_generation != request.predecessor_generation
        || rollback.rollback_digest.is_zero()
        || rollback.owner_id != request.owner_id
        || rollback.authority_epoch != request.expected_authority_epoch
        || rollback.trigger != trigger
    {
        return invariant(
            LearningOperatorStageV1::Rollback,
            "rollback did not restore the exact predecessor under the current owner epoch",
        );
    }
    let audit_digest = rollback_audit_digest(request, candidate, &published, &rollback);
    Ok(LearningOperatorRunOutcomeV1 {
        run_id: request.run_id.clone(),
        candidate_artifact_digest: candidate.artifact_digest,
        publication_digest: published.publication_digest,
        terminal: LearningOperatorTerminalV1::RolledBack(rollback),
        audit_digest,
    })
}

fn validate_request(
    request: &LearningOperatorRunRequestV1,
) -> Result<(), LearningOperatorCoordinatorErrorV1> {
    if request.objective_digest.is_zero()
        || request.training_source_digest.is_zero()
        || request.evaluation_source_digest.is_zero()
        || request.predecessor_artifact_digest.is_zero()
    {
        return Err(LearningOperatorCoordinatorErrorV1::InvalidRequest(
            "all objective, source, and predecessor digests must be nonzero",
        ));
    }
    if request.training_source_digest == request.evaluation_source_digest {
        return Err(LearningOperatorCoordinatorErrorV1::InvalidRequest(
            "training and independent evaluation sources must differ",
        ));
    }
    if request.expected_authority_epoch == 0 || request.now_unix_micros == 0 {
        return Err(LearningOperatorCoordinatorErrorV1::InvalidRequest(
            "trusted time and authority epoch are mandatory",
        ));
    }
    Ok(())
}

fn validate_frozen(
    request: &LearningOperatorRunRequestV1,
    value: &FrozenOperatorDatasetV1,
    expected_source: Digest32,
    stage: LearningOperatorStageV1,
) -> Result<(), LearningOperatorCoordinatorErrorV1> {
    if value.owner_id != request.owner_id
        || value.authority_epoch != request.expected_authority_epoch
        || value.source_digest != expected_source
        || value.dataset_digest.is_zero()
        || value.row_commitment_digest.is_zero()
        || !valid_window(request.now_unix_micros, value.frozen_at, value.expires_at)
    {
        return invariant(
            stage,
            "frozen dataset is stale or not bound to owner, epoch, source, and row commitment",
        );
    }
    Ok(())
}

fn valid_publication(
    request: &LearningOperatorRunRequestV1,
    candidate: &FittedOperatorCandidateV1,
    certificate: &CertifiedOperatorCandidateV1,
    published: &PublishedOperatorCandidateV1,
) -> bool {
    published.artifact_digest == candidate.artifact_digest
        && published.payload_digest == candidate.payload_digest
        && published.owner_id == request.owner_id
        && published.authority_epoch == request.expected_authority_epoch
        && published.certificate_digest == certificate.certificate_digest
        && !published.registry_head_digest.is_zero()
        && !published.publication_digest.is_zero()
}

fn valid_window(now: u64, issued_at: u64, expires_at: u64) -> bool {
    issued_at != 0 && issued_at <= now && now < expires_at
}

fn port<T>(
    stage: LearningOperatorStageV1,
    result: Result<T, String>,
) -> Result<T, LearningOperatorCoordinatorErrorV1> {
    result.map_err(|message| LearningOperatorCoordinatorErrorV1::Port { stage, message })
}

fn invariant<T>(
    stage: LearningOperatorStageV1,
    message: &'static str,
) -> Result<T, LearningOperatorCoordinatorErrorV1> {
    Err(LearningOperatorCoordinatorErrorV1::Invariant { stage, message })
}

#[allow(clippy::too_many_arguments)]
fn audit_digest(
    request: &LearningOperatorRunRequestV1,
    candidate: &FittedOperatorCandidateV1,
    evaluation: &IndependentOperatorEvaluationV1,
    selection: &SelectedOperatorCandidateV1,
    certificate: &CertifiedOperatorCandidateV1,
    published: &PublishedOperatorCandidateV1,
    canary_digest: Digest32,
    terminal_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-operator.coordinator-audit.v1\0".to_vec();
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
        evaluation.dataset_digest,
        evaluation.evidence_digest,
        selection.selection_digest,
        selection.reason.policy_digest,
        certificate.certificate_digest,
        published.registry_head_digest,
        published.publication_digest,
        canary_digest,
        terminal_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.expected_authority_epoch.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn rollback_audit_digest(
    request: &LearningOperatorRunRequestV1,
    candidate: &FittedOperatorCandidateV1,
    published: &PublishedOperatorCandidateV1,
    rollback: &RolledBackOperatorCandidateV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-operator.coordinator-rollback-audit.v1\0".to_vec();
    push_id(&mut bytes, &request.run_id);
    for digest in [
        request.predecessor_artifact_digest,
        candidate.artifact_digest,
        published.publication_digest,
        rollback.rollback_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.expected_authority_epoch.to_be_bytes());
    bytes.push(rollback_trigger_code(rollback.trigger));
    Digest32::of_bytes(&bytes)
}

fn rollback_trigger_code(value: LearningOperatorRollbackTriggerV1) -> u8 {
    match value {
        LearningOperatorRollbackTriggerV1::PublicationBindingMismatch => 1,
        LearningOperatorRollbackTriggerV1::CanaryUnavailable => 2,
        LearningOperatorRollbackTriggerV1::CanaryRejected => 3,
        LearningOperatorRollbackTriggerV1::CanaryBindingMismatch => 4,
        LearningOperatorRollbackTriggerV1::ActivationUnavailable => 5,
        LearningOperatorRollbackTriggerV1::ActivationBindingMismatch => 6,
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
        SameEvaluationDataset,
        EvaluatorIsProducer,
        CertificateExpired,
        PersistedPayloadMismatch,
        PublicationEpochMismatch,
        PublishCrash,
        CanaryRejected,
        CanaryCrash,
        ActivationCrash,
        ActivationBindingMismatch,
        RollbackMismatch,
    }

    struct Ports {
        fault: Fault,
        stages: Vec<LearningOperatorStageV1>,
    }

    impl Ports {
        fn new(fault: Fault) -> Self {
            Self {
                fault,
                stages: Vec::new(),
            }
        }

        fn request() -> LearningOperatorRunRequestV1 {
            LearningOperatorRunRequestV1 {
                run_id: id("run"),
                owner_id: id("owner"),
                producer_id: id("producer"),
                objective_digest: hash("objective"),
                training_source_digest: hash("training-source"),
                evaluation_source_digest: hash("evaluation-source"),
                predecessor_id: id("predecessor"),
                predecessor_generation: generation(7),
                predecessor_artifact_digest: hash("predecessor-artifact"),
                expected_authority_epoch: 11,
                now_unix_micros: 100,
            }
        }

        fn training() -> FrozenOperatorDatasetV1 {
            FrozenOperatorDatasetV1 {
                receipt_id: id("training-receipt"),
                owner_id: id("owner"),
                authority_epoch: 11,
                source_digest: hash("training-source"),
                dataset_digest: hash("training-dataset"),
                row_commitment_digest: hash("training-rows"),
                frozen_at: 90,
                expires_at: 200,
            }
        }

        fn evaluation(&self) -> FrozenOperatorDatasetV1 {
            let same = self.fault == Fault::SameEvaluationDataset;
            FrozenOperatorDatasetV1 {
                receipt_id: if same {
                    id("training-receipt")
                } else {
                    id("evaluation-receipt")
                },
                owner_id: id("owner"),
                authority_epoch: 11,
                source_digest: hash("evaluation-source"),
                dataset_digest: if same {
                    hash("training-dataset")
                } else {
                    hash("evaluation-dataset")
                },
                row_commitment_digest: if same {
                    hash("training-rows")
                } else {
                    hash("evaluation-rows")
                },
                frozen_at: 91,
                expires_at: 200,
            }
        }
    }

    impl LearningOperatorCoordinatorPortsV1 for Ports {
        fn freeze_training(
            &mut self,
            _request: &LearningOperatorRunRequestV1,
        ) -> Result<FrozenOperatorDatasetV1, String> {
            self.stages.push(LearningOperatorStageV1::FreezeTraining);
            Ok(Self::training())
        }

        fn derive(
            &mut self,
            _request: &LearningOperatorRunRequestV1,
            training: &FrozenOperatorDatasetV1,
        ) -> Result<DerivedOperatorTrainingInputV1, String> {
            self.stages.push(LearningOperatorStageV1::Derive);
            Ok(DerivedOperatorTrainingInputV1 {
                training_receipt_id: training.receipt_id.clone(),
                dataset_digest: training.dataset_digest,
                row_commitment_digest: training.row_commitment_digest,
                input_digest: hash("input"),
            })
        }

        fn fit(
            &mut self,
            request: &LearningOperatorRunRequestV1,
            input: &DerivedOperatorTrainingInputV1,
        ) -> Result<FittedOperatorCandidateV1, String> {
            self.stages.push(LearningOperatorStageV1::Fit);
            Ok(FittedOperatorCandidateV1 {
                artifact_id: id("candidate"),
                producer_id: request.producer_id.clone(),
                generation: request.predecessor_generation.next().unwrap(),
                objective_digest: request.objective_digest,
                dataset_digest: input.dataset_digest,
                artifact_digest: hash("candidate-artifact"),
                payload_digest: hash("candidate-payload"),
            })
        }

        fn freeze_evaluation(
            &mut self,
            _request: &LearningOperatorRunRequestV1,
            _candidate: &FittedOperatorCandidateV1,
        ) -> Result<FrozenOperatorDatasetV1, String> {
            self.stages.push(LearningOperatorStageV1::FreezeEvaluation);
            Ok(self.evaluation())
        }

        fn evaluate(
            &mut self,
            request: &LearningOperatorRunRequestV1,
            candidate: &FittedOperatorCandidateV1,
            evaluation_dataset: &FrozenOperatorDatasetV1,
        ) -> Result<IndependentOperatorEvaluationV1, String> {
            self.stages.push(LearningOperatorStageV1::Evaluate);
            Ok(IndependentOperatorEvaluationV1 {
                evaluation_id: id("evaluation"),
                evaluator_id: if self.fault == Fault::EvaluatorIsProducer {
                    request.producer_id.clone()
                } else {
                    id("evaluator")
                },
                dataset_receipt_id: evaluation_dataset.receipt_id.clone(),
                dataset_digest: evaluation_dataset.dataset_digest,
                candidate_artifact_digest: candidate.artifact_digest,
                evidence_digest: hash("evaluation-evidence"),
                trust_digest: hash("trust"),
                authority_epoch: 11,
                observed_at: 99,
                expires_at: 200,
            })
        }

        fn select(
            &mut self,
            _request: &LearningOperatorRunRequestV1,
            candidate: &FittedOperatorCandidateV1,
            evaluation: &IndependentOperatorEvaluationV1,
        ) -> Result<SelectedOperatorCandidateV1, String> {
            self.stages.push(LearningOperatorStageV1::Select);
            Ok(SelectedOperatorCandidateV1 {
                selection_id: id("selection"),
                selector_id: id("selector"),
                candidate_artifact_digest: candidate.artifact_digest,
                evaluation_evidence_digest: evaluation.evidence_digest,
                selection_digest: hash("selection"),
                reason: AuditableLearningOperatorSelectionReasonV1 {
                    code: LearningOperatorSelectionReasonCodeV1::IndependentFutureWindowSuperiority,
                    policy_digest: hash("selection-policy"),
                    evidence_digest: evaluation.evidence_digest,
                },
            })
        }

        fn certify(
            &mut self,
            request: &LearningOperatorRunRequestV1,
            candidate: &FittedOperatorCandidateV1,
            selection: &SelectedOperatorCandidateV1,
        ) -> Result<CertifiedOperatorCandidateV1, String> {
            self.stages.push(LearningOperatorStageV1::Certify);
            Ok(CertifiedOperatorCandidateV1 {
                certificate_digest: hash("certificate"),
                artifact_digest: candidate.artifact_digest,
                selection_digest: selection.selection_digest,
                owner_id: request.owner_id.clone(),
                authority_epoch: request.expected_authority_epoch,
                issued_at: 99,
                expires_at: if self.fault == Fault::CertificateExpired {
                    100
                } else {
                    200
                },
            })
        }

        fn persist(
            &mut self,
            _request: &LearningOperatorRunRequestV1,
            candidate: &FittedOperatorCandidateV1,
            _certificate: &CertifiedOperatorCandidateV1,
        ) -> Result<PersistedOperatorCandidateV1, String> {
            self.stages.push(LearningOperatorStageV1::Persist);
            Ok(PersistedOperatorCandidateV1 {
                artifact_digest: candidate.artifact_digest,
                payload_digest: if self.fault == Fault::PersistedPayloadMismatch {
                    hash("other-payload")
                } else {
                    candidate.payload_digest
                },
                storage_receipt_digest: hash("storage"),
            })
        }

        fn publish(
            &mut self,
            request: &LearningOperatorRunRequestV1,
            candidate: &FittedOperatorCandidateV1,
            certificate: &CertifiedOperatorCandidateV1,
            _persisted: &PersistedOperatorCandidateV1,
        ) -> Result<PublishedOperatorCandidateV1, String> {
            self.stages.push(LearningOperatorStageV1::Publish);
            if self.fault == Fault::PublishCrash {
                return Err("simulated crash before durable publication receipt".to_string());
            }
            Ok(PublishedOperatorCandidateV1 {
                artifact_digest: candidate.artifact_digest,
                payload_digest: candidate.payload_digest,
                owner_id: request.owner_id.clone(),
                authority_epoch: if self.fault == Fault::PublicationEpochMismatch {
                    request.expected_authority_epoch + 1
                } else {
                    request.expected_authority_epoch
                },
                certificate_digest: certificate.certificate_digest,
                registry_head_digest: hash("registry-head"),
                publication_digest: hash("publication"),
            })
        }

        fn canary(
            &mut self,
            request: &LearningOperatorRunRequestV1,
            published: &PublishedOperatorCandidateV1,
        ) -> Result<OperatorCanaryReceiptV1, String> {
            self.stages.push(LearningOperatorStageV1::Canary);
            if self.fault == Fault::CanaryCrash {
                return Err("simulated canary dependency failure".to_string());
            }
            Ok(OperatorCanaryReceiptV1 {
                publication_digest: published.publication_digest,
                canary_digest: hash("canary"),
                passed: !matches!(self.fault, Fault::CanaryRejected | Fault::RollbackMismatch),
                observation_count: 128,
                started_at: request.now_unix_micros,
                completed_at: request.now_unix_micros + 10,
            })
        }

        fn activate(
            &mut self,
            request: &LearningOperatorRunRequestV1,
            published: &PublishedOperatorCandidateV1,
            _canary: &OperatorCanaryReceiptV1,
        ) -> Result<ActivatedOperatorCandidateV1, String> {
            self.stages.push(LearningOperatorStageV1::Activate);
            if self.fault == Fault::ActivationCrash {
                return Err("simulated activation failure".to_string());
            }
            Ok(ActivatedOperatorCandidateV1 {
                publication_digest: published.publication_digest,
                activation_digest: hash("activation"),
                owner_id: request.owner_id.clone(),
                authority_epoch: if self.fault == Fault::ActivationBindingMismatch {
                    request.expected_authority_epoch + 1
                } else {
                    request.expected_authority_epoch
                },
            })
        }

        fn rollback(
            &mut self,
            request: &LearningOperatorRunRequestV1,
            published: &PublishedOperatorCandidateV1,
            trigger: LearningOperatorRollbackTriggerV1,
        ) -> Result<RolledBackOperatorCandidateV1, String> {
            self.stages.push(LearningOperatorStageV1::Rollback);
            Ok(RolledBackOperatorCandidateV1 {
                failed_publication_digest: published.publication_digest,
                restored_artifact_digest: if self.fault == Fault::RollbackMismatch {
                    hash("wrong-predecessor")
                } else {
                    request.predecessor_artifact_digest
                },
                restored_generation: request.predecessor_generation,
                rollback_digest: hash("rollback"),
                owner_id: request.owner_id.clone(),
                authority_epoch: request.expected_authority_epoch,
                trigger,
            })
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn hash(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).unwrap()
    }

    #[test]
    fn full_pipeline_activates_only_after_independent_evaluation_and_canary() {
        let mut ports = Ports::new(Fault::None);
        let outcome =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorTerminalV1::Activated(_)
        ));
        assert!(!outcome.audit_digest.is_zero());
        assert_eq!(
            ports.stages,
            vec![
                LearningOperatorStageV1::FreezeTraining,
                LearningOperatorStageV1::Derive,
                LearningOperatorStageV1::Fit,
                LearningOperatorStageV1::FreezeEvaluation,
                LearningOperatorStageV1::Evaluate,
                LearningOperatorStageV1::Select,
                LearningOperatorStageV1::Certify,
                LearningOperatorStageV1::Persist,
                LearningOperatorStageV1::Publish,
                LearningOperatorStageV1::Canary,
                LearningOperatorStageV1::Activate,
            ]
        );
    }

    #[test]
    fn same_training_and_evaluation_receipt_is_rejected() {
        let mut ports = Ports::new(Fault::SameEvaluationDataset);
        let error =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap_err();
        assert!(matches!(
            error,
            LearningOperatorCoordinatorErrorV1::Invariant {
                stage: LearningOperatorStageV1::FreezeEvaluation,
                ..
            }
        ));
        assert!(!ports.stages.contains(&LearningOperatorStageV1::Evaluate));
    }

    #[test]
    fn producer_cannot_be_its_own_independent_evaluator() {
        let mut ports = Ports::new(Fault::EvaluatorIsProducer);
        let error =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap_err();
        assert!(matches!(
            error,
            LearningOperatorCoordinatorErrorV1::Invariant {
                stage: LearningOperatorStageV1::Evaluate,
                ..
            }
        ));
    }

    #[test]
    fn clock_expiry_rejects_certificate_before_persistence() {
        let mut ports = Ports::new(Fault::CertificateExpired);
        let error =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap_err();
        assert!(matches!(
            error,
            LearningOperatorCoordinatorErrorV1::Invariant {
                stage: LearningOperatorStageV1::Certify,
                ..
            }
        ));
        assert!(!ports.stages.contains(&LearningOperatorStageV1::Persist));
    }

    #[test]
    fn registry_payload_mismatch_rejects_before_publication() {
        let mut ports = Ports::new(Fault::PersistedPayloadMismatch);
        let error =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap_err();
        assert!(matches!(
            error,
            LearningOperatorCoordinatorErrorV1::Invariant {
                stage: LearningOperatorStageV1::Persist,
                ..
            }
        ));
        assert!(!ports.stages.contains(&LearningOperatorStageV1::Publish));
    }

    #[test]
    fn authority_rotation_at_publication_forces_exact_predecessor_rollback() {
        let mut ports = Ports::new(Fault::PublicationEpochMismatch);
        let outcome =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorTerminalV1::RolledBack(RolledBackOperatorCandidateV1 {
                trigger: LearningOperatorRollbackTriggerV1::PublicationBindingMismatch,
                ..
            })
        ));
        assert_eq!(ports.stages.last(), Some(&LearningOperatorStageV1::Rollback));
    }

    #[test]
    fn rejected_canary_rolls_back_without_activation() {
        let mut ports = Ports::new(Fault::CanaryRejected);
        let outcome =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorTerminalV1::RolledBack(RolledBackOperatorCandidateV1 {
                trigger: LearningOperatorRollbackTriggerV1::CanaryRejected,
                ..
            })
        ));
        assert!(!ports.stages.contains(&LearningOperatorStageV1::Activate));
    }

    #[test]
    fn unavailable_canary_forces_rollback() {
        let mut ports = Ports::new(Fault::CanaryCrash);
        let outcome =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorTerminalV1::RolledBack(RolledBackOperatorCandidateV1 {
                trigger: LearningOperatorRollbackTriggerV1::CanaryUnavailable,
                ..
            })
        ));
    }

    #[test]
    fn activation_failure_is_not_retried_and_rolls_back() {
        let mut ports = Ports::new(Fault::ActivationCrash);
        let outcome =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorTerminalV1::RolledBack(RolledBackOperatorCandidateV1 {
                trigger: LearningOperatorRollbackTriggerV1::ActivationUnavailable,
                ..
            })
        ));
        assert_eq!(
            ports
                .stages
                .iter()
                .filter(|stage| **stage == LearningOperatorStageV1::Activate)
                .count(),
            1
        );
    }

    #[test]
    fn crash_before_publication_receipt_never_canaries_or_activates() {
        let mut ports = Ports::new(Fault::PublishCrash);
        let error =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap_err();
        assert!(matches!(
            error,
            LearningOperatorCoordinatorErrorV1::Port {
                stage: LearningOperatorStageV1::Publish,
                ..
            }
        ));
        assert!(!ports.stages.contains(&LearningOperatorStageV1::Canary));
        assert!(!ports.stages.contains(&LearningOperatorStageV1::Activate));
    }

    #[test]
    fn stale_activation_receipt_forces_rollback() {
        let mut ports = Ports::new(Fault::ActivationBindingMismatch);
        let outcome =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorTerminalV1::RolledBack(RolledBackOperatorCandidateV1 {
                trigger: LearningOperatorRollbackTriggerV1::ActivationBindingMismatch,
                ..
            })
        ));
    }

    #[test]
    fn bad_rollback_receipt_is_terminally_rejected() {
        let mut ports = Ports::new(Fault::RollbackMismatch);
        let error =
            coordinate_learning_operator_run_v1(&mut ports, Ports::request()).unwrap_err();
        assert!(matches!(
            error,
            LearningOperatorCoordinatorErrorV1::Invariant {
                stage: LearningOperatorStageV1::Rollback,
                ..
            }
        ));
    }

    #[test]
    fn independent_source_requirement_is_part_of_request_admission() {
        let mut request = Ports::request();
        request.evaluation_source_digest = request.training_source_digest;
        let mut ports = Ports::new(Fault::None);
        let error = coordinate_learning_operator_run_v1(&mut ports, request).unwrap_err();
        assert!(matches!(
            error,
            LearningOperatorCoordinatorErrorV1::InvalidRequest(_)
        ));
        assert!(ports.stages.is_empty());
    }
}
