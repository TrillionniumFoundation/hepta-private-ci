use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn request() -> LaneFRunRequestV1 {
    LaneFRunRequestV1 {
        run_id: id("run:lane-f"),
        request_digest: digest(b"request"),
        snapshot: CoherentLaneFSnapshotV1 {
            objective_revision: 1,
            authority_epoch: 2,
            body_generation: 3,
            model_artifact_digest: digest(b"model"),
            ndu_artifact_digest: digest(b"ndu"),
            neuron_checkpoint_digest: digest(b"checkpoint"),
            prompt_registry_generation: 4,
            learning_artifact_generation: 5,
            context_schema_revision: 6,
        },
        budget: LaneFBudgetV1 {
            total_micros: 8_000,
            objective_micros: 1_000,
            legal_set_micros: 1_000,
            neural_micros: 1_000,
            prompt_micros: 1_000,
            intuition_micros: 1_000,
            context_micros: 1_000,
            dispatch_micros: 1_000,
            ledger_micros: 1_000,
        },
    }
}

#[derive(Clone)]
struct FakePorts {
    failure: Option<(LaneFStageV1, PortFailureClassV1)>,
    intuition_decision: PortDecisionV1,
    wrong_snapshot: Option<LaneFStageV1>,
    authority_widening: Option<LaneFStageV1>,
    calls: Vec<LaneFStageV1>,
}

impl Default for FakePorts {
    fn default() -> Self {
        Self {
            failure: None,
            intuition_decision: PortDecisionV1::Continue,
            wrong_snapshot: None,
            authority_widening: None,
            calls: Vec::new(),
        }
    }
}

impl FakePorts {
    fn call(
        &mut self,
        input: &PortInputV1,
        producer: &str,
        decision: PortDecisionV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.calls.push(input.stage);
        if let Some((stage, class)) = self.failure
            && stage == input.stage
        {
            return Err(PortFailureV1 {
                class,
                evidence_digest: digest(format!("failure:{stage:?}").as_bytes()),
            });
        }
        let mut authority = AuthorityPosture::DENY_ALL;
        if self.authority_widening == Some(input.stage) {
            authority.runtime = true;
        }
        Ok(PortReceiptV1 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: if self.wrong_snapshot == Some(input.stage) {
                digest(b"mixed-snapshot")
            } else {
                input.snapshot_digest
            },
            predecessor_digest: input.predecessor_digest,
            output_digest: digest(format!("output:{:?}", input.stage).as_bytes()),
            decision,
            authority,
        })
    }
}

impl LaneFShadowPortsV1 for FakePorts {
    fn validate_objective(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "objective.compiler", PortDecisionV1::Continue)
    }

    fn build_legal_set(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "intelligence.control", PortDecisionV1::Continue)
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "neuron.runtime", PortDecisionV1::Continue)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "prompt.optimizer", PortDecisionV1::Continue)
    }

    fn decide_intuition(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "intuition.policy", self.intuition_decision)
    }

    fn compile_context(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "context.compiler", PortDecisionV1::Continue)
    }

    fn propose_dispatch(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "runtime.agentd", PortDecisionV1::Continue)
    }

    fn record_learning(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "learning.ledger", PortDecisionV1::Continue)
    }
}

