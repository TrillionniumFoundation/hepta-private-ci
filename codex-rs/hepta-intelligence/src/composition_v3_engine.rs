use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompositionCancellationV3;
use crate::CompositionClockV3;
use crate::CompositionDispositionV3;
use crate::CompositionErrorV3;
use crate::IntelligenceHostEnvelopeV1;
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
use crate::composition_v3_validate::cancellation_digest_v3;
use crate::composition_v3_validate::digest_trace_v3;
use crate::composition_v3_validate::fallback_digest_v3;
use crate::composition_v3_validate::producer_for_stage;

pub(super) enum Step {
    Continue(PortReceiptV3),
    Terminal(LaneFCompositionReceiptV3),
}

enum PortCall {
    Success(PortReceiptV3),
    Failure(PortFailureV3),
    Cancelled(Digest32),
    TotalTimedOut(Digest32),
}

pub(super) struct Runner<'a, C, X> {
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

impl<'a, C, X> Runner<'a, C, X>
where
    C: CompositionClockV3,
    X: CompositionCancellationV3,
{
    pub(super) fn new(
        request: LaneFCompositionRequestV3,
        total_deadline: u64,
        clock: &'a mut C,
        cancellation: &'a X,
    ) -> Self {
        let predecessor = request.request_digest;
        Self {
            objective_digest: request.snapshot.objective_digest(),
            snapshot_digest: request.snapshot.digest(),
            candidate_set_digest: request.legal_candidates.digest(),
            request,
            total_deadline,
            clock,
            cancellation,
            predecessor,
            stages: Vec::with_capacity(11),
            host_envelope: None,
        }
    }

    pub(super) fn run_id(&self) -> &StableId {
        &self.request.run_id
    }

    pub(super) const fn request_digest(&self) -> Digest32 {
        self.request.request_digest
    }

    pub(super) const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    pub(super) const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    pub(super) const fn candidate_set_digest(&self) -> Digest32 {
        self.candidate_set_digest
    }

    pub(super) fn stages(&self) -> &[StageTraceV3] {
        &self.stages
    }

    pub(super) fn set_host_envelope(&mut self, envelope: IntelligenceHostEnvelopeV1) {
        self.host_envelope = Some(envelope);
    }

    pub(super) fn required<F>(
        &mut self,
        stage: LaneFStageV3,
        call: F,
    ) -> Result<Step, CompositionErrorV3>
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
            PortCall::TotalTimedOut(evidence) => self.timed_out(stage, evidence),
        }
    }

    pub(super) fn optional<F>(
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
            PortCall::Cancelled(evidence) => {
                let step = self.cancelled(stage, evidence)?;
                Self::terminal_optional(step)
            }
            PortCall::TotalTimedOut(evidence) => {
                let step = self.timed_out(stage, evidence)?;
                Self::terminal_optional(step)
            }
        }
    }

    pub(super) fn advisory<F>(&mut self, call: F) -> Result<Step, CompositionErrorV3>
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
            PortCall::TotalTimedOut(evidence) => self.timed_out(stage, evidence),
        }
    }

    pub(super) fn internal_legal_set(
        &mut self,
    ) -> Result<Option<LaneFCompositionReceiptV3>, CompositionErrorV3> {
        self.internal(LaneFStageV3::LegalSetBuilt, self.candidate_set_digest)
    }

    pub(super) fn internal_host_envelope(
        &mut self,
        envelope: IntelligenceHostEnvelopeV1,
    ) -> Result<Option<LaneFCompositionReceiptV3>, CompositionErrorV3> {
        self.internal(LaneFStageV3::HostEnvelopePrepared, envelope.envelope_digest)
    }

    pub(super) fn finish(
        self,
        disposition: CompositionDispositionV3,
    ) -> Result<LaneFCompositionReceiptV3, CompositionErrorV3> {
        self.build_receipt(disposition)
    }

    fn internal(
        &mut self,
        stage: LaneFStageV3,
        output_digest: Digest32,
    ) -> Result<Option<LaneFCompositionReceiptV3>, CompositionErrorV3> {
        if output_digest.is_zero() {
            return Err(CompositionErrorV3::EmptyDigest("internal output"));
        }
        let now = self.clock.now_micros();
        let evidence = control_evidence(self.snapshot_digest, stage, now);
        if self.cancellation.is_cancelled() {
            let step = self.cancelled(stage, evidence)?;
            return Self::terminal_optional(step);
        }
        if now >= self.total_deadline {
            let step = self.timed_out(stage, evidence)?;
            return Self::terminal_optional(step);
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
            Err(failure) if failure.evidence_digest.is_zero() => {
                Err(CompositionErrorV3::InvalidFailure)
            }
            Err(failure) => Ok(PortCall::Failure(failure)),
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
        let output = fallback_digest_v3(stage, self.predecessor, class, evidence_digest);
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

    fn failed(&mut self, stage: LaneFStageV3, failure: PortFailureV3) -> Result<Step, CompositionErrorV3> {
        let output = fallback_digest_v3(stage, self.predecessor, failure.class, failure.evidence_digest);
        self.push_terminal(
            stage,
            output,
            StageOutcomeV3::Failed(failure.class),
            failure.evidence_digest,
            CompositionDispositionV3::Failed(failure.class),
        )
    }

    fn timed_out(&mut self, stage: LaneFStageV3, evidence: Digest32) -> Result<Step, CompositionErrorV3> {
        self.failed(
            stage,
            PortFailureV3 {
                class: PortFailureClassV1::TimedOut,
                evidence_digest: evidence,
            },
        )
    }

    fn cancelled(&mut self, stage: LaneFStageV3, evidence: Digest32) -> Result<Step, CompositionErrorV3> {
        self.push_terminal(
            stage,
            cancellation_digest_v3(stage, self.predecessor, evidence),
            StageOutcomeV3::Cancelled,
            evidence,
            CompositionDispositionV3::Cancelled,
        )
    }

    fn push_terminal(
        &mut self,
        stage: LaneFStageV3,
        output_digest: Digest32,
        outcome: StageOutcomeV3,
        evidence_digest: Digest32,
        disposition: CompositionDispositionV3,
    ) -> Result<Step, CompositionErrorV3> {
        self.stages.push(StageTraceV3 {
            stage,
            producer: stable_id(producer_for_stage(stage))?,
            predecessor_digest: self.predecessor,
            output_digest,
            outcome,
            evidence_digest,
        });
        self.predecessor = output_digest;
        Ok(Step::Terminal(self.build_receipt(disposition)?))
    }

    fn terminal_optional(
        step: Step,
    ) -> Result<Option<LaneFCompositionReceiptV3>, CompositionErrorV3> {
        match step {
            Step::Terminal(receipt) => Ok(Some(receipt)),
            Step::Continue(_) => Err(CompositionErrorV3::InvalidReceipt("terminal continue")),
        }
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
