//! Unified V3 intelligence composition graph.
//!
//! V1/V2 entrypoints remain compatibility surfaces. V3 is the converged
//! composition contract: one frozen capability snapshot, one predecessor chain,
//! explicit utility/evaluation stages, bounded optional neural/prompt fallbacks,
//! a durable decision-record stage, and a typed host envelope for Agentd.
//!
//! The graph is authority-free and effect-free. Agentd consumes the envelope and
//! owns dispatch lifecycle; terminal Outcome/Credit observations are appended
//! separately through the learning owner after an external result is observed.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;
use crate::PortDecisionV1;
use crate::PortFailureClassV1;
use crate::PortFailureV1;

// Reserve two ledger candidate identities for abstain and slow-path.
const MAX_CANDIDATES_V3: usize = 126;
const MAX_SUPPORT_PPM: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateV1 {
    pub candidate_id: StableId,
    pub support_digest: Digest32,
    pub support_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
    candidate_set_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LegalActionCandidateSetErrorV1 {
    CandidateLimitExceeded,
    InvalidSupportFloor,
    EmptyDigest(&'static str),
    DuplicateCandidate(String),
    SupportBelowFloor(String),
}

impl fmt::Display for LegalActionCandidateSetErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LegalActionCandidateSetErrorV1 {}

impl LegalActionCandidateSetV1 {
    pub fn new(
        candidate_set_id: StableId,
        state_digest: Digest32,
        generator_id: StableId,
        grammar_digest: Digest32,
        mut candidates: Vec<LegalActionCandidateV1>,
        support_floor_ppm: u32,
    ) -> Result<Self, LegalActionCandidateSetErrorV1> {
        if candidates.len() > MAX_CANDIDATES_V3 {
            return Err(LegalActionCandidateSetErrorV1::CandidateLimitExceeded);
        }
        if support_floor_ppm > MAX_SUPPORT_PPM {
            return Err(LegalActionCandidateSetErrorV1::InvalidSupportFloor);
        }
        if state_digest.is_zero() {
            return Err(LegalActionCandidateSetErrorV1::EmptyDigest("state"));
        }
        if grammar_digest.is_zero() {
            return Err(LegalActionCandidateSetErrorV1::EmptyDigest("grammar"));
        }
        candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
        let mut seen = BTreeSet::new();
        for candidate in &candidates {
            if !seen.insert(candidate.candidate_id.clone()) {
                return Err(LegalActionCandidateSetErrorV1::DuplicateCandidate(
                    candidate.candidate_id.to_string(),
                ));
            }
            if candidate.support_digest.is_zero() {
                return Err(LegalActionCandidateSetErrorV1::EmptyDigest(
                    "candidate support",
                ));
            }
            if candidate.support_ppm < support_floor_ppm
                || candidate.support_ppm > MAX_SUPPORT_PPM
            {
                return Err(LegalActionCandidateSetErrorV1::SupportBelowFloor(
                    candidate.candidate_id.to_string(),
                ));
            }
        }
        let candidate_set_digest = digest_candidate_set(
            &candidate_set_id,
            state_digest,
            &generator_id,
            grammar_digest,
            &candidates,
            support_floor_ppm,
        )?;
        Ok(Self {
            candidate_set_id,
            state_digest,
            generator_id,
            grammar_digest,
            candidates,
            support_floor_ppm,
            candidate_set_digest,
        })
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.candidate_set_digest
    }

    pub fn validate(&self) -> Result<(), LegalActionCandidateSetErrorV1> {
        let rebuilt = Self::new(
            self.candidate_set_id.clone(),
            self.state_digest,
            self.generator_id.clone(),
            self.grammar_digest,
            self.candidates.clone(),
            self.support_floor_ppm,
        )?;
        if rebuilt.candidate_set_digest != self.candidate_set_digest {
            return Err(LegalActionCandidateSetErrorV1::EmptyDigest(
                "candidate set digest",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionStageV3 {
    ObjectiveValidated,
    LegalSetBuilt,
    UtilityEvaluated,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
    EvaluationAdmitted,
    DecisionRecorded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StageOutcomeV3 {
    Completed,
    FallbackUsed(PortFailureClassV1),
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
    Cancelled,
    DeadlineExceeded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StageTraceV3 {
    pub stage: CompositionStageV3,
    pub producer: StableId,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub evidence_digest: Digest32,
    pub outcome: StageOutcomeV3,
    pub started_at_micros: u64,
    pub finished_at_micros: u64,
    pub stage_deadline_micros: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionDispositionV3 {
    ReadyForDispatch,
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
    Cancelled,
    DeadlineExceeded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompositionBudgetV3 {
    pub total_micros: u64,
    pub evidence_floor_micros: u64,
    pub recovery_floor_micros: u64,
    pub objective_micros: u64,
    pub legal_set_micros: u64,
    pub utility_micros: u64,
    pub neural_micros: u64,
    pub prompt_micros: u64,
    pub intuition_micros: u64,
    pub context_micros: u64,
    pub evaluation_micros: u64,
    pub ledger_micros: u64,
}

impl CompositionBudgetV3 {
    fn validate(self) -> Result<(), CompositionErrorV3> {
        let stages = [
            self.objective_micros,
            self.legal_set_micros,
            self.utility_micros,
            self.neural_micros,
            self.prompt_micros,
            self.intuition_micros,
            self.context_micros,
            self.evaluation_micros,
            self.ledger_micros,
        ];
        if self.total_micros == 0
            || self.evidence_floor_micros == 0
            || self.recovery_floor_micros == 0
            || stages.contains(&0)
        {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        let mut committed = self
            .evidence_floor_micros
            .checked_add(self.recovery_floor_micros)
            .ok_or(CompositionErrorV3::Arithmetic)?;
        for stage in stages {
            committed = committed
                .checked_add(stage)
                .ok_or(CompositionErrorV3::Arithmetic)?;
        }
        if committed > self.total_micros {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        Ok(())
    }

    const fn for_stage(self, stage: CompositionStageV3) -> u64 {
        match stage {
            CompositionStageV3::ObjectiveValidated => self.objective_micros,
            CompositionStageV3::LegalSetBuilt => self.legal_set_micros,
            CompositionStageV3::UtilityEvaluated => self.utility_micros,
            CompositionStageV3::NeuralSignalCollected => self.neural_micros,
            CompositionStageV3::PromptPortfolioBuilt => self.prompt_micros,
            CompositionStageV3::IntuitionDecided => self.intuition_micros,
            CompositionStageV3::ContextCompiled => self.context_micros,
            CompositionStageV3::EvaluationAdmitted => self.evaluation_micros,
            CompositionStageV3::DecisionRecorded => self.ledger_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionRunRequestV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub started_at_micros: u64,
    pub deadline_micros: u64,
    pub budget: CompositionBudgetV3,
    pub candidate_set: LegalActionCandidateSetV1,
}

pub trait CompositionControlV3 {
    fn now_micros(&self) -> u64;
    fn is_cancelled(&self) -> bool;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionPortInputV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub candidate_set_digest: Digest32,
    /// Frozen implementation identity for this capability. Optional stages
    /// carry None only when the capability is absent and the adapter is not called.
    pub capability_implementation_digest: Option<Digest32>,
    /// Frozen owner generation for this capability.
    pub capability_generation: Option<Generation>,
    pub budget_micros: u64,
    pub stage_deadline_micros: u64,
    pub stage: CompositionStageV3,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionPortReceiptV3 {
    pub stage: CompositionStageV3,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub evidence_digest: Digest32,
    pub decision: PortDecisionV1,
    pub authority: AuthorityPosture,
}

pub trait CompositionPortsV3 {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;

    /// Must append the actual durable Decision through learning.ledger.
    fn record_decision(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub utility_digest: Digest32,
    pub neural_stage_digest: Digest32,
    pub prompt_stage_digest: Digest32,
    pub intuition_digest: Digest32,
    pub context_digest: Digest32,
    pub context_receipt_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub decision_record_digest: Digest32,
    pub composition_trace_digest: Digest32,
    pub authority_epoch: u64,
    pub deadline_micros: u64,
    pub envelope_digest: Digest32,
}

impl IntelligenceHostEnvelopeV1 {
    pub fn validate(&self) -> Result<(), CompositionErrorV3> {
        if self.authority_epoch == 0 || self.deadline_micros == 0 {
            return Err(CompositionErrorV3::InvalidDeadline);
        }
        for (name, digest) in [
            ("request", self.request_digest),
            ("snapshot", self.snapshot_digest),
            ("objective", self.objective_digest),
            ("body", self.body_digest),
            ("artifact set", self.artifact_set_digest),
            ("candidate set", self.candidate_set_digest),
            ("utility", self.utility_digest),
            ("neural stage", self.neural_stage_digest),
            ("prompt stage", self.prompt_stage_digest),
            ("intuition", self.intuition_digest),
            ("context", self.context_digest),
            ("context receipt", self.context_receipt_digest),
            ("evaluation", self.evaluation_digest),
            ("decision record", self.decision_record_digest),
            ("composition trace", self.composition_trace_digest),
            ("envelope", self.envelope_digest),
        ] {
            if digest.is_zero() {
                return Err(CompositionErrorV3::EmptyDigest(name));
            }
        }
        if self.envelope_digest != digest_host_envelope(self)? {
            return Err(CompositionErrorV3::EnvelopeDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedIntelligenceRunV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub disposition: CompositionDispositionV3,
    pub stages: Vec<StageTraceV3>,
    pub trace_digest: Digest32,
    pub envelope: Option<IntelligenceHostEnvelopeV1>,
    pub authority: AuthorityPosture,
}

impl PreparedIntelligenceRunV3 {
    pub fn validate(&self) -> Result<(), CompositionErrorV3> {
        if self.snapshot_digest.is_zero() || self.trace_digest.is_zero() {
            return Err(CompositionErrorV3::EmptyDigest("prepared run"));
        }
        if self.authority.grants_any() {
            return Err(CompositionErrorV3::AuthorityWidening);
        }
        if self.stages.is_empty() || self.stages.len() > 9 {
            return Err(CompositionErrorV3::InvalidTrace("stage count"));
        }
        let mut expected = Some(CompositionStageV3::ObjectiveValidated);
        let mut previous = None;
        let mut intuition_outcome = None;
        for (index, trace) in self.stages.iter().enumerate() {
            if Some(trace.stage) != expected {
                return Err(CompositionErrorV3::InvalidTrace("stage order"));
            }
            if trace.output_digest.is_zero()
                || trace.evidence_digest.is_zero()
                || trace.predecessor_digest.is_zero()
            {
                return Err(CompositionErrorV3::InvalidTrace("empty stage digest"));
            }
            if trace.started_at_micros > trace.finished_at_micros
                || trace.finished_at_micros > trace.stage_deadline_micros
                    && !matches!(trace.outcome, StageOutcomeV3::DeadlineExceeded)
            {
                return Err(CompositionErrorV3::InvalidTrace("stage timing"));
            }
            if let Some(digest) = previous
                && trace.predecessor_digest != digest
            {
                return Err(CompositionErrorV3::PredecessorMismatch);
            }
            if trace.producer.as_str() != producer_for_stage(trace.stage) {
                return Err(CompositionErrorV3::ProducerMismatch);
            }
            previous = Some(trace.output_digest);
            if trace.stage == CompositionStageV3::IntuitionDecided {
                intuition_outcome = Some(trace.outcome);
            }
            expected = match trace.outcome {
                StageOutcomeV3::Completed | StageOutcomeV3::FallbackUsed(_) => {
                    next_stage(trace.stage)
                }
                StageOutcomeV3::Abstained | StageOutcomeV3::SlowPath
                    if trace.stage == CompositionStageV3::IntuitionDecided =>
                {
                    Some(CompositionStageV3::DecisionRecorded)
                }
                StageOutcomeV3::Abstained
                | StageOutcomeV3::SlowPath
                | StageOutcomeV3::Failed(_)
                | StageOutcomeV3::Cancelled
                | StageOutcomeV3::DeadlineExceeded => None,
            };
            if index + 1 < self.stages.len() && expected.is_none() {
                return Err(CompositionErrorV3::InvalidTrace("terminal continuation"));
            }
        }
        let terminal = self
            .stages
            .last()
            .ok_or(CompositionErrorV3::InvalidTrace("stage count"))?;
        match self.disposition {
            CompositionDispositionV3::ReadyForDispatch => {
                if terminal.stage != CompositionStageV3::DecisionRecorded
                    || terminal.outcome != StageOutcomeV3::Completed
                    || self.envelope.is_none()
                {
                    return Err(CompositionErrorV3::InvalidTrace("ready disposition"));
                }
            }
            CompositionDispositionV3::Abstained => {
                if intuition_outcome != Some(StageOutcomeV3::Abstained)
                    || terminal.stage != CompositionStageV3::DecisionRecorded
                    || terminal.outcome != StageOutcomeV3::Completed
                    || self.envelope.is_some()
                {
                    return Err(CompositionErrorV3::InvalidTrace("abstain disposition"));
                }
            }
            CompositionDispositionV3::SlowPath => {
                if intuition_outcome != Some(StageOutcomeV3::SlowPath)
                    || terminal.stage != CompositionStageV3::DecisionRecorded
                    || terminal.outcome != StageOutcomeV3::Completed
                    || self.envelope.is_some()
                {
                    return Err(CompositionErrorV3::InvalidTrace("slow-path disposition"));
                }
            }
            CompositionDispositionV3::Failed(class) => {
                if terminal.outcome != StageOutcomeV3::Failed(class) || self.envelope.is_some() {
                    return Err(CompositionErrorV3::InvalidTrace("failure disposition"));
                }
            }
            CompositionDispositionV3::Cancelled => {
                if terminal.outcome != StageOutcomeV3::Cancelled || self.envelope.is_some() {
                    return Err(CompositionErrorV3::InvalidTrace("cancel disposition"));
                }
            }
            CompositionDispositionV3::DeadlineExceeded => {
                if terminal.outcome != StageOutcomeV3::DeadlineExceeded || self.envelope.is_some() {
                    return Err(CompositionErrorV3::InvalidTrace("deadline disposition"));
                }
            }
        }
        let expected_trace = digest_trace_v3(
            &self.run_id,
            self.snapshot_digest,
            self.disposition,
            &self.stages,
        )?;
        if expected_trace != self.trace_digest {
            return Err(CompositionErrorV3::TraceDigestMismatch);
        }
        if let Some(envelope) = &self.envelope {
            envelope.validate()?;
            if envelope.run_id != self.run_id
                || envelope.snapshot_digest != self.snapshot_digest
                || envelope.composition_trace_digest != self.trace_digest
            {
                return Err(CompositionErrorV3::InvalidTrace("envelope binding"));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompositionErrorV3 {
    InvalidBudget,
    InvalidDeadline,
    EmptyDigest(&'static str),
    CandidateSet(LegalActionCandidateSetErrorV1),
    CandidateSnapshotMismatch,
    ObjectiveSnapshotMismatch,
    MissingCapability(&'static str),
    OwnerMismatch(&'static str),
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    PredecessorMismatch,
    AuthorityWidening,
    UnexpectedDecision,
    InvalidPortFailure,
    ClockRegression,
    Arithmetic,
    InvalidTrace(&'static str),
    TraceDigestMismatch,
    EnvelopeDigestMismatch,
}

impl fmt::Display for CompositionErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CompositionErrorV3 {}

impl From<LegalActionCandidateSetErrorV1> for CompositionErrorV3 {
    fn from(value: LegalActionCandidateSetErrorV1) -> Self {
        Self::CandidateSet(value)
    }
}

pub fn prepare_intelligence_run_v3<P: CompositionPortsV3, C: CompositionControlV3>(
    request: CompositionRunRequestV3,
    ports: &mut P,
    control: &C,
) -> Result<PreparedIntelligenceRunV3, CompositionErrorV3> {
    validate_run_request(&request)?;
    validate_capabilities(&request.snapshot)?;
    request.candidate_set.validate()?;
    let snapshot_digest = request.snapshot.digest();
    if request.candidate_set.state_digest != snapshot_digest {
        return Err(CompositionErrorV3::CandidateSnapshotMismatch);
    }

    let mut stages = Vec::with_capacity(9);
    let mut predecessor = request.request_digest;

    macro_rules! required {
        ($stage:expr, $producer:literal, $call:expr) => {{
            match run_required_stage(
                &request,
                control,
                snapshot_digest,
                predecessor,
                $stage,
                $producer,
                &mut stages,
                $call,
            )? {
                StageAdvanceV3::Continue(output) => predecessor = output,
                StageAdvanceV3::Terminal(disposition) => {
                    return finish_v3(
                        &request,
                        snapshot_digest,
                        disposition,
                        stages,
                        None,
                    );
                }
            }
        }};
    }

    required!(
        CompositionStageV3::ObjectiveValidated,
        "objective.compiler",
        |input| ports.validate_objective(input)
    );
    if predecessor != request.snapshot.objective_digest() {
        return Err(CompositionErrorV3::ObjectiveSnapshotMismatch);
    }

    match guard_stage(&request, control, CompositionStageV3::LegalSetBuilt, predecessor)? {
        GuardV3::Proceed(input, started) => {
            let finished = control.now_micros();
            if finished < started {
                return Err(CompositionErrorV3::ClockRegression);
            }
            if control.is_cancelled() {
                stages.push(control_trace(
                    CompositionStageV3::LegalSetBuilt,
                    "intelligence.control",
                    predecessor,
                    StageOutcomeV3::Cancelled,
                    started,
                    finished,
                    input.stage_deadline_micros,
                )?);
                return finish_v3(
                    &request,
                    snapshot_digest,
                    CompositionDispositionV3::Cancelled,
                    stages,
                    None,
                );
            }
            if finished > input.stage_deadline_micros {
                stages.push(control_trace(
                    CompositionStageV3::LegalSetBuilt,
                    "intelligence.control",
                    predecessor,
                    StageOutcomeV3::DeadlineExceeded,
                    started,
                    finished,
                    input.stage_deadline_micros,
                )?);
                return finish_v3(
                    &request,
                    snapshot_digest,
                    CompositionDispositionV3::DeadlineExceeded,
                    stages,
                    None,
                );
            }
            let digest = request.candidate_set.digest();
            stages.push(StageTraceV3 {
                stage: CompositionStageV3::LegalSetBuilt,
                producer: stable_id("intelligence.control")?,
                predecessor_digest: predecessor,
                output_digest: digest,
                evidence_digest: digest,
                outcome: StageOutcomeV3::Completed,
                started_at_micros: started,
                finished_at_micros: finished,
                stage_deadline_micros: input.stage_deadline_micros,
            });
            predecessor = digest;
        }
        GuardV3::Terminal(trace, disposition) => {
            stages.push(trace);
            return finish_v3(&request, snapshot_digest, disposition, stages, None);
        }
    }

    required!(
        CompositionStageV3::UtilityEvaluated,
        "utility.ndu",
        |input| ports.evaluate_utility(input)
    );

    predecessor = match run_optional_stage(
        &request,
        control,
        snapshot_digest,
        predecessor,
        CompositionStageV3::NeuralSignalCollected,
        "neuron.runtime",
        request.snapshot.bound_owner("neural.signal").is_some(),
        &mut stages,
        |input| ports.collect_neural_signal(input),
    )? {
        StageAdvanceV3::Continue(output) => output,
        StageAdvanceV3::Terminal(disposition) => {
            return finish_v3(&request, snapshot_digest, disposition, stages, None);
        }
    };

    predecessor = match run_optional_stage(
        &request,
        control,
        snapshot_digest,
        predecessor,
        CompositionStageV3::PromptPortfolioBuilt,
        "prompt.optimizer",
        request.snapshot.bound_owner("prompt.portfolio").is_some(),
        &mut stages,
        |input| ports.build_prompt_portfolio(input),
    )? {
        StageAdvanceV3::Continue(output) => output,
        StageAdvanceV3::Terminal(disposition) => {
            return finish_v3(&request, snapshot_digest, disposition, stages, None);
        }
    };

    let advisory_disposition = match run_decision_stage(
        &request,
        control,
        snapshot_digest,
        predecessor,
        &mut stages,
        |input| ports.decide_intuition(input),
    )? {
        DecisionAdvanceV3::Continue(output) => {
            predecessor = output;
            None
        }
        DecisionAdvanceV3::Advisory(output, disposition) => {
            predecessor = output;
            Some(disposition)
        }
        DecisionAdvanceV3::Terminal(disposition) => {
            return finish_v3(&request, snapshot_digest, disposition, stages, None);
        }
    };

    if let Some(disposition) = advisory_disposition {
        required!(
            CompositionStageV3::DecisionRecorded,
            "learning.ledger",
            |input| ports.record_decision(input)
        );
        let _decision_record_digest = predecessor;
        return finish_v3(&request, snapshot_digest, disposition, stages, None);
    }

    required!(
        CompositionStageV3::ContextCompiled,
        "context.compiler",
        |input| ports.compile_context(input)
    );
    required!(
        CompositionStageV3::EvaluationAdmitted,
        "learning.eval",
        |input| ports.admit_evaluation(input)
    );
    required!(
        CompositionStageV3::DecisionRecorded,
        "learning.ledger",
        |input| ports.record_decision(input)
    );
    let _decision_record_digest = predecessor;

    let trace_digest = digest_trace_v3(
        &request.run_id,
        snapshot_digest,
        CompositionDispositionV3::ReadyForDispatch,
        &stages,
    )?;
    let envelope = build_host_envelope(&request, snapshot_digest, trace_digest, &stages)?;
    let result = PreparedIntelligenceRunV3 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        disposition: CompositionDispositionV3::ReadyForDispatch,
        stages,
        trace_digest,
        envelope: Some(envelope),
        authority: AuthorityPosture::DENY_ALL,
    };
    result.validate()?;
    Ok(result)
}

fn validate_run_request(request: &CompositionRunRequestV3) -> Result<(), CompositionErrorV3> {
    request.budget.validate()?;
    for (name, digest) in [
        ("request", request.request_digest),
        ("body", request.body_digest),
        ("artifact set", request.artifact_set_digest),
    ] {
        if digest.is_zero() {
            return Err(CompositionErrorV3::EmptyDigest(name));
        }
    }
    if request.started_at_micros == 0 || request.deadline_micros <= request.started_at_micros {
        return Err(CompositionErrorV3::InvalidDeadline);
    }
    let horizon = request
        .deadline_micros
        .checked_sub(request.started_at_micros)
        .ok_or(CompositionErrorV3::InvalidDeadline)?;
    if request.budget.total_micros > horizon {
        return Err(CompositionErrorV3::InvalidDeadline);
    }
    Ok(())
}

fn validate_capabilities(snapshot: &CapabilitySnapshotV2) -> Result<(), CompositionErrorV3> {
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("evaluation.admission", "learning.eval"),
        ("learning.record", "learning.ledger"),
        ("dispatch.proposal", "runtime.agentd"),
    ] {
        match snapshot.bound_owner(capability) {
            None => return Err(CompositionErrorV3::MissingCapability(capability)),
            Some(actual) if actual != owner => {
                return Err(CompositionErrorV3::OwnerMismatch(capability));
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
            return Err(CompositionErrorV3::OwnerMismatch(capability));
        }
    }
    Ok(())
}

enum StageAdvanceV3 {
    Continue(Digest32),
    Terminal(CompositionDispositionV3),
}

enum DecisionAdvanceV3 {
    Continue(Digest32),
    Advisory(Digest32, CompositionDispositionV3),
    Terminal(CompositionDispositionV3),
}

enum GuardV3 {
    Proceed(CompositionPortInputV3, u64),
    Terminal(StageTraceV3, CompositionDispositionV3),
}

fn guard_stage<C: CompositionControlV3>(
    request: &CompositionRunRequestV3,
    control: &C,
    stage: CompositionStageV3,
    predecessor: Digest32,
) -> Result<GuardV3, CompositionErrorV3> {
    let now = control.now_micros();
    if now < request.started_at_micros {
        return Err(CompositionErrorV3::ClockRegression);
    }
    let budget = request.budget.for_stage(stage);
    let stage_deadline = now
        .checked_add(budget)
        .ok_or(CompositionErrorV3::Arithmetic)?
        .min(request.deadline_micros);
    if control.is_cancelled() {
        return Ok(GuardV3::Terminal(
            control_trace(
                stage,
                producer_for_stage(stage),
                predecessor,
                StageOutcomeV3::Cancelled,
                now,
                now,
                stage_deadline,
            )?,
            CompositionDispositionV3::Cancelled,
        ));
    }
    if now >= request.deadline_micros {
        return Ok(GuardV3::Terminal(
            control_trace(
                stage,
                producer_for_stage(stage),
                predecessor,
                StageOutcomeV3::DeadlineExceeded,
                now,
                now,
                stage_deadline,
            )?,
            CompositionDispositionV3::DeadlineExceeded,
        ));
    }
    let capability = capability_for_stage(stage);
    Ok(GuardV3::Proceed(
        CompositionPortInputV3 {
            run_id: request.run_id.clone(),
            snapshot_digest: request.snapshot.digest(),
            predecessor_digest: predecessor,
            candidate_set_digest: request.candidate_set.digest(),
            capability_implementation_digest: request
                .snapshot
                .bound_implementation_digest(capability),
            capability_generation: request.snapshot.bound_generation(capability),
            budget_micros: budget,
            stage_deadline_micros: stage_deadline,
            stage,
        },
        now,
    ))
}

fn run_required_stage<F, C: CompositionControlV3>(
    request: &CompositionRunRequestV3,
    control: &C,
    _snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: CompositionStageV3,
    producer: &str,
    traces: &mut Vec<StageTraceV3>,
    call: F,
) -> Result<StageAdvanceV3, CompositionErrorV3>
where
    F: FnOnce(&CompositionPortInputV3) -> Result<CompositionPortReceiptV3, PortFailureV1>,
{
    let (input, started) = match guard_stage(request, control, stage, predecessor)? {
        GuardV3::Proceed(input, started) => (input, started),
        GuardV3::Terminal(trace, disposition) => {
            traces.push(trace);
            return Ok(StageAdvanceV3::Terminal(disposition));
        }
    };
    let result = call(&input);
    let finished = control.now_micros();
    if finished < started {
        return Err(CompositionErrorV3::ClockRegression);
    }
    if control.is_cancelled() {
        traces.push(control_trace(
            stage,
            producer,
            predecessor,
            StageOutcomeV3::Cancelled,
            started,
            finished,
            input.stage_deadline_micros,
        )?);
        return Ok(StageAdvanceV3::Terminal(
            CompositionDispositionV3::Cancelled,
        ));
    }
    if finished > input.stage_deadline_micros {
        traces.push(control_trace(
            stage,
            producer,
            predecessor,
            StageOutcomeV3::DeadlineExceeded,
            started,
            finished,
            input.stage_deadline_micros,
        )?);
        return Ok(StageAdvanceV3::Terminal(
            CompositionDispositionV3::DeadlineExceeded,
        ));
    }
    match result {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != PortDecisionV1::Continue {
                return Err(CompositionErrorV3::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            traces.push(StageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: output,
                evidence_digest: receipt.evidence_digest,
                outcome: StageOutcomeV3::Completed,
                started_at_micros: started,
                finished_at_micros: finished,
                stage_deadline_micros: input.stage_deadline_micros,
            });
            Ok(StageAdvanceV3::Continue(output))
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let output = fallback_digest_v3(stage, predecessor, &failure);
            traces.push(StageTraceV3 {
                stage,
                producer: stable_id(producer)?,
                predecessor_digest: predecessor,
                output_digest: output,
                evidence_digest: failure.evidence_digest,
                outcome: StageOutcomeV3::Failed(failure.class),
                started_at_micros: started,
                finished_at_micros: finished,
                stage_deadline_micros: input.stage_deadline_micros,
            });
            Ok(StageAdvanceV3::Terminal(CompositionDispositionV3::Failed(
                failure.class,
            )))
        }
    }
}

fn run_optional_stage<F, C: CompositionControlV3>(
    request: &CompositionRunRequestV3,
    control: &C,
    _snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: CompositionStageV3,
    producer: &str,
    present: bool,
    traces: &mut Vec<StageTraceV3>,
    call: F,
) -> Result<StageAdvanceV3, CompositionErrorV3>
where
    F: FnOnce(&CompositionPortInputV3) -> Result<CompositionPortReceiptV3, PortFailureV1>,
{
    let (input, started) = match guard_stage(request, control, stage, predecessor)? {
        GuardV3::Proceed(input, started) => (input, started),
        GuardV3::Terminal(trace, disposition) => {
            traces.push(trace);
            return Ok(StageAdvanceV3::Terminal(disposition));
        }
    };
    let result = if present {
        call(&input)
    } else {
        Err(PortFailureV1 {
            class: PortFailureClassV1::Unavailable,
            evidence_digest: absent_capability_digest(request.snapshot.digest(), stage),
        })
    };
    let finished = control.now_micros();
    if finished < started {
        return Err(CompositionErrorV3::ClockRegression);
    }
    if control.is_cancelled() {
        traces.push(control_trace(
            stage,
            producer,
            predecessor,
            StageOutcomeV3::Cancelled,
            started,
            finished,
            input.stage_deadline_micros,
        )?);
        return Ok(StageAdvanceV3::Terminal(
            CompositionDispositionV3::Cancelled,
        ));
    }
    if finished > input.stage_deadline_micros {
        traces.push(control_trace(
            stage,
            producer,
            predecessor,
            StageOutcomeV3::DeadlineExceeded,
            started,
            finished,
            input.stage_deadline_micros,
        )?);
        return Ok(StageAdvanceV3::Terminal(
            CompositionDispositionV3::DeadlineExceeded,
        ));
    }
    match result {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != PortDecisionV1::Continue {
                return Err(CompositionErrorV3::UnexpectedDecision);
            }
            traces.push(StageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: receipt.output_digest,
                evidence_digest: receipt.evidence_digest,
                outcome: StageOutcomeV3::Completed,
                started_at_micros: started,
                finished_at_micros: finished,
                stage_deadline_micros: input.stage_deadline_micros,
            });
            Ok(StageAdvanceV3::Continue(receipt.output_digest))
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let output = fallback_digest_v3(stage, predecessor, &failure);
            traces.push(StageTraceV3 {
                stage,
                producer: stable_id(producer)?,
                predecessor_digest: predecessor,
                output_digest: output,
                evidence_digest: failure.evidence_digest,
                outcome: StageOutcomeV3::FallbackUsed(failure.class),
                started_at_micros: started,
                finished_at_micros: finished,
                stage_deadline_micros: input.stage_deadline_micros,
            });
            Ok(StageAdvanceV3::Continue(output))
        }
    }
}

fn run_decision_stage<F, C: CompositionControlV3>(
    request: &CompositionRunRequestV3,
    control: &C,
    _snapshot_digest: Digest32,
    predecessor: Digest32,
    traces: &mut Vec<StageTraceV3>,
    call: F,
) -> Result<DecisionAdvanceV3, CompositionErrorV3>
where
    F: FnOnce(&CompositionPortInputV3) -> Result<CompositionPortReceiptV3, PortFailureV1>,
{
    let stage = CompositionStageV3::IntuitionDecided;
    let (input, started) = match guard_stage(request, control, stage, predecessor)? {
        GuardV3::Proceed(input, started) => (input, started),
        GuardV3::Terminal(trace, disposition) => {
            traces.push(trace);
            return Ok(DecisionAdvanceV3::Terminal(disposition));
        }
    };
    let result = call(&input);
    let finished = control.now_micros();
    if finished < started {
        return Err(CompositionErrorV3::ClockRegression);
    }
    if control.is_cancelled() {
        traces.push(control_trace(
            stage,
            "intuition.policy",
            predecessor,
            StageOutcomeV3::Cancelled,
            started,
            finished,
            input.stage_deadline_micros,
        )?);
        return Ok(DecisionAdvanceV3::Terminal(
            CompositionDispositionV3::Cancelled,
        ));
    }
    if finished > input.stage_deadline_micros {
        traces.push(control_trace(
            stage,
            "intuition.policy",
            predecessor,
            StageOutcomeV3::DeadlineExceeded,
            started,
            finished,
            input.stage_deadline_micros,
        )?);
        return Ok(DecisionAdvanceV3::Terminal(
            CompositionDispositionV3::DeadlineExceeded,
        ));
    }
    match result {
        Ok(receipt) => {
            validate_receipt(&input, "intuition.policy", &receipt)?;
            let outcome = match receipt.decision {
                PortDecisionV1::Continue => StageOutcomeV3::Completed,
                PortDecisionV1::Abstain => StageOutcomeV3::Abstained,
                PortDecisionV1::SlowPath => StageOutcomeV3::SlowPath,
            };
            traces.push(StageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: receipt.output_digest,
                evidence_digest: receipt.evidence_digest,
                outcome,
                started_at_micros: started,
                finished_at_micros: finished,
                stage_deadline_micros: input.stage_deadline_micros,
            });
            Ok(match receipt.decision {
                PortDecisionV1::Continue => DecisionAdvanceV3::Continue(receipt.output_digest),
                PortDecisionV1::Abstain => DecisionAdvanceV3::Advisory(
                    receipt.output_digest,
                    CompositionDispositionV3::Abstained,
                ),
                PortDecisionV1::SlowPath => DecisionAdvanceV3::Advisory(
                    receipt.output_digest,
                    CompositionDispositionV3::SlowPath,
                ),
            })
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let output = fallback_digest_v3(stage, predecessor, &failure);
            traces.push(StageTraceV3 {
                stage,
                producer: stable_id("intuition.policy")?,
                predecessor_digest: predecessor,
                output_digest: output,
                evidence_digest: failure.evidence_digest,
                outcome: StageOutcomeV3::Failed(failure.class),
                started_at_micros: started,
                finished_at_micros: finished,
                stage_deadline_micros: input.stage_deadline_micros,
            });
            Ok(DecisionAdvanceV3::Terminal(CompositionDispositionV3::Failed(
                failure.class,
            )))
        }
    }
}

fn validate_receipt(
    input: &CompositionPortInputV3,
    expected_producer: &str,
    receipt: &CompositionPortReceiptV3,
) -> Result<(), CompositionErrorV3> {
    if receipt.stage != input.stage {
        return Err(CompositionErrorV3::StageMismatch);
    }
    if receipt.producer.as_str() != expected_producer {
        return Err(CompositionErrorV3::ProducerMismatch);
    }
    if receipt.snapshot_digest != input.snapshot_digest {
        return Err(CompositionErrorV3::SnapshotMismatch);
    }
    if receipt.predecessor_digest != input.predecessor_digest {
        return Err(CompositionErrorV3::PredecessorMismatch);
    }
    if receipt.output_digest.is_zero() || receipt.evidence_digest.is_zero() {
        return Err(CompositionErrorV3::EmptyDigest("port receipt"));
    }
    if receipt.authority.grants_any() {
        return Err(CompositionErrorV3::AuthorityWidening);
    }
    Ok(())
}

fn validate_failure(failure: &PortFailureV1) -> Result<(), CompositionErrorV3> {
    if failure.evidence_digest.is_zero() {
        return Err(CompositionErrorV3::InvalidPortFailure);
    }
    Ok(())
}

fn finish_v3(
    request: &CompositionRunRequestV3,
    snapshot_digest: Digest32,
    disposition: CompositionDispositionV3,
    stages: Vec<StageTraceV3>,
    envelope: Option<IntelligenceHostEnvelopeV1>,
) -> Result<PreparedIntelligenceRunV3, CompositionErrorV3> {
    let trace_digest = digest_trace_v3(&request.run_id, snapshot_digest, disposition, &stages)?;
    let value = PreparedIntelligenceRunV3 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        disposition,
        stages,
        trace_digest,
        envelope,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.validate()?;
    Ok(value)
}

fn build_host_envelope(
    request: &CompositionRunRequestV3,
    snapshot_digest: Digest32,
    trace_digest: Digest32,
    stages: &[StageTraceV3],
) -> Result<IntelligenceHostEnvelopeV1, CompositionErrorV3> {
    let get = |stage| {
        stages
            .iter()
            .find(|trace| trace.stage == stage)
            .ok_or(CompositionErrorV3::InvalidTrace("missing envelope stage"))
    };
    let objective = get(CompositionStageV3::ObjectiveValidated)?;
    let utility = get(CompositionStageV3::UtilityEvaluated)?;
    let neural = get(CompositionStageV3::NeuralSignalCollected)?;
    let prompt = get(CompositionStageV3::PromptPortfolioBuilt)?;
    let intuition = get(CompositionStageV3::IntuitionDecided)?;
    let context = get(CompositionStageV3::ContextCompiled)?;
    let evaluation = get(CompositionStageV3::EvaluationAdmitted)?;
    let decision = get(CompositionStageV3::DecisionRecorded)?;
    let mut envelope = IntelligenceHostEnvelopeV1 {
        run_id: request.run_id.clone(),
        request_digest: request.request_digest,
        snapshot_digest,
        objective_digest: objective.output_digest,
        body_digest: request.body_digest,
        artifact_set_digest: request.artifact_set_digest,
        candidate_set_digest: request.candidate_set.digest(),
        utility_digest: utility.output_digest,
        neural_stage_digest: neural.output_digest,
        prompt_stage_digest: prompt.output_digest,
        intuition_digest: intuition.output_digest,
        context_digest: context.output_digest,
        context_receipt_digest: context.evidence_digest,
        evaluation_digest: evaluation.output_digest,
        decision_record_digest: decision.output_digest,
        composition_trace_digest: trace_digest,
        authority_epoch: request.snapshot.authority_epoch(),
        deadline_micros: request.deadline_micros,
        envelope_digest: Digest32::ZERO,
    };
    envelope.envelope_digest = digest_host_envelope(&envelope)?;
    envelope.validate()?;
    Ok(envelope)
}

fn digest_candidate_set(
    candidate_set_id: &StableId,
    state_digest: Digest32,
    generator_id: &StableId,
    grammar_digest: Digest32,
    candidates: &[LegalActionCandidateV1],
    support_floor_ppm: u32,
) -> Result<Digest32, LegalActionCandidateSetErrorV1> {
    let mut bytes = b"hepta.legal-action-candidate-set.v1\0".to_vec();
    push_id_contract(&mut bytes, candidate_set_id)?;
    bytes.extend_from_slice(state_digest.as_array());
    push_id_contract(&mut bytes, generator_id)?;
    bytes.extend_from_slice(grammar_digest.as_array());
    bytes.extend_from_slice(&support_floor_ppm.to_be_bytes());
    let count = u32::try_from(candidates.len())
        .map_err(|_| LegalActionCandidateSetErrorV1::CandidateLimitExceeded)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for candidate in candidates {
        push_id_contract(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(candidate.support_digest.as_array());
        bytes.extend_from_slice(&candidate.support_ppm.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_host_envelope(value: &IntelligenceHostEnvelopeV1) -> Result<Digest32, CompositionErrorV3> {
    let mut bytes = b"hepta.intelligence-host-envelope.v1\0".to_vec();
    push_id(&mut bytes, &value.run_id)?;
    for digest in [
        value.request_digest,
        value.snapshot_digest,
        value.objective_digest,
        value.body_digest,
        value.artifact_set_digest,
        value.candidate_set_digest,
        value.utility_digest,
        value.neural_stage_digest,
        value.prompt_stage_digest,
        value.intuition_digest,
        value.context_digest,
        value.context_receipt_digest,
        value.evaluation_digest,
        value.decision_record_digest,
        value.composition_trace_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.deadline_micros.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_trace_v3(
    run_id: &StableId,
    snapshot_digest: Digest32,
    disposition: CompositionDispositionV3,
    stages: &[StageTraceV3],
) -> Result<Digest32, CompositionErrorV3> {
    let mut bytes = b"hepta.intelligence.composition-trace.v3\0".to_vec();
    push_id(&mut bytes, run_id)?;
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(disposition_code(disposition));
    let count = u32::try_from(stages.len()).map_err(|_| CompositionErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for stage in stages {
        bytes.push(stage_code(stage.stage));
        push_id(&mut bytes, &stage.producer)?;
        bytes.extend_from_slice(stage.predecessor_digest.as_array());
        bytes.extend_from_slice(stage.output_digest.as_array());
        bytes.extend_from_slice(stage.evidence_digest.as_array());
        bytes.push(outcome_code(stage.outcome));
        bytes.extend_from_slice(&stage.started_at_micros.to_be_bytes());
        bytes.extend_from_slice(&stage.finished_at_micros.to_be_bytes());
        bytes.extend_from_slice(&stage.stage_deadline_micros.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn control_trace(
    stage: CompositionStageV3,
    producer: &str,
    predecessor: Digest32,
    outcome: StageOutcomeV3,
    started: u64,
    finished: u64,
    deadline: u64,
) -> Result<StageTraceV3, CompositionErrorV3> {
    let mut bytes = b"hepta.intelligence.control-stop.v3\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(outcome_code(outcome));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&started.to_be_bytes());
    bytes.extend_from_slice(&finished.to_be_bytes());
    bytes.extend_from_slice(&deadline.to_be_bytes());
    let digest = Digest32::of_bytes(&bytes);
    Ok(StageTraceV3 {
        stage,
        producer: stable_id(producer)?,
        predecessor_digest: predecessor,
        output_digest: digest,
        evidence_digest: digest,
        outcome,
        started_at_micros: started,
        finished_at_micros: finished,
        stage_deadline_micros: deadline,
    })
}

fn absent_capability_digest(snapshot: Digest32, stage: CompositionStageV3) -> Digest32 {
    let mut bytes = b"hepta.intelligence.absent-capability.v3\0".to_vec();
    bytes.extend_from_slice(snapshot.as_array());
    bytes.push(stage_code(stage));
    Digest32::of_bytes(&bytes)
}

fn fallback_digest_v3(
    stage: CompositionStageV3,
    predecessor: Digest32,
    failure: &PortFailureV1,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.fallback.v3\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(failure_code(failure.class));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(failure.evidence_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn capability_for_stage(stage: CompositionStageV3) -> &'static str {
    match stage {
        CompositionStageV3::ObjectiveValidated => "objective.validation",
        CompositionStageV3::LegalSetBuilt => "legal.actions",
        CompositionStageV3::UtilityEvaluated => "utility.evaluation",
        CompositionStageV3::NeuralSignalCollected => "neural.signal",
        CompositionStageV3::PromptPortfolioBuilt => "prompt.portfolio",
        CompositionStageV3::IntuitionDecided => "intuition.decision",
        CompositionStageV3::ContextCompiled => "context.compilation",
        CompositionStageV3::EvaluationAdmitted => "evaluation.admission",
        CompositionStageV3::DecisionRecorded => "learning.record",
    }
}

fn producer_for_stage(stage: CompositionStageV3) -> &'static str {
    match stage {
        CompositionStageV3::ObjectiveValidated => "objective.compiler",
        CompositionStageV3::LegalSetBuilt => "intelligence.control",
        CompositionStageV3::UtilityEvaluated => "utility.ndu",
        CompositionStageV3::NeuralSignalCollected => "neuron.runtime",
        CompositionStageV3::PromptPortfolioBuilt => "prompt.optimizer",
        CompositionStageV3::IntuitionDecided => "intuition.policy",
        CompositionStageV3::ContextCompiled => "context.compiler",
        CompositionStageV3::EvaluationAdmitted => "learning.eval",
        CompositionStageV3::DecisionRecorded => "learning.ledger",
    }
}

const fn next_stage(stage: CompositionStageV3) -> Option<CompositionStageV3> {
    Some(match stage {
        CompositionStageV3::ObjectiveValidated => CompositionStageV3::LegalSetBuilt,
        CompositionStageV3::LegalSetBuilt => CompositionStageV3::UtilityEvaluated,
        CompositionStageV3::UtilityEvaluated => CompositionStageV3::NeuralSignalCollected,
        CompositionStageV3::NeuralSignalCollected => CompositionStageV3::PromptPortfolioBuilt,
        CompositionStageV3::PromptPortfolioBuilt => CompositionStageV3::IntuitionDecided,
        CompositionStageV3::IntuitionDecided => CompositionStageV3::ContextCompiled,
        CompositionStageV3::ContextCompiled => CompositionStageV3::EvaluationAdmitted,
        CompositionStageV3::EvaluationAdmitted => CompositionStageV3::DecisionRecorded,
        CompositionStageV3::DecisionRecorded => return None,
    })
}

fn stable_id(value: &str) -> Result<StableId, CompositionErrorV3> {
    StableId::new(value).map_err(|_| CompositionErrorV3::Arithmetic)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), CompositionErrorV3> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| CompositionErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_id_contract(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), LegalActionCandidateSetErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| LegalActionCandidateSetErrorV1::CandidateLimitExceeded)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

const fn stage_code(value: CompositionStageV3) -> u8 {
    match value {
        CompositionStageV3::ObjectiveValidated => 0,
        CompositionStageV3::LegalSetBuilt => 1,
        CompositionStageV3::UtilityEvaluated => 2,
        CompositionStageV3::NeuralSignalCollected => 3,
        CompositionStageV3::PromptPortfolioBuilt => 4,
        CompositionStageV3::IntuitionDecided => 5,
        CompositionStageV3::ContextCompiled => 6,
        CompositionStageV3::EvaluationAdmitted => 7,
        CompositionStageV3::DecisionRecorded => 8,
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

const fn outcome_code(value: StageOutcomeV3) -> u8 {
    match value {
        StageOutcomeV3::Completed => 0,
        StageOutcomeV3::FallbackUsed(class) => 10 + failure_code(class),
        StageOutcomeV3::Abstained => 1,
        StageOutcomeV3::SlowPath => 2,
        StageOutcomeV3::Failed(class) => 20 + failure_code(class),
        StageOutcomeV3::Cancelled => 3,
        StageOutcomeV3::DeadlineExceeded => 4,
    }
}

const fn disposition_code(value: CompositionDispositionV3) -> u8 {
    match value {
        CompositionDispositionV3::ReadyForDispatch => 0,
        CompositionDispositionV3::Abstained => 1,
        CompositionDispositionV3::SlowPath => 2,
        CompositionDispositionV3::Failed(class) => 10 + failure_code(class),
        CompositionDispositionV3::Cancelled => 3,
        CompositionDispositionV3::DeadlineExceeded => 4,
    }
}

#[cfg(test)]
#[path = "composition_v3_tests.rs"]
mod tests;
