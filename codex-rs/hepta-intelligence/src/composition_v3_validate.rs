use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompositionDispositionV3;
use crate::CompositionErrorV3;
use crate::LaneFCompositionReceiptV3;
use crate::LaneFStageV3;
use crate::PortFailureClassV1;
use crate::StageOutcomeV3;
use crate::StageTraceV3;

impl LaneFCompositionReceiptV3 {
    pub fn validate(&self) -> Result<(), CompositionErrorV3> {
        if self.request_digest.is_zero()
            || self.snapshot_digest.is_zero()
            || self.objective_digest.is_zero()
            || self.candidate_set_digest.is_zero()
            || self.trace_digest.is_zero()
            || self.authority.grants_any()
            || self.stages.is_empty()
            || self.stages.len() > 11
        {
            return Err(CompositionErrorV3::InvalidReceipt("identity or stage count"));
        }
        let mut expected = Some(LaneFStageV3::ObjectiveValidated);
        let mut predecessor = self.request_digest;
        let mut host_index = None;
        let mut utility = None;
        let mut evaluation = None;
        let mut intuition = None;
        let mut context = None;
        for (index, trace) in self.stages.iter().enumerate() {
            if Some(trace.stage) != expected {
                return Err(CompositionErrorV3::InvalidReceipt("stage order"));
            }
            validate_trace_identity(trace, predecessor)?;
            if trace.producer.as_str() != producer_for_stage(trace.stage) {
                return Err(CompositionErrorV3::ProducerMismatch);
            }
            match trace.stage {
                LaneFStageV3::UtilityEvaluated => utility = Some(trace.output_digest),
                LaneFStageV3::EvaluationAdmitted => evaluation = Some(trace.output_digest),
                LaneFStageV3::IntuitionDecided => intuition = Some(trace.output_digest),
                LaneFStageV3::ContextCompiled => context = Some(trace.output_digest),
                LaneFStageV3::HostEnvelopePrepared => host_index = Some(index),
                LaneFStageV3::ObjectiveValidated
                | LaneFStageV3::LegalSetBuilt
                | LaneFStageV3::NeuralSignalCollected
                | LaneFStageV3::PromptPortfolioBuilt
                | LaneFStageV3::DispatchProposed
                | LaneFStageV3::LearningRecorded => {}
            }
            expected = next_stage(trace, index + 1 == self.stages.len(), self.disposition)?;
            predecessor = trace.output_digest;
        }
        if expected.is_some() {
            return Err(CompositionErrorV3::InvalidReceipt("truncated trace"));
        }
        validate_terminal_shape(self)?;
        validate_envelope(
            self,
            host_index,
            utility,
            evaluation,
            intuition,
            context,
        )?;
        let expected_digest = digest_trace_v3(
            &self.run_id,
            self.request_digest,
            self.snapshot_digest,
            self.objective_digest,
            self.candidate_set_digest,
            self.disposition,
            &self.stages,
            predecessor,
        );
        if expected_digest != self.trace_digest {
            return Err(CompositionErrorV3::TraceDigestMismatch);
        }
        Ok(())
    }
}

fn validate_trace_identity(
    trace: &StageTraceV3,
    predecessor: Digest32,
) -> Result<(), CompositionErrorV3> {
    if trace.predecessor_digest != predecessor {
        return Err(CompositionErrorV3::PredecessorMismatch);
    }
    if trace.output_digest.is_zero() || trace.evidence_digest.is_zero() {
        return Err(CompositionErrorV3::InvalidReceipt("empty stage digest"));
    }
    if matches!(trace.outcome, StageOutcomeV3::FallbackUsed(_))
        && !matches!(
            trace.stage,
            LaneFStageV3::NeuralSignalCollected | LaneFStageV3::PromptPortfolioBuilt
        )
    {
        return Err(CompositionErrorV3::InvalidReceipt("invalid fallback"));
    }
    Ok(())
}

fn next_stage(
    trace: &StageTraceV3,
    is_last: bool,
    disposition: CompositionDispositionV3,
) -> Result<Option<LaneFStageV3>, CompositionErrorV3> {
    match trace.outcome {
        StageOutcomeV3::Failed(class) => {
            if !is_last || disposition != CompositionDispositionV3::Failed(class) {
                return Err(CompositionErrorV3::InvalidReceipt("failure disposition"));
            }
            Ok(None)
        }
        StageOutcomeV3::Cancelled => {
            if !is_last || disposition != CompositionDispositionV3::Cancelled {
                return Err(CompositionErrorV3::InvalidReceipt("cancel disposition"));
            }
            Ok(None)
        }
        StageOutcomeV3::Abstained | StageOutcomeV3::SlowPath => {
            if trace.stage != LaneFStageV3::IntuitionDecided {
                return Err(CompositionErrorV3::UnexpectedDecision);
            }
            Ok(Some(LaneFStageV3::LearningRecorded))
        }
        StageOutcomeV3::Completed | StageOutcomeV3::FallbackUsed(_) => Ok(match trace.stage {
            LaneFStageV3::ObjectiveValidated => Some(LaneFStageV3::LegalSetBuilt),
            LaneFStageV3::LegalSetBuilt => Some(LaneFStageV3::UtilityEvaluated),
            LaneFStageV3::UtilityEvaluated => Some(LaneFStageV3::EvaluationAdmitted),
            LaneFStageV3::EvaluationAdmitted => Some(LaneFStageV3::NeuralSignalCollected),
            LaneFStageV3::NeuralSignalCollected => Some(LaneFStageV3::PromptPortfolioBuilt),
            LaneFStageV3::PromptPortfolioBuilt => Some(LaneFStageV3::IntuitionDecided),
            LaneFStageV3::IntuitionDecided => Some(LaneFStageV3::ContextCompiled),
            LaneFStageV3::ContextCompiled => Some(LaneFStageV3::HostEnvelopePrepared),
            LaneFStageV3::HostEnvelopePrepared => Some(LaneFStageV3::DispatchProposed),
            LaneFStageV3::DispatchProposed => Some(LaneFStageV3::LearningRecorded),
            LaneFStageV3::LearningRecorded => None,
        }),
    }
}

