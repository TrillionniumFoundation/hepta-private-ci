use std::collections::BTreeMap;

use codex_hepta_intelligence::CompositionControlV3;
use codex_hepta_intelligence::DurableLearningJournal;
use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_intelligence::LaneFCompositionReceiptV3;
use codex_hepta_intelligence::LaneFRunRequestV3;
use codex_hepta_intelligence::LaneFStageV3;
use codex_hepta_intelligence::LaneFV3Ports;
use codex_hepta_intelligence::NativeV3OwnerInputs;
use codex_hepta_intelligence::NativeV3OwnerPorts;
use codex_hepta_intelligence::NeverCancelledV3;
use codex_hepta_intelligence::OutcomeCreditClosureErrorV1;
use codex_hepta_intelligence::OutcomeCreditClosureReceiptV1;
use codex_hepta_intelligence::OutcomeCreditClosureRequestV1;
use codex_hepta_intelligence::PortDecisionV3;
use codex_hepta_intelligence::PortFailureClassV3;
use codex_hepta_intelligence::PortFailureV3;
use codex_hepta_intelligence::PortInputV3;
use codex_hepta_intelligence::PortReceiptV3;
use codex_hepta_intelligence::StageOutcomeV3;
use codex_hepta_intelligence::append_outcome_credit_v1;
use codex_hepta_intelligence::run_composition_v3_with_control;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::intelligence_host::AgentdIntelligenceHostV1;

const MAX_ACTIVE_RUNS: usize = 256;
const MAX_RETAINED_RUNS: usize = 1_024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RunPhase {
    Admitted,
    ContextAttached,
    Dispatched,
    Cancelling,
    Cancelled,
    Succeeded,
    Failed,
    Indeterminate,
}

impl RunPhase {
    fn closed(self) -> bool {
        matches!(self, Self::Cancelled | Self::Succeeded | Self::Failed)
    }

