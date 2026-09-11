//! Authenticated evaluation consumption and durable shadow decisions.
//!
//! The host supplies the first seven F ports, trusted current keys/time, real
//! evaluation observations, authenticated calibration/OOD/completeness inputs,
//! and a valid assignment draw. This adapter owns only admission and the eighth
//! port's Decision append. It never
//! invents outcomes, trains a model, activates an artifact, or executes dispatch.

use std::error::Error;
use std::fmt;

use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::SignedEvaluationError;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibratedError;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::decide_calibrated_v2;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::LaneFRunRequestV1;
use crate::LaneFShadowPipelineReceiptV1;
use crate::LaneFShadowPortsV1;
use crate::PipelineErrorV1;
use crate::PortDecisionV1;
use crate::PortFailureClassV1;
use crate::PortFailureV1;
use crate::PortInputV1;
use crate::PortReceiptV1;
use crate::run_shadow_pipeline;

const MAX_CANDIDATE_BYTES: usize = 16 * 1024 * 1024;
const ABSTAIN: &str = "abstain";
const SLOW_PATH: &str = "shadow:slow-path";

pub struct EvaluatedShadowRequestV1<'a> {
    pub run: LaneFRunRequestV1,
    pub evaluation: IndependentEvaluationBundleV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub evaluation_evidence: &'a SignedEvaluationEvidenceV1,
    /// Exact opaque candidate bytes, not a claim that these constitute a model.
    pub candidate_bytes: &'a [u8],
    /// The same evaluator signs `evaluated_candidate_signing_payload_v1`.
    pub candidate_evidence: &'a SignedLearningEvidenceV1,
    pub dataset: &'a DatasetSnapshotReceiptV3,
    pub intuition: CalibratedDecisionRequestV1,
    pub episode_id: StableId,
    /// Retain the original predecessor for an exact retry, even after later appends.
    pub expected_ledger_head: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluatedShadowReceiptV1 {
    pub evaluation: SignedEvaluationDecisionV1,
    pub pipeline: LaneFShadowPipelineReceiptV1,
    /// Present only when the actual durable Decision append succeeded.
    pub learning: Option<AppendReceipt>,
}