#[test]
fn full_shadow_path_is_ordered_and_authority_free() {
    let mut ports = FakePorts::default();
    let receipt = run_shadow_pipeline(request(), &mut ports)
        .unwrap_or_else(|error| panic!("shadow pipeline: {error:?}"));
    assert_eq!(receipt.disposition, PipelineDispositionV1::DispatchProposed);
    assert_eq!(receipt.stages.len(), 8);
    assert_eq!(
        ports.calls,
        vec![
            LaneFStageV1::ObjectiveValidated,
            LaneFStageV1::LegalSetBuilt,
            LaneFStageV1::NeuralSignalCollected,
            LaneFStageV1::PromptPortfolioBuilt,
            LaneFStageV1::IntuitionDecided,
            LaneFStageV1::ContextCompiled,
            LaneFStageV1::DispatchProposed,
            LaneFStageV1::LearningRecorded,
        ]
    );
    assert!(!receipt.trace_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn optional_neuron_outage_uses_bounded_fallback() {
    let mut ports = FakePorts {
        failure: Some((
            LaneFStageV1::NeuralSignalCollected,
            PortFailureClassV1::Unavailable,
        )),
        ..FakePorts::default()
    };
    let receipt = run_shadow_pipeline(request(), &mut ports)
        .unwrap_or_else(|error| panic!("fallback pipeline: {error:?}"));
    assert_eq!(receipt.disposition, PipelineDispositionV1::DispatchProposed);
    assert!(receipt.stages.iter().any(|stage| {
        stage.stage == LaneFStageV1::NeuralSignalCollected
            && stage.outcome == StageOutcomeV1::FallbackUsed(PortFailureClassV1::Unavailable)
    }));
}

#[test]
fn required_objective_failure_is_terminal_and_receipted() {
    let mut ports = FakePorts {
        failure: Some((
            LaneFStageV1::ObjectiveValidated,
            PortFailureClassV1::Rejected,
        )),
        ..FakePorts::default()
    };
    let receipt = run_shadow_pipeline(request(), &mut ports)
        .unwrap_or_else(|error| panic!("terminal receipt: {error:?}"));
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV1::Failed(PortFailureClassV1::Rejected)
    );
    assert_eq!(receipt.stages.len(), 1);
    assert_eq!(
        receipt.stages[0].outcome,
        StageOutcomeV1::Failed(PortFailureClassV1::Rejected)
    );
}

#[test]
fn slow_path_skips_context_and_dispatch_but_records_decision() {
    let mut ports = FakePorts {
        intuition_decision: PortDecisionV1::SlowPath,
        ..FakePorts::default()
    };
    let receipt = run_shadow_pipeline(request(), &mut ports)
        .unwrap_or_else(|error| panic!("slow path: {error:?}"));
    assert_eq!(receipt.disposition, PipelineDispositionV1::SlowPath);
    assert!(!ports.calls.contains(&LaneFStageV1::ContextCompiled));
    assert!(!ports.calls.contains(&LaneFStageV1::DispatchProposed));
    assert_eq!(ports.calls.last(), Some(&LaneFStageV1::LearningRecorded));
}

#[test]
fn mixed_snapshot_rejects_before_next_stage() {
    let mut ports = FakePorts {
        wrong_snapshot: Some(LaneFStageV1::PromptPortfolioBuilt),
        ..FakePorts::default()
    };
    assert_eq!(
        run_shadow_pipeline(request(), &mut ports),
        Err(PipelineErrorV1::SnapshotMismatch)
    );
}

#[test]
fn port_cannot_widen_authority() {
    let mut ports = FakePorts {
        authority_widening: Some(LaneFStageV1::IntuitionDecided),
        ..FakePorts::default()
    };
    assert_eq!(
        run_shadow_pipeline(request(), &mut ports),
        Err(PipelineErrorV1::AuthorityWidening)
    );
}

#[test]
fn invalid_budget_fails_before_any_port_call() {
    let mut value = request();
    value.budget.total_micros = 7_999;
    let mut ports = FakePorts::default();
    assert_eq!(
        run_shadow_pipeline(value, &mut ports),
        Err(PipelineErrorV1::InvalidBudget)
    );
    assert!(ports.calls.is_empty());
}

#[test]
fn trace_digest_is_deterministic_for_equal_port_receipts() {
    let value = request();
    let mut left = FakePorts::default();
    let mut right = FakePorts::default();
    let first = run_shadow_pipeline(value.clone(), &mut left)
        .unwrap_or_else(|error| panic!("first pipeline: {error:?}"));
    let second = run_shadow_pipeline(value, &mut right)
        .unwrap_or_else(|error| panic!("second pipeline: {error:?}"));
    assert_eq!(first, second);
}

#[test]
fn ledger_failure_overrides_advisory_decision() {
    let mut ports = FakePorts {
        failure: Some((
            LaneFStageV1::LearningRecorded,
            PortFailureClassV1::Indeterminate,
        )),
        ..FakePorts::default()
    };
    let receipt = run_shadow_pipeline(request(), &mut ports)
        .unwrap_or_else(|error| panic!("ledger failure receipt: {error:?}"));
    assert_eq!(
        receipt.disposition,
        PipelineDispositionV1::Failed(PortFailureClassV1::Indeterminate)
    );
    assert_eq!(
        receipt.stages.last().map(|stage| stage.outcome),
        Some(StageOutcomeV1::Failed(PortFailureClassV1::Indeterminate))
    );
}