    fn terminal_observed(self) -> bool {
        matches!(self, Self::Cancelled | Self::Succeeded | Self::Failed)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeComposition {
    pub agent_id: String,
    pub supervisor_generation: u64,
    pub agentd_generation: u64,
    pub configuration_digest: String,
    pub ports_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunSnapshot {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAttachment {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunReceipt {
    pub run_id: String,
    pub revision: u64,
    pub phase: RunPhase,
    pub context_digest: Option<String>,
    pub terminal_observed: bool,
    pub idempotent: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceRunReceiptV3 {
    pub composition: LaneFCompositionReceiptV3,
    pub runtime: Option<RunReceipt>,
    /// Present only for the native product caller after the real durable
    /// LearningRecorded append succeeds.
    pub durable_decision_chain_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceTerminalClosureReceiptV3 {
    pub runtime: RunReceipt,
    pub learning: OutcomeCreditClosureReceiptV1,
}

#[derive(Debug, Eq, PartialEq)]
pub enum IntelligenceTerminalClosureErrorV3 {
    Runtime(AgentRunError),
    Learning {
        runtime: RunReceipt,
        error: OutcomeCreditClosureErrorV1,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CancellationDisposition {
    CancelledBeforeDispatch,
    CancellingAfterDispatch,
    AlreadyTerminal,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentRunError {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidGeneration,
    InvalidDeadline,
    CapacityExceeded,
    RunNotFound,
    Conflict,
    InvalidTransition,
    StaleRevision,
    MixedSnapshot,
    ContextRequired,
    InvalidIntelligenceEnvelope,
    IntelligenceCompositionFailed,
    TerminalObservationRequired,
    ArithmeticOverflow,
}

#[derive(Clone, Debug)]
struct RunRecord {
    snapshot: RunSnapshot,
    revision: u64,
    phase: RunPhase,
    context_digest: Option<String>,
    compilation_receipt_digest: Option<String>,
}

/// Owner-local Lane B coordinator for Agentd.
///
/// This type owns only ephemeral run admission and immutable snapshot references.
/// Codex remains the thread/turn execution owner, and domain stores remain with
/// their canonical modules.
#[derive(Debug)]
pub struct AgentRunCoordinator {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
}

/// Product composition wrapper that makes the V3 runtime.agentd stage a real
/// AgentRunCoordinator mutation. The wrapped owner ports never get to substitute
/// a validation-only host receipt for actual runtime admission.
struct AgentdRuntimePorts<'a, P> {
    inner: &'a mut P,
    coordinator: &'a mut AgentRunCoordinator,
    expected_revision: u64,
}

impl<P: LaneFV3Ports> LaneFV3Ports for AgentdRuntimePorts<'_, P> {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.validate_objective(input)
    }

    fn evaluate_utility(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.evaluate_utility(input)
    }

    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.admit_evaluation(input)
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.collect_neural_signal(input)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.build_prompt_portfolio(input)
    }

    fn decide_intuition(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.decide_intuition(input)
    }

    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.compile_context(input)
    }

    fn accept_host_envelope(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        if input.stage != LaneFStageV3::HostHandoffAccepted
            || input.run_id != envelope.run_id
            || input.snapshot_digest != envelope.snapshot_digest
            || input.predecessor_digest != envelope.envelope_digest
        {
            return Err(agentd_handoff_failure(input, envelope, "handoff-binding"));
        }

        let proposal = self.inner.accept_host_envelope(input, envelope)?;
        if proposal.stage != input.stage
            || proposal.producer.as_str() != "runtime.agentd"
            || proposal.snapshot_digest != input.snapshot_digest
            || proposal.predecessor_digest != input.predecessor_digest
            || proposal.output_digest.is_zero()
            || proposal.decision != PortDecisionV3::Continue
            || proposal.authority.grants_any()
        {
            return Err(agentd_handoff_failure(
                input,
                envelope,
                "host-proposal-receipt",
            ));
        }

        let run = self
            .coordinator
            .attach_intelligence_envelope(self.expected_revision, envelope)
            .map_err(|error| {
                agentd_handoff_failure(input, envelope, &format!("runtime:{error:?}"))
            })?;

        let mut bytes = b"hepta.agentd.runtime-intelligence-handoff.v1\0".to_vec();
        bytes.extend_from_slice(envelope.envelope_digest.as_array());
        bytes.extend_from_slice(&run.revision.to_be_bytes());
        let producer = StableId::new("runtime.agentd")
            .map_err(|_| agentd_handoff_failure(input, envelope, "producer-id"))?;

        Ok(PortReceiptV3 {
            stage: input.stage,
            producer,
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: Digest32::of_bytes(&bytes),
            decision: PortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.inner.record_learning(input)
    }
}

fn agentd_handoff_failure(
    input: &PortInputV3,
    envelope: &IntelligenceHostEnvelopeV1,
    reason: &str,
) -> PortFailureV3 {
    let mut bytes = b"hepta.agentd.runtime-intelligence-handoff-failure.v1\0".to_vec();
    bytes.extend_from_slice(input.snapshot_digest.as_array());
    bytes.extend_from_slice(input.predecessor_digest.as_array());
    bytes.extend_from_slice(envelope.envelope_digest.as_array());
    bytes.extend_from_slice(reason.as_bytes());
    PortFailureV3 {
        class: PortFailureClassV3::Rejected,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

impl AgentRunCoordinator {
    pub fn compose_runtime(composition: RuntimeComposition) -> Result<Self, AgentRunError> {
        validate_identity(&composition.agent_id, "agent")?;
        validate_digest(&composition.configuration_digest, "configuration")?;
        validate_digest(&composition.ports_digest, "ports")?;
        if composition.supervisor_generation == 0 || composition.agentd_generation == 0 {
            return Err(AgentRunError::InvalidGeneration);
        }
        Ok(Self {
            composition,
            runs: BTreeMap::new(),
        })
    }

    pub fn composition(&self) -> &RuntimeComposition {
        &self.composition
    }

    pub fn start_run(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_snapshot(now_ms, &snapshot)?;
        if let Some(current) = self.runs.get(&snapshot.run_id) {
            if current.snapshot == snapshot {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
        if self.active_run_count() >= MAX_ACTIVE_RUNS || self.runs.len() >= MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
        let record = RunRecord {
            snapshot: snapshot.clone(),
            revision: 1,
            phase: RunPhase::Admitted,
            context_digest: None,
            compilation_receipt_digest: None,
        };
        let result = receipt(&record, /*idempotent*/ false);
        self.runs.insert(snapshot.run_id, record);
        Ok(result)
    }

    pub fn attach_context(
        &mut self,
        expected_revision: u64,
        attachment: ContextAttachment,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_attachment(&attachment)?;
        let record = self
            .runs
            .get_mut(&attachment.run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if attachment.request_digest != record.snapshot.request_digest
            || attachment.objective_digest != record.snapshot.objective_digest
            || attachment.body_digest != record.snapshot.body_digest
            || attachment.artifact_set_digest != record.snapshot.artifact_set_digest
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        if record.phase == RunPhase::ContextAttached
            && record.context_digest.as_deref() == Some(attachment.context_digest.as_str())
            && record.compilation_receipt_digest.as_deref()
                == Some(attachment.compilation_receipt_digest.as_str())
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Admitted {
            return Err(AgentRunError::InvalidTransition);
        }
        record.context_digest = Some(attachment.context_digest);
        record.compilation_receipt_digest = Some(attachment.compilation_receipt_digest);
        record.phase = RunPhase::ContextAttached;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Attach the canonical intelligence facade handoff to an admitted run.
    ///
    /// The envelope is validated before mutating runtime state. Agentd reuses its
    /// existing context-attached phase; the context digest is the compiled
    /// context and the compilation receipt is the exact intelligence envelope.
    /// Codex/App Server remains the execution owner after this handoff.
    pub fn attach_intelligence_envelope(
        &mut self,
        expected_revision: u64,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<RunReceipt, AgentRunError> {
        envelope
            .validate()
            .map_err(|_| AgentRunError::InvalidIntelligenceEnvelope)?;
        let run_id = envelope.run_id.as_str();
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        let deadline_ms = envelope
            .deadline_unix_micros
            .checked_add(999)
            .ok_or(AgentRunError::ArithmeticOverflow)?
            / 1_000;
        if record.snapshot.request_digest != envelope.request_digest.to_string()
            || record.snapshot.objective_digest != envelope.objective_digest.to_string()
            || record.snapshot.body_digest != envelope.body_digest.to_string()
            || record.snapshot.artifact_set_digest != envelope.artifact_set_digest.to_string()
            || record.snapshot.authority_epoch != envelope.authority_epoch
            || record.snapshot.deadline_ms != deadline_ms
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        let context_digest = envelope.context_digest.to_string();
        let envelope_digest = envelope.envelope_digest.to_string();
        if record.phase == RunPhase::ContextAttached
            && record.context_digest.as_deref() == Some(context_digest.as_str())
            && record.compilation_receipt_digest.as_deref() == Some(envelope_digest.as_str())
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Admitted {
            return Err(AgentRunError::InvalidTransition);
        }
        record.context_digest = Some(context_digest);
        record.compilation_receipt_digest = Some(envelope_digest);
        record.phase = RunPhase::ContextAttached;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Run the canonical V3 intelligence composition for an already admitted run.
    ///
    /// A successful host handoff is attached to this coordinator's existing
    /// ContextAttached phase. Abstain, slow-path and terminal-failure receipts
    /// remain observable without mutating the runtime into a dispatchable state.
    pub fn run_intelligence_v3<P: LaneFV3Ports>(
        &mut self,
        expected_revision: u64,
        request: LaneFRunRequestV3,
        ports: &mut P,
    ) -> Result<IntelligenceRunReceiptV3, AgentRunError> {
        self.run_intelligence_v3_with_control(expected_revision, request, ports, &NeverCancelledV3)
    }

    pub fn run_intelligence_v3_with_control<P: LaneFV3Ports, C: CompositionControlV3>(
        &mut self,
        expected_revision: u64,
        request: LaneFRunRequestV3,
        ports: &mut P,
        control: &C,
    ) -> Result<IntelligenceRunReceiptV3, AgentRunError> {
        let run_id = request.run_id.clone();
        let composition = {
            let mut runtime_ports = AgentdRuntimePorts {
                inner: ports,
                coordinator: self,
                expected_revision,
            };
            run_composition_v3_with_control(request, &mut runtime_ports, control)
                .map_err(|_| AgentRunError::IntelligenceCompositionFailed)?
        };
        let host_attached = composition.stages.iter().any(|stage| {
            stage.stage == LaneFStageV3::HostHandoffAccepted
                && stage.outcome == StageOutcomeV3::Completed
        });
        let runtime = if host_attached {
            self.run(run_id.as_str())
        } else {
            None
        };
        Ok(IntelligenceRunReceiptV3 {
            composition,
            runtime,
            durable_decision_chain_digest: None,
        })
    }

    /// Product-side V3 caller using the registered owner implementations and the
    /// typed Agentd host handoff. This remains proposal-only: Codex/App Server
    /// execution and terminal observation stay in their existing runtime owners.
    pub fn run_native_intelligence_v3(
        &mut self,
        expected_revision: u64,
        request: LaneFRunRequestV3,
        inputs: NativeV3OwnerInputs,
        ledger: &mut dyn DurableLearningJournal,
        expected_ledger_head: Digest32,
    ) -> Result<IntelligenceRunReceiptV3, AgentRunError> {
        self.run_native_intelligence_v3_with_control(
            expected_revision,
            request,
            inputs,
            ledger,
            expected_ledger_head,
            &NeverCancelledV3,
        )
    }

    pub fn run_native_intelligence_v3_with_control<C: CompositionControlV3>(
        &mut self,
        expected_revision: u64,
        request: LaneFRunRequestV3,
        inputs: NativeV3OwnerInputs,
        ledger: &mut dyn DurableLearningJournal,
        expected_ledger_head: Digest32,
        control: &C,
    ) -> Result<IntelligenceRunReceiptV3, AgentRunError> {
        let mut ports = NativeV3OwnerPorts::new(
            inputs,
            ledger,
            expected_ledger_head,
            AgentdIntelligenceHostV1,
        );
        let mut receipt =
            self.run_intelligence_v3_with_control(expected_revision, request, &mut ports, control)?;
        receipt.durable_decision_chain_digest =
            ports.learning_append().map(|append| append.chain_digest);
        Ok(receipt)
    }

    pub fn mark_dispatched(
        &mut self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Dispatched {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::ContextRequired);
        }
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    pub fn cancel_run(
        &mut self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        require_revision(record, expected_revision)?;
        let disposition = match record.phase {
            RunPhase::Admitted | RunPhase::ContextAttached => {
                record.phase = RunPhase::Cancelled;
                advance_revision(record)?;
                CancellationDisposition::CancelledBeforeDispatch
            }
            RunPhase::Dispatched => {
                record.phase = RunPhase::Cancelling;
                advance_revision(record)?;
                CancellationDisposition::CancellingAfterDispatch
            }
            RunPhase::Cancelling => CancellationDisposition::CancellingAfterDispatch,
            RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed => {
                CancellationDisposition::AlreadyTerminal
            }
            RunPhase::Indeterminate => return Err(AgentRunError::TerminalObservationRequired),
        };
        Ok((disposition, receipt(record, /*idempotent*/ false)))
    }

    pub fn observe_terminal(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        phase: RunPhase,
        terminal_observed: bool,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == phase
            && ((terminal_observed && phase.terminal_observed())
                || (!terminal_observed && phase == RunPhase::Indeterminate))
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        // An unknown external outcome consumes capacity until its owner reports
        // a terminal observation. It must be reconcilable without redispatch.
        if !matches!(
            record.phase,
            RunPhase::Dispatched | RunPhase::Cancelling | RunPhase::Indeterminate
        ) {
            return Err(AgentRunError::InvalidTransition);
        }
        if terminal_observed {
            if !matches!(
                phase,
                RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed
            ) {
                return Err(AgentRunError::TerminalObservationRequired);
            }
        } else if phase != RunPhase::Indeterminate {
            return Err(AgentRunError::TerminalObservationRequired);
        }
        record.phase = phase;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Record an already-observed terminal runtime fact and then close the
    /// corresponding learning episode through the sealed ledger owner.
    ///
    /// Runtime terminality is committed first because Agentd owns that fact. A
    /// later learning failure never rolls the runtime state back; the returned
    /// error preserves the committed runtime receipt so reconciliation can retry
    /// the exact ledger closure without redispatching the run.
    pub fn observe_intelligence_terminal_and_record(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        phase: RunPhase,
        closure: OutcomeCreditClosureRequestV1,
        ledger: &mut dyn DurableLearningJournal,
    ) -> Result<IntelligenceTerminalClosureReceiptV3, IntelligenceTerminalClosureErrorV3> {
        if closure.run_id.as_str() != run_id {
            return Err(IntelligenceTerminalClosureErrorV3::Runtime(
                AgentRunError::InvalidIdentity("intelligence closure run"),
            ));
        }
        let runtime = self
            .observe_terminal(run_id, expected_revision, phase, true)
            .map_err(IntelligenceTerminalClosureErrorV3::Runtime)?;
        let learning = append_outcome_credit_v1(closure, ledger).map_err(|error| {
            IntelligenceTerminalClosureErrorV3::Learning {
                runtime: runtime.clone(),
                error,
            }
        })?;
        Ok(IntelligenceTerminalClosureReceiptV3 { runtime, learning })
    }

    pub fn remove_closed_run(
        &mut self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self.runs.get(run_id).ok_or(AgentRunError::RunNotFound)?;
        require_revision(record, expected_revision)?;
        if !record.phase.closed() {
            return Err(AgentRunError::InvalidTransition);
        }
        let receipt = receipt(record, /*idempotent*/ false);
        self.runs.remove(run_id);
        Ok(receipt)
    }

    pub fn run(&self, run_id: &str) -> Option<RunReceipt> {
        self.runs
            .get(run_id)
            .map(|record| receipt(record, /*idempotent*/ false))
    }

    fn active_run_count(&self) -> usize {
        self.runs
            .values()
            .filter(|record| !record.phase.closed())
            .count()
    }
}

fn validate_snapshot(now_ms: u64, value: &RunSnapshot) -> Result<(), AgentRunError> {
    validate_identity(&value.run_id, "run")?;
    for (digest, field) in [
        (&value.request_digest, "request"),
        (&value.objective_digest, "objective"),
        (&value.body_digest, "body"),
        (&value.artifact_set_digest, "artifact set"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.authority_epoch == 0 {
        return Err(AgentRunError::InvalidGeneration);
    }
    if value.deadline_ms <= now_ms {
        return Err(AgentRunError::InvalidDeadline);
    }
    Ok(())
}

fn validate_attachment(value: &ContextAttachment) -> Result<(), AgentRunError> {
    validate_identity(&value.run_id, "run")?;
    for (digest, field) in [
        (&value.request_digest, "request"),
        (&value.objective_digest, "objective"),
        (&value.body_digest, "body"),
        (&value.artifact_set_digest, "artifact set"),
        (&value.context_digest, "context"),
        (&value.compilation_receipt_digest, "compilation receipt"),
    ] {
        validate_digest(digest, field)?;
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), AgentRunError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(AgentRunError::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), AgentRunError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(AgentRunError::InvalidDigest(field));
    }
    Ok(())
}

fn require_revision(record: &RunRecord, expected_revision: u64) -> Result<(), AgentRunError> {
    if record.revision != expected_revision {
        return Err(AgentRunError::StaleRevision);
    }
    Ok(())
}

fn advance_revision(record: &mut RunRecord) -> Result<(), AgentRunError> {
    record.revision = record
        .revision
        .checked_add(1)
        .ok_or(AgentRunError::ArithmeticOverflow)?;
    Ok(())
}

fn receipt(record: &RunRecord, idempotent: bool) -> RunReceipt {
    RunReceipt {
        run_id: record.snapshot.run_id.clone(),
        revision: record.revision,
        phase: record.phase,
        context_digest: record.context_digest.clone(),
        terminal_observed: record.phase.terminal_observed(),
        idempotent,
    }
}

#[cfg(test)]
#[path = "lane_b_runtime_tests.rs"]
mod tests;
