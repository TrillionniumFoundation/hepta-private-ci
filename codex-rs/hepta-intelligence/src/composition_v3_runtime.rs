use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompositionCancellationV3;
use crate::CompositionClockV3;
use crate::CompositionDispositionV3;
use crate::CompositionErrorV3;
use crate::IntelligenceHostEnvelopeInputV1;
use crate::IntelligenceHostEnvelopeV1;
use crate::LaneFCompositionPortsV3;
use crate::LaneFCompositionReceiptV3;
use crate::LaneFCompositionRequestV3;
use crate::LaneFStageV3;
use crate::PortDecisionV1;
use crate::PortFailureClassV1;
use crate::PortFailureV3;
use crate::PortInputV3;
use crate::PortReceiptV3;
use crate::StageOutcomeV3;
use crate::StageTraceV3;
use crate::composition_v3::digest_trace_prefix_v3;
use crate::composition_v3::digest_trace_v3;
use crate::composition_v3::producer_for_stage;

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
    validate_capabilities(&request)?;
    let started = clock.now_micros();
    let total_deadline = started
        .checked_add(request.budget.total_micros)
        .ok_or(CompositionErrorV3::Arithmetic)?;
    let mut runner = Runner {
        objective_digest: request.snapshot.objective_digest(),
        snapshot_digest,
        candidate_set_digest: request.legal_candidates.digest(),
        request,
        total_deadline,
        clock,
        cancellation,
        predecessor: Digest32::ZERO,
        stages: Vec::with_capacity(11),
        host_envelope: None,
    };
    runner.predecessor = runner.request.request_digest;

    let _objective = match runner.required(LaneFStageV3::ObjectiveValidated, |input| {
        ports.validate_objective(input)
    })? {
        Step::Continue(receipt) => receipt,
        Step::Terminal(receipt) => return Ok(receipt),
    };
    if let Some(receipt) = runner.internal(
        LaneFStageV3::LegalSetBuilt,
        runner.candidate_set_digest,
    )? {
        return Ok(receipt);
    }
    let utility = match runner.required(LaneFStageV3::UtilityEvaluated, |input| {
        ports.evaluate_utility(input)
    })? {
        Step::Continue(receipt) => receipt,
        Step::Terminal(receipt) => return Ok(receipt),
    };
    let evaluation = match runner.required(LaneFStageV3::EvaluationAdmitted, |input| {
        ports.admit_evaluation(input)
    })? {
        Step::Continue(receipt) => receipt,
        Step::Terminal(receipt) => return Ok(receipt),
    };
    if let Some(receipt) = runner.optional(
        LaneFStageV3::NeuralSignalCollected,
        "neural.signal",
        |input| ports.collect_neural_signal(input),
    )? {
        return Ok(receipt);
    }
    if let Some(receipt) = runner.optional(
        LaneFStageV3::PromptPortfolioBuilt,
        "prompt.portfolio",
        |input| ports.build_prompt_portfolio(input),
    )? {
        return Ok(receipt);
    }
    let intuition = match runner.advisory(|input| ports.decide_intuition(input))? {
        Step::Continue(receipt) => receipt,
        Step::Terminal(receipt) => return Ok(receipt),
    };
    let disposition = match intuition.decision {
        PortDecisionV1::Continue => CompositionDispositionV3::DispatchProposed,
        PortDecisionV1::Abstain => CompositionDispositionV3::Abstained,
        PortDecisionV1::SlowPath => CompositionDispositionV3::SlowPath,
    };

    if intuition.decision == PortDecisionV1::Continue {
        let context = match runner.required(LaneFStageV3::ContextCompiled, |input| {
            ports.compile_context(input)
        })? {
            Step::Continue(receipt) => receipt,
            Step::Terminal(receipt) => return Ok(receipt),
        };
        let trace_prefix = digest_trace_prefix_v3(
            &runner.request.run_id,
            runner.request.request_digest,
            runner.snapshot_digest,
            runner.objective_digest,
            runner.candidate_set_digest,
            &runner.stages,
        );
        let envelope = IntelligenceHostEnvelopeV1::new(IntelligenceHostEnvelopeInputV1 {
            run_id: runner.request.run_id.clone(),
            request_digest: runner.request.request_digest,
            snapshot_digest: runner.snapshot_digest,
            objective_digest: runner.objective_digest,
            legal_candidate_set_digest: runner.candidate_set_digest,
            utility_digest: utility.output_digest,
            evaluation_digest: evaluation.output_digest,
            intuition_digest: intuition.output_digest,
            context_digest: context.output_digest,
            composition_trace_digest: trace_prefix,
        })
        .map_err(CompositionErrorV3::Contract)?;
        let envelope_digest = envelope.envelope_digest;
        runner.host_envelope = Some(envelope);
        if let Some(receipt) = runner.internal(LaneFStageV3::HostEnvelopePrepared, envelope_digest)? {
            return Ok(receipt);
        }
        if let Step::Terminal(receipt) = runner.required(LaneFStageV3::DispatchProposed, |input| {
            ports.propose_dispatch(input)
        })? {
            return Ok(receipt);
        }
    }

    if let Step::Terminal(receipt) = runner.required(LaneFStageV3::LearningRecorded, |input| {
        ports.record_learning(input)
    })? {
        return Ok(receipt);
    }
    runner.finish(disposition)
}

