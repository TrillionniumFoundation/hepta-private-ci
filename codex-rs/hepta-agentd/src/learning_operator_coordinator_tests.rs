use super::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const TRAINING_AT: u64 = 110;
const EVALUATION_FREEZE_AT: u64 = 200;
const EVALUATION_AT: u64 = 250;
const LOAD_AT: u64 = 300;
const SHADOW_AT: u64 = 400;
const CURRENTNESS_AT: u64 = 500;
const EXPIRES_AT: u64 = 900;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Fault {
    None,
    LoadPayloadMismatch,
    LoadAfterDeadline,
    ShadowRejected,
    CurrentnessClockRegression,
    HostClockRegression,
    TrainingExpiresDuringDerive,
    EvaluationExpiresDuringEvaluate,
    FrozenEvaluationAtTrainingTime,
    FrozenEvaluationBeforeFitCompleted,
    PersistUnknown,
    PersistWrongArtifact,
    PersistAfterDeadline,
    LoadBackdatedAfterDeadline,
    ShadowAfterLoadExpiry,
    CurrentnessAfterShadowExpiry,
    FutureDatedTraining,
    DifferentRollbackReceipt,
    DifferentSelectionReason,
    RollbackUnknown,
    RollbackWrongPredecessor,
}

struct Fixture {
    fault: Fault,
    now: u64,
    stages: Vec<LearningOperatorShadowStageV1>,
    currentness: LearningOperatorCurrentnessStateV1,
    last_trigger: Option<LearningOperatorShadowRollbackTriggerV1>,
}

impl Fixture {
    fn new() -> Self {
        Self {
            fault: Fault::None,
            now: 100,
            stages: Vec::new(),
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
    frozen_at: u64,
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
        frozen_at,
        expires_at: EXPIRES_AT,
    }
}

impl LearningOperatorShadowPortsV1 for Fixture {
    fn now_unix_micros(&mut self) -> u64 {
        self.now
    }

    fn freeze_training(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
    ) -> Result<FrozenOperatorDatasetV1, String> {
        self.stages
            .push(LearningOperatorShadowStageV1::FreezeTraining);
        self.now = TRAINING_AT;
        let mut receipt = frozen(
            request,
            "training",
            request.training_source_digest,
            TRAINING_AT,
        );
        if self.fault == Fault::TrainingExpiresDuringDerive {
            receipt.expires_at = TRAINING_AT + 5;
        }
        if self.fault == Fault::FutureDatedTraining {
            receipt.frozen_at = TRAINING_AT + 1;
        }
        Ok(receipt)
    }

    fn derive(
        &mut self,
        _request: &LearningOperatorShadowRequestV1,
        training: &FrozenOperatorDatasetV1,
    ) -> Result<DerivedOperatorTrainingInputV1, String> {
        self.stages.push(LearningOperatorShadowStageV1::Derive);
        self.now = if self.fault == Fault::HostClockRegression {
            TRAINING_AT - 1
        } else {
            120
        };
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
        self.stages.push(LearningOperatorShadowStageV1::Fit);
        self.now = 130;
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
        self.stages
            .push(LearningOperatorShadowStageV1::FreezeEvaluation);
        self.now = EVALUATION_FREEZE_AT;
        let mut receipt = frozen(
            request,
            "evaluation",
            request.evaluation_source_digest,
            EVALUATION_FREEZE_AT,
        );
        if self.fault == Fault::EvaluationExpiresDuringEvaluate {
            receipt.expires_at = EVALUATION_FREEZE_AT + 20;
        }
        if self.fault == Fault::FrozenEvaluationAtTrainingTime {
            receipt.frozen_at = TRAINING_AT;
        }
        if self.fault == Fault::FrozenEvaluationBeforeFitCompleted {
            receipt.frozen_at = 130;
        }
        Ok(receipt)
    }

