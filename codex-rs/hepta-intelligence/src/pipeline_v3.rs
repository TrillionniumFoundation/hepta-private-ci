//! Unified V3 intelligence composition graph.
//!
//! V3 is the convergence path for the existing read-only, generic shadow and
//! evaluated-shadow slices. It keeps those compatibility entrypoints intact but
//! gives product callers one typed predecessor chain across objective admission,
//! independent evaluation, legal-set construction, utility/NDU evaluation,
//! optional neural and prompt inputs, calibrated intuition, context compilation,
//! Agentd handoff and learning-decision recording. This module never invokes a
//! model, tool or provider and never grants effect authority.

use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;

const MAX_CANDIDATES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntelligenceStageV3 {
    ObjectiveValidated,
    EvaluationAdmitted,
    LegalSetBuilt,
    UtilityEvaluated,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
    HostHandoff,
    LearningRecorded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IntelligenceBudgetV3 {
    pub total_micros: u64,
    pub objective_micros: u64,
    pub evaluation_micros: u64,
    pub legal_set_micros: u64,
    pub utility_micros: u64,
    pub neural_micros: u64,
    pub prompt_micros: u64,
    pub intuition_micros: u64,
    pub context_micros: u64,
    pub handoff_micros: u64,
    pub ledger_micros: u64,
}

impl IntelligenceBudgetV3 {
    fn validate(self) -> Result<(), IntelligencePipelineErrorV3> {
        let stages = [
            self.objective_micros,
            self.evaluation_micros,
            self.legal_set_micros,
            self.utility_micros,
            self.neural_micros,
            self.prompt_micros,
            self.intuition_micros,
            self.context_micros,
            self.handoff_micros,
            self.ledger_micros,
        ];
        if self.total_micros == 0 || stages.contains(&0) {
            return Err(IntelligencePipelineErrorV3::InvalidBudget);
        }
        let sum = stages
            .into_iter()
            .try_fold(0u64, u64::checked_add)
            .ok_or(IntelligencePipelineErrorV3::InvalidBudget)?;
        if sum > self.total_micros {
            return Err(IntelligencePipelineErrorV3::InvalidBudget);
        }
        Ok(())
    }

    const fn for_stage(self, stage: IntelligenceStageV3) -> u64 {
        match stage {
            IntelligenceStageV3::ObjectiveValidated => self.objective_micros,
            IntelligenceStageV3::EvaluationAdmitted => self.evaluation_micros,
            IntelligenceStageV3::LegalSetBuilt => self.legal_set_micros,
            IntelligenceStageV3::UtilityEvaluated => self.utility_micros,
            IntelligenceStageV3::NeuralSignalCollected => self.neural_micros,
            IntelligenceStageV3::PromptPortfolioBuilt => self.prompt_micros,
            IntelligenceStageV3::IntuitionDecided => self.intuition_micros,
            IntelligenceStageV3::ContextCompiled => self.context_micros,
            IntelligenceStageV3::HostHandoff => self.handoff_micros,
            IntelligenceStageV3::LearningRecorded => self.ledger_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceRunRequestV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub budget: IntelligenceBudgetV3,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntelligencePortDecisionV3 {
    Continue,
    Abstain,
    SlowPath,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntelligenceFailureClassV3 {
    Rejected,
    Unavailable,
    TimedOut,
    Quarantined,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligencePortInputV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub budget_micros: u64,
    pub stage: IntelligenceStageV3,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligencePortReceiptV3 {
    pub stage: IntelligenceStageV3,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub decision: IntelligencePortDecisionV3,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligencePortFailureV3 {
    pub class: IntelligenceFailureClassV3,
    pub evidence_digest: Digest32,
}

pub trait IntelligenceCompositionPortsV3 {
    fn validate_objective(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn admit_evaluation(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn build_legal_set(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn evaluate_utility(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn collect_neural_signal(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn build_prompt_portfolio(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn decide_intuition(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn compile_context(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn handoff_to_host(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn record_learning(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntelligenceStageOutcomeV3 {
    Completed,
    FallbackUsed(IntelligenceFailureClassV3),
    Abstained,
    SlowPath,
    Failed(IntelligenceFailureClassV3),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceStageTraceV3 {
    pub stage: IntelligenceStageV3,
    pub producer: StableId,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub outcome: IntelligenceStageOutcomeV3,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntelligenceDispositionV3 {
    HostHandedOff,
    Abstained,
    SlowPath,
    Failed(IntelligenceFailureClassV3),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<StableId>,
    pub support_floor_ppm: u32,
    pub candidate_set_digest: Digest32,
}

impl LegalActionCandidateSetV1 {
    pub fn new(
        candidate_set_id: StableId,
        state_digest: Digest32,
        generator_id: StableId,
        grammar_digest: Digest32,
        mut candidates: Vec<StableId>,
        support_floor_ppm: u32,
    ) -> Result<Self, IntelligencePipelineErrorV3> {
        if state_digest.is_zero()
            || grammar_digest.is_zero()
            || candidates.is_empty()
            || candidates.len() > MAX_CANDIDATES
            || support_floor_ppm > 1_000_000
        {
            return Err(IntelligencePipelineErrorV3::InvalidCandidateSet);
        }
        candidates.sort();
        if candidates.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(IntelligencePipelineErrorV3::InvalidCandidateSet);
        }
        let mut bytes = b"hepta.intelligence.legal-action-candidate-set.v1\0".to_vec();
        push_id(&mut bytes, &candidate_set_id)?;
        bytes.extend_from_slice(state_digest.as_array());
        push_id(&mut bytes, &generator_id)?;
        bytes.extend_from_slice(grammar_digest.as_array());
        bytes.extend_from_slice(&support_floor_ppm.to_be_bytes());
        bytes.extend_from_slice(
            &u32::try_from(candidates.len())
                .map_err(|_| IntelligencePipelineErrorV3::Arithmetic)?
                .to_be_bytes(),
        );
        for candidate in &candidates {
            push_id(&mut bytes, candidate)?;
        }
        Ok(Self {
            candidate_set_id,
            state_digest,
            generator_id,
            grammar_digest,
            candidates,
            support_floor_ppm,
            candidate_set_digest: Digest32::of_bytes(&bytes),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub objective_receipt_digest: Digest32,
    pub evaluation_receipt_digest: Digest32,
    pub candidate_set_receipt_digest: Digest32,
    pub utility_receipt_digest: Digest32,
    pub intuition_receipt_digest: Digest32,
    pub context_receipt_digest: Digest32,
    pub handoff_receipt_digest: Digest32,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceCompositionReceiptV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub disposition: IntelligenceDispositionV3,
    pub stages: Vec<IntelligenceStageTraceV3>,
    pub host_envelope: Option<IntelligenceHostEnvelopeV1>,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntelligencePipelineErrorV3 {
    InvalidBudget,
    EmptyDigest(&'static str),
    MissingCapability(&'static str),
    OwnerMismatch(&'static str),
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    PredecessorMismatch,
    AuthorityWidening,
    UnexpectedDecision,
    InvalidPortFailure,
    InvalidCandidateSet,
    InvalidReceipt(&'static str),
    Arithmetic,
}

impl fmt::Display for IntelligencePipelineErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for IntelligencePipelineErrorV3 {}

pub fn run_composition_v3<P: IntelligenceCompositionPortsV3>(
    request: IntelligenceRunRequestV3,
    ports: &mut P,
) -> Result<IntelligenceCompositionReceiptV3, IntelligencePipelineErrorV3> {
    if request.request_digest.is_zero() {
        return Err(IntelligencePipelineErrorV3::EmptyDigest("request"));
    }
    request.budget.validate()?;
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("evaluation.admission", "learning.eval"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.handoff", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ] {
        match request.snapshot.bound_owner(capability) {
            None => return Err(IntelligencePipelineErrorV3::MissingCapability(capability)),
            Some(actual) if actual != owner => {
                return Err(IntelligencePipelineErrorV3::OwnerMismatch(capability));
            }
            Some(_) => {}
        }
    }
    for (capability, owner) in [
        ("neural.signal", "neuron.runtime"),
        ("prompt.portfolio", "prompt.optimizer"),
    ] {
        if let Some(actual) = request.snapshot.bound_owner(capability)
            && actual != owner
        {
            return Err(IntelligencePipelineErrorV3::OwnerMismatch(capability));
        }
    }

    let snapshot_digest = request.snapshot.digest();
    if snapshot_digest.is_zero() {
        return Err(IntelligencePipelineErrorV3::EmptyDigest("snapshot"));
    }

    let mut stages = Vec::with_capacity(10);
    let mut predecessor = request.request_digest;

    macro_rules! required {
        ($stage:expr, $producer:literal, $call:expr) => {{
            let input = port_input(&request, snapshot_digest, predecessor, $stage);
            match $call(&input) {
                Ok(receipt) => {
                    validate_receipt(&input, $producer, &receipt)?;
                    if receipt.decision != IntelligencePortDecisionV3::Continue {
                        return Err(IntelligencePipelineErrorV3::UnexpectedDecision);
                    }
                    predecessor = receipt.output_digest;
                    stages.push(trace_completed(receipt));
                }
                Err(failure) => {
                    validate_failure(&failure)?;
                    let terminal =
                        append_failure(&mut stages, $stage, $producer, predecessor, failure)?;
                    return finish(
                        request.run_id,
                        snapshot_digest,
                        IntelligenceDispositionV3::Failed(
                            stages
                                .last()
                                .and_then(|trace| match trace.outcome {
                                    IntelligenceStageOutcomeV3::Failed(class) => Some(class),
                                    _ => None,
                                })
                                .ok_or(IntelligencePipelineErrorV3::InvalidReceipt(
                                    "terminal failure",
                                ))?,
                        ),
                        stages,
                        None,
                        terminal,
                    );
                }
            }
        }};
    }

    required!(
        IntelligenceStageV3::ObjectiveValidated,
        "objective.compiler",
        |input| ports.validate_objective(input)
    );
    required!(
        IntelligenceStageV3::EvaluationAdmitted,
        "learning.eval",
        |input| ports.admit_evaluation(input)
    );
    required!(
        IntelligenceStageV3::LegalSetBuilt,
        "intelligence.control",
        |input| ports.build_legal_set(input)
    );
    required!(
        IntelligenceStageV3::UtilityEvaluated,
        "utility.ndu",
        |input| ports.evaluate_utility(input)
    );

    predecessor = optional_stage(
        &request,
        snapshot_digest,
        predecessor,
        IntelligenceStageV3::NeuralSignalCollected,
        "neuron.runtime",
        request.snapshot.bound_owner("neural.signal").is_some(),
        &mut stages,
        |input| ports.collect_neural_signal(input),
    )?;
    predecessor = optional_stage(
        &request,
        snapshot_digest,
        predecessor,
        IntelligenceStageV3::PromptPortfolioBuilt,
        "prompt.optimizer",
        request.snapshot.bound_owner("prompt.portfolio").is_some(),
        &mut stages,
        |input| ports.build_prompt_portfolio(input),
    )?;

    let intuition_input = port_input(
        &request,
        snapshot_digest,
        predecessor,
        IntelligenceStageV3::IntuitionDecided,
    );
    let intuition = ports
        .decide_intuition(&intuition_input)
        .map_err(|failure| failure_as_pipeline(
            &mut stages,
            IntelligenceStageV3::IntuitionDecided,
            "intuition.policy",
            predecessor,
            failure,
        ))
        .and_then(|receipt| {
            validate_receipt(&intuition_input, "intuition.policy", &receipt)?;
            Ok(receipt)
        })?;
    predecessor = intuition.output_digest;
    let disposition = match intuition.decision {
        IntelligencePortDecisionV3::Continue => IntelligenceDispositionV3::HostHandedOff,
        IntelligencePortDecisionV3::Abstain => IntelligenceDispositionV3::Abstained,
        IntelligencePortDecisionV3::SlowPath => IntelligenceDispositionV3::SlowPath,
    };
    stages.push(IntelligenceStageTraceV3 {
        stage: intuition.stage,
        producer: intuition.producer,
        predecessor_digest: intuition.predecessor_digest,
        output_digest: intuition.output_digest,
        outcome: match intuition.decision {
            IntelligencePortDecisionV3::Continue => IntelligenceStageOutcomeV3::Completed,
            IntelligencePortDecisionV3::Abstain => IntelligenceStageOutcomeV3::Abstained,
            IntelligencePortDecisionV3::SlowPath => IntelligenceStageOutcomeV3::SlowPath,
        },
        evidence_digest: intuition.output_digest,
    });

    let mut host_envelope = None;
    if intuition.decision == IntelligencePortDecisionV3::Continue {
        required!(
            IntelligenceStageV3::ContextCompiled,
            "context.compiler",
            |input| ports.compile_context(input)
        );
        required!(
            IntelligenceStageV3::HostHandoff,
            "runtime.agentd",
            |input| ports.handoff_to_host(input)
        );
        host_envelope = Some(build_host_envelope(
            &request.run_id,
            snapshot_digest,
            &stages,
        )?);
    }

    required!(
        IntelligenceStageV3::LearningRecorded,
        "learning.ledger",
        |input| ports.record_learning(input)
    );

    finish(
        request.run_id,
        snapshot_digest,
        disposition,
        stages,
        host_envelope,
        predecessor,
    )
}

fn optional_stage<F>(
    request: &IntelligenceRunRequestV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: IntelligenceStageV3,
    producer: &str,
    present: bool,
    traces: &mut Vec<IntelligenceStageTraceV3>,
    call: F,
) -> Result<Digest32, IntelligencePipelineErrorV3>
where
    F: FnOnce(
        &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>,
{
    let input = port_input(request, snapshot_digest, predecessor, stage);
    if !present {
        let evidence = absent_digest(snapshot_digest, stage);
        let output = fallback_digest(stage, predecessor, IntelligenceFailureClassV3::Unavailable, evidence);
        traces.push(IntelligenceStageTraceV3 {
            stage,
            producer: stable_id(producer)?,
            predecessor_digest: predecessor,
            output_digest: output,
            outcome: IntelligenceStageOutcomeV3::FallbackUsed(
                IntelligenceFailureClassV3::Unavailable,
            ),
            evidence_digest: evidence,
        });
        return Ok(output);
    }
    match call(&input) {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != IntelligencePortDecisionV3::Continue {
                return Err(IntelligencePipelineErrorV3::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            traces.push(trace_completed(receipt));
            Ok(output)
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let output = fallback_digest(stage, predecessor, failure.class, failure.evidence_digest);
            traces.push(IntelligenceStageTraceV3 {
                stage,
                producer: stable_id(producer)?,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: IntelligenceStageOutcomeV3::FallbackUsed(failure.class),
                evidence_digest: failure.evidence_digest,
            });
            Ok(output)
        }
    }
}

fn failure_as_pipeline(
    traces: &mut Vec<IntelligenceStageTraceV3>,
    stage: IntelligenceStageV3,
    producer: &str,
    predecessor: Digest32,
    failure: IntelligencePortFailureV3,
) -> IntelligencePipelineErrorV3 {
    if validate_failure(&failure).is_err() {
        return IntelligencePipelineErrorV3::InvalidPortFailure;
    }
    let _ = append_failure(traces, stage, producer, predecessor, failure);
    IntelligencePipelineErrorV3::InvalidReceipt("intuition failure")
}

fn append_failure(
    traces: &mut Vec<IntelligenceStageTraceV3>,
    stage: IntelligenceStageV3,
    producer: &str,
    predecessor: Digest32,
    failure: IntelligencePortFailureV3,
) -> Result<Digest32, IntelligencePipelineErrorV3> {
    let output = fallback_digest(stage, predecessor, failure.class, failure.evidence_digest);
    traces.push(IntelligenceStageTraceV3 {
        stage,
        producer: stable_id(producer)?,
        predecessor_digest: predecessor,
        output_digest: output,
        outcome: IntelligenceStageOutcomeV3::Failed(failure.class),
        evidence_digest: failure.evidence_digest,
    });
    Ok(output)
}

fn trace_completed(receipt: IntelligencePortReceiptV3) -> IntelligenceStageTraceV3 {
    IntelligenceStageTraceV3 {
        stage: receipt.stage,
        producer: receipt.producer,
        predecessor_digest: receipt.predecessor_digest,
        output_digest: receipt.output_digest,
        outcome: IntelligenceStageOutcomeV3::Completed,
        evidence_digest: receipt.output_digest,
    }
}

fn port_input(
    request: &IntelligenceRunRequestV3,
    snapshot_digest: Digest32,
    predecessor_digest: Digest32,
    stage: IntelligenceStageV3,
) -> IntelligencePortInputV3 {
    IntelligencePortInputV3 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        predecessor_digest,
        budget_micros: request.budget.for_stage(stage),
        stage,
    }
}

fn validate_receipt(
    input: &IntelligencePortInputV3,
    producer: &str,
    receipt: &IntelligencePortReceiptV3,
) -> Result<(), IntelligencePipelineErrorV3> {
    if receipt.stage != input.stage {
        return Err(IntelligencePipelineErrorV3::StageMismatch);
    }
    if receipt.producer.as_str() != producer {
        return Err(IntelligencePipelineErrorV3::ProducerMismatch);
    }
    if receipt.snapshot_digest != input.snapshot_digest {
        return Err(IntelligencePipelineErrorV3::SnapshotMismatch);
    }
    if receipt.predecessor_digest != input.predecessor_digest {
        return Err(IntelligencePipelineErrorV3::PredecessorMismatch);
    }
    if receipt.output_digest.is_zero() {
        return Err(IntelligencePipelineErrorV3::EmptyDigest("port output"));
    }
    if receipt.authority.grants_any() {
        return Err(IntelligencePipelineErrorV3::AuthorityWidening);
    }
    Ok(())
}

fn validate_failure(
    failure: &IntelligencePortFailureV3,
) -> Result<(), IntelligencePipelineErrorV3> {
    if failure.evidence_digest.is_zero() {
        return Err(IntelligencePipelineErrorV3::InvalidPortFailure);
    }
    Ok(())
}

fn build_host_envelope(
    run_id: &StableId,
    snapshot_digest: Digest32,
    stages: &[IntelligenceStageTraceV3],
) -> Result<IntelligenceHostEnvelopeV1, IntelligencePipelineErrorV3> {
    let digest_for = |stage| {
        stages
            .iter()
            .find(|trace| trace.stage == stage)
            .map(|trace| trace.output_digest)
            .ok_or(IntelligencePipelineErrorV3::InvalidReceipt("missing envelope stage"))
    };
    let objective_receipt_digest = digest_for(IntelligenceStageV3::ObjectiveValidated)?;
    let evaluation_receipt_digest = digest_for(IntelligenceStageV3::EvaluationAdmitted)?;
    let candidate_set_receipt_digest = digest_for(IntelligenceStageV3::LegalSetBuilt)?;
    let utility_receipt_digest = digest_for(IntelligenceStageV3::UtilityEvaluated)?;
    let intuition_receipt_digest = digest_for(IntelligenceStageV3::IntuitionDecided)?;
    let context_receipt_digest = digest_for(IntelligenceStageV3::ContextCompiled)?;
    let handoff_receipt_digest = digest_for(IntelligenceStageV3::HostHandoff)?;
    let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    for digest in [
        snapshot_digest,
        objective_receipt_digest,
        evaluation_receipt_digest,
        candidate_set_receipt_digest,
        utility_receipt_digest,
        intuition_receipt_digest,
        context_receipt_digest,
        handoff_receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(IntelligenceHostEnvelopeV1 {
        run_id: run_id.clone(),
        snapshot_digest,
        objective_receipt_digest,
        evaluation_receipt_digest,
        candidate_set_receipt_digest,
        utility_receipt_digest,
        intuition_receipt_digest,
        context_receipt_digest,
        handoff_receipt_digest,
        envelope_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn finish(
    run_id: StableId,
    snapshot_digest: Digest32,
    disposition: IntelligenceDispositionV3,
    stages: Vec<IntelligenceStageTraceV3>,
    host_envelope: Option<IntelligenceHostEnvelopeV1>,
    terminal_digest: Digest32,
) -> Result<IntelligenceCompositionReceiptV3, IntelligencePipelineErrorV3> {
    if stages.is_empty() || stages.len() > 10 {
        return Err(IntelligencePipelineErrorV3::InvalidReceipt("stage count"));
    }
    let mut bytes = b"hepta.intelligence.composition-v3\0".to_vec();
    push_id(&mut bytes, &run_id)?;
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(disposition_code(disposition));
    for trace in &stages {
        bytes.push(stage_code(trace.stage));
        bytes.extend_from_slice(trace.predecessor_digest.as_array());
        bytes.extend_from_slice(trace.output_digest.as_array());
        bytes.push(outcome_code(trace.outcome));
        bytes.extend_from_slice(trace.evidence_digest.as_array());
    }
    if let Some(envelope) = &host_envelope {
        bytes.extend_from_slice(envelope.envelope_digest.as_array());
    }
    bytes.extend_from_slice(terminal_digest.as_array());
    Ok(IntelligenceCompositionReceiptV3 {
        run_id,
        snapshot_digest,
        disposition,
        stages,
        host_envelope,
        trace_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn fallback_digest(
    stage: IntelligenceStageV3,
    predecessor: Digest32,
    class: IntelligenceFailureClassV3,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.fallback-v3\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(failure_code(class));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn absent_digest(snapshot_digest: Digest32, stage: IntelligenceStageV3) -> Digest32 {
    let mut bytes = b"hepta.intelligence.absent-v3\0".to_vec();
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(stage_code(stage));
    Digest32::of_bytes(&bytes)
}

fn stable_id(value: &str) -> Result<StableId, IntelligencePipelineErrorV3> {
    StableId::new(value).map_err(|_| IntelligencePipelineErrorV3::Arithmetic)
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), IntelligencePipelineErrorV3> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| IntelligencePipelineErrorV3::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

const fn stage_code(stage: IntelligenceStageV3) -> u8 {
    match stage {
        IntelligenceStageV3::ObjectiveValidated => 0,
        IntelligenceStageV3::EvaluationAdmitted => 1,
        IntelligenceStageV3::LegalSetBuilt => 2,
        IntelligenceStageV3::UtilityEvaluated => 3,
        IntelligenceStageV3::NeuralSignalCollected => 4,
        IntelligenceStageV3::PromptPortfolioBuilt => 5,
        IntelligenceStageV3::IntuitionDecided => 6,
        IntelligenceStageV3::ContextCompiled => 7,
        IntelligenceStageV3::HostHandoff => 8,
        IntelligenceStageV3::LearningRecorded => 9,
    }
}

const fn failure_code(class: IntelligenceFailureClassV3) -> u8 {
    match class {
        IntelligenceFailureClassV3::Rejected => 0,
        IntelligenceFailureClassV3::Unavailable => 1,
        IntelligenceFailureClassV3::TimedOut => 2,
        IntelligenceFailureClassV3::Quarantined => 3,
        IntelligenceFailureClassV3::Indeterminate => 4,
    }
}

const fn disposition_code(disposition: IntelligenceDispositionV3) -> u8 {
    match disposition {
        IntelligenceDispositionV3::HostHandedOff => 0,
        IntelligenceDispositionV3::Abstained => 1,
        IntelligenceDispositionV3::SlowPath => 2,
        IntelligenceDispositionV3::Failed(class) => 10 + failure_code(class),
    }
}

const fn outcome_code(outcome: IntelligenceStageOutcomeV3) -> u8 {
    match outcome {
        IntelligenceStageOutcomeV3::Completed => 0,
        IntelligenceStageOutcomeV3::Abstained => 1,
        IntelligenceStageOutcomeV3::SlowPath => 2,
        IntelligenceStageOutcomeV3::FallbackUsed(class) => 10 + failure_code(class),
        IntelligenceStageOutcomeV3::Failed(class) => 20 + failure_code(class),
    }
}

#[cfg(test)]
#[path = "pipeline_v3_tests.rs"]
mod tests;