struct Runner<'a, C, X> {
    request: LaneFCompositionRequestV3,
    objective_digest: Digest32,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    total_deadline: u64,
    clock: &'a mut C,
    cancellation: &'a X,
    predecessor: Digest32,
    stages: Vec<StageTraceV3>,
    host_envelope: Option<IntelligenceHostEnvelopeV1>,
}

enum Step {
    Continue(PortReceiptV3),
    Terminal(LaneFCompositionReceiptV3),
}

enum PortCall {
    Success(PortReceiptV3),
    Failure(PortFailureV3),
    Cancelled(Digest32),
    TotalTimedOut(Digest32),
}

impl<C: CompositionClockV3, X: CompositionCancellationV3> Runner<'_, C, X> {
    fn required<F>(&mut self, stage: LaneFStageV3, call: F) -> Result<Step, CompositionErrorV3>
    where
        F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
    {
        match self.call_port(stage, call)? {
            PortCall::Success(receipt) => {
                if receipt.decision != PortDecisionV1::Continue {
                    return Err(CompositionErrorV3::UnexpectedDecision);
                }
                self.push_success(&receipt, StageOutcomeV3::Completed);
                Ok(Step::Continue(receipt))
            }
            PortCall::Failure(failure) => self.failed(stage, failure),
            PortCall::Cancelled(evidence) => self.cancelled(stage, evidence),
            PortCall::TotalTimedOut(evidence) => self.failed(
                stage,
                PortFailureV3 {
                    class: PortFailureClassV1::TimedOut,
                    evidence_digest: evidence,
                },
            ),
        }
    }

    fn optional<F>(
        &mut self,
        stage: LaneFStageV3,
        capability: &str,
        call: F,
    ) -> Result<Option<LaneFCompositionReceiptV3>, CompositionErrorV3>
    where
        F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
    {
        if self.request.snapshot.bound_owner(capability).is_none() {
            self.push_fallback(
                stage,
                PortFailureClassV1::Unavailable,
                absent_capability_digest(self.snapshot_digest, capability),
            )?;
            return Ok(None);
        }
        match self.call_port(stage, call)? {
            PortCall::Success(receipt) => {
                if receipt.decision != PortDecisionV1::Continue {
                    return Err(CompositionErrorV3::UnexpectedDecision);
                }
                self.push_success(&receipt, StageOutcomeV3::Completed);
                Ok(None)
            }
            PortCall::Failure(failure) => {
                self.push_fallback(stage, failure.class, failure.evidence_digest)?;
                Ok(None)
            }
            PortCall::Cancelled(evidence) => match self.cancelled(stage, evidence)? {
                Step::Terminal(receipt) => Ok(Some(receipt)),
                Step::Continue(_) => Err(CompositionErrorV3::InvalidReceipt("cancel continue")),
            },
            PortCall::TotalTimedOut(evidence) => match self.failed(
                stage,
                PortFailureV3 {
                    class: PortFailureClassV1::TimedOut,
                    evidence_digest: evidence,
                },
            )? {
                Step::Terminal(receipt) => Ok(Some(receipt)),
                Step::Continue(_) => Err(CompositionErrorV3::InvalidReceipt("timeout continue")),
            },
        }
    }

    fn advisory<F>(&mut self, call: F) -> Result<Step, CompositionErrorV3>
    where
        F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
    {
        let stage = LaneFStageV3::IntuitionDecided;
        match self.call_port(stage, call)? {
            PortCall::Success(receipt) => {
                let outcome = match receipt.decision {
                    PortDecisionV1::Continue => StageOutcomeV3::Completed,
                    PortDecisionV1::Abstain => StageOutcomeV3::Abstained,
                    PortDecisionV1::SlowPath => StageOutcomeV3::SlowPath,
                };
                self.push_success(&receipt, outcome);
                Ok(Step::Continue(receipt))
            }
            PortCall::Failure(failure) => self.failed(stage, failure),
            PortCall::Cancelled(evidence) => self.cancelled(stage, evidence),
            PortCall::TotalTimedOut(evidence) => self.failed(
                stage,
                PortFailureV3 {
                    class: PortFailureClassV1::TimedOut,
                    evidence_digest: evidence,
                },
            ),
        }
    }

    fn internal(
        &mut self,
        stage: LaneFStageV3,
        output_digest: Digest32,
    ) -> Result<Option<LaneFCompositionReceiptV3>, CompositionErrorV3> {
        if output_digest.is_zero() {
            return Err(CompositionErrorV3::EmptyDigest("internal output"));
        }
        let evidence = control_evidence(self.snapshot_digest, stage, self.clock.now_micros());
        if self.cancellation.is_cancelled() {
            return match self.cancelled(stage, evidence)? {
                Step::Terminal(receipt) => Ok(Some(receipt)),
                Step::Continue(_) => Err(CompositionErrorV3::InvalidReceipt("cancel continue")),
            };
        }
        if self.clock.now_micros() >= self.total_deadline {
            return match self.failed(
                stage,
                PortFailureV3 {
                    class: PortFailureClassV1::TimedOut,
                    evidence_digest: evidence,
                },
            )? {
                Step::Terminal(receipt) => Ok(Some(receipt)),
                Step::Continue(_) => Err(CompositionErrorV3::InvalidReceipt("timeout continue")),
            };
        }
        let trace = StageTraceV3 {
            stage,
            producer: stable_id(producer_for_stage(stage))?,
            predecessor_digest: self.predecessor,
            output_digest,
            outcome: StageOutcomeV3::Completed,
            evidence_digest: output_digest,
        };
        self.predecessor = output_digest;
        self.stages.push(trace);
        Ok(None)
    }

    fn call_port<F>(&mut self, stage: LaneFStageV3, call: F) -> Result<PortCall, CompositionErrorV3>
    where
        F: FnOnce(&PortInputV3) -> Result<PortReceiptV3, PortFailureV3>,
    {
        let now = self.clock.now_micros();
        if self.cancellation.is_cancelled() {
            return Ok(PortCall::Cancelled(control_evidence(
                self.snapshot_digest,
                stage,
                now,
            )));
        }
        if now >= self.total_deadline {
            return Ok(PortCall::TotalTimedOut(control_evidence(
                self.snapshot_digest,
                stage,
                now,
            )));
        }
        let stage_deadline = now
            .checked_add(self.request.budget.for_stage(stage))
            .ok_or(CompositionErrorV3::Arithmetic)?
            .min(self.total_deadline);
        let input = PortInputV3 {
            run_id: self.request.run_id.clone(),
            snapshot_digest: self.snapshot_digest,
            candidate_set_digest: self.candidate_set_digest,
            predecessor_digest: self.predecessor,
            stage,
            budget_micros: self.request.budget.for_stage(stage),
            deadline_micros: stage_deadline,
        };
        let result = call(&input);
        let finished = self.clock.now_micros();
        if self.cancellation.is_cancelled() {
            return Ok(PortCall::Cancelled(control_evidence(
                self.snapshot_digest,
                stage,
                finished,
            )));
        }
        if finished > self.total_deadline {
            return Ok(PortCall::TotalTimedOut(control_evidence(
                self.snapshot_digest,
                stage,
                finished,
            )));
        }
        if finished > stage_deadline {
            return Ok(PortCall::Failure(PortFailureV3 {
                class: PortFailureClassV1::TimedOut,
                evidence_digest: control_evidence(self.snapshot_digest, stage, stage_deadline),
            }));
        }
        match result {
            Ok(receipt) => {
                validate_receipt(&input, &receipt)?;
                Ok(PortCall::Success(receipt))
            }
            Err(failure) => {
                if failure.evidence_digest.is_zero() {
                    return Err(CompositionErrorV3::InvalidFailure);
                }
                Ok(PortCall::Failure(failure))
            }
        }
    }

    fn push_success(&mut self, receipt: &PortReceiptV3, outcome: StageOutcomeV3) {
        self.stages.push(StageTraceV3 {
            stage: receipt.stage,
            producer: receipt.producer.clone(),
            predecessor_digest: receipt.predecessor_digest,
            output_digest: receipt.output_digest,
            outcome,
            evidence_digest: receipt.output_digest,
        });
        self.predecessor = receipt.output_digest;
    }

    fn push_fallback(
        &mut self,
        stage: LaneFStageV3,
        class: PortFailureClassV1,
        evidence_digest: Digest32,
    ) -> Result<(), CompositionErrorV3> {
        if evidence_digest.is_zero() {
            return Err(CompositionErrorV3::InvalidFailure);
        }
        let output = fallback_digest(stage, self.predecessor, class, evidence_digest);
        self.stages.push(StageTraceV3 {
            stage,
            producer: stable_id(producer_for_stage(stage))?,
            predecessor_digest: self.predecessor,
            output_digest: output,
            outcome: StageOutcomeV3::FallbackUsed(class),
            evidence_digest,
        });
        self.predecessor = output;
        Ok(())
    }

    fn failed(
        &mut self,
        stage: LaneFStageV3,
        failure: PortFailureV3,
    ) -> Result<Step, CompositionErrorV3> {
        let output = fallback_digest(
            stage,
            self.predecessor,
            failure.class,
            failure.evidence_digest,
        );
        self.stages.push(StageTraceV3 {
            stage,
            producer: stable_id(producer_for_stage(stage))?,
            predecessor_digest: self.predecessor,
            output_digest: output,
            outcome: StageOutcomeV3::Failed(failure.class),
            evidence_digest: failure.evidence_digest,
        });
        self.predecessor = output;
        Ok(Step::Terminal(
            self.build_receipt(CompositionDispositionV3::Failed(failure.class))?,
        ))
    }

    fn cancelled(&mut self, stage: LaneFStageV3, evidence: Digest32) -> Result<Step, CompositionErrorV3> {
        let output = cancellation_digest(stage, self.predecessor, evidence);
        self.stages.push(StageTraceV3 {
            stage,
            producer: stable_id(producer_for_stage(stage))?,
            predecessor_digest: self.predecessor,
            output_digest: output,
            outcome: StageOutcomeV3::Cancelled,
            evidence_digest: evidence,
        });
        self.predecessor = output;
        Ok(Step::Terminal(
            self.build_receipt(CompositionDispositionV3::Cancelled)?,
        ))
    }

    fn finish(self, disposition: CompositionDispositionV3) -> Result<LaneFCompositionReceiptV3, CompositionErrorV3> {
        self.build_receipt(disposition)
    }

    fn build_receipt(
        &self,
        disposition: CompositionDispositionV3,
    ) -> Result<LaneFCompositionReceiptV3, CompositionErrorV3> {
        let trace_digest = digest_trace_v3(
            &self.request.run_id,
            self.request.request_digest,
            self.snapshot_digest,
            self.objective_digest,
            self.candidate_set_digest,
            disposition,
            &self.stages,
            self.predecessor,
        );
        let receipt = LaneFCompositionReceiptV3 {
            run_id: self.request.run_id.clone(),
            request_digest: self.request.request_digest,
            snapshot_digest: self.snapshot_digest,
            objective_digest: self.objective_digest,
            candidate_set_digest: self.candidate_set_digest,
            disposition,
            host_envelope: self.host_envelope.clone(),
            stages: self.stages.clone(),
            trace_digest,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate()?;
        Ok(receipt)
    }
}