#[derive(Debug)]
pub enum EvaluatedShadowError {
    Binding(&'static str),
    Ineligible(IndependentEvaluationDispositionV1),
    Evaluation(SignedEvaluationError),
    Evidence(SignedEvidenceError),
    Dataset(DatasetReceiptError),
    Intuition(CalibratedError),
    Pipeline(PipelineErrorV1),
    Ledger(DurableLedgerError),
}

impl fmt::Display for EvaluatedShadowError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for EvaluatedShadowError {}

/// Bind the evaluated candidate to exact bytes and generation, in addition to
/// E's complete signed request. Sign with the bundle evaluator's registered key.
/// Signers must inspect the actual artifact; a signature establishes attribution,
/// not artifact semantics, freshness, model quality, or host enrollment.
pub fn evaluated_candidate_signing_payload_v1(
    evaluation: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
    candidate_bytes: &[u8],
    generation: u64,
) -> Result<Vec<u8>, EvaluatedShadowError> {
    if candidate_bytes.is_empty() || candidate_bytes.len() > MAX_CANDIDATE_BYTES || generation == 0
    {
        return Err(EvaluatedShadowError::Binding("candidate bounds"));
    }
    let evaluated = evaluation_signing_payload_v2(evaluation, roles)
        .map_err(|error| EvaluatedShadowError::Evaluation(error.into()))?;
    let mut bytes = b"hepta.intelligence.evaluated-candidate.v1\0".to_vec();
    bytes.extend_from_slice(Digest32::of_bytes(&evaluated).as_array());
    bytes.extend_from_slice(Digest32::of_bytes(candidate_bytes).as_array());
    bytes.extend_from_slice(&(candidate_bytes.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&generation.to_be_bytes());
    Ok(bytes)
}

/// Authenticate before invoking any host port. Host ports must be proposal-only
/// and honor their budgets. The synchronous coordinator cannot interrupt them.
/// Dataset verification recomputes its manifest identity; the host still owns
/// raw-record provenance, frozen-plan persistence, holdout-use durability and
/// current revocation/rollback witnesses. A terminal host failure appends no Decision.
/// This single-dataset interface checks the complete snapshot-ID set. Ledger
/// sync is blocking and cannot be cancelled safely at a latency budget boundary.
pub fn run_evaluated_shadow_v1<P: LaneFShadowPortsV1>(
    request: EvaluatedShadowRequestV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    ledger: &mut DurableLedger,
    ports: &mut P,
    now: u64,
) -> Result<EvaluatedShadowReceiptV1, EvaluatedShadowError> {
    use EvaluatedShadowError as E;
    if request.run.request_digest.is_zero() {
        return Err(E::Binding("empty request"));
    }
    let snapshot_digest = request.run.snapshot.digest().map_err(E::Pipeline)?;
    verify_dataset_snapshot_receipt_v3(request.dataset, now).map_err(E::Dataset)?;
    let bundle = &request.evaluation;
    if request.dataset.snapshot.dataset_digest != bundle.dataset_digest
        || request.dataset.snapshot.objective_digest != bundle.objective_digest
        || bundle.snapshot_ids.as_slice() != [request.dataset.snapshot.snapshot_id.clone()]
    {
        return Err(E::Binding("dataset"));
    }
    let candidate_payload = evaluated_candidate_signing_payload_v1(
        bundle,
        &request.metric_roles,
        request.candidate_bytes,
        request.run.snapshot.learning_artifact_generation,
    )?;
    let candidate = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            request.candidate_evidence,
            &candidate_payload,
            now,
        )
        .map_err(E::Evidence)?;
    if candidate.principal() != &bundle.evaluator
        || request.run.snapshot.model_artifact_digest != Digest32::of_bytes(request.candidate_bytes)
        || request.intuition.objective_digest != bundle.objective_digest
        || request.intuition.state_digest != snapshot_digest
        || request.intuition.policy_digest != request.run.snapshot.model_artifact_digest
        || request.intuition.policy_generation != request.run.snapshot.learning_artifact_generation
        || request.intuition.decision_id != request.run.run_id
    {
        return Err(E::Binding("candidate or run"));
    }
    if request.intuition.completeness.omitted_count_bound != 0
        || request.intuition.candidates.len() > 126
        || request
            .intuition
            .candidates
            .iter()
            .any(|candidate| matches!(candidate.candidate_id.as_str(), ABSTAIN | SLOW_PATH))
    {
        return Err(E::Binding("reserved or excessive candidates"));
    }
    let policy_id = bundle.candidate_id.clone();
    let evaluation = decide_with_signed_evidence_v2(
        request.evaluation,
        request.metric_roles,
        request.evaluation_evidence,
        verifier,
        now,
    )
    .map_err(E::Evaluation)?;
    if evaluation.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(E::Ineligible(evaluation.decision.disposition));
    }
    let intuition = decide_calibrated_v2(request.intuition.clone()).map_err(E::Intuition)?;
    let mut admission = b"hepta.intelligence.evaluated-shadow.v1\0".to_vec();
    for digest in [
        evaluation.decision.evidence_digest,
        evaluation.authentication_digest,
        Digest32::of_bytes(&request.candidate_evidence.signing_bytes()),
        Digest32::of_bytes(&candidate_payload),
        snapshot_digest,
        request.run.request_digest,
        intuition.receipt_digest,
    ] {
        admission.extend_from_slice(digest.as_array());
    }
    let budget = request.run.budget;
    for micros in [
        budget.total_micros,
        budget.objective_micros,
        budget.legal_set_micros,
        budget.neural_micros,
        budget.prompt_micros,
        budget.intuition_micros,
        budget.context_micros,
        budget.dispatch_micros,
        budget.ledger_micros,
    ] {
        admission.extend_from_slice(&micros.to_be_bytes());
    }
    let mut run = request.run;
    run.request_digest = Digest32::of_bytes(&admission);
    let mut adapter = DurableDecisionPorts {
        host: ports,
        ledger,
        expected_head: request.expected_ledger_head,
        policy_id,
        episode_id: request.episode_id,
        request: request.intuition,
        intuition,
        admission_digest: run.request_digest,
        appended: None,
        failure: None,
    };
    let pipeline = run_shadow_pipeline(run, &mut adapter).map_err(E::Pipeline)?;
    if let Some(error) = adapter.failure {
        return Err(E::Ledger(error));
    }
    Ok(EvaluatedShadowReceiptV1 {
        evaluation,
        pipeline,
        learning: adapter.appended,
    })
}

