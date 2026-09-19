//! Unified V3 composition graph for intelligence.control.
//!
//! V1/V2 shadow entrypoints remain compatibility surfaces. V3 is the first
//! facade that places objective, legal-set construction, NDU utility,
//! independent evaluation, neuron, prompt, intuition and context under one
//! frozen capability snapshot and one predecessor chain. It prepares a
//! host envelope only; it never invokes a model, tool, provider or external
//! effect.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;

const MAX_LEGAL_CANDIDATES: usize = 128;
const MAX_PPM: u32 = 1_000_000;
const INTELLIGENCE_CONTROL: &str = "intelligence.control";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateV1 {
    pub candidate_id: StableId,
    pub action_digest: Digest32,
    pub support_digest: Digest32,
    pub support_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetRequestV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LegalActionCandidateSetErrorV1 {
    EmptyDigest(&'static str),
    CandidateLimitExceeded,
    InvalidSupportFloor,
    DuplicateCandidate(String),
    InvalidCandidate(String),
}

impl fmt::Display for LegalActionCandidateSetErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LegalActionCandidateSetErrorV1 {}

pub fn build_legal_candidates(
    mut request: LegalActionCandidateSetRequestV1,
) -> Result<LegalActionCandidateSetV1, LegalActionCandidateSetErrorV1> {
    for (field, digest) in [
        ("state", request.state_digest),
        ("grammar", request.grammar_digest),
    ] {
        if digest.is_zero() {
            return Err(LegalActionCandidateSetErrorV1::EmptyDigest(field));
        }
    }
    if request.candidates.len() > MAX_LEGAL_CANDIDATES {
        return Err(LegalActionCandidateSetErrorV1::CandidateLimitExceeded);
    }
    if request.support_floor_ppm > MAX_PPM {
        return Err(LegalActionCandidateSetErrorV1::InvalidSupportFloor);
    }

    request
        .candidates
        .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    for candidate in &request.candidates {
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(LegalActionCandidateSetErrorV1::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.action_digest.is_zero()
            || candidate.support_digest.is_zero()
            || candidate.support_ppm > MAX_PPM
            || candidate.support_ppm < request.support_floor_ppm
        {
            return Err(LegalActionCandidateSetErrorV1::InvalidCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
    }

    let value = LegalActionCandidateSetV1 {
        candidate_set_id: request.candidate_set_id,
        state_digest: request.state_digest,
        generator_id: StableId::new(INTELLIGENCE_CONTROL)
            .map_err(|_| LegalActionCandidateSetErrorV1::InvalidCandidate(INTELLIGENCE_CONTROL.into()))?,
        grammar_digest: request.grammar_digest,
        candidates: request.candidates,
        support_floor_ppm: request.support_floor_ppm,
    };
    value.validate()?;
    Ok(value)
}

impl LegalActionCandidateSetV1 {
    pub fn validate(&self) -> Result<(), LegalActionCandidateSetErrorV1> {
        if self.generator_id.as_str() != INTELLIGENCE_CONTROL {
            return Err(LegalActionCandidateSetErrorV1::InvalidCandidate(
                "generator".to_string(),
            ));
        }
        if self.state_digest.is_zero() {
            return Err(LegalActionCandidateSetErrorV1::EmptyDigest("state"));
        }
        if self.grammar_digest.is_zero() {
            return Err(LegalActionCandidateSetErrorV1::EmptyDigest("grammar"));
        }
        if self.candidates.len() > MAX_LEGAL_CANDIDATES {
            return Err(LegalActionCandidateSetErrorV1::CandidateLimitExceeded);
        }
        if self.support_floor_ppm > MAX_PPM {
            return Err(LegalActionCandidateSetErrorV1::InvalidSupportFloor);
        }
        let mut seen = BTreeSet::new();
        for candidate in &self.candidates {
            if !seen.insert(candidate.candidate_id.clone()) {
                return Err(LegalActionCandidateSetErrorV1::DuplicateCandidate(
                    candidate.candidate_id.to_string(),
                ));
            }
            if candidate.action_digest.is_zero()
                || candidate.support_digest.is_zero()
                || candidate.support_ppm > MAX_PPM
                || candidate.support_ppm < self.support_floor_ppm
            {
                return Err(LegalActionCandidateSetErrorV1::InvalidCandidate(
                    candidate.candidate_id.to_string(),
                ));
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.intelligence.legal-action-candidate-set.v1\0".to_vec();
        push_id(&mut bytes, &self.candidate_set_id);
        bytes.extend_from_slice(self.state_digest.as_array());
        push_id(&mut bytes, &self.generator_id);
        bytes.extend_from_slice(self.grammar_digest.as_array());
        bytes.extend_from_slice(&self.support_floor_ppm.to_be_bytes());
        bytes.extend_from_slice(
            &u32::try_from(self.candidates.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for candidate in &self.candidates {
            push_id(&mut bytes, &candidate.candidate_id);
            bytes.extend_from_slice(candidate.action_digest.as_array());
            bytes.extend_from_slice(candidate.support_digest.as_array());
            bytes.extend_from_slice(&candidate.support_ppm.to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
    pub body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub utility_digest: Digest32,
    pub utility_receipt_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub evaluation_receipt_digest: Digest32,
    pub neural_signal_digest: Option<Digest32>,
    pub prompt_portfolio_digest: Option<Digest32>,
    pub intuition_digest: Digest32,
    pub intuition_receipt_digest: Digest32,
    pub context_digest: Digest32,
    pub context_receipt_digest: Digest32,
    pub composition_trace_digest: Digest32,
    pub deadline_unix_micros: u64,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl IntelligenceHostEnvelopeV1 {
    #[must_use]
    pub fn canonical_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
        push_id(&mut bytes, &self.run_id);
        for digest in [
            self.request_digest,
            self.snapshot_digest,
            self.objective_digest,
            self.body_digest,
            self.artifact_set_digest,
            self.candidate_set_digest,
            self.utility_digest,
            self.utility_receipt_digest,
            self.evaluation_digest,
            self.evaluation_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        push_optional_digest(&mut bytes, self.neural_signal_digest);
        push_optional_digest(&mut bytes, self.prompt_portfolio_digest);
        for digest in [
            self.intuition_digest,
            self.intuition_receipt_digest,
            self.context_digest,
            self.context_receipt_digest,
            self.composition_trace_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.deadline_unix_micros.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), CompositionErrorV3> {
        for (field, digest) in [
            ("request", self.request_digest),
            ("snapshot", self.snapshot_digest),
            ("objective", self.objective_digest),
            ("body", self.body_digest),
            ("artifact set", self.artifact_set_digest),
            ("candidate set", self.candidate_set_digest),
            ("utility", self.utility_digest),
            ("utility receipt", self.utility_receipt_digest),
            ("evaluation", self.evaluation_digest),
            ("evaluation receipt", self.evaluation_receipt_digest),
            ("intuition", self.intuition_digest),
            ("intuition receipt", self.intuition_receipt_digest),
            ("context", self.context_digest),
            ("context receipt", self.context_receipt_digest),
            ("composition trace", self.composition_trace_digest),
            ("envelope", self.envelope_digest),
        ] {
            if digest.is_zero() {
                return Err(CompositionErrorV3::EmptyDigest(field));
            }
        }
        for digest in [self.neural_signal_digest, self.prompt_portfolio_digest]
            .into_iter()
            .flatten()
        {
            if digest.is_zero() {
                return Err(CompositionErrorV3::EmptyDigest("optional stage"));
            }
        }
        if self.authority_epoch == 0 {
            return Err(CompositionErrorV3::InvalidPipelineReceipt("authority epoch"));
        }
        if self.deadline_unix_micros == 0 {
            return Err(CompositionErrorV3::InvalidDeadline);
        }
        if self.authority.grants_any() {
            return Err(CompositionErrorV3::AuthorityWidening);
        }
        if self.envelope_digest != self.canonical_digest() {
            return Err(CompositionErrorV3::EnvelopeDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionStageV3 {
    ObjectiveValidated,
    LegalCandidatesBuilt,
    UtilityEvaluated,
    EvaluationAdmitted,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
}

const STAGE_ORDER_V3: [CompositionStageV3; 8] = [
    CompositionStageV3::ObjectiveValidated,
    CompositionStageV3::LegalCandidatesBuilt,
    CompositionStageV3::UtilityEvaluated,
    CompositionStageV3::EvaluationAdmitted,
    CompositionStageV3::NeuralSignalCollected,
    CompositionStageV3::PromptPortfolioBuilt,
    CompositionStageV3::IntuitionDecided,
    CompositionStageV3::ContextCompiled,
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompositionBudgetV3 {
    pub total_micros: u64,
    pub objective_micros: u64,
    pub legal_set_micros: u64,
    pub utility_micros: u64,
    pub evaluation_micros: u64,
    pub neural_micros: u64,
    pub prompt_micros: u64,
    pub intuition_micros: u64,
    pub context_micros: u64,
}

impl CompositionBudgetV3 {
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
        ];
        if self.total_micros == 0 || stages.contains(&0) {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        let sum = stages
            .into_iter()
            .try_fold(0_u64, u64::checked_add)
            .ok_or(CompositionErrorV3::InvalidBudget)?;
        if sum > self.total_micros {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        Ok(())
    }

    const fn for_stage(self, stage: CompositionStageV3) -> u64 {
        match stage {
            CompositionStageV3::ObjectiveValidated => self.objective_micros,
            CompositionStageV3::LegalCandidatesBuilt => self.legal_set_micros,
            CompositionStageV3::UtilityEvaluated => self.utility_micros,
            CompositionStageV3::EvaluationAdmitted => self.evaluation_micros,
            CompositionStageV3::NeuralSignalCollected => self.neural_micros,
            CompositionStageV3::PromptPortfolioBuilt => self.prompt_micros,
            CompositionStageV3::IntuitionDecided => self.intuition_micros,
            CompositionStageV3::ContextCompiled => self.context_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionRunRequestV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub legal_candidates: LegalActionCandidateSetV1,
    pub budget: CompositionBudgetV3,
    pub deadline_unix_micros: u64,
}

pub trait CompositionControlV3 {
    fn now_unix_micros(&self) -> u64;
    fn is_cancelled(&self, run_id: &StableId) -> bool;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionPortDecisionV3 {
    Continue,
    Abstain,
    SlowPath,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionFailureClassV3 {
    Rejected,
    Unavailable,
    TimedOut,
    Quarantined,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionPortInputV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub stage: CompositionStageV3,
    pub budget_micros: u64,
    pub deadline_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionPortReceiptV3 {
    pub stage: CompositionStageV3,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub evidence_digest: Digest32,
    pub decision: CompositionPortDecisionV3,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionPortFailureV3 {
    pub class: CompositionFailureClassV3,
    pub evidence_digest: Digest32,
}

pub trait CompositionPortsV3 {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>;

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>;

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>;

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>;

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>;

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>;

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionStageOutcomeV3 {
    Completed,
    FallbackUsed(CompositionFailureClassV3),
    Abstained,
    SlowPath,
    Failed(CompositionFailureClassV3),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionStageTraceV3 {
    pub stage: CompositionStageV3,
    pub producer: StableId,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub outcome: CompositionStageOutcomeV3,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionDispositionV3 {
    HostEnvelopePrepared,
    Abstained,
    SlowPath,
    Failed(CompositionFailureClassV3),
    Cancelled,
    DeadlineExceeded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionPipelineReceiptV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub disposition: CompositionDispositionV3,
    pub stages: Vec<CompositionStageTraceV3>,
    pub trace_digest: Digest32,
    pub envelope: Option<IntelligenceHostEnvelopeV1>,
    pub authority: AuthorityPosture,
}

impl CompositionPipelineReceiptV3 {
    pub fn validate(&self) -> Result<(), CompositionErrorV3> {
        if self.request_digest.is_zero()
            || self.snapshot_digest.is_zero()
            || self.trace_digest.is_zero()
        {
            return Err(CompositionErrorV3::InvalidPipelineReceipt("empty digest"));
        }
        if self.authority.grants_any() {
            return Err(CompositionErrorV3::AuthorityWidening);
        }
        if self.stages.len() > STAGE_ORDER_V3.len() {
            return Err(CompositionErrorV3::InvalidPipelineReceipt("stage count"));
        }

        let mut predecessor = self.request_digest;
        for (index, trace) in self.stages.iter().enumerate() {
            if trace.stage != STAGE_ORDER_V3[index] {
                return Err(CompositionErrorV3::InvalidPipelineReceipt("stage order"));
            }
            if trace.predecessor_digest != predecessor {
                return Err(CompositionErrorV3::PredecessorMismatch);
            }
            if trace.output_digest.is_zero() || trace.evidence_digest.is_zero() {
                return Err(CompositionErrorV3::InvalidPipelineReceipt(
                    "empty stage digest",
                ));
            }
            let producer = match trace.outcome {
                CompositionStageOutcomeV3::Completed
                | CompositionStageOutcomeV3::Abstained
                | CompositionStageOutcomeV3::SlowPath => producer_for_stage(trace.stage),
                CompositionStageOutcomeV3::FallbackUsed(_)
                | CompositionStageOutcomeV3::Failed(_) => INTELLIGENCE_CONTROL,
            };
            if trace.producer.as_str() != producer {
                return Err(CompositionErrorV3::ProducerMismatch);
            }
            if matches!(trace.outcome, CompositionStageOutcomeV3::FallbackUsed(_))
                && !is_optional_stage(trace.stage)
            {
                return Err(CompositionErrorV3::InvalidPipelineReceipt(
                    "required stage fallback",
                ));
            }
            if matches!(
                trace.outcome,
                CompositionStageOutcomeV3::Abstained | CompositionStageOutcomeV3::SlowPath
            ) && trace.stage != CompositionStageV3::IntuitionDecided
            {
                return Err(CompositionErrorV3::UnexpectedDecision);
            }
            predecessor = trace.output_digest;
        }

        let last = self.stages.last();
        match self.disposition {
            CompositionDispositionV3::HostEnvelopePrepared => {
                if self.stages.len() != STAGE_ORDER_V3.len()
                    || last.map(|value| value.stage) != Some(CompositionStageV3::ContextCompiled)
                    || !matches!(
                        last.map(|value| value.outcome),
                        Some(CompositionStageOutcomeV3::Completed)
                    )
                {
                    return Err(CompositionErrorV3::InvalidPipelineReceipt(
                        "prepared disposition",
                    ));
                }
                let envelope = self
                    .envelope
                    .as_ref()
                    .ok_or(CompositionErrorV3::InvalidPipelineReceipt("missing envelope"))?;
                envelope.validate()?;
                if envelope.run_id != self.run_id
                    || envelope.request_digest != self.request_digest
                    || envelope.snapshot_digest != self.snapshot_digest
                    || envelope.composition_trace_digest != self.trace_digest
                {
                    return Err(CompositionErrorV3::InvalidPipelineReceipt(
                        "envelope binding",
                    ));
                }
            }
            CompositionDispositionV3::Abstained => {
                if self.stages.len() != 7
                    || !matches!(
                        last.map(|value| value.outcome),
                        Some(CompositionStageOutcomeV3::Abstained)
                    )
                    || self.envelope.is_some()
                {
                    return Err(CompositionErrorV3::InvalidPipelineReceipt(
                        "abstain disposition",
                    ));
                }
            }
            CompositionDispositionV3::SlowPath => {
                if self.stages.len() != 7
                    || !matches!(
                        last.map(|value| value.outcome),
                        Some(CompositionStageOutcomeV3::SlowPath)
                    )
                    || self.envelope.is_some()
                {
                    return Err(CompositionErrorV3::InvalidPipelineReceipt(
                        "slow-path disposition",
                    ));
                }
            }
            CompositionDispositionV3::Failed(class) => {
                if !matches!(
                    last.map(|value| value.outcome),
                    Some(CompositionStageOutcomeV3::Failed(actual)) if actual == class
                ) || self.envelope.is_some()
                {
                    return Err(CompositionErrorV3::InvalidPipelineReceipt(
                        "failure disposition",
                    ));
                }
            }
            CompositionDispositionV3::Cancelled | CompositionDispositionV3::DeadlineExceeded => {
                if self.envelope.is_some()
                    || self.stages.iter().any(|stage| {
                        matches!(stage.outcome, CompositionStageOutcomeV3::Failed(_))
                    })
                {
                    return Err(CompositionErrorV3::InvalidPipelineReceipt(
                        "control disposition",
                    ));
                }
            }
        }

        let expected = digest_trace_v3(
            &self.run_id,
            self.request_digest,
            self.snapshot_digest,
            self.disposition,
            &self.stages,
        );
        if expected != self.trace_digest {
            return Err(CompositionErrorV3::TraceDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompositionErrorV3 {
    EmptyDigest(&'static str),
    InvalidBudget,
    InvalidDeadline,
    CandidateSet(LegalActionCandidateSetErrorV1),
    CandidateStateMismatch,
    MissingCapability(&'static str),
    OwnerMismatch(&'static str),
    InvalidPortFailure,
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    PredecessorMismatch,
    AuthorityWidening,
    UnexpectedDecision,
    ObjectiveDigestMismatch,
    InvalidPipelineReceipt(&'static str),
    TraceDigestMismatch,
    EnvelopeDigestMismatch,
}

impl fmt::Display for CompositionErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompositionErrorV3 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::CandidateSet(error) => Some(error),
            _ => None,
        }
    }
}

impl From<LegalActionCandidateSetErrorV1> for CompositionErrorV3 {
    fn from(value: LegalActionCandidateSetErrorV1) -> Self {
        Self::CandidateSet(value)
    }
}

enum AdvanceV3 {
    Continue(Digest32),
    Terminal(CompositionDispositionV3),
}

pub fn prepare_intelligence_run_v3<P, C>(
    request: CompositionRunRequestV3,
    ports: &mut P,
    control: &C,
) -> Result<CompositionPipelineReceiptV3, CompositionErrorV3>
where
    P: CompositionPortsV3,
    C: CompositionControlV3,
{
    for (field, digest) in [
        ("request", request.request_digest),
        ("body", request.body_digest),
        ("artifact set", request.artifact_set_digest),
    ] {
        if digest.is_zero() {
            return Err(CompositionErrorV3::EmptyDigest(field));
        }
    }
    if request.deadline_unix_micros == 0 {
        return Err(CompositionErrorV3::InvalidDeadline);
    }
    request.budget.validate()?;
    request.legal_candidates.validate()?;

    let snapshot_digest = request.snapshot.digest();
    if request.legal_candidates.state_digest != snapshot_digest {
        return Err(CompositionErrorV3::CandidateStateMismatch);
    }
    validate_capabilities(&request.snapshot)?;

    let mut stages = Vec::with_capacity(STAGE_ORDER_V3.len());
    let mut predecessor = request.request_digest;

    if let Some(disposition) = control_disposition(&request, control) {
        return finish_without_envelope(&request, snapshot_digest, disposition, stages);
    }

    match required_stage(
        &request,
        snapshot_digest,
        predecessor,
        CompositionStageV3::ObjectiveValidated,
        "objective.compiler",
        &mut stages,
        control,
        |input| ports.validate_objective(input),
    )? {
        AdvanceV3::Continue(output) => {
            if output != request.snapshot.objective_digest() {
                return Err(CompositionErrorV3::ObjectiveDigestMismatch);
            }
            predecessor = output;
        }
        AdvanceV3::Terminal(disposition) => {
            return finish_without_envelope(
                &request,
                snapshot_digest,
                disposition,
                stages,
            );
        }
    }

    if let Some(disposition) = control_disposition(&request, control) {
        return finish_without_envelope(&request, snapshot_digest, disposition, stages);
    }
    let legal_deadline = stage_deadline(
        control.now_unix_micros(),
        request.budget.for_stage(CompositionStageV3::LegalCandidatesBuilt),
        request.deadline_unix_micros,
    );
    if control.now_unix_micros() >= legal_deadline {
        return finish_without_envelope(
            &request,
            snapshot_digest,
            CompositionDispositionV3::DeadlineExceeded,
            stages,
        );
    }
    let legal_digest = request.legal_candidates.digest();
    stages.push(CompositionStageTraceV3 {
        stage: CompositionStageV3::LegalCandidatesBuilt,
        producer: stable_id(INTELLIGENCE_CONTROL)?,
        predecessor_digest: predecessor,
        output_digest: legal_digest,
        outcome: CompositionStageOutcomeV3::Completed,
        evidence_digest: legal_digest,
    });
    predecessor = legal_digest;

    match required_stage(
        &request,
        snapshot_digest,
        predecessor,
        CompositionStageV3::UtilityEvaluated,
        "utility.ndu",
        &mut stages,
        control,
        |input| ports.evaluate_utility(input),
    )? {
        AdvanceV3::Continue(output) => predecessor = output,
        AdvanceV3::Terminal(disposition) => {
            return finish_without_envelope(
                &request,
                snapshot_digest,
                disposition,
                stages,
            );
        }
    }

    match required_stage(
        &request,
        snapshot_digest,
        predecessor,
        CompositionStageV3::EvaluationAdmitted,
        "learning.eval",
        &mut stages,
        control,
        |input| ports.admit_evaluation(input),
    )? {
        AdvanceV3::Continue(output) => predecessor = output,
        AdvanceV3::Terminal(disposition) => {
            return finish_without_envelope(
                &request,
                snapshot_digest,
                disposition,
                stages,
            );
        }
    }

    match optional_stage(
        &request,
        snapshot_digest,
        predecessor,
        CompositionStageV3::NeuralSignalCollected,
        "neuron.runtime",
        "neural.signal",
        &mut stages,
        control,
        |input| ports.collect_neural_signal(input),
    )? {
        AdvanceV3::Continue(output) => predecessor = output,
        AdvanceV3::Terminal(disposition) => {
            return finish_without_envelope(
                &request,
                snapshot_digest,
                disposition,
                stages,
            );
        }
    }

    match optional_stage(
        &request,
        snapshot_digest,
        predecessor,
        CompositionStageV3::PromptPortfolioBuilt,
        "prompt.optimizer",
        "prompt.portfolio",
        &mut stages,
        control,
        |input| ports.build_prompt_portfolio(input),
    )? {
        AdvanceV3::Continue(output) => predecessor = output,
        AdvanceV3::Terminal(disposition) => {
            return finish_without_envelope(
                &request,
                snapshot_digest,
                disposition,
                stages,
            );
        }
    }

    let intuition_input = port_input(
        &request,
        snapshot_digest,
        predecessor,
        CompositionStageV3::IntuitionDecided,
        control.now_unix_micros(),
    );
    if let Some(disposition) = control_disposition(&request, control) {
        return finish_without_envelope(&request, snapshot_digest, disposition, stages);
    }
    let intuition = ports.decide_intuition(&intuition_input);
    if let Some(disposition) = post_call_control_disposition(&request, &intuition_input, control) {
        return finish_without_envelope(&request, snapshot_digest, disposition, stages);
    }
    let intuition = match intuition {
        Ok(receipt) => {
            validate_receipt(&intuition_input, "intuition.policy", &receipt)?;
            receipt
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let class = failure.class;
            append_failure_trace(
                &mut stages,
                CompositionStageV3::IntuitionDecided,
                predecessor,
                failure,
            )?;
            return finish_without_envelope(
                &request,
                snapshot_digest,
                CompositionDispositionV3::Failed(class),
                stages,
            );
        }
    };
    predecessor = intuition.output_digest;
    let disposition = match intuition.decision {
        CompositionPortDecisionV3::Continue => CompositionDispositionV3::HostEnvelopePrepared,
        CompositionPortDecisionV3::Abstain => CompositionDispositionV3::Abstained,
        CompositionPortDecisionV3::SlowPath => CompositionDispositionV3::SlowPath,
    };
    stages.push(CompositionStageTraceV3 {
        stage: CompositionStageV3::IntuitionDecided,
        producer: intuition.producer,
        predecessor_digest: intuition.predecessor_digest,
        output_digest: intuition.output_digest,
        outcome: match intuition.decision {
            CompositionPortDecisionV3::Continue => CompositionStageOutcomeV3::Completed,
            CompositionPortDecisionV3::Abstain => CompositionStageOutcomeV3::Abstained,
            CompositionPortDecisionV3::SlowPath => CompositionStageOutcomeV3::SlowPath,
        },
        evidence_digest: intuition.evidence_digest,
    });

    if disposition != CompositionDispositionV3::HostEnvelopePrepared {
        return finish_without_envelope(&request, snapshot_digest, disposition, stages);
    }

    match required_stage(
        &request,
        snapshot_digest,
        predecessor,
        CompositionStageV3::ContextCompiled,
        "context.compiler",
        &mut stages,
        control,
        |input| ports.compile_context(input),
    )? {
        AdvanceV3::Continue(_) => {}
        AdvanceV3::Terminal(disposition) => {
            return finish_without_envelope(
                &request,
                snapshot_digest,
                disposition,
                stages,
            );
        }
    }

    finish_prepared(request, snapshot_digest, stages)
}

fn validate_capabilities(snapshot: &CapabilitySnapshotV2) -> Result<(), CompositionErrorV3> {
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("utility.evaluation", "utility.ndu"),
        ("evaluation.admission", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
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

fn required_stage<F, C>(
    request: &CompositionRunRequestV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: CompositionStageV3,
    producer: &str,
    traces: &mut Vec<CompositionStageTraceV3>,
    control: &C,
    call: F,
) -> Result<AdvanceV3, CompositionErrorV3>
where
    F: FnOnce(
        &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>,
    C: CompositionControlV3,
{
    if let Some(disposition) = control_disposition(request, control) {
        return Ok(AdvanceV3::Terminal(disposition));
    }
    let input = port_input(
        request,
        snapshot_digest,
        predecessor,
        stage,
        control.now_unix_micros(),
    );
    let result = call(&input);
    if let Some(disposition) = post_call_control_disposition(request, &input, control) {
        if disposition == CompositionDispositionV3::DeadlineExceeded
            && control.now_unix_micros() < request.deadline_unix_micros
        {
            let evidence = timeout_evidence(stage, predecessor, input.deadline_unix_micros);
            let failure = CompositionPortFailureV3 {
                class: CompositionFailureClassV3::TimedOut,
                evidence_digest: evidence,
            };
            append_failure_trace(traces, stage, predecessor, failure)?;
            return Ok(AdvanceV3::Terminal(CompositionDispositionV3::Failed(
                CompositionFailureClassV3::TimedOut,
            )));
        }
        return Ok(AdvanceV3::Terminal(disposition));
    }

    match result {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != CompositionPortDecisionV3::Continue {
                return Err(CompositionErrorV3::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            traces.push(CompositionStageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: CompositionStageOutcomeV3::Completed,
                evidence_digest: receipt.evidence_digest,
            });
            Ok(AdvanceV3::Continue(output))
        }
        Err(failure) => {
            validate_failure(&failure)?;
            let class = failure.class;
            append_failure_trace(traces, stage, predecessor, failure)?;
            Ok(AdvanceV3::Terminal(CompositionDispositionV3::Failed(
                class,
            )))
        }
    }
}

fn optional_stage<F, C>(
    request: &CompositionRunRequestV3,
    snapshot_digest: Digest32,
    predecessor: Digest32,
    stage: CompositionStageV3,
    producer: &str,
    capability: &'static str,
    traces: &mut Vec<CompositionStageTraceV3>,
    control: &C,
    call: F,
) -> Result<AdvanceV3, CompositionErrorV3>
where
    F: FnOnce(
        &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3>,
    C: CompositionControlV3,
{
    if let Some(disposition) = control_disposition(request, control) {
        return Ok(AdvanceV3::Terminal(disposition));
    }

    if request.snapshot.bound_owner(capability).is_none() {
        let evidence = absent_capability_evidence(snapshot_digest, capability);
        let output = fallback_digest(
            stage,
            predecessor,
            CompositionFailureClassV3::Unavailable,
            evidence,
        );
        traces.push(CompositionStageTraceV3 {
            stage,
            producer: stable_id(INTELLIGENCE_CONTROL)?,
            predecessor_digest: predecessor,
            output_digest: output,
            outcome: CompositionStageOutcomeV3::FallbackUsed(
                CompositionFailureClassV3::Unavailable,
            ),
            evidence_digest: evidence,
        });
        return Ok(AdvanceV3::Continue(output));
    }

    let input = port_input(
        request,
        snapshot_digest,
        predecessor,
        stage,
        control.now_unix_micros(),
    );
    let result = call(&input);
    if let Some(disposition) = post_call_control_disposition(request, &input, control) {
        if disposition == CompositionDispositionV3::DeadlineExceeded
            && control.now_unix_micros() < request.deadline_unix_micros
        {
            let evidence = timeout_evidence(stage, predecessor, input.deadline_unix_micros);
            let output = fallback_digest(
                stage,
                predecessor,
                CompositionFailureClassV3::TimedOut,
                evidence,
            );
            traces.push(CompositionStageTraceV3 {
                stage,
                producer: stable_id(INTELLIGENCE_CONTROL)?,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: CompositionStageOutcomeV3::FallbackUsed(
                    CompositionFailureClassV3::TimedOut,
                ),
                evidence_digest: evidence,
            });
            return Ok(AdvanceV3::Continue(output));
        }
        return Ok(AdvanceV3::Terminal(disposition));
    }

    match result {
        Ok(receipt) => {
            validate_receipt(&input, producer, &receipt)?;
            if receipt.decision != CompositionPortDecisionV3::Continue {
                return Err(CompositionErrorV3::UnexpectedDecision);
            }
            let output = receipt.output_digest;
            traces.push(CompositionStageTraceV3 {
                stage,
                producer: receipt.producer,
                predecessor_digest: predecessor,
                output_digest: output,
                outcome: CompositionStageOutcomeV3::Completed,
                evidence_digest: receipt.evidence_digest,
            });
            Ok(AdvanceV3::Continue(output))
        }
        Err(failure) => {
            validate_failure(&failure)?;
            if matches!(
                failure.class,
                CompositionFailureClassV3::Unavailable | CompositionFailureClassV3::TimedOut
            ) {
                let output =
                    fallback_digest(stage, predecessor, failure.class, failure.evidence_digest);
                traces.push(CompositionStageTraceV3 {
                    stage,
                    producer: stable_id(INTELLIGENCE_CONTROL)?,
                    predecessor_digest: predecessor,
                    output_digest: output,
                    outcome: CompositionStageOutcomeV3::FallbackUsed(failure.class),
                    evidence_digest: failure.evidence_digest,
                });
                Ok(AdvanceV3::Continue(output))
            } else {
                let class = failure.class;
                append_failure_trace(traces, stage, predecessor, failure)?;
                Ok(AdvanceV3::Terminal(CompositionDispositionV3::Failed(
                    class,
                )))
            }
        }
    }
}

fn append_failure_trace(
    traces: &mut Vec<CompositionStageTraceV3>,
    stage: CompositionStageV3,
    predecessor: Digest32,
    failure: CompositionPortFailureV3,
) -> Result<(), CompositionErrorV3> {
    let output = fallback_digest(stage, predecessor, failure.class, failure.evidence_digest);
    traces.push(CompositionStageTraceV3 {
        stage,
        producer: stable_id(INTELLIGENCE_CONTROL)?,
        predecessor_digest: predecessor,
        output_digest: output,
        outcome: CompositionStageOutcomeV3::Failed(failure.class),
        evidence_digest: failure.evidence_digest,
    });
    Ok(())
}

fn port_input(
    request: &CompositionRunRequestV3,
    snapshot_digest: Digest32,
    predecessor_digest: Digest32,
    stage: CompositionStageV3,
    now_unix_micros: u64,
) -> CompositionPortInputV3 {
    CompositionPortInputV3 {
        run_id: request.run_id.clone(),
        snapshot_digest,
        predecessor_digest,
        stage,
        budget_micros: request.budget.for_stage(stage),
        deadline_unix_micros: stage_deadline(
            now_unix_micros,
            request.budget.for_stage(stage),
            request.deadline_unix_micros,
        ),
    }
}

fn validate_receipt(
    input: &CompositionPortInputV3,
    producer: &str,
    receipt: &CompositionPortReceiptV3,
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
    if receipt.predecessor_digest != input.predecessor_digest {
        return Err(CompositionErrorV3::PredecessorMismatch);
    }
    if receipt.output_digest.is_zero() {
        return Err(CompositionErrorV3::EmptyDigest("port output"));
    }
    if receipt.evidence_digest.is_zero() {
        return Err(CompositionErrorV3::EmptyDigest("port evidence"));
    }
    if receipt.authority.grants_any() {
        return Err(CompositionErrorV3::AuthorityWidening);
    }
    Ok(())
}

fn validate_failure(failure: &CompositionPortFailureV3) -> Result<(), CompositionErrorV3> {
    if failure.evidence_digest.is_zero() {
        return Err(CompositionErrorV3::InvalidPortFailure);
    }
    Ok(())
}

fn control_disposition<C: CompositionControlV3>(
    request: &CompositionRunRequestV3,
    control: &C,
) -> Option<CompositionDispositionV3> {
    if control.is_cancelled(&request.run_id) {
        Some(CompositionDispositionV3::Cancelled)
    } else if control.now_unix_micros() >= request.deadline_unix_micros {
        Some(CompositionDispositionV3::DeadlineExceeded)
    } else {
        None
    }
}

fn post_call_control_disposition<C: CompositionControlV3>(
    request: &CompositionRunRequestV3,
    input: &CompositionPortInputV3,
    control: &C,
) -> Option<CompositionDispositionV3> {
    if control.is_cancelled(&request.run_id) {
        return Some(CompositionDispositionV3::Cancelled);
    }
    let now = control.now_unix_micros();
    if now >= request.deadline_unix_micros || now >= input.deadline_unix_micros {
        Some(CompositionDispositionV3::DeadlineExceeded)
    } else {
        None
    }
}

const fn stage_deadline(start: u64, budget: u64, run_deadline: u64) -> u64 {
    let stage = start.saturating_add(budget);
    if stage < run_deadline {
        stage
    } else {
        run_deadline
    }
}

fn finish_without_envelope(
    request: &CompositionRunRequestV3,
    snapshot_digest: Digest32,
    disposition: CompositionDispositionV3,
    stages: Vec<CompositionStageTraceV3>,
) -> Result<CompositionPipelineReceiptV3, CompositionErrorV3> {
    let trace_digest = digest_trace_v3(
        &request.run_id,
        request.request_digest,
        snapshot_digest,
        disposition,
        &stages,
    );
    let receipt = CompositionPipelineReceiptV3 {
        run_id: request.run_id.clone(),
        request_digest: request.request_digest,
        snapshot_digest,
        disposition,
        stages,
        trace_digest,
        envelope: None,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn finish_prepared(
    request: CompositionRunRequestV3,
    snapshot_digest: Digest32,
    stages: Vec<CompositionStageTraceV3>,
) -> Result<CompositionPipelineReceiptV3, CompositionErrorV3> {
    let disposition = CompositionDispositionV3::HostEnvelopePrepared;
    let trace_digest = digest_trace_v3(
        &request.run_id,
        request.request_digest,
        snapshot_digest,
        disposition,
        &stages,
    );

    let utility = trace_for(&stages, CompositionStageV3::UtilityEvaluated)?;
    let evaluation = trace_for(&stages, CompositionStageV3::EvaluationAdmitted)?;
    let neural = trace_for(&stages, CompositionStageV3::NeuralSignalCollected)?;
    let prompt = trace_for(&stages, CompositionStageV3::PromptPortfolioBuilt)?;
    let intuition = trace_for(&stages, CompositionStageV3::IntuitionDecided)?;
    let context = trace_for(&stages, CompositionStageV3::ContextCompiled)?;

    let mut envelope = IntelligenceHostEnvelopeV1 {
        run_id: request.run_id.clone(),
        request_digest: request.request_digest,
        snapshot_digest,
        objective_digest: request.snapshot.objective_digest(),
        authority_epoch: request.snapshot.authority_epoch(),
        body_digest: request.body_digest,
        artifact_set_digest: request.artifact_set_digest,
        candidate_set_digest: request.legal_candidates.digest(),
        utility_digest: utility.output_digest,
        utility_receipt_digest: utility.evidence_digest,
        evaluation_digest: evaluation.output_digest,
        evaluation_receipt_digest: evaluation.evidence_digest,
        neural_signal_digest: if matches!(
            neural.outcome,
            CompositionStageOutcomeV3::Completed
        ) {
            Some(neural.output_digest)
        } else {
            None
        },
        prompt_portfolio_digest: if matches!(
            prompt.outcome,
            CompositionStageOutcomeV3::Completed
        ) {
            Some(prompt.output_digest)
        } else {
            None
        },
        intuition_digest: intuition.output_digest,
        intuition_receipt_digest: intuition.evidence_digest,
        context_digest: context.output_digest,
        context_receipt_digest: context.evidence_digest,
        composition_trace_digest: trace_digest,
        deadline_unix_micros: request.deadline_unix_micros,
        envelope_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    envelope.envelope_digest = envelope.canonical_digest();
    envelope.validate()?;

    let receipt = CompositionPipelineReceiptV3 {
        run_id: request.run_id,
        request_digest: request.request_digest,
        snapshot_digest,
        disposition,
        stages,
        trace_digest,
        envelope: Some(envelope),
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn trace_for(
    stages: &[CompositionStageTraceV3],
    stage: CompositionStageV3,
) -> Result<&CompositionStageTraceV3, CompositionErrorV3> {
    stages
        .iter()
        .find(|value| value.stage == stage)
        .ok_or(CompositionErrorV3::InvalidPipelineReceipt(
            "missing required trace",
        ))
}

fn producer_for_stage(stage: CompositionStageV3) -> &'static str {
    match stage {
        CompositionStageV3::ObjectiveValidated => "objective.compiler",
        CompositionStageV3::LegalCandidatesBuilt => INTELLIGENCE_CONTROL,
        CompositionStageV3::UtilityEvaluated => "utility.ndu",
        CompositionStageV3::EvaluationAdmitted => "learning.eval",
        CompositionStageV3::NeuralSignalCollected => "neuron.runtime",
        CompositionStageV3::PromptPortfolioBuilt => "prompt.optimizer",
        CompositionStageV3::IntuitionDecided => "intuition.policy",
        CompositionStageV3::ContextCompiled => "context.compiler",
    }
}

const fn is_optional_stage(stage: CompositionStageV3) -> bool {
    matches!(
        stage,
        CompositionStageV3::NeuralSignalCollected | CompositionStageV3::PromptPortfolioBuilt
    )
}

fn absent_capability_evidence(snapshot: Digest32, capability: &str) -> Digest32 {
    let mut bytes = b"hepta.intelligence.absent-capability.v3\0".to_vec();
    bytes.extend_from_slice(snapshot.as_array());
    bytes.extend_from_slice(capability.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn timeout_evidence(
    stage: CompositionStageV3,
    predecessor: Digest32,
    deadline_unix_micros: u64,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.stage-timeout.v3\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&deadline_unix_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn fallback_digest(
    stage: CompositionStageV3,
    predecessor: Digest32,
    class: CompositionFailureClassV3,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.composition-fallback.v3\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(failure_code(class));
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_trace_v3(
    run_id: &StableId,
    request_digest: Digest32,
    snapshot_digest: Digest32,
    disposition: CompositionDispositionV3,
    stages: &[CompositionStageTraceV3],
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.composition-trace.v3\0".to_vec();
    push_id(&mut bytes, run_id);
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.push(disposition_code(disposition));
    bytes.extend_from_slice(
        &u32::try_from(stages.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for trace in stages {
        bytes.push(stage_code(trace.stage));
        push_id(&mut bytes, &trace.producer);
        bytes.extend_from_slice(trace.predecessor_digest.as_array());
        bytes.extend_from_slice(trace.output_digest.as_array());
        bytes.push(outcome_code(trace.outcome));
        bytes.extend_from_slice(trace.evidence_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn stable_id(value: &str) -> Result<StableId, CompositionErrorV3> {
    StableId::new(value).map_err(|_| CompositionErrorV3::InvalidPipelineReceipt("stable id"))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}

const fn stage_code(value: CompositionStageV3) -> u8 {
    match value {
        CompositionStageV3::ObjectiveValidated => 0,
        CompositionStageV3::LegalCandidatesBuilt => 1,
        CompositionStageV3::UtilityEvaluated => 2,
        CompositionStageV3::EvaluationAdmitted => 3,
        CompositionStageV3::NeuralSignalCollected => 4,
        CompositionStageV3::PromptPortfolioBuilt => 5,
        CompositionStageV3::IntuitionDecided => 6,
        CompositionStageV3::ContextCompiled => 7,
    }
}

const fn failure_code(value: CompositionFailureClassV3) -> u8 {
    match value {
        CompositionFailureClassV3::Rejected => 0,
        CompositionFailureClassV3::Unavailable => 1,
        CompositionFailureClassV3::TimedOut => 2,
        CompositionFailureClassV3::Quarantined => 3,
        CompositionFailureClassV3::Indeterminate => 4,
    }
}

const fn disposition_code(value: CompositionDispositionV3) -> u8 {
    match value {
        CompositionDispositionV3::HostEnvelopePrepared => 0,
        CompositionDispositionV3::Abstained => 1,
        CompositionDispositionV3::SlowPath => 2,
        CompositionDispositionV3::Failed(class) => 10 + failure_code(class),
        CompositionDispositionV3::Cancelled => 30,
        CompositionDispositionV3::DeadlineExceeded => 31,
    }
}

const fn outcome_code(value: CompositionStageOutcomeV3) -> u8 {
    match value {
        CompositionStageOutcomeV3::Completed => 0,
        CompositionStageOutcomeV3::FallbackUsed(class) => 10 + failure_code(class),
        CompositionStageOutcomeV3::Abstained => 1,
        CompositionStageOutcomeV3::SlowPath => 2,
        CompositionStageOutcomeV3::Failed(class) => 20 + failure_code(class),
    }
}

#[cfg(test)]
#[path = "composition_v3_tests.rs"]
mod tests;