fn validate_terminal_shape(receipt: &LaneFCompositionReceiptV3) -> Result<(), CompositionErrorV3> {
    let saw_context = receipt
        .stages
        .iter()
        .any(|trace| trace.stage == LaneFStageV3::ContextCompiled);
    let saw_dispatch = receipt
        .stages
        .iter()
        .any(|trace| trace.stage == LaneFStageV3::DispatchProposed);
    match receipt.disposition {
        CompositionDispositionV3::DispatchProposed if !saw_context || !saw_dispatch => {
            Err(CompositionErrorV3::InvalidReceipt("dispatch shape"))
        }
        CompositionDispositionV3::Abstained | CompositionDispositionV3::SlowPath
            if saw_context || saw_dispatch =>
        {
            Err(CompositionErrorV3::InvalidReceipt("advisory shape"))
        }
        CompositionDispositionV3::DispatchProposed
        | CompositionDispositionV3::Abstained
        | CompositionDispositionV3::SlowPath => {
            if receipt.stages.last().map(|trace| trace.stage)
                != Some(LaneFStageV3::LearningRecorded)
            {
                return Err(CompositionErrorV3::InvalidReceipt("learning terminal"));
            }
            Ok(())
        }
        CompositionDispositionV3::Failed(_) | CompositionDispositionV3::Cancelled => Ok(()),
    }
}

fn validate_envelope(
    receipt: &LaneFCompositionReceiptV3,
    host_index: Option<usize>,
    utility: Option<Digest32>,
    evaluation: Option<Digest32>,
    intuition: Option<Digest32>,
    context: Option<Digest32>,
) -> Result<(), CompositionErrorV3> {
    let Some(index) = host_index else {
        if receipt.host_envelope.is_some() {
            return Err(CompositionErrorV3::InvalidReceipt("unexpected host envelope"));
        }
        return Ok(());
    };
    let envelope = receipt
        .host_envelope
        .as_ref()
        .ok_or(CompositionErrorV3::InvalidReceipt("missing host envelope"))?;
    envelope.validate().map_err(CompositionErrorV3::Contract)?;
    let trace = &receipt.stages[index];
    if trace.output_digest != envelope.envelope_digest
        || envelope.run_id != receipt.run_id
        || envelope.request_digest != receipt.request_digest
        || envelope.snapshot_digest != receipt.snapshot_digest
        || envelope.objective_digest != receipt.objective_digest
        || envelope.legal_candidate_set_digest != receipt.candidate_set_digest
        || Some(envelope.utility_digest) != utility
        || Some(envelope.evaluation_digest) != evaluation
        || Some(envelope.intuition_digest) != intuition
        || Some(envelope.context_digest) != context
        || envelope.composition_trace_digest
            != digest_trace_prefix_v3(
                &receipt.run_id,
                receipt.request_digest,
                receipt.snapshot_digest,
                receipt.objective_digest,
                receipt.candidate_set_digest,
                &receipt.stages[..index],
            )
    {
        return Err(CompositionErrorV3::InvalidReceipt("host envelope binding"));
    }
    Ok(())
}

pub(super) fn producer_for_stage(stage: LaneFStageV3) -> &'static str {
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

pub(super) fn digest_trace_prefix_v3(
    run_id: &StableId,
    request_digest: Digest32,
    snapshot_digest: Digest32,
    objective_digest: Digest32,
    candidate_set_digest: Digest32,
    stages: &[StageTraceV3],
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.trace-prefix\0".to_vec();
    crate::push_id(&mut bytes, run_id);
    for digest in [
        request_digest,
        snapshot_digest,
        objective_digest,
        candidate_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for trace in stages {
        bytes.push(stage_code_v3(trace.stage));
        bytes.extend_from_slice(trace.output_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_trace_v3(
    run_id: &StableId,
    request_digest: Digest32,
    snapshot_digest: Digest32,
    objective_digest: Digest32,
    candidate_set_digest: Digest32,
    disposition: CompositionDispositionV3,
    stages: &[StageTraceV3],
    terminal: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.trace\0".to_vec();
    crate::push_id(&mut bytes, run_id);
    for digest in [
        request_digest,
        snapshot_digest,
        objective_digest,
        candidate_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
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
    stage as u8
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
