//! Canonical V3 intelligence composition graph.
//!
//! V1/V2 remain compatibility surfaces. V3 is the single graph that binds
//! objective, legal candidates, NDU utility, independent evaluation, optional
//! neuron/prompt inputs, calibrated intuition, context, agentd handoff and the
//! learning record into one predecessor chain. Ports are proposal-only: the
//! coordinator checks cancellation and wall-clock budgets before and after each
//! synchronous call but cannot preempt a port that blocks internally.

use std::error::Error as StdError;
use std::fmt;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;
use crate::IntelligenceContractErrorV1;
use crate::IntelligenceHostEnvelopeV1;
use crate::LegalActionCandidateSetV1;

const MAX_V3_STAGES: usize = 11;

enum StageAdvanceV3 {
    Continue(Digest32),
    Terminal(PortFailureClassV3, Digest32),
}

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
    HostEnvelopeBuilt,
    HostHandoffAccepted,
    LearningRecorded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortDecisionV3 {
    Continue,
    Abstain,
    SlowPath,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortFailureClassV3 {
    Rejected,
    Unavailable,
    TimedOut,
    Quarantined,
    Indeterminate,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LaneFBudgetV3 {
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
    pub host_handoff_micros: u64,
    pub ledger_micros: u64,
}

impl LaneFBudgetV3 {
    fn validate(self) -> Result<(), PipelineErrorV3> {
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
            self.host_handoff_micros,
            self.ledger_micros,
        ];
        if self.total_micros == 0 || stages.contains(&0) {
            return Err(PipelineErrorV3::InvalidBudget);
        }
        let sum = stages
            .into_iter()
            .try_fold(0u64, u64::checked_add)
            .ok_or(PipelineErrorV3::InvalidBudget)?;
        if sum > self.total_micros {
            return Err(PipelineErrorV3::InvalidBudget);
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
            LaneFStageV3::HostEnvelopeBuilt => self.envelope_micros,
            LaneFStageV3::HostHandoffAccepted => self.host_handoff_micros,
            LaneFStageV3::LearningRecorded => self.ledger_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFRunRequestV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub legal_candidates: LegalActionCandidateSetV1,
    pub budget: LaneFBudgetV3,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortInputV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub budget_micros: u64,
    pub stage: LaneFStageV3,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortReceiptV3 {
    pub stage: LaneFStageV3,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub decision: PortDecisionV3,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortFailureV3 {
    pub class: PortFailureClassV3,
    pub evidence_digest: Digest32,
}

pub trait LaneFV3Ports {
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
    fn accept_host_envelope(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3>;
    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
}

pub trait CompositionControlV3 {
    fn cancelled(&self) -> bool;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NeverCancelledV3;

impl CompositionControlV3 for NeverCancelledV3 {
    fn cancelled(&self) -> bool {
        false
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StageOutcomeV3 {
    Completed,
    FallbackUsed(PortFailureClassV3),
    Abstained,
    SlowPath,
    Failed(PortFailureClassV3),
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
pub enum PipelineDispositionV3 {
    HostHandoffAccepted,
    Abstained,
    SlowPath,
    Failed(PortFailureClassV3),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFCompositionReceiptV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub disposition: PipelineDispositionV3,
    pub stages: Vec<StageTraceV3>,
    pub host_envelope: Option<IntelligenceHostEnvelopeV1>,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl LaneFCompositionReceiptV3 {
    pub fn validate(&self) -> Result<(), PipelineErrorV3> {
        if self.snapshot_digest.is_zero() || self.trace_digest.is_zero() {
            return Err(PipelineErrorV3::InvalidReceipt("empty digest"));
        }
        if self.authority.grants_any() {
            return Err(PipelineErrorV3::AuthorityWidening);
        }
        if self.stages.is_empty() || self.stages.len() > MAX_V3_STAGES {
            return Err(PipelineErrorV3::InvalidReceipt("stage count"));
        }
        let mut previous = None;
        for (index, trace) in self.stages.iter().enumerate() {
            if trace.producer.as_str() != producer_for_stage(trace.stage) {
                return Err(PipelineErrorV3::ProducerMismatch);
            }
            if trace.predecessor_digest.is_zero()
                || trace.output_digest.is_zero()
                || trace.evidence_digest.is_zero()
            {
                return Err(PipelineErrorV3::InvalidReceipt("empty stage digest"));
            }
            if let Some(expected) = previous
                && trace.predecessor_digest != expected
            {
                return Err(PipelineErrorV3::PredecessorMismatch);
            }
            if index > 0 {
                let prior = self.stages[index - 1].stage;
                if !valid_transition(prior, trace.stage, self.stages[index - 1].outcome) {
                    return Err(PipelineErrorV3::InvalidReceipt("stage order"));
                }
            } else if trace.stage != LaneFStageV3::ObjectiveValidated {
                return Err(PipelineErrorV3::InvalidReceipt("first stage"));
            }
            if matches!(trace.outcome, StageOutcomeV3::FallbackUsed(_))
                && !matches!(
                    trace.stage,
                    LaneFStageV3::NeuralSignalCollected | LaneFStageV3::PromptPortfolioBuilt
                )
            {
                return Err(PipelineErrorV3::InvalidReceipt("invalid fallback"));
            }
            previous = Some(trace.output_digest);
        }

        match self.disposition {
            PipelineDispositionV3::HostHandoffAccepted => {
                let envelope = self
                    .host_envelope
                    .as_ref()
                    .ok_or(PipelineErrorV3::InvalidReceipt("missing host envelope"))?;
                envelope.validate().map_err(PipelineErrorV3::Contract)?;
                if !self
                    .stages
                    .iter()
                    .any(|trace| trace.stage == LaneFStageV3::HostHandoffAccepted)
                    || self.stages.last().map(|trace| trace.stage)
                        != Some(LaneFStageV3::LearningRecorded)
                {
                    return Err(PipelineErrorV3::InvalidReceipt("host disposition"));
                }
            }
            PipelineDispositionV3::Abstained => {
                if self.host_envelope.is_some()
                    || !matches!(
                        self.stages
                            .iter()
                            .find(|trace| trace.stage == LaneFStageV3::IntuitionDecided)
                            .map(|trace| trace.outcome),
                        Some(StageOutcomeV3::Abstained)
                    )
                {
                    return Err(PipelineErrorV3::InvalidReceipt("abstain disposition"));
                }
            }
            PipelineDispositionV3::SlowPath => {
                if self.host_envelope.is_some()
                    || !matches!(
                        self.stages
                            .iter()
                            .find(|trace| trace.stage == LaneFStageV3::IntuitionDecided)
                            .map(|trace| trace.outcome),
                        Some(StageOutcomeV3::SlowPath)
                    )
                {
                    return Err(PipelineErrorV3::InvalidReceipt("slow-path disposition"));
                }
            }
            PipelineDispositionV3::Failed(class) => {
                if !matches!(
                    self.stages.last().map(|trace| trace.outcome),
                    Some(StageOutcomeV3::Failed(actual)) if actual == class
                ) {
                    return Err(PipelineErrorV3::InvalidReceipt("failure disposition"));
                }
            }
        }
        let terminal = self
            .stages
            .last()
            .ok_or(PipelineErrorV3::InvalidReceipt("stage count"))?
            .output_digest;
        if digest_trace(
            &self.run_id,
            self.snapshot_digest,
            self.disposition,
            &self.stages,
            terminal,
        )? != self.trace_digest
        {
            return Err(PipelineErrorV3::TraceDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PipelineErrorV3 {
    InvalidBudget,
    EmptyDigest(&'static str),
    MissingCapability(&'static str),
    OwnerMismatch(&'static str),
    InvalidPortFailure,
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    PredecessorMismatch,
    AuthorityWidening,
    UnexpectedDecision,
    InvalidReceipt(&'static str),
    TraceDigestMismatch,
    Contract(IntelligenceContractErrorV1),
    Arithmetic,
}

impl fmt::Display for PipelineErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PipelineErrorV3 {}

impl From<IntelligenceContractErrorV1> for PipelineErrorV3 {
    fn from(value: IntelligenceContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

pub fn run_composition_v3<P: LaneFV3Ports>(
    request: LaneFRunRequestV3,
    ports: &mut P,
) -> Result<LaneFCompositionReceiptV3, PipelineErrorV3> {
    run_composition_v3_with_control(request, ports, &NeverCancelledV3)
}

pub fn run_composition_v3_with_control<P: LaneFV3Ports, C: CompositionControlV3>(
    request: LaneFRunRequestV3,
    ports: &mut P,
    control: &C,
) -> Result<LaneFCompositionReceiptV3, PipelineErrorV3> {
    if request.request_digest.is_zero() {
        return Err(PipelineErrorV3::EmptyDigest("request"));
    }
    request.budget.validate()?;
    request.legal_candidates.validate()?;
    validate_capabilities(&request.snapshot)?;
    let snapshot_digest = request.snapshot.digest();
    let objective_digest = request.snapshot.objective_digest();
    let started = Instant::now();
    let mut stages = Vec::with_capacity(MAX_V3_STAGES);
    let mut predecessor = request.request_digest;

    predecessor = required_port_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::ObjectiveValidated,
        "objective.compiler",
        &mut stages,
        started,
        control,
        |input| ports.validate_objective(input),
    )?;

    predecessor = internal_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::LegalSetBuilt,
        request.legal_candidates.candidate_set_digest,
        &mut stages,
        started,
        control,
    )?;
    let legal_set_digest = predecessor;

    predecessor = required_port_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::UtilityEvaluated,
        "utility.ndu",
        &mut stages,
        started,
        control,
        |input| ports.evaluate_utility(input),
    )?;
    let utility_digest = predecessor;

    predecessor = required_port_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::EvaluationAdmitted,
        "learning.eval",
        &mut stages,
        started,
        control,
        |input| ports.admit_evaluation(input),
    )?;
    let evaluation_digest = predecessor;

    predecessor = optional_port_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::NeuralSignalCollected,
        "neuron.runtime",
        "neural.signal",
        &mut stages,
        started,
        control,
        |input| ports.collect_neural_signal(input),
    )?;
    let neural_digest = stage_completed_digest(&stages, LaneFStageV3::NeuralSignalCollected);

    predecessor = optional_port_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::PromptPortfolioBuilt,
        "prompt.optimizer",
        "prompt.portfolio",
        &mut stages,
        started,
        control,
        |input| ports.build_prompt_portfolio(input),
    )?;
    let prompt_digest = stage_completed_digest(&stages, LaneFStageV3::PromptPortfolioBuilt);

    let intuition_input = port_input(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::IntuitionDecided,
    );
    let intuition = timed_call(
        &request,
        snapshot_digest,
        predecessor,
        &intuition_input,
        started,
        control,
        |input| ports.decide_intuition(input),
    )?;
    let intuition = match intuition {
        Ok(receipt) => {
            validate_receipt(&intuition_input, "intuition.policy", &receipt)?;
            receipt
        }
        Err(failure) => {
            return terminal_failure(
                request.run_id,
                snapshot_digest,
                stages,
                LaneFStageV3::IntuitionDecided,
                "intuition.policy",
                predecessor,
                failure,
                None,
            );
        }
    };
    predecessor = intuition.output_digest;
    let intuition_digest = predecessor;
    let disposition = match intuition.decision {
        PortDecisionV3::Continue => PipelineDispositionV3::HostHandoffAccepted,
        PortDecisionV3::Abstain => PipelineDispositionV3::Abstained,
        PortDecisionV3::SlowPath => PipelineDispositionV3::SlowPath,
    };
    stages.push(StageTraceV3 {
        stage: LaneFStageV3::IntuitionDecided,
        producer: intuition.producer,
        predecessor_digest: intuition.predecessor_digest,
        output_digest: intuition.output_digest,
        outcome: match intuition.decision {
            PortDecisionV3::Continue => StageOutcomeV3::Completed,
            PortDecisionV3::Abstain => StageOutcomeV3::Abstained,
            PortDecisionV3::SlowPath => StageOutcomeV3::SlowPath,
        },
        evidence_digest: intuition.output_digest,
    });

    let mut host_envelope = None;
    if intuition.decision == PortDecisionV3::Continue {
        predecessor = required_port_stage(
            &request,
            snapshot_digest,
            predecessor,
            LaneFStageV3::ContextCompiled,
            "context.compiler",
            &mut stages,
            started,
            control,
            |input| ports.compile_context(input),
        )?;
        let context_digest = predecessor;
        let prefix = digest_prefix(
            &request.run_id,
            snapshot_digest,
            &stages,
            predecessor,
        )?;
        let envelope = IntelligenceHostEnvelopeV1::new(
            request.run_id.clone(),
            snapshot_digest,
            objective_digest,
            legal_set_digest,
            utility_digest,
            evaluation_digest,
            neural_digest,
            prompt_digest,
            intuition_digest,
            context_digest,
            prefix,
            request.budget.total_micros,
        )?;
        predecessor = internal_stage(
            &request,
            snapshot_digest,
            predecessor,
            LaneFStageV3::HostEnvelopeBuilt,
            envelope.envelope_digest,
            &mut stages,
            started,
            control,
        )?;
        let host_input = port_input(
            &request,
            snapshot_digest,
            predecessor,
            LaneFStageV3::HostHandoffAccepted,
        );
        let accepted = timed_call(
            &request,
            snapshot_digest,
            predecessor,
            &host_input,
            started,
            control,
            |input| ports.accept_host_envelope(input, &envelope),
        )?;
        let accepted = match accepted {
            Ok(receipt) => {
                validate_receipt(&host_input, "runtime.agentd", &receipt)?;
                if receipt.decision != PortDecisionV3::Continue {
                    return Err(PipelineErrorV3::UnexpectedDecision);
                }
                receipt
            }
            Err(failure) => {
                return terminal_failure(
                    request.run_id,
                    snapshot_digest,
                    stages,
                    LaneFStageV3::HostHandoffAccepted,
                    "runtime.agentd",
                    predecessor,
                    failure,
                    Some(envelope),
                );
            }
        };
        predecessor = accepted.output_digest;
        stages.push(StageTraceV3 {
            stage: LaneFStageV3::HostHandoffAccepted,
            producer: accepted.producer,
            predecessor_digest: accepted.predecessor_digest,
            output_digest: accepted.output_digest,
            outcome: StageOutcomeV3::Completed,
            evidence_digest: accepted.output_digest,
        });
        host_envelope = Some(envelope);
    }

    predecessor = required_port_stage(
        &request,
        snapshot_digest,
        predecessor,
        LaneFStageV3::LearningRecorded,
        "learning.ledger",
        &mut stages,
        started,
        control,
        |input| ports.record_learning(input),
    )?;

    finish(
        request.run_id,
        snapshot_digest,
        disposition,
        stages,
        predecessor,
        host_envelope,
    )
}

fn validate_capabilities(snapshot: &CapabilitySnapshotV2) -> Result<(), PipelineErrorV3> {
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("learning.evaluation", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.handoff", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ] {
        match snapshot.bound_owner(capability) {
            None => return Err(PipelineErrorV3::MissingCapability(capability)),
            Some(actual) if actual != owner => {
                return Err(PipelineErrorV3::OwnerMismatch(capability));
            }
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
            return Err(PipelineErrorV3::OwnerMismatch(capability));
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn required_port_stage<C, F>(
    request: &LaneFRunRequestV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: LaneFStageV3,
    producer: &str,
    stages: &mut Vec<StageTraceV3>,
    started: Instant,
    control: &C,
    call: F,
) -> Result<StageAdvanceV3, PipelineErrorV3>
where
    C: CompositionControlV3,
    F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
{
    let input = port_input(request, snapshot_digest, predecessor, stage);
    match timed_call(
        request,
        snapshot_digest,
        predecessor,
        &input,
        started,
        control,
        call,
    )? {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != PortDecisionV3::Continue {
                return Err(PipelineErrorV3::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            stages.push(StageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV3::Completed,
                evidence_digest: output,
            });
            Ok(StageAdvanceV3::Continue(output))
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let class = failure.class;
            let output = fallback_digest(stage, predecessor, class, failure.evidence_digest);
            stages.push(StageTraceV3 {
                stage,
                producer: stable_id(producer)?,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV3::Failed(class),
                evidence_digest: failure.evidence_digest,
            });
            Ok(StageAdvanceV3::Terminal(class, output))
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn optional_port_stage<C, F>(
    request: &LaneFRunRequestV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: LaneFStageV3,
    producer: &str,
    capability: &'static str,
    stages: &mut Vec<StageTraceV3>,
    started: Instant,
    control: &C,
    call: F,
) -> Result<Digest32, PipelineErrorV3>
where
    C: CompositionControlV3,
    F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
{
    if request.snapshot.bound_owner(capability).is_none() {
        let evidence = absent_digest(snapshot_digest, capability);
        let output = fallback_digest(stage, predecessor, PortFailureClassV3::Unavailable, evidence);
        stages.push(StageTraceV3 {
            stage,
            producer: stable_id(producer)?,
            predecessor_digest: predecessor,
            output_digest: output,
            outcome: StageOutcomeV3::FallbackUsed(PortFailureClassV3::Unavailable),
            evidence_digest: evidence,
        });
        return Ok(output);
    }
    let input = port_input(request, snapshot_digest, predecessor, stage);
    match timed_call(
        request,
        snapshot_digest,
        predecessor,
        &input,
        started,
        control,
        call,
    )? {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != PortDecisionV3::Continue {
                return Err(PipelineErrorV3::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            stages.push(StageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV3::Completed,
                evidence_digest: output,
            });
            Ok(output)
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let output =
                fallback_digest(stage, predecessor, failure.class, failure.evidence_digest);
            stages.push(StageTraceV3 {
                stage,
                producer: stable_id(producer)?,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: StageOutcomeV3::FallbackUsed(failure.class),
                evidence_digest: failure.evidence_digest,
            });
            Ok(output)
        }
    }
}

fn internal_stage<C: CompositionControlV3>(
    request: &LaneFRunRequestV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: LaneFStageV3,
    output_digest: Digest32,
    stages: &mut Vec<StageTraceV3>,
    started: Instant,
    control: &C,
) -> Result<Digest32, PipelineErrorV3> {
    if output_digest.is_zero() {
        return Err(PipelineErrorV3::EmptyDigest("internal stage"));
    }
    let input = port_input(request, snapshot_digest, predecessor, stage);
    let stage_started = Instant::now();
    if control.cancelled() {
        let failure = control_failure(stage, snapshot_digest, predecessor, PortFailureClassV3::Cancelled);
        return Err(PipelineErrorV3::InvalidReceipt(match failure.class {
            PortFailureClassV3::Cancelled => "cancelled internal stage",
            _ => "internal stage",
        }));
    }
    if started.elapsed() > Duration::from_micros(request.budget.total_micros)
        || stage_started.elapsed() > Duration::from_micros(input.budget_micros)
    {
        return Err(PipelineErrorV3::InvalidReceipt("timed out internal stage"));
    }
    stages.push(StageTraceV3 {
        stage,
        producer: stable_id("intelligence.control")?,
        predecessor_digest: predecessor,
        output_digest,
        outcome: StageOutcomeV3::Completed,
        evidence_digest: output_digest,
    });
    Ok(output_digest)
}

fn timed_call<C, F>(
    request: &LaneFRunRequestV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    input: &PortInputV3,
    started: Instant,
    control: &C,
    call: F,
) -> Result<Result<PortReceiptV3, PortFailureV3>, PipelineErrorV3>
where
    C: CompositionControlV3,
    F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
{
    if control.cancelled() {
        return Ok(Err(control_failure(
            input.stage,
            snapshot_digest,
            predecessor,
            PortFailureClassV3::Cancelled,
        )));
    }
    if started.elapsed() > Duration::from_micros(request.budget.total_micros) {
        return Ok(Err(control_failure(
            input.stage,
            snapshot_digest,
            predecessor,
            PortFailureClassV3::TimedOut,
        )));
    }
    let stage_started = Instant::now();
    let result = call(input);
    if control.cancelled() {
        return Ok(Err(control_failure(
            input.stage,
            snapshot_digest,
            predecessor,
            PortFailureClassV3::Cancelled,
        )));
    }
    if stage_started.elapsed() > Duration::from_micros(input.budget_micros)
        || started.elapsed() > Duration::from_micros(request.budget.total_micros)
    {
        return Ok(Err(control_failure(
            input.stage,
            snapshot_digest,
            predecessor,
            PortFailureClassV3::TimedOut,
        )));
    }
    Ok(result)
}

fn terminal_failure(
    run_id: StableId,
    snapshot_digest: Digest32,
    mut stages: Vec<StageTraceV3>,
    stage: LaneFStageV3,
    producer: &str,
    predecessor: Digest32,
    failure: PortFailureV3,
    host_envelope: Option<IntelligenceHostEnvelopeV1>,
) -> Result<LaneFCompositionReceiptV3, PipelineErrorV3> {
    validate_failure(&failure)?;
    let class = failure.class;
    let output = fallback_digest(stage, predecessor, class, failure.evidence_digest);
    stages.push(StageTraceV3 {
        stage,
        producer: stable_id(producer)?,
        predecessor_digest: predecessor,
        output_digest: output,
        outcome: StageOutcomeV3::Failed(class),
        evidence_digest: failure.evidence_digest,
    });
    finish(
        run_id,
        snapshot_digest,
        PipelineDispositionV3::Failed(class),
        stages,
        output,
        host_envelope,
    )
}

fn finish(
    run_id: StableId,
    snapshot_digest: Digest32,
    disposition: PipelineDispositionV3,
    stages: Vec<StageTraceV3>,
    terminal_digest: Digest32,
    host_envelope: Option<IntelligenceHostEnvelopeV1>,
) -> Result<LaneFCompositionReceiptV3, PipelineErrorV3> {
    let trace_digest = digest_trace(
        &run_id,
        snapshot_digest,
        disposition,
        &stages,
        terminal_digest,
    )?;
    let receipt = LaneFCompositionReceiptV3 {
        run_id,
        snapshot_digest,
        disposition,
        stages,
        host_envelope,
        trace_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn port_input(
    request: &LaneFRunRequestV3,
    snapshot_digest: Digest32,
    predecessor_digest: Digest32,
    stage: LaneFStageV3,
) -> PortInputV3 {
    PortInputV3 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        predecessor_digest,
        budget_micros: request.budget.for_stage(stage),
        stage,
    }
}

fn validate_receipt(
    input: &PortInputV3,
    expected_producer: &str,
    receipt: &PortReceiptV3,
) -> Result<(), PipelineErrorV3> {
    if receipt.stage != input.stage {
        return Err(PipelineErrorV3::StageMismatch);
    }
    if receipt.producer.as_str() != expected_producer {
        return Err(PipelineErrorV3::ProducerMismatch);
    }
    if receipt.snapshot_digest != input.snapshot_digest {
        return Err(PipelineErrorV3::SnapshotMismatch);
    }
    if receipt.predecessor_digest != input.predecessor_digest {
        return Err(PipelineErrorV3::PredecessorMismatch);
    }
    if receipt.output_digest.is_zero() {
        return Err(PipelineErrorV3::EmptyDigest("port output"));
    }
    if receipt.authority.grants_any() {
        return Err(PipelineErrorV3::AuthorityWidening);
    }
    Ok(())
}

fn validate_failure(failure: &PortFailureV3) -> Result<(), PipelineErrorV3> {
    if failure.evidence_digest.is_zero() {
        return Err(PipelineErrorV3::InvalidPortFailure);
    }
    Ok(())
}

fn stage_completed_digest(stages: &[StageTraceV3], stage: LaneFStageV3) -> Option<Digest32> {
    stages
        .iter()
        .find(|trace| trace.stage == stage && trace.outcome == StageOutcomeV3::Completed)
        .map(|trace| trace.output_digest)
}

fn valid_transition(
    prior: LaneFStageV3,
    next: LaneFStageV3,
    prior_outcome: StageOutcomeV3,
) -> bool {
    if matches!(prior_outcome, StageOutcomeV3::Failed(_)) {
        return false;
    }
    match prior_outcome {
        StageOutcomeV3::Abstained | StageOutcomeV3::SlowPath => {
            prior == LaneFStageV3::IntuitionDecided && next == LaneFStageV3::LearningRecorded
        }
        StageOutcomeV3::Completed | StageOutcomeV3::FallbackUsed(_) => matches!(
            (prior, next),
            (LaneFStageV3::ObjectiveValidated, LaneFStageV3::LegalSetBuilt)
                | (LaneFStageV3::LegalSetBuilt, LaneFStageV3::UtilityEvaluated)
                | (LaneFStageV3::UtilityEvaluated, LaneFStageV3::EvaluationAdmitted)
                | (LaneFStageV3::EvaluationAdmitted, LaneFStageV3::NeuralSignalCollected)
                | (LaneFStageV3::NeuralSignalCollected, LaneFStageV3::PromptPortfolioBuilt)
                | (LaneFStageV3::PromptPortfolioBuilt, LaneFStageV3::IntuitionDecided)
                | (LaneFStageV3::IntuitionDecided, LaneFStageV3::ContextCompiled)
                | (LaneFStageV3::ContextCompiled, LaneFStageV3::HostEnvelopeBuilt)
                | (LaneFStageV3::HostEnvelopeBuilt, LaneFStageV3::HostHandoffAccepted)
                | (LaneFStageV3::HostHandoffAccepted, LaneFStageV3::LearningRecorded)
        ),
        StageOutcomeV3::Failed(_) => false,
    }
}

fn producer_for_stage(stage: LaneFStageV3) -> &'static str {
    match stage {
        LaneFStageV3::ObjectiveValidated => "objective.compiler",
        LaneFStageV3::LegalSetBuilt | LaneFStageV3::HostEnvelopeBuilt => "intelligence.control",
        LaneFStageV3::UtilityEvaluated => "utility.ndu",
        LaneFStageV3::EvaluationAdmitted => "learning.eval",
        LaneFStageV3::NeuralSignalCollected => "neuron.runtime",
        LaneFStageV3::PromptPortfolioBuilt => "prompt.optimizer",
        LaneFStageV3::IntuitionDecided => "intuition.policy",
        LaneFStageV3::ContextCompiled => "context.compiler",
        LaneFStageV3::HostHandoffAccepted => "runtime.agentd",
        LaneFStageV3::LearningRecorded => "learning.ledger",
    }
}

fn control_failure(
    stage: LaneFStageV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    class: PortFailureClassV3,
) -> PortFailureV3 {
    let mut bytes = b"hepta.intelligence.v3.control-failure\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(failure_code(class));
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(predecessor.as_array());
    PortFailureV3 {
        class,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

fn absent_digest(snapshot_digest: Digest32, capability: &str) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.absent-capability\0".to_vec();
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(capability.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn fallback_digest(
    stage: LaneFStageV3,
    predecessor: Digest32,
    class: PortFailureClassV3,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.fallback\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(failure_code(class));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_prefix(
    run_id: &StableId,
    snapshot_digest: Digest32,
    stages: &[StageTraceV3],
    terminal_digest: Digest32,
) -> Result<Digest32, PipelineErrorV3> {
    let mut bytes = b"hepta.intelligence.v3.pre-handoff\0".to_vec();
    push_id(&mut bytes, run_id)?;
    bytes.extend_from_slice(snapshot_digest.as_array());
    append_traces(&mut bytes, stages)?;
    bytes.extend_from_slice(terminal_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_trace(
    run_id: &StableId,
    snapshot_digest: Digest32,
    disposition: PipelineDispositionV3,
    stages: &[StageTraceV3],
    terminal_digest: Digest32,
) -> Result<Digest32, PipelineErrorV3> {
    let mut bytes = b"hepta.intelligence.v3.trace\0".to_vec();
    push_id(&mut bytes, run_id)?;
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(disposition_code(disposition));
    append_traces(&mut bytes, stages)?;
    bytes.extend_from_slice(terminal_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn append_traces(bytes: &mut Vec<u8>, stages: &[StageTraceV3]) -> Result<(), PipelineErrorV3> {
    let count = u32::try_from(stages.len()).map_err(|_| PipelineErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for trace in stages {
        bytes.push(stage_code(trace.stage));
        push_id(bytes, &trace.producer)?;
        bytes.extend_from_slice(trace.predecessor_digest.as_array());
        bytes.extend_from_slice(trace.output_digest.as_array());
        bytes.push(outcome_code(trace.outcome));
        bytes.extend_from_slice(trace.evidence_digest.as_array());
    }
    Ok(())
}

fn stable_id(value: &str) -> Result<StableId, PipelineErrorV3> {
    StableId::new(value).map_err(|_| PipelineErrorV3::Arithmetic)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), PipelineErrorV3> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| PipelineErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

const fn stage_code(stage: LaneFStageV3) -> u8 {
    match stage {
        LaneFStageV3::ObjectiveValidated => 0,
        LaneFStageV3::LegalSetBuilt => 1,
        LaneFStageV3::UtilityEvaluated => 2,
        LaneFStageV3::EvaluationAdmitted => 3,
        LaneFStageV3::NeuralSignalCollected => 4,
        LaneFStageV3::PromptPortfolioBuilt => 5,
        LaneFStageV3::IntuitionDecided => 6,
        LaneFStageV3::ContextCompiled => 7,
        LaneFStageV3::HostEnvelopeBuilt => 8,
        LaneFStageV3::HostHandoffAccepted => 9,
        LaneFStageV3::LearningRecorded => 10,
    }
}

const fn failure_code(class: PortFailureClassV3) -> u8 {
    match class {
        PortFailureClassV3::Rejected => 0,
        PortFailureClassV3::Unavailable => 1,
        PortFailureClassV3::TimedOut => 2,
        PortFailureClassV3::Quarantined => 3,
        PortFailureClassV3::Indeterminate => 4,
        PortFailureClassV3::Cancelled => 5,
    }
}

const fn disposition_code(disposition: PipelineDispositionV3) -> u8 {
    match disposition {
        PipelineDispositionV3::HostHandoffAccepted => 0,
        PipelineDispositionV3::Abstained => 1,
        PipelineDispositionV3::SlowPath => 2,
        PipelineDispositionV3::Failed(class) => 10 + failure_code(class),
    }
}

const fn outcome_code(outcome: StageOutcomeV3) -> u8 {
    match outcome {
        StageOutcomeV3::Completed => 0,
        StageOutcomeV3::FallbackUsed(class) => 10 + failure_code(class),
        StageOutcomeV3::Abstained => 1,
        StageOutcomeV3::SlowPath => 2,
        StageOutcomeV3::Failed(class) => 20 + failure_code(class),
    }
}