fn validate_capabilities(request: &LaneFCompositionRequestV3) -> Result<(), CompositionErrorV3> {
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
        match request.snapshot.bound_owner(capability) {
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
        if let Some(actual) = request.snapshot.bound_owner(capability)
            && actual != owner
        {
            return Err(CompositionErrorV3::OwnerMismatch(capability));
        }
    }
    Ok(())
}

fn validate_receipt(input: &PortInputV3, receipt: &PortReceiptV3) -> Result<(), CompositionErrorV3> {
    if receipt.stage != input.stage {
        return Err(CompositionErrorV3::StageMismatch);
    }
    if receipt.producer.as_str() != producer_for_stage(input.stage) {
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

fn stable_id(value: &str) -> Result<StableId, CompositionErrorV3> {
    StableId::new(value).map_err(|_| CompositionErrorV3::Arithmetic)
}

fn control_evidence(snapshot: Digest32, stage: LaneFStageV3, observed_micros: u64) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.control\0".to_vec();
    bytes.extend_from_slice(snapshot.as_array());
    bytes.push(stage as u8);
    bytes.extend_from_slice(&observed_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn absent_capability_digest(snapshot: Digest32, capability: &str) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.absent-capability\0".to_vec();
    bytes.extend_from_slice(snapshot.as_array());
    bytes.extend_from_slice(capability.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn fallback_digest(
    stage: LaneFStageV3,
    predecessor: Digest32,
    class: PortFailureClassV1,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.fallback\0".to_vec();
    bytes.push(stage as u8);
    bytes.push(match class {
        PortFailureClassV1::Rejected => 0,
        PortFailureClassV1::Unavailable => 1,
        PortFailureClassV1::TimedOut => 2,
        PortFailureClassV1::Quarantined => 3,
        PortFailureClassV1::Indeterminate => 4,
    });
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn cancellation_digest(stage: LaneFStageV3, predecessor: Digest32, evidence: Digest32) -> Digest32 {
    let mut bytes = b"hepta.intelligence.v3.cancellation\0".to_vec();
    bytes.push(stage as u8);
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}