    fn evaluate(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        dataset: &FrozenOperatorDatasetV1,
    ) -> Result<IndependentOperatorEvaluationV1, String> {
        self.stages.push(LearningOperatorShadowStageV1::Evaluate);
        self.now = EVALUATION_AT;
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
            observed_at: EVALUATION_AT,
            expires_at: EXPIRES_AT,
        })
    }

    fn select(
        &mut self,
        _request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        evaluation: &IndependentOperatorEvaluationV1,
    ) -> Result<SelectedOperatorCandidateV1, String> {
        self.stages.push(LearningOperatorShadowStageV1::Select);
        self.now = 260;
        Ok(SelectedOperatorCandidateV1 {
            selection_id: id("selection"),
            selector_id: id("selector"),
            candidate_artifact_digest: candidate.artifact_digest,
            evaluation_evidence_digest: evaluation.evidence_digest,
            selection_digest: digest("selection"),
            reason: AuditableLearningOperatorSelectionReasonV1 {
                code: if self.fault == Fault::DifferentSelectionReason {
                    LearningOperatorSelectionReasonCodeV1::SafetyEquivalentLowerResourceCost
                } else {
                    LearningOperatorSelectionReasonCodeV1::IndependentFutureWindowSuperiority
                },
                policy_digest: digest("selection-policy"),
                evidence_digest: evaluation.evidence_digest,
            },
        })
    }

    fn persist(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
    ) -> Result<PersistedOperatorCandidateV1, String> {
        self.stages.push(LearningOperatorShadowStageV1::Persist);
        self.now = if self.fault == Fault::PersistAfterDeadline {
            request.deadline_unix_micros
        } else {
            270
        };
        if self.fault == Fault::PersistUnknown {
            return Err("write acknowledgement lost".to_owned());
        }
        Ok(PersistedOperatorCandidateV1 {
            artifact_digest: if self.fault == Fault::PersistWrongArtifact {
                digest("unrelated-artifact")
            } else {
                candidate.artifact_digest
            },
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
        self.stages
            .push(LearningOperatorShadowStageV1::FreshProcessLoad);
        self.now = if self.fault == Fault::LoadBackdatedAfterDeadline {
            request.deadline_unix_micros
        } else {
            LOAD_AT
        };
        let payload_digest = if self.fault == Fault::LoadPayloadMismatch {
            digest("wrong-payload")
        } else {
            persisted.payload_digest
        };
        let loaded_at = if self.fault == Fault::LoadAfterDeadline {
            request.deadline_unix_micros
        } else {
            LOAD_AT
        };
        Ok(FreshProcessLoadedOperatorV1 {
            process_id: id("fresh-process"),
            boot_nonce_digest: digest("boot-nonce"),
            artifact_digest: persisted.artifact_digest,
            payload_digest,
            selection_digest: persisted.selection_digest,
            storage_receipt_digest: persisted.storage_receipt_digest,
            loaded_digest: digest("loaded"),
            loaded_at,
            expires_at: if self.fault == Fault::ShadowAfterLoadExpiry {
                SHADOW_AT
            } else {
                EXPIRES_AT
            },
        })
    }

    fn shadow(
        &mut self,
        _request: &LearningOperatorShadowRequestV1,
        loaded: &FreshProcessLoadedOperatorV1,
    ) -> Result<OperatorShadowReceiptV1, String> {
        self.stages.push(LearningOperatorShadowStageV1::Shadow);
        self.now = SHADOW_AT;
        Ok(OperatorShadowReceiptV1 {
            process_id: loaded.process_id.clone(),
            loaded_digest: loaded.loaded_digest,
            artifact_digest: loaded.artifact_digest,
            selection_digest: loaded.selection_digest,
            shadow_digest: digest("shadow"),
            passed: self.fault != Fault::ShadowRejected,
            observation_count: 64,
            observed_at: SHADOW_AT,
            expires_at: if self.fault == Fault::CurrentnessAfterShadowExpiry {
                CURRENTNESS_AT
            } else {
                EXPIRES_AT
            },
        })
    }

    fn revalidate(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
        _shadow: &OperatorShadowReceiptV1,
    ) -> Result<OperatorCurrentnessReceiptV1, String> {
        self.stages.push(LearningOperatorShadowStageV1::Revalidate);
        self.now = CURRENTNESS_AT;
        let observed_at = if self.fault == Fault::CurrentnessClockRegression {
            SHADOW_AT - 1
        } else {
            CURRENTNESS_AT
        };
        Ok(OperatorCurrentnessReceiptV1 {
            artifact_digest: candidate.artifact_digest,
            selection_digest: selection.selection_digest,
            ledger_head_digest: digest("current-ledger"),
            registry_head_digest: digest("current-registry"),
            authority_epoch: request.expected_authority_epoch,
            stop_epoch: request.expected_stop_epoch,
            state: self.currentness,
            observed_at,
            expires_at: EXPIRES_AT,
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
        self.stages.push(LearningOperatorShadowStageV1::Rollback);
        self.last_trigger = Some(trigger);
        if self.fault == Fault::RollbackUnknown {
            return Err("cleanup acknowledgement lost".to_owned());
        }
        Ok(RolledBackOperatorCandidateV1 {
            failed_artifact_digest: candidate.artifact_digest,
            failed_selection_digest: selection.selection_digest,
            restored_artifact_digest: if self.fault == Fault::RollbackWrongPredecessor {
                digest("unrelated-predecessor")
            } else {
                request.predecessor_artifact_digest
            },
            restored_generation: request.predecessor_generation,
            rollback_digest: if self.fault == Fault::DifferentRollbackReceipt {
                digest("another-rollback")
            } else {
                digest("rollback")
            },
            owner_id: request.owner_id.clone(),
            authority_epoch: request.expected_authority_epoch,
            stop_epoch: request.expected_stop_epoch,
            trigger,
        })
    }
}

#[test]
fn realistic_monotonic_shadow_timeline_is_qualified_then_rolled_back() {
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
fn fresh_process_load_at_deadline_is_rejected_and_rolled_back() {
    let mut fixture = Fixture::new();
    fixture.fault = Fault::LoadAfterDeadline;
    let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
    assert!(matches!(
        outcome.terminal,
        LearningOperatorShadowTerminalV1::RejectedAndRolledBack(_)
    ));
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

#[test]
fn currentness_clock_regression_is_rejected_and_rolled_back() {
    let mut fixture = Fixture::new();
    fixture.fault = Fault::CurrentnessClockRegression;
    let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
    assert!(matches!(
        outcome.terminal,
        LearningOperatorShadowTerminalV1::RejectedAndRolledBack(_)
    ));
    assert_eq!(
        fixture.last_trigger,
        Some(LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch)
    );
}

#[test]
fn host_clock_and_receipt_expiry_reject_pre_persistence_work() {
    for (fault, rejected_stage) in [
        (
            Fault::HostClockRegression,
            LearningOperatorShadowStageV1::Derive,
        ),
        (
            Fault::TrainingExpiresDuringDerive,
            LearningOperatorShadowStageV1::Derive,
        ),
        (
            Fault::EvaluationExpiresDuringEvaluate,
            LearningOperatorShadowStageV1::Evaluate,
        ),
        (
            Fault::FrozenEvaluationAtTrainingTime,
            LearningOperatorShadowStageV1::FreezeEvaluation,
        ),
        (
            Fault::FrozenEvaluationBeforeFitCompleted,
            LearningOperatorShadowStageV1::FreezeEvaluation,
        ),
        (
            Fault::FutureDatedTraining,
            LearningOperatorShadowStageV1::FreezeTraining,
        ),
    ] {
        let mut fixture = Fixture::new();
        fixture.fault = fault;
        let error = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap_err();
        assert!(
            matches!(error, LearningOperatorShadowErrorV1::Invariant { stage, .. } if stage == rejected_stage)
        );
        assert!(
            !fixture
                .stages
                .contains(&LearningOperatorShadowStageV1::Persist)
        );
        assert_eq!(fixture.last_trigger, None);
    }
}

#[test]
fn verified_persistence_is_cleaned_up_when_actual_host_deadline_passes() {
    for (fault, trigger, excluded_stage) in [
        (
            Fault::PersistAfterDeadline,
            LearningOperatorShadowRollbackTriggerV1::PersistDeadlineExceeded,
            Some(LearningOperatorShadowStageV1::FreshProcessLoad),
        ),
        (
            Fault::LoadBackdatedAfterDeadline,
            LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch,
            Some(LearningOperatorShadowStageV1::Shadow),
        ),
        (
            Fault::ShadowAfterLoadExpiry,
            LearningOperatorShadowRollbackTriggerV1::ShadowRejected,
            Some(LearningOperatorShadowStageV1::Revalidate),
        ),
        (
            Fault::CurrentnessAfterShadowExpiry,
            LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch,
            None,
        ),
    ] {
        let mut fixture = Fixture::new();
        fixture.fault = fault;
        let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
        assert!(matches!(
            outcome.terminal,
            LearningOperatorShadowTerminalV1::RejectedAndRolledBack(_)
        ));
        assert_eq!(fixture.last_trigger, Some(trigger));
        if let Some(excluded_stage) = excluded_stage {
            assert!(!fixture.stages.contains(&excluded_stage));
        }
    }
}

#[test]
fn unverified_persistence_retains_recovery_identity_and_never_targets_an_unrelated_object() {
    for fault in [Fault::PersistUnknown, Fault::PersistWrongArtifact] {
        let mut fixture = Fixture::new();
        fixture.fault = fault;
        let error = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap_err();
        let LearningOperatorShadowErrorV1::PersistenceOutcomeUnknown { recovery, .. } = error
        else {
            panic!("persistence uncertainty must be distinguished from a pre-write failure");
        };
        assert_eq!(
            (
                recovery.run_id,
                recovery.candidate_artifact_digest,
                recovery.selection_digest
            ),
            (id("run"), digest("artifact"), digest("selection"))
        );
        assert_eq!(
            recovery.reported.is_some(),
            fault == Fault::PersistWrongArtifact
        );
        assert_eq!(
            fixture.stages.last(),
            Some(&LearningOperatorShadowStageV1::Persist)
        );
        assert_eq!(fixture.last_trigger, None);
    }
}

#[test]
fn terminal_audit_commits_to_selection_reason_and_cleanup_evidence() {
    let baseline = coordinate_learning_operator_shadow_v1(&mut Fixture::new(), request()).unwrap();
    for fault in [
        Fault::DifferentRollbackReceipt,
        Fault::DifferentSelectionReason,
    ] {
        let mut fixture = Fixture::new();
        fixture.fault = fault;
        let outcome = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap();
        assert_ne!(baseline.audit_digest, outcome.audit_digest);
        assert_eq!(
            baseline.candidate_artifact_digest,
            outcome.candidate_artifact_digest
        );
        assert_eq!(baseline.selection_digest, outcome.selection_digest);
    }
}

#[test]
fn unverified_cleanup_is_not_a_terminal_outcome_and_retains_the_verified_storage_binding() {
    for fault in [Fault::RollbackUnknown, Fault::RollbackWrongPredecessor] {
        let mut fixture = Fixture::new();
        fixture.fault = fault;
        let error = coordinate_learning_operator_shadow_v1(&mut fixture, request()).unwrap_err();
        let LearningOperatorShadowErrorV1::RollbackFailed {
            trigger, recovery, ..
        } = error
        else {
            panic!("unverified cleanup must retain its reconciliation identity");
        };
        assert_eq!(
            trigger,
            LearningOperatorShadowRollbackTriggerV1::ShadowCompleted
        );
        assert_eq!(
            *recovery,
            LearningOperatorPersistenceRecoveryV1 {
                run_id: id("run"),
                candidate_artifact_digest: digest("artifact"),
                selection_digest: digest("selection"),
                reported: Some(PersistedOperatorCandidateV1 {
                    artifact_digest: digest("artifact"),
                    payload_digest: digest("payload"),
                    selection_digest: digest("selection"),
                    storage_receipt_digest: digest("storage"),
                }),
            }
        );
        assert_eq!(
            fixture.stages.last(),
            Some(&LearningOperatorShadowStageV1::Rollback)
        );
    }
}

#[test]
fn terminal_audit_binds_producer_and_generation_identity_despite_equal_opaque_receipt_digests() {
    let baseline = coordinate_learning_operator_shadow_v1(&mut Fixture::new(), request()).unwrap();
    let mut other_producer = request();
    other_producer.producer_id = id("other-producer");
    let mut other_generation = request();
    other_generation.predecessor_generation = Generation::new(2).unwrap();
    for changed_request in [other_producer, other_generation] {
        let outcome =
            coordinate_learning_operator_shadow_v1(&mut Fixture::new(), changed_request).unwrap();
        assert_eq!(
            baseline.candidate_artifact_digest,
            outcome.candidate_artifact_digest
        );
        assert_eq!(baseline.selection_digest, outcome.selection_digest);
        assert_eq!(baseline.shadow_digest, outcome.shadow_digest);
        assert_eq!(baseline.currentness_digest, outcome.currentness_digest);
        assert_ne!(baseline.audit_digest, outcome.audit_digest);
    }
}
