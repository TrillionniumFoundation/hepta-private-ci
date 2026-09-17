use std::error::Error as StdError;
use std::fmt;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;
use crate::IntelligenceContractErrorV1;
use crate::IntelligenceHostEnvelopeV1;
use crate::LegalActionCandidateSetV1;
use crate::PortDecisionV1;
use crate::PortFailureClassV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LaneFStageV3 {
    ObjectiveValidated,
    LegalSetBuilt,
    UtilityEvaluated,
    EvaluationAdmitted,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
    HostEnvelopePrepared,
    DispatchProposed,
    LearningRecorded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LaneFCompositionBudgetV3 {
    pub total_micros: u64,
    pub objective_micros: u64,
    pub legal_set_micros: u64,
    pub utility_micros: u64,
    pub evaluation_micros: u64,
    pub neural_micros: u64,
    pub prompt_micros: u64,
    pub intuition_micros: u64,
    pub context_micros: u64,
    pub envelope_micros: u64,
    pub dispatch_micros: u64,
    pub ledger_micros: u64,
}

impl LaneFCompositionBudgetV3 {
    fn validate(self) -> Result<(), CompositionErrorV3> {
        let stages = [
            self.objective_micros,
            self.legal_set_micros,
            self.utility_micros,
            self.evaluation_micros,
            self.neural_micros,
            self.prompt_micros,
            self.intuition_micros,
            self.context_micros,
            self.envelope_micros,
            self.dispatch_micros,
            self.ledger_micros,
        ];
        if self.total_micros == 0 || stages.contains(&0) {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        let sum = stages
            .into_iter()
            .try_fold(0u64, u64::checked_add)
            .ok_or(CompositionErrorV3::InvalidBudget)?;
        if sum > self.total_micros {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        Ok(())
    }

    const fn for_stage(self, stage: LaneFStageV3) -> u64 {
        match stage {
            LaneFStageV3::ObjectiveValidated => self.objective_micros,
            LaneFStageV3::LegalSetBuilt => self.legal_set_micros,
            LaneFStageV3::UtilityEvaluated => self.utility_micros,
            LaneFStageV3::EvaluationAdmitted => self.evaluation_micros,
            LaneFStageV3::NeuralSignalCollected => self.neural_micros,
            LaneFStageV3::PromptPortfolioBuilt => self.prompt_micros,
            LaneFStageV3::IntuitionDecided => self.intuition_micros,
            LaneFStageV3::ContextCompiled => self.context_micros,
            LaneFStageV3::HostEnvelopePrepared => self.envelope_micros,
            LaneFStageV3::DispatchProposed => self.dispatch_micros,
            LaneFStageV3::LearningRecorded => self.ledger_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFCompositionRequestV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub legal_candidates: LegalActionCandidateSetV1,
    pub budget: LaneFCompositionBudgetV3,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortInputV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub stage: LaneFStageV3,
    pub budget_micros: u64,
    pub deadline_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortReceiptV3 {
    pub stage: LaneFStageV3,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub decision: PortDecisionV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortFailureV3 {
    pub class: PortFailureClassV1,
    pub evidence_digest: Digest32,
}

/// Owner adapters for the canonical V3 composition graph. Implementations must
/// return owner-native receipt digests, remain effect-free, honor the supplied
/// monotonic deadline and preserve the frozen snapshot/candidate-set bindings.
pub trait LaneFCompositionPortsV3 {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn evaluate_utility(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3>;
    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3>;
    fn decide_intuition(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn propose_dispatch(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
}

/// Monotonic clock for hard wall-clock accounting. Production hosts should use
/// one process-local monotonic domain; deterministic tests may inject a fake.
pub trait CompositionClockV3 {
    fn now_micros(&mut self) -> u64;
}

#[derive(Debug)]
pub struct SystemCompositionClockV3 {
    started: Instant,
}

impl Default for SystemCompositionClockV3 {
    fn default() -> Self {
        Self {
            started: Instant::now(),
        }
    }
}

impl CompositionClockV3 for SystemCompositionClockV3 {
    fn now_micros(&mut self) -> u64 {
        u64::try_from(self.started.elapsed().as_micros()).unwrap_or(u64::MAX)
    }
}

/// Cancellation fence checked before and after every owner boundary. Port
/// implementations remain responsible for making long-running calls themselves
/// interruptible before they are admitted as production adapters.
pub trait CompositionCancellationV3 {
    fn is_cancelled(&self) -> bool;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NeverCancelledV3;

impl CompositionCancellationV3 for NeverCancelledV3 {
    fn is_cancelled(&self) -> bool {
        false
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StageOutcomeV3 {
    Completed,
    FallbackUsed(PortFailureClassV1),
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StageTraceV3 {
    pub stage: LaneFStageV3,
    pub producer: StableId,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub outcome: StageOutcomeV3,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionDispositionV3 {
    DispatchProposed,
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFCompositionReceiptV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub disposition: CompositionDispositionV3,
    pub host_envelope: Option<IntelligenceHostEnvelopeV1>,
    pub stages: Vec<StageTraceV3>,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl LaneFCompositionReceiptV3 {
    pub fn validate(&self) -> Result<(), CompositionErrorV3> {
        if self.snapshot_digest.is_zero()
            || self.candidate_set_digest.is_zero()
            || self.trace_digest.is_zero()
        {
            return Err(CompositionErrorV3::InvalidReceipt("empty digest"));
        }
        if self.authority.grants_any() || self.stages.is_empty() || self.stages.len() > 11 {
            return Err(CompositionErrorV3::InvalidReceipt("authority or stage count"));
        }
        let mut previous = None;
        for trace in &self.stages {
            if trace.predecessor_digest.is_zero()
                || trace.output_digest.is_zero()
                || trace.evidence_digest.is_zero()
            {
                return Err(CompositionErrorV3::InvalidReceipt("empty stage digest"));
            }
            if let Some(output) = previous
                && trace.predecessor_digest != output
            {
                return Err(CompositionErrorV3::PredecessorMismatch);
            }
            if trace.producer.as_str() != producer_for_stage(trace.stage) {
                return Err(CompositionErrorV3::ProducerMismatch);
            }
            previous = Some(trace.output_digest);
        }
        if let Some(envelope) = &self.host_envelope {
            envelope.validate().map_err(CompositionErrorV3::Contract)?;
            if envelope.snapshot_digest != self.snapshot_digest
                || envelope.legal_candidate_set_digest != self.candidate_set_digest
            {
                return Err(CompositionErrorV3::SnapshotMismatch);
            }
        }
        let terminal = previous.ok_or(CompositionErrorV3::InvalidReceipt("stage count"))?;
        let expected = digest_trace_v3(
            &self.run_id,
            self.snapshot_digest,
            self.candidate_set_digest,
            self.disposition,
            &self.stages,
            terminal,
        );
        if expected != self.trace_digest {
            return Err(CompositionErrorV3::TraceDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompositionErrorV3 {
    InvalidBudget,
    EmptyDigest(&'static str),
    MissingCapability(&'static str),
    OwnerMismatch(&'static str),
    CandidateSnapshotMismatch,
    Contract(IntelligenceContractErrorV1),
    InvalidFailure,
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    CandidateSetMismatch,
    PredecessorMismatch,
    AuthorityWidening,
    UnexpectedDecision,
    InvalidReceipt(&'static str),
    TraceDigestMismatch,
    Arithmetic,
}

impl fmt::Display for CompositionErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompositionErrorV3 {}

pub fn run_composition_v3<P, C, X>(
    request: LaneFCompositionRequestV3,
    ports: &mut P,
    clock: &mut C,
    cancellation: &X,
) -> Result<LaneFCompositionReceiptV3, CompositionErrorV3>
where
    P: LaneFCompositionPortsV3,
    C: CompositionClockV3,
    X: CompositionCancellationV3,
{
    request.budget.validate()?;
    if request.request_digest.is_zero() {
        return Err(CompositionErrorV3::EmptyDigest("request"));
    }
    request
        .legal_candidates
        .validate()
        .map_err(CompositionErrorV3::Contract)?;
    let snapshot_digest = request.snapshot.digest();
    if request.legal_candidates.state_digest != snapshot_digest {
        return Err(CompositionErrorV3::CandidateSnapshotMismatch);
    }
    validate_capabilities(&request.snapshot)?;
    let started = clock.now_micros();
    let total_deadline = started
        .checked_add(request.budget.total_micros)
        .ok_or(CompositionErrorV3::Arithmetic)?;
    let candidate_set_digest = request.legal_candidates.digest();
    let mut stages = Vec::with_capacity(11);
    let mut predecessor = request.request_digest;

    macro_rules! required {
        ($stage:expr, $producer:literal, $call:expr) => {{
            match call_owner_stage(
                &request,
                snapshot_digest,
                candidate_set_digest,
                predecessor,
                total_deadline,
                $stage,
                $producer,
                clock,
                cancellation,
                $call,
            )? {
                StageAdvanceV3::Continue(receipt) => {
                    predecessor = receipt.output_digest;
                    stages.push(StageTraceV3 {
                        stage: receipt.stage,
                        producer: receipt.producer,
                        predecessor_digest: receipt.predecessor_digest,
                        output_digest: receipt.output_digest,
                        outcome: StageOutcomeV3::Completed,
                        evidence_digest: receipt.output_digest,
                    });
                    receipt
                }
                StageAdvanceV3::Terminal(disposition, trace) => {
                    stages.push(trace);
                    return finish(
                        request.run_id,
                        snapshot_digest,
                        candidate_set_digest,
                        disposition,
                        None,
                        stages,
                    );
                }
            }
        }};
    }

    let objective = required!(LaneFStageV3::ObjectiveValidated, "objective.compiler", |input| {
        ports.validate_objective(input)
    });
    predecessor = internal_stage(
        &request,
        snapshot_digest,
        candidate_set_digest,
        predecessor,
        total_deadline,
        LaneFStageV3::LegalSetBuilt,
        request.legal_candidates.digest(),
        clock,
        cancellation,
        &mut stages,
    )?;
    let utility = required!(LaneFStageV3::UtilityEvaluated, "utility.ndu", |input| {
        ports.evaluate_utility(input)
    });
    let evaluation = required!(LaneFStageV3::EvaluationAdmitted, "learning.eval", |input| {
        ports.admit_evaluation(input)
    });
    predecessor = optional_stage(
        &request,
        snapshot_digest,
        candidate_set_digest,
        predecessor,
        total_deadline,
        LaneFStageV3::NeuralSignalCollected,
        "neuron.runtime",
        "neural.signal",
        &mut stages,
        clock,
        cancellation,
        |input| ports.collect_neural_signal(input),
    )?;
    predecessor = optional_stage(
        &request,
        snapshot_digest,
        candidate_set_digest,
        predecessor,
        total_deadline,
        LaneFStageV3::PromptPortfolioBuilt,
        "prompt.optimizer",
        "prompt.portfolio",
        &mut stages,
        clock,
        cancellation,
        |input| ports.build_prompt_portfolio(input),
    )?;
    let intuition = call_intuition(
        &request,
        snapshot_digest,
        candidate_set_digest,
        predecessor,
        total_deadline,
        ports,
        &mut stages,
        clock,
        cancellation,
    )?;
    predecessor = intuition.output_digest;
    let disposition = match intuition.decision {
        PortDecisionV1::Continue => CompositionDispositionV3::DispatchProposed,
        PortDecisionV1::Abstain => CompositionDispositionV3::Abstained,
        PortDecisionV1::SlowPath => CompositionDispositionV3::SlowPath,
    };

    let mut host_envelope = None;
    if intuition.decision == PortDecisionV1::Continue {
        let context = required!(LaneFStageV3::ContextCompiled, "context.compiler", |input| {
            ports.compile_context(input)
        });
        let prefix_digest = digest_trace_prefix_v3(
            &request.run_id,
            snapshot_digest,
            candidate_set_digest,
            &stages,
        );
        let envelope = IntelligenceHostEnvelopeV1::new(
            request.run_id.clone(),
            request.request_digest,
            snapshot_digest,
            objective.output_digest,
            candidate_set_digest,
            utility.output_digest,
            evaluation.output_digest,
            intuition.output_digest,
            context.output_digest,
            prefix_digest,
        )
        .map_err(CompositionErrorV3::Contract)?;
        predecessor = internal_stage(
            &request,
            snapshot_digest,
            candidate_set_digest,
            predecessor,
            total_deadline,
            LaneFStageV3::HostEnvelopePrepared,
            envelope.envelope_digest,
            clock,
            cancellation,
            &mut stages,
        )?;
        host_envelope = Some(envelope);
        required!(LaneFStageV3::DispatchProposed, "runtime.agentd", |input| {
            ports.propose_dispatch(input)
        });
    }

    match call_owner_stage(
        &request,
        snapshot_digest,
        candidate_set_digest,
        predecessor,
        total_deadline,
        LaneFStageV3::LearningRecorded,
        "learning.ledger",
        clock,
        cancellation,
        |input| ports.record_learning(input),
    )? {
        StageAdvanceV3::Continue(receipt) => {
            stages.push(StageTraceV3 {
                stage: receipt.stage,
                producer: receipt.producer,
                predecessor_digest: receipt.predecessor_digest,
                output_digest: receipt.output_digest,
                outcome: StageOutcomeV3::Completed,
                evidence_digest: receipt.output_digest,
            });
        }
        StageAdvanceV3::Terminal(terminal, trace) => {
            stages.push(trace);
            return finish(
                request.run_id,
                snapshot_digest,
                candidate_set_digest,
                terminal,
                host_envelope,
                stages,
            );
        }
    }
    finish(
        request.run_id,
        snapshot_digest,
        candidate_set_digest,
        disposition,
        host_envelope,
        stages,
    )
}

enum StageAdvanceV3 {
    Continue(PortReceiptV3),
    Terminal(CompositionDispositionV3, StageTraceV3),
}

#[allow(clippy::too_many_arguments)]
fn call_owner_stage<C, X, F>(
    request: &LaneFCompositionRequestV3,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    predecessor: Digest32,
    total_deadline: u64,
    stage: LaneFStageV3,
    producer: &str,
    clock: &mut C,
    cancellation: &X,
    call: F,
) -> Result<StageAdvanceV3, CompositionErrorV3>
where
    C: CompositionClockV3,
    X: CompositionCancellationV3,
    F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
{
    if cancellation.is_cancelled() {
        return Ok(StageAdvanceV3::Terminal(
            CompositionDispositionV3::Cancelled,
            cancellation_trace(stage, producer, predecessor, snapshot_digest)?,
        ));
    }
    let now = clock.now_micros();
    let deadline = now
        .checked_add(request.budget.for_stage(stage))
        .ok_or(CompositionErrorV3::Arithmetic)?
        .min(total_deadline);
    if now >= total_deadline {
        return Ok(timeout_advance(stage, producer, predecessor, snapshot_digest, deadline)?);
    }
    let input = PortInputV3 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        candidate_set_digest,
        predecessor_digest: predecessor,
        stage,
        budget_micros: request.budget.for_stage(stage),
        deadline_micros: deadline,
    };
    let result = call(&input);
    if cancellation.is_cancelled() {
        return Ok(StageAdvanceV3::Terminal(
            CompositionDispositionV3::Cancelled,
            cancellation_trace(stage, producer, predecessor, snapshot_digest)?,
        ));
    }
    if clock.now_micros() > deadline {
        return Ok(timeout_advance(stage, producer, predecessor, snapshot_digest, deadline)?);
    }
    match result {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != PortDecisionV1::Continue {
                return Err(CompositionErrorV3::UnexpectedDecision);
            }
            Ok(StageAdvanceV3::Continue(receipt))
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let trace = failure_trace(stage, producer, predecessor, failure.clone())?;
            Ok(StageAdvanceV3::Terminal(
                CompositionDispositionV3::Failed(failure.class),
                trace,
            ))
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn optional_stage<C, X, F>(
    request: &LaneFCompositionRequestV3,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    predecessor: Digest32,
    total_deadline: u64,
    stage: LaneFStageV3,
    producer: &str,
    capability: &str,
    traces: &mut Vec<StageTraceV3>,
    clock: &mut C,
    cancellation: &X,
    call: F,
) -> Result<Digest32, CompositionErrorV3>
where
    C: CompositionClockV3,
    X: CompositionCancellationV3,
    F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
{
    if request.snapshot.bound_owner(capability).is_none() {
        let evidence = absent_capability_digest(snapshot_digest, capability);
        let output = fallback_digest_v3(stage, predecessor, PortFailureClassV1::Unavailable, evidence);
        traces.push(StageTraceV3 {
            stage,
            producer: stable_id(producer)?,
            predecessor_digest: predecessor,
            output_digest: output,
            outcome: StageOutcomeV3::FallbackUsed(PortFailureClassV1::Unavailable),
            evidence_digest: evidence,
        });
        return Ok(output);
    }
    match call_owner_stage(
        request,
        snapshot_digest,
        candidate_set_digest,
        predecessor,
        total_deadline,
        stage,
        producer,
        clock,
        cancellation,
        call,
    )? {
        StageAdvanceV3::Continue(receipt) => {
            traces.push(StageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: receipt.predecessor_digest,
                output_digest: receipt.output_digest,
                outcome: StageOutcomeV3::Completed,
                evidence_digest: receipt.output_digest,
            });
            Ok(receipt.output_digest)
        }
        StageAdvanceV3::Terminal(CompositionDispositionV3::Failed(class), trace) => {
            let output = fallback_digest_v3(stage, predecessor, class, trace.evidence_digest);
            traces.push(StageTraceV3 {
                stage,
                producer: stable_id(producer)?,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV3::FallbackUsed(class),
                evidence_digest: trace.evidence_digest,
            });
            Ok(output)
        }
        StageAdvanceV3::Terminal(disposition, trace) => {
            traces.push(trace);
            Err(match disposition {
                CompositionDispositionV3::Cancelled => CompositionErrorV3::InvalidReceipt("cancelled optional stage"),
                CompositionDispositionV3::DispatchProposed
                | CompositionDispositionV3::Abstained
                | CompositionDispositionV3::SlowPath
                | CompositionDispositionV3::Failed(_) => CompositionErrorV3::InvalidReceipt("optional stage terminal"),
            })
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn call_intuition<P, C, X>(
    request: &LaneFCompositionRequestV3,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    predecessor: Digest32,
    total_deadline: u64,
    ports: &mut P,
    traces: &mut Vec<StageTraceV3>,
    clock: &mut C,
    cancellation: &X,
) -> Result<PortReceiptV3, CompositionErrorV3>
where
    P: LaneFCompositionPortsV3,
    C: CompositionClockV3,
    X: CompositionCancellationV3,
{
    let stage = LaneFStageV3::IntuitionDecided;
    let now = clock.now_micros();
    let deadline = now
        .checked_add(request.budget.for_stage(stage))
        .ok_or(CompositionErrorV3::Arithmetic)?
        .min(total_deadline);
    if cancellation.is_cancelled() || now >= total_deadline {
        return Err(CompositionErrorV3::InvalidReceipt("intuition cancelled or timed out"));
    }
    let input = PortInputV3 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        candidate_set_digest,
        predecessor_digest: predecessor,
        stage,
        budget_micros: request.budget.for_stage(stage),
        deadline_micros: deadline,
    };
    let receipt = ports.decide_intuition(&input).map_err(|failure| {
        if failure.evidence_digest.is_zero() {
            CompositionErrorV3::InvalidFailure
        } else {
            CompositionErrorV3::InvalidReceipt("intuition failure")
        }
    })?;
    if cancellation.is_cancelled() || clock.now_micros() > deadline {
        return Err(CompositionErrorV3::InvalidReceipt("intuition cancelled or timed out"));
    }
    validate_receipt(&input, "intuition.policy", &receipt)?;
    traces.push(StageTraceV3 {
        stage,
        producer: receipt.producer.clone(),
        predecessor_digest: predecessor,
        output_digest: receipt.output_digest,
        outcome: match receipt.decision {
            PortDecisionV1::Continue => StageOutcomeV3::Completed,
            PortDecisionV1::Abstain => StageOutcomeV3::Abstained,
            PortDecisionV1::SlowPath => StageOutcomeV3::SlowPath,
        },
        evidence_digest: receipt.output_digest,
    });
    Ok(receipt)
}

#[allow(clippy::too_many_arguments)]
fn internal_stage<C, X>(
    request: &LaneFCompositionRequestV3,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    predecessor: Digest32,
    total_deadline: u64,
    stage: LaneFStageV3,
    output_digest: Digest32,
    clock: &mut C,
    cancellation: &X,
    traces: &mut Vec<StageTraceV3>,
) -> Result<Digest32, CompositionErrorV3>
where
    C: CompositionClockV3,
    X: CompositionCancellationV3,
{
    let now = clock.now_micros();
    let deadline = now
        .checked_add(request.budget.for_stage(stage))
        .ok_or(CompositionErrorV3::Arithmetic)?
        .min(total_deadline);
    if cancellation.is_cancelled() || now >= deadline || output_digest.is_zero() {
        return Err(CompositionErrorV3::InvalidReceipt("internal stage unavailable"));
    }
    let producer = stable_id("intelligence.control")?;
    traces.push(StageTraceV3 {
        stage,
        producer,
        predecessor_digest: predecessor,
        output_digest,
        outcome: StageOutcomeV3::Completed,
        evidence_digest: output_digest,
    });
    let _ = (snapshot_digest, candidate_set_digest);
    Ok(output_digest)
}

fn validate_capabilities(snapshot: &CapabilitySnapshotV2) -> Result<(), CompositionErrorV3> {
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("learning.evaluation", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.envelope", "intelligence.control"),
        ("dispatch.proposal", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ] {
        match snapshot.bound_owner(capability) {
            None => return Err(CompositionErrorV3::MissingCapability(capability)),
            Some(actual) if actual != owner => return Err(CompositionErrorV3::OwnerMismatch(capability)),
            Some(_) => {}
        }
    }
    for (capability, owner) in [
        ("neural.signal", "neuron.runtime"),
        ("prompt.portfolio", "prompt.optimizer"),
    ] {
        if let Some(actual) = snapshot.bound_owner(capability)
            && actual != owner
        {
            return Err(CompositionErrorV3::OwnerMismatch(capability));
        }
    }
    Ok(())
}

fn validate_receipt(
    input: &PortInputV3,
    producer: &str,
    receipt: &PortReceiptV3,
) -> Result<(), CompositionErrorV3> {
    if receipt.stage != input.stage {
        return Err(CompositionErrorV3::StageMismatch);
    }
    if receipt.producer.as_str() != producer {
        return Err(CompositionErrorV3::ProducerMismatch);
    }
    if receipt.snapshot_digest != input.snapshot_digest {
        return Err(CompositionErrorV3::SnapshotMismatch);
    }
    if receipt.candidate_set_digest != input.candidate_set_digest {
        return Err(CompositionErrorV3::CandidateSetMismatch);
    }
    if receipt.predecessor_digest != input.predecessor_digest {
        return Err(CompositionErrorV3::PredecessorMismatch);
    }
    if receipt.output_digest.is_zero() {
        return Err(CompositionErrorV3::EmptyDigest("port output"));
    }
    if receipt.authority.grants_any() {
        return Err(CompositionErrorV3::AuthorityWidening);
    }
    Ok(())
}

fn validate_failure(failure: &PortFailureV3) -> Result<(), CompositionErrorV3> {
    if failure.evidence_digest.is_zero() {
        return Err(CompositionErrorV3::InvalidFailure);
    }
    Ok(())
}

fn timeout_advance(
    stage: LaneFStageV3,
    producer: &str,
    predecessor: Digest32,
    snapshot_digest: Digest32,
    deadline: u64,
) -> Result<StageAdvanceV3, CompositionErrorV3> {
    let mut bytes = b"hepta.intelligence.v3.timeout\0".to_vec();
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(&deadline.to_be_bytes());
    let evidence = Digest32::of_bytes(&bytes);
    let failure = PortFailureV3 {
        class: PortFailureClassV1::TimedOut,
        evidence_digest: evidence,
    };
    Ok(StageAdvanceV3::Terminal(
        CompositionDispositionV3::Failed(PortFailureClassV1::TimedOut),
        failure_trace(stage, producer, predecessor, failure)?,
    ))
}

fn cancellation_trace(
    stage: LaneFStageV3,
    producer: &str,
    predecessor: Digest32,
    snapshot_digest: Digest32,
) -> Result<StageTraceV3, CompositionErrorV3> {
    let mut bytes = b"hepta.intelligence.v3.cancelled\0".to_vec();
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(stage_code_v3(stage));
    let evidence = Digest32::of_bytes(&bytes);
    let output = cancellation_digest_v3(stage, predecessor, evidence);
    Ok(StageTraceV3 {
        stage,
        producer: stable_id(producer)?,
        predecessor_digest: predecessor,
        output_digest: output,
        outcome: StageOutcomeV3::Cancelled,
        evidence_digest: evidence,
    })
}

fn failure_trace(
    stage: LaneFStageV3,
    producer: &str,
    predecessor: Digest32,
    failure: PortFailureV3,
) -> Result<StageTraceV3, CompositionErrorV3> {
    Ok(StageTraceV3 {
        stage,
        producer: stable_id(producer)?,
        predecessor_digest: predecessor,
        output_digest: fallback_digest_v3(stage, predecessor, failure.class, failure.evidence_digest),
        outcome: StageOutcomeV3::Failed(failure.class),
        evidence_digest: failure.evidence_digest,
    })
}

fn finish(
    run_id: StableId,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    disposition: CompositionDispositionV3,
    host_envelope: Option<IntelligenceHostEnvelopeV1>,
    stages: Vec<StageTraceV3>,
) -> Result<LaneFCompositionReceiptV3, CompositionErrorV3> {
    let terminal = stages
        .last()
        .ok_or(CompositionErrorV3::InvalidReceipt("stage count"))?
        .output_digest;
    let trace_digest = digest_trace_v3(
        &run_id,
        snapshot_digest,
        candidate_set_digest,
        disposition,
        &stages,
        terminal,
    );
    let receipt = LaneFCompositionReceiptV3 {
        run_id,
        snapshot_digest,
        candidate_set_digest,
        disposition,
        host_envelope,
        stages,
        trace_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn producer_for_stage(stage: LaneFStageV3) -> &'static str {
    match stage {
        LaneFStageV3::ObjectiveValidated => "objective.compiler",
        LaneFStageV3::LegalSetBuilt | LaneFStageV3::HostEnvelopePrepared => "intelligence.control",
        LaneFStageV3::UtilityEvaluated => "utility.ndu",
        LaneFStageV3::EvaluationAdmitted => "learning.eval",
        LaneFStageV3::NeuralSignalCollected => "neuron.runtime",
        LaneFStageV3::PromptPortfolioBuilt => "prompt.optimizer",
        LaneFStageV3::IntuitionDecided => "intuition.policy",
        LaneFStageV3::ContextCompiled => "context.compiler",
        LaneFStageV3::DispatchProposed => "runtime.agentd",
        LaneFStageV3::LearningRecorded => "learning.ledger",
    }
}

fn stable_id(value: &str) -> Result<StableId, CompositionErrorV3> {
    StableId::new(value).map_err(|_| CompositionErrorV3::Arithmetic)
}

fn absent_capability_digest(snapshot: Digest32, capability: &str) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.absent-capability\0".to_vec();
    bytes.extend_from_slice(snapshot.as_array());
    bytes.extend_from_slice(capability.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn fallback_digest_v3(
    stage: LaneFStageV3,
    predecessor: Digest32,
    class: PortFailureClassV1,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.fallback\0".to_vec();
    bytes.push(stage_code_v3(stage));
    bytes.push(failure_code_v3(class));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn cancellation_digest_v3(
    stage: LaneFStageV3,
    predecessor: Digest32,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.cancellation\0".to_vec();
    bytes.push(stage_code_v3(stage));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_trace_prefix_v3(
    run_id: &StableId,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    stages: &[StageTraceV3],
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.trace-prefix\0".to_vec();
    crate::push_id(&mut bytes, run_id);
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(candidate_set_digest.as_array());
    for trace in stages {
        bytes.push(stage_code_v3(trace.stage));
        bytes.extend_from_slice(trace.output_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_trace_v3(
    run_id: &StableId,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    disposition: CompositionDispositionV3,
    stages: &[StageTraceV3],
    terminal: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.trace\0".to_vec();
    crate::push_id(&mut bytes, run_id);
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(candidate_set_digest.as_array());
    bytes.push(disposition_code_v3(disposition));
    bytes.extend_from_slice(&u32::try_from(stages.len()).unwrap_or(u32::MAX).to_be_bytes());
    for trace in stages {
        bytes.push(stage_code_v3(trace.stage));
        crate::push_id(&mut bytes, &trace.producer);
        bytes.extend_from_slice(trace.predecessor_digest.as_array());
        bytes.extend_from_slice(trace.output_digest.as_array());
        bytes.push(outcome_code_v3(trace.outcome));
        bytes.extend_from_slice(trace.evidence_digest.as_array());
    }
    bytes.extend_from_slice(terminal.as_array());
    Digest32::of_bytes(&bytes)
}

const fn stage_code_v3(stage: LaneFStageV3) -> u8 {
    match stage {
        LaneFStageV3::ObjectiveValidated => 0,
        LaneFStageV3::LegalSetBuilt => 1,
        LaneFStageV3::UtilityEvaluated => 2,
        LaneFStageV3::EvaluationAdmitted => 3,
        LaneFStageV3::NeuralSignalCollected => 4,
        LaneFStageV3::PromptPortfolioBuilt => 5,
        LaneFStageV3::IntuitionDecided => 6,
        LaneFStageV3::ContextCompiled => 7,
        LaneFStageV3::HostEnvelopePrepared => 8,
        LaneFStageV3::DispatchProposed => 9,
        LaneFStageV3::LearningRecorded => 10,
    }
}

const fn failure_code_v3(class: PortFailureClassV1) -> u8 {
    match class {
        PortFailureClassV1::Rejected => 0,
        PortFailureClassV1::Unavailable => 1,
        PortFailureClassV1::TimedOut => 2,
        PortFailureClassV1::Quarantined => 3,
        PortFailureClassV1::Indeterminate => 4,
    }
}

const fn disposition_code_v3(disposition: CompositionDispositionV3) -> u8 {
    match disposition {
        CompositionDispositionV3::DispatchProposed => 0,
        CompositionDispositionV3::Abstained => 1,
        CompositionDispositionV3::SlowPath => 2,
        CompositionDispositionV3::Cancelled => 3,
        CompositionDispositionV3::Failed(class) => 10 + failure_code_v3(class),
    }
}

const fn outcome_code_v3(outcome: StageOutcomeV3) -> u8 {
    match outcome {
        StageOutcomeV3::Completed => 0,
        StageOutcomeV3::Abstained => 1,
        StageOutcomeV3::SlowPath => 2,
        StageOutcomeV3::Cancelled => 3,
        StageOutcomeV3::FallbackUsed(class) => 10 + failure_code_v3(class),
        StageOutcomeV3::Failed(class) => 20 + failure_code_v3(class),
    }
}

#[cfg(test)]
#[path = "composition_v3_tests.rs"]
mod tests;