struct DurableDecisionPorts<'a, P> {
    host: &'a mut P,
    ledger: &'a mut DurableLedger,
    expected_head: Digest32,
    policy_id: StableId,
    episode_id: StableId,
    request: CalibratedDecisionRequestV1,
    intuition: CalibratedIntuitionReceiptV1,
    admission_digest: Digest32,
    appended: Option<AppendReceipt>,
    failure: Option<DurableLedgerError>,
}

impl<P: LaneFShadowPortsV1> LaneFShadowPortsV1 for DurableDecisionPorts<'_, P> {
    fn validate_objective(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.host.validate_objective(input)
    }
    fn build_legal_set(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.host.build_legal_set(input)
    }
    fn collect_neural_signal(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.host.collect_neural_signal(input)
    }
    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.host.build_prompt_portfolio(input)
    }
    fn compile_context(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.host.compile_context(input)
    }
    fn propose_dispatch(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.host.propose_dispatch(input)
    }
    fn decide_intuition(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        let receipt = self.host.decide_intuition(input)?;
        let decision = match self.intuition.disposition {
            CalibratedDispositionV1::Selected(_) => PortDecisionV1::Continue,
            CalibratedDispositionV1::Abstained(_) => PortDecisionV1::Abstain,
            CalibratedDispositionV1::SlowPath(_) => PortDecisionV1::SlowPath,
        };
        if receipt.output_digest != self.intuition.receipt_digest || receipt.decision != decision {
            return Err(PortFailureV1 {
                class: PortFailureClassV1::Rejected,
                evidence_digest: self.intuition.receipt_digest,
            });
        }
        Ok(receipt)
    }
    fn record_learning(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        let identifier = |value| {
            StableId::new(value).map_err(|_| PortFailureV1 {
                class: PortFailureClassV1::Rejected,
                evidence_digest: self.admission_digest,
            })
        };
        let abstain = identifier(ABSTAIN)?;
        let slow_path = identifier(SLOW_PATH)?;
        let producer = identifier("learning.ledger")?;
        let (selected, propensity) = match &self.intuition.disposition {
            CalibratedDispositionV1::Selected(candidate) => (
                candidate.clone(),
                self.intuition
                    .propensities
                    .iter()
                    .find(|row| &row.candidate_id == candidate)
                    .map(|row| row.probability),
            ),
            CalibratedDispositionV1::Abstained(_) => {
                (abstain.clone(), Some(self.intuition.abstain_probability))
            }
            CalibratedDispositionV1::SlowPath(_) => (
                slow_path.clone(),
                Some(self.intuition.slow_path_probability),
            ),
        };
        let Some(propensity) = propensity.filter(|value| value.raw() > 0) else {
            return Err(PortFailureV1 {
                class: PortFailureClassV1::Rejected,
                evidence_digest: self.intuition.receipt_digest,
            });
        };
        let mut candidates: Vec<_> = self
            .request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect();
        candidates.push(abstain);
        candidates.push(slow_path);
        let mut support = b"hepta.intelligence.durable-shadow-decision.v1\0".to_vec();
        support.extend_from_slice(self.admission_digest.as_array());
        support.extend_from_slice(input.predecessor_digest.as_array());
        let event = LedgerEvent::Decision(EpisodeDecision {
            record_id: input.run_id.clone(),
            episode_id: self.episode_id.clone(),
            objective_digest: self.request.objective_digest,
            policy_id: self.policy_id.clone(),
            candidate_ids: candidates,
            selected_candidate_id: selected,
            selected_propensity: propensity,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: Digest32::of_bytes(&support),
        });
        match self.ledger.append(self.expected_head, event) {
            Ok(receipt) => {
                let output_digest = receipt.chain_digest;
                self.appended = Some(receipt);
                Ok(PortReceiptV1 {
                    stage: input.stage,
                    producer,
                    snapshot_digest: input.snapshot_digest,
                    predecessor_digest: input.predecessor_digest,
                    output_digest,
                    decision: PortDecisionV1::Continue,
                    authority: AuthorityPosture::DENY_ALL,
                })
            }
            Err(error) => {
                self.failure = Some(error);
                Err(PortFailureV1 {
                    class: PortFailureClassV1::Indeterminate,
                    evidence_digest: Digest32::of_bytes(&support),
                })
            }
        }
    }
}

#[cfg(test)]
#[path = "evaluated_shadow_tests.rs"]
mod tests;
