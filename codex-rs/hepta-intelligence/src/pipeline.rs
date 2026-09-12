//! Typed, authority-free Lane F shadow composition host.
//!
//! This stage machine composes registered owner ports against one coherent
//! snapshot. It does not invoke a model, tool or provider and cannot execute an
//! external effect. A dispatch result is a proposal only.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoherentLaneFSnapshotV1 {
    pub objective_revision: u64,
    pub authority_epoch: u64,
    pub body_generation: u64,
    pub model_artifact_digest: Digest32,
    pub ndu_artifact_digest: Digest32,
    pub neuron_checkpoint_digest: Digest32,
    pub prompt_registry_generation: u64,
    pub learning_artifact_generation: u64,
    pub context_schema_revision: u64,
}

impl CoherentLaneFSnapshotV1 {
    pub fn digest(&self) -> Result<Digest32, PipelineErrorV1> {
        if self.objective_revision == 0
            || self.authority_epoch == 0
            || self.body_generation == 0
            || self.prompt_registry_generation == 0
            || self.learning_artifact_generation == 0
            || self.context_schema_revision == 0
        {
            return Err(PipelineErrorV1::InvalidSnapshot);
        }
        for digest in [
            self.model_artifact_digest,
            self.ndu_artifact_digest,
            self.neuron_checkpoint_digest,
        ] {
            if digest.is_zero() {
                return Err(PipelineErrorV1::InvalidSnapshot);
            }
        }
        let mut bytes = b"hepta.intelligence.lane-f-snapshot.v1".to_vec();
        for value in [
            self.objective_revision,
            self.authority_epoch,
            self.body_generation,
            self.prompt_registry_generation,
            self.learning_artifact_generation,
            self.context_schema_revision,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for digest in [
            self.model_artifact_digest,
            self.ndu_artifact_digest,
            self.neuron_checkpoint_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LaneFBudgetV1 {
    pub total_micros: u64,
    pub objective_micros: u64,
    pub legal_set_micros: u64,
    pub neural_micros: u64,
    pub prompt_micros: u64,
    pub intuition_micros: u64,
    pub context_micros: u64,
    pub dispatch_micros: u64,
    pub ledger_micros: u64,
}

impl LaneFBudgetV1 {
    fn validate(self) -> Result<(), PipelineErrorV1> {
        let stages = [
            self.objective_micros,
            self.legal_set_micros,
            self.neural_micros,
            self.prompt_micros,
            self.intuition_micros,
            self.context_micros,
            self.dispatch_micros,
            self.ledger_micros,
        ];
        if self.total_micros == 0 || stages.contains(&0) {
            return Err(PipelineErrorV1::InvalidBudget);
        }
        let sum = stages
            .into_iter()
            .try_fold(0u64, u64::checked_add)
            .ok_or(PipelineErrorV1::InvalidBudget)?;
        if sum > self.total_micros {
            return Err(PipelineErrorV1::InvalidBudget);
        }
        Ok(())
    }

    const fn for_stage(self, stage: LaneFStageV1) -> u64 {
        match stage {
            LaneFStageV1::ObjectiveValidated => self.objective_micros,
            LaneFStageV1::LegalSetBuilt => self.legal_set_micros,
            LaneFStageV1::NeuralSignalCollected => self.neural_micros,
            LaneFStageV1::PromptPortfolioBuilt => self.prompt_micros,
            LaneFStageV1::IntuitionDecided => self.intuition_micros,
            LaneFStageV1::ContextCompiled => self.context_micros,
            LaneFStageV1::DispatchProposed => self.dispatch_micros,
            LaneFStageV1::LearningRecorded => self.ledger_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFRunRequestV1 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CoherentLaneFSnapshotV1,
    pub budget: LaneFBudgetV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LaneFStageV1 {
    ObjectiveValidated,
    LegalSetBuilt,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
    DispatchProposed,
    LearningRecorded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortDecisionV1 {
    Continue,
    Abstain,
    SlowPath,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortFailureClassV1 {
    Rejected,
    Unavailable,
    TimedOut,
    Quarantined,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortInputV1 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub budget_micros: u64,
    pub stage: LaneFStageV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortReceiptV1 {
    pub stage: LaneFStageV1,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub decision: PortDecisionV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortFailureV1 {
    pub class: PortFailureClassV1,
    pub evidence_digest: Digest32,
}

/// Host adapters for the eight shadow stages. Implementations must honor the
/// coherent snapshot and predecessor, enforce their supplied time budget, and
/// return owner evidence without executing the dispatch proposal. This
/// synchronous coordinator cannot interrupt a blocked port call.
pub trait LaneFShadowPortsV1 {
    fn validate_objective(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1>;

    fn build_legal_set(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1>;

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1>;

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1>;

    fn decide_intuition(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1>;

    fn compile_context(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1>;

    fn propose_dispatch(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1>;

    fn record_learning(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StageOutcomeV1 {
    Completed,
    FallbackUsed(PortFailureClassV1),
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StageTraceV1 {
    pub stage: LaneFStageV1,
    pub producer: StableId,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub outcome: StageOutcomeV1,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PipelineDispositionV1 {
    DispatchProposed,
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFShadowPipelineReceiptV1 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub disposition: PipelineDispositionV1,
    pub stages: Vec<StageTraceV1>,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl LaneFShadowPipelineReceiptV1 {
    /// Validate a pipeline receipt before it is handed to another owner.
    ///
    /// The coordinator validates every port response while running, but the
    /// resulting receipt can be persisted, transported, or reconstructed by a
    /// caller.  Re-validating the stage chain prevents a forged or truncated
    /// trace from being treated as evidence of a completed shadow run.
    pub fn validate(&self) -> Result<(), PipelineErrorV1> {
        if self.snapshot_digest.is_zero() || self.trace_digest.is_zero() {
            return Err(PipelineErrorV1::InvalidPipelineReceipt("empty digest"));
        }
        if self.authority.grants_any() {
            return Err(PipelineErrorV1::AuthorityWidening);
        }
        if self.stages.is_empty() || self.stages.len() > 8 {
            return Err(PipelineErrorV1::InvalidPipelineReceipt("stage count"));
        }

        let mut previous_stage = None;
        let mut previous_output = None;
        let mut intuition_outcome = None;
        let mut saw_context = false;
        let mut saw_dispatch = false;
        for trace in &self.stages {
            if let Some(previous) = previous_stage
                && stage_code(trace.stage) <= stage_code(previous)
            {
                return Err(PipelineErrorV1::InvalidPipelineReceipt("stage order"));
            }
            if trace.predecessor_digest.is_zero()
                || trace.output_digest.is_zero()
                || trace.evidence_digest.is_zero()
            {
                return Err(PipelineErrorV1::InvalidPipelineReceipt(
                    "empty stage digest",
                ));
            }
            if let Some(output) = previous_output
                && trace.predecessor_digest != output
            {
                return Err(PipelineErrorV1::PredecessorMismatch);
            }
            let expected_producer = producer_for_stage(trace.stage);
            if trace.producer.as_str() != expected_producer {
                return Err(PipelineErrorV1::ProducerMismatch);
            }
            if matches!(trace.outcome, StageOutcomeV1::FallbackUsed(_))
                && !matches!(
                    trace.stage,
                    LaneFStageV1::NeuralSignalCollected | LaneFStageV1::PromptPortfolioBuilt
                )
            {
                return Err(PipelineErrorV1::InvalidPipelineReceipt(
                    "required stage fallback",
                ));
            }
            if let StageOutcomeV1::FallbackUsed(class) | StageOutcomeV1::Failed(class) =
                trace.outcome
            {
                let expected = fallback_digest(
                    trace.stage,
                    trace.predecessor_digest,
                    class,
                    trace.evidence_digest,
                );
                if trace.output_digest != expected {
                    return Err(PipelineErrorV1::InvalidPipelineReceipt("fallback digest"));
                }
            }
            if trace.stage == LaneFStageV1::IntuitionDecided {
                intuition_outcome = Some(trace.outcome);
            }
            saw_context |= trace.stage == LaneFStageV1::ContextCompiled;
            saw_dispatch |= trace.stage == LaneFStageV1::DispatchProposed;
            previous_stage = Some(trace.stage);
            previous_output = Some(trace.output_digest);
        }

        let last = self.stages.last().expect("non-empty checked above");
        match self.disposition {
            PipelineDispositionV1::DispatchProposed => {
                if !saw_context
                    || !saw_dispatch
                    || !matches!(last.outcome, StageOutcomeV1::Completed)
                    || last.stage != LaneFStageV1::LearningRecorded
                {
                    return Err(PipelineErrorV1::InvalidPipelineReceipt(
                        "dispatch disposition",
                    ));
                }
            }
            PipelineDispositionV1::Abstained => {
                if intuition_outcome != Some(StageOutcomeV1::Abstained)
                    || saw_context
                    || saw_dispatch
                    || last.stage != LaneFStageV1::LearningRecorded
                {
                    return Err(PipelineErrorV1::InvalidPipelineReceipt(
                        "abstain disposition",
                    ));
                }
            }
            PipelineDispositionV1::SlowPath => {
                if intuition_outcome != Some(StageOutcomeV1::SlowPath)
                    || saw_context
                    || saw_dispatch
                    || last.stage != LaneFStageV1::LearningRecorded
                {
                    return Err(PipelineErrorV1::InvalidPipelineReceipt(
                        "slow-path disposition",
                    ));
                }
            }
            PipelineDispositionV1::Failed(class) => {
                if last.outcome != StageOutcomeV1::Failed(class) {
                    return Err(PipelineErrorV1::InvalidPipelineReceipt(
                        "failure disposition",
                    ));
                }
            }
        }
        let expected_trace = digest_trace(
            &self.run_id,
            self.snapshot_digest,
            self.disposition,
            &self.stages,
            last.output_digest,
        )?;
        if self.trace_digest != expected_trace {
            return Err(PipelineErrorV1::TraceDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PipelineErrorV1 {
    InvalidSnapshot,
    InvalidBudget,
    EmptyDigest(&'static str),
    InvalidPortFailure,
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    PredecessorMismatch,
    AuthorityWidening,
    UnexpectedDecision,
    InvalidPipelineReceipt(&'static str),
    TraceDigestMismatch,
    Arithmetic,
}

impl fmt::Display for PipelineErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PipelineErrorV1 {}

enum StageAdvance {
    Continue(Digest32),
    Terminal(PortFailureClassV1, Digest32),
}

pub fn run_shadow_pipeline<P: LaneFShadowPortsV1>(
    request: LaneFRunRequestV1,
    ports: &mut P,
) -> Result<LaneFShadowPipelineReceiptV1, PipelineErrorV1> {
    if request.request_digest.is_zero() {
        return Err(PipelineErrorV1::EmptyDigest("request"));
    }
    request.budget.validate()?;
    let snapshot_digest = request.snapshot.digest()?;
    let mut stages = Vec::with_capacity(8);
    let mut predecessor = request.request_digest;

    macro_rules! required {
        ($stage:expr, $producer:literal, $call:expr) => {
            match required_stage(
                &request,
                snapshot_digest,
                predecessor,
                $stage,
                $producer,
                &mut stages,
                $call,
            )? {
                StageAdvance::Continue(output) => predecessor = output,
                StageAdvance::Terminal(class, terminal) => {
                    return finish(
                        request.run_id,
                        snapshot_digest,
                        PipelineDispositionV1::Failed(class),
                        stages,
                        terminal,
                    );
                }
            }
        };
    }

    required!(
        LaneFStageV1::ObjectiveValidated,
        "objective.compiler",
        |input| ports.validate_objective(input)
    );
    required!(
        LaneFStageV1::LegalSetBuilt,
        "intelligence.control",
        |input| ports.build_legal_set(input)
    );

    predecessor = optional_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV1::NeuralSignalCollected,
        "neuron.runtime",
        &mut stages,
        |input| ports.collect_neural_signal(input),
    )?;
    predecessor = optional_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV1::PromptPortfolioBuilt,
        "prompt.optimizer",
        &mut stages,
        |input| ports.build_prompt_portfolio(input),
    )?;

    let intuition_input = port_input(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV1::IntuitionDecided,
    );
    let intuition = match ports.decide_intuition(&intuition_input) {
        Ok(receipt) => {
            validate_receipt(&intuition_input, "intuition.policy", &receipt)?;
            receipt
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let class = failure.class;
            let terminal = append_failure_trace(
                &mut stages,
                LaneFStageV1::IntuitionDecided,
                "intuition.policy",
                predecessor,
                failure,
            )?;
            return finish(
                request.run_id,
                snapshot_digest,
                PipelineDispositionV1::Failed(class),
                stages,
                terminal,
            );
        }
    };
    predecessor = intuition.output_digest;
    let disposition = match intuition.decision {
        PortDecisionV1::Continue => PipelineDispositionV1::DispatchProposed,
        PortDecisionV1::Abstain => PipelineDispositionV1::Abstained,
        PortDecisionV1::SlowPath => PipelineDispositionV1::SlowPath,
    };
    stages.push(StageTraceV1 {
        stage: intuition.stage,
        producer: intuition.producer,
        predecessor_digest: intuition.predecessor_digest,
        output_digest: intuition.output_digest,
        outcome: match intuition.decision {
            PortDecisionV1::Continue => StageOutcomeV1::Completed,
            PortDecisionV1::Abstain => StageOutcomeV1::Abstained,
            PortDecisionV1::SlowPath => StageOutcomeV1::SlowPath,
        },
        evidence_digest: intuition.output_digest,
    });

    if intuition.decision == PortDecisionV1::Continue {
        required!(LaneFStageV1::ContextCompiled, "context.compiler", |input| {
            ports.compile_context(input)
        });
        required!(LaneFStageV1::DispatchProposed, "runtime.agentd", |input| {
            ports.propose_dispatch(input)
        });
    }

    match required_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV1::LearningRecorded,
        "learning.ledger",
        &mut stages,
        |input| ports.record_learning(input),
    )? {
        StageAdvance::Continue(output) => predecessor = output,
        StageAdvance::Terminal(class, terminal) => {
            return finish(
                request.run_id,
                snapshot_digest,
                PipelineDispositionV1::Failed(class),
                stages,
                terminal,
            );
        }
    }

    finish(
        request.run_id,
        snapshot_digest,
        disposition,
        stages,
        predecessor,
    )
}

fn required_stage<F>(
    request: &LaneFRunRequestV1,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: LaneFStageV1,
    producer: &str,
    traces: &mut Vec<StageTraceV1>,
    call: F,
) -> Result<StageAdvance, PipelineErrorV1>
where
    F: FnOnce(&PortInputV1) -> Result<PortReceiptV1, PortFailureV1>,
{
    let input = port_input(request, snapshot_digest, predecessor, stage);
    match call(&input) {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != PortDecisionV1::Continue {
                return Err(PipelineErrorV1::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            traces.push(StageTraceV1 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV1::Completed,
                evidence_digest: output,
            });
            Ok(StageAdvance::Continue(output))
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let class = failure.class;
            let terminal = append_failure_trace(traces, stage, producer, predecessor, failure)?;
            Ok(StageAdvance::Terminal(class, terminal))
        }
    }
}

fn optional_stage<F>(
    request: &LaneFRunRequestV1,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: LaneFStageV1,
    producer: &str,
    traces: &mut Vec<StageTraceV1>,
    call: F,
) -> Result<Digest32, PipelineErrorV1>
where
    F: FnOnce(&PortInputV1) -> Result<PortReceiptV1, PortFailureV1>,
{
    let input = port_input(request, snapshot_digest, predecessor, stage);
    match call(&input) {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != PortDecisionV1::Continue {
                return Err(PipelineErrorV1::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            traces.push(StageTraceV1 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV1::Completed,
                evidence_digest: output,
            });
            Ok(output)
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let output =
                fallback_digest(stage, predecessor, failure.class, failure.evidence_digest);
            traces.push(StageTraceV1 {
                stage,
                producer: stable_id(producer)?,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV1::FallbackUsed(failure.class),
                evidence_digest: failure.evidence_digest,
            });
            Ok(output)
        }
    }
}

fn append_failure_trace(
    traces: &mut Vec<StageTraceV1>,
    stage: LaneFStageV1,
    producer: &str,
    predecessor: Digest32,
    failure: PortFailureV1,
) -> Result<Digest32, PipelineErrorV1> {
    let output = fallback_digest(stage, predecessor, failure.class, failure.evidence_digest);
    traces.push(StageTraceV1 {
        stage,
        producer: stable_id(producer)?,
        predecessor_digest: predecessor,
        output_digest: output,
        outcome: StageOutcomeV1::Failed(failure.class),
        evidence_digest: failure.evidence_digest,
    });
    Ok(output)
}

fn finish(
    run_id: StableId,
    snapshot_digest: Digest32,
    disposition: PipelineDispositionV1,
    stages: Vec<StageTraceV1>,
    terminal_digest: Digest32,
) -> Result<LaneFShadowPipelineReceiptV1, PipelineErrorV1> {
    let trace_digest = digest_trace(
        &run_id,
        snapshot_digest,
        disposition,
        &stages,
        terminal_digest,
    )?;
    let receipt = LaneFShadowPipelineReceiptV1 {
        run_id,
        snapshot_digest,
        disposition,
        stages,
        trace_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn producer_for_stage(stage: LaneFStageV1) -> &'static str {
    match stage {
        LaneFStageV1::ObjectiveValidated => "objective.compiler",
        LaneFStageV1::LegalSetBuilt => "intelligence.control",
        LaneFStageV1::NeuralSignalCollected => "neuron.runtime",
        LaneFStageV1::PromptPortfolioBuilt => "prompt.optimizer",
        LaneFStageV1::IntuitionDecided => "intuition.policy",
        LaneFStageV1::ContextCompiled => "context.compiler",
        LaneFStageV1::DispatchProposed => "runtime.agentd",
        LaneFStageV1::LearningRecorded => "learning.ledger",
    }
}

fn port_input(
    request: &LaneFRunRequestV1,
    snapshot_digest: Digest32,
    predecessor_digest: Digest32,
    stage: LaneFStageV1,
) -> PortInputV1 {
    PortInputV1 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        predecessor_digest,
        budget_micros: request.budget.for_stage(stage),
        stage,
    }
}

fn validate_receipt(
    input: &PortInputV1,
    expected_producer: &str,
    receipt: &PortReceiptV1,
) -> Result<(), PipelineErrorV1> {
    if receipt.stage != input.stage {
        return Err(PipelineErrorV1::StageMismatch);
    }
    if receipt.producer.as_str() != expected_producer {
        return Err(PipelineErrorV1::ProducerMismatch);
    }
    if receipt.snapshot_digest != input.snapshot_digest {
        return Err(PipelineErrorV1::SnapshotMismatch);
    }
    if receipt.predecessor_digest != input.predecessor_digest {
        return Err(PipelineErrorV1::PredecessorMismatch);
    }
    if receipt.output_digest.is_zero() {
        return Err(PipelineErrorV1::EmptyDigest("port output"));
    }
    if receipt.authority.grants_any() {
        return Err(PipelineErrorV1::AuthorityWidening);
    }
    Ok(())
}

fn validate_failure(failure: &PortFailureV1) -> Result<(), PipelineErrorV1> {
    if failure.evidence_digest.is_zero() {
        return Err(PipelineErrorV1::InvalidPortFailure);
    }
    Ok(())
}

fn fallback_digest(
    stage: LaneFStageV1,
    predecessor: Digest32,
    class: PortFailureClassV1,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.lane-f-fallback.v1".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(failure_code(class));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_trace(
    run_id: &StableId,
    snapshot_digest: Digest32,
    disposition: PipelineDispositionV1,
    traces: &[StageTraceV1],
    terminal_digest: Digest32,
) -> Result<Digest32, PipelineErrorV1> {
    let mut bytes = b"hepta.intelligence.lane-f-shadow-trace.v1".to_vec();
    push_id(&mut bytes, run_id)?;
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(disposition_code(disposition));
    let count = u32::try_from(traces.len()).map_err(|_| PipelineErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for trace in traces {
        bytes.push(stage_code(trace.stage));
        push_id(&mut bytes, &trace.producer)?;
        bytes.extend_from_slice(trace.predecessor_digest.as_array());
        bytes.extend_from_slice(trace.output_digest.as_array());
        bytes.push(outcome_code(trace.outcome));
        bytes.extend_from_slice(trace.evidence_digest.as_array());
    }
    bytes.extend_from_slice(terminal_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn stable_id(value: &str) -> Result<StableId, PipelineErrorV1> {
    StableId::new(value).map_err(|_| PipelineErrorV1::Arithmetic)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), PipelineErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| PipelineErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

const fn stage_code(value: LaneFStageV1) -> u8 {
    match value {
        LaneFStageV1::ObjectiveValidated => 0,
        LaneFStageV1::LegalSetBuilt => 1,
        LaneFStageV1::NeuralSignalCollected => 2,
        LaneFStageV1::PromptPortfolioBuilt => 3,
        LaneFStageV1::IntuitionDecided => 4,
        LaneFStageV1::ContextCompiled => 5,
        LaneFStageV1::DispatchProposed => 6,
        LaneFStageV1::LearningRecorded => 7,
    }
}

const fn failure_code(value: PortFailureClassV1) -> u8 {
    match value {
        PortFailureClassV1::Rejected => 0,
        PortFailureClassV1::Unavailable => 1,
        PortFailureClassV1::TimedOut => 2,
        PortFailureClassV1::Quarantined => 3,
        PortFailureClassV1::Indeterminate => 4,
    }
}

const fn disposition_code(value: PipelineDispositionV1) -> u8 {
    match value {
        PipelineDispositionV1::DispatchProposed => 0,
        PipelineDispositionV1::Abstained => 1,
        PipelineDispositionV1::SlowPath => 2,
        PipelineDispositionV1::Failed(class) => 10 + failure_code(class),
    }
}

const fn outcome_code(value: StageOutcomeV1) -> u8 {
    match value {
        StageOutcomeV1::Completed => 0,
        StageOutcomeV1::FallbackUsed(class) => 10 + failure_code(class),
        StageOutcomeV1::Abstained => 1,
        StageOutcomeV1::SlowPath => 2,
        StageOutcomeV1::Failed(class) => 20 + failure_code(class),
    }
}

#[cfg(test)]
#[path = "pipeline_tests.rs"]
mod tests;
