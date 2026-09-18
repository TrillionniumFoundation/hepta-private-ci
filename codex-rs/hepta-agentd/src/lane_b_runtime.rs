use std::collections::BTreeMap;

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
    TerminalObservationRequired,
    ArithmeticOverflow,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct IntelligenceRunBinding {
    envelope_digest: String,
    expected_context_digest: String,
    expected_context_receipt_digest: String,
}

#[derive(Clone, Debug)]
struct RunRecord {
    snapshot: RunSnapshot,
    intelligence: Option<IntelligenceRunBinding>,
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
        self.start_run_bound(now_ms, snapshot, None)
    }

    /// Additive V3 admission path. Legacy RunSnapshot callers remain source
    /// compatible; the intelligence binding stays private to Agentd.
    pub fn start_intelligence_run(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
        envelope_digest: String,
        expected_context_digest: String,
        expected_context_receipt_digest: String,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_digest(&envelope_digest, "intelligence envelope")?;
        validate_digest(&expected_context_digest, "expected context")?;
        validate_digest(&expected_context_receipt_digest, "expected context receipt")?;
        self.start_run_bound(
            now_ms,
            snapshot,
            Some(IntelligenceRunBinding {
                envelope_digest,
                expected_context_digest,
                expected_context_receipt_digest,
            }),
        )
    }

    fn start_run_bound(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
        intelligence: Option<IntelligenceRunBinding>,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_snapshot(now_ms, &snapshot)?;
        if let Some(current) = self.runs.get(&snapshot.run_id) {
            if current.snapshot == snapshot && current.intelligence == intelligence {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
        if self.active_run_count() >= MAX_ACTIVE_RUNS || self.runs.len() >= MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
        let record = RunRecord {
            snapshot: snapshot.clone(),
            intelligence,
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
            || record
                .intelligence
                .as_ref()
                .is_some_and(|binding| binding.expected_context_digest != attachment.context_digest)
            || record.intelligence.as_ref().is_some_and(|binding| {
                binding.expected_context_receipt_digest != attachment.compilation_receipt_digest
            })
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

    pub fn mark_dispatched(
        &mut self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mark_dispatched_bound(run_id, expected_revision, None)
    }

    /// Dispatch an intelligence-bound run only when the exact admitted host
    /// envelope is presented again. Legacy runs use `mark_dispatched`.
    pub fn mark_dispatched_with_intelligence_envelope(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        envelope_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_digest(envelope_digest, "intelligence envelope")?;
        self.mark_dispatched_bound(run_id, expected_revision, Some(envelope_digest))
    }

    fn mark_dispatched_bound(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        envelope_digest: Option<&str>,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        let expected_envelope = record
            .intelligence
            .as_ref()
            .map(|binding| binding.envelope_digest.as_str());
        if expected_envelope != envelope_digest {
            return Err(AgentRunError::MixedSnapshot);
        }
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
