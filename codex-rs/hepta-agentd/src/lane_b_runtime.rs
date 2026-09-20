use std::collections::BTreeMap;

const MAX_ACTIVE_RUNS: usize = 256;
const MAX_RETAINED_RUNS: usize = 1_024;
const MAX_CANCEL_REASON_BYTES: usize = 512;
const DEADLINE_CANCEL_REASON: &str = "deadline_elapsed";

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

    fn unresolved_after_dispatch(self) -> bool {
        matches!(
            self,
            Self::Dispatched | Self::Cancelling | Self::Indeterminate
        )
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
    pub authority_epoch: u64,
    pub deadline_ms: u64,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunRecovery {
    pub snapshot: RunSnapshot,
    pub revision: u64,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
    pub cancel_reason: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunReceipt {
    pub run_id: String,
    pub revision: u64,
    pub phase: RunPhase,
    pub context_digest: Option<String>,
    pub authority_epoch: u64,
    pub deadline_ms: u64,
    pub cancel_reason: Option<String>,
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
    InvalidCancelReason,
    AdmissionClosed,
    DeadlineElapsed,
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

#[derive(Clone, Debug)]
struct RunRecord {
    snapshot: RunSnapshot,
    revision: u64,
    phase: RunPhase,
    context_digest: Option<String>,
    compilation_receipt_digest: Option<String>,
    cancel_reason: Option<String>,
}

/// Owner-local Lane B coordinator for Agentd.
///
/// This type owns only run admission and immutable snapshot references. Codex
/// remains the thread/turn execution owner, and domain stores remain with their
/// canonical modules. Recovery can only rehydrate a previously-dispatched run
/// as indeterminate; it can never authorize redispatch.
#[derive(Debug)]
pub struct AgentRunCoordinator {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    accepting_runs: bool,
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
            accepting_runs: true,
        })
    }

    pub fn composition(&self) -> &RuntimeComposition {
        &self.composition
    }

    pub fn admissions_open(&self) -> bool {
        self.accepting_runs
    }

    pub fn close_admissions(&mut self) {
        self.accepting_runs = false;
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
        if !self.accepting_runs {
            return Err(AgentRunError::AdmissionClosed);
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
            cancel_reason: None,
        };
        let result = receipt(&record, /*idempotent*/ false);
        self.runs.insert(snapshot.run_id, record);
        Ok(result)
    }

    pub fn attach_context(
        &mut self,
        now_ms: u64,
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
            || attachment.authority_epoch != record.snapshot.authority_epoch
            || attachment.deadline_ms != record.snapshot.deadline_ms
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
        require_live_deadline(record, now_ms)?;
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
        now_ms: u64,
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
        require_live_deadline(record, now_ms)?;
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::ContextRequired);
        }
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    pub fn cancel_run(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        reason: &str,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_cancel_reason(reason)?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        require_revision(record, expected_revision)?;
        let expired = expire_record(record, now_ms)?;
        if expired {
            let disposition = match record.phase {
                RunPhase::Cancelled => CancellationDisposition::AlreadyTerminal,
                RunPhase::Cancelling => CancellationDisposition::CancellingAfterDispatch,
                _ => return Err(AgentRunError::InvalidTransition),
            };
            return Ok((disposition, receipt(record, /*idempotent*/ false)));
        }

        let disposition = match record.phase {
            RunPhase::Admitted | RunPhase::ContextAttached => {
                record.phase = RunPhase::Cancelled;
                record.cancel_reason = Some(reason.to_string());
                advance_revision(record)?;
                CancellationDisposition::CancelledBeforeDispatch
            }
            RunPhase::Dispatched => {
                record.phase = RunPhase::Cancelling;
                record.cancel_reason = Some(reason.to_string());
                advance_revision(record)?;
                CancellationDisposition::CancellingAfterDispatch
            }
            RunPhase::Cancelling => {
                if record.cancel_reason.as_deref() != Some(reason) {
                    return Err(AgentRunError::Conflict);
                }
                return Ok((
                    CancellationDisposition::CancellingAfterDispatch,
                    receipt(record, /*idempotent*/ true),
                ));
            }
            RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed => {
                return Ok((
                    CancellationDisposition::AlreadyTerminal,
                    receipt(record, /*idempotent*/ true),
                ));
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
        if !record.phase.unresolved_after_dispatch() {
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

    pub fn recover_indeterminate(
        &mut self,
        recovery: RunRecovery,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_recovery(&recovery)?;
        let run_id = recovery.snapshot.run_id.clone();
        if let Some(current) = self.runs.get(&run_id) {
            let same = current.snapshot == recovery.snapshot
                && current.revision == recovery.revision
                && current.phase == RunPhase::Indeterminate
                && current.context_digest.as_deref() == Some(recovery.context_digest.as_str())
                && current.compilation_receipt_digest.as_deref()
                    == Some(recovery.compilation_receipt_digest.as_str())
                && current.cancel_reason == recovery.cancel_reason;
            if same {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
        if self.active_run_count() >= MAX_ACTIVE_RUNS || self.runs.len() >= MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
        let record = RunRecord {
            snapshot: recovery.snapshot,
            revision: recovery.revision,
            phase: RunPhase::Indeterminate,
            context_digest: Some(recovery.context_digest),
            compilation_receipt_digest: Some(recovery.compilation_receipt_digest),
            cancel_reason: recovery.cancel_reason,
        };
        let result = receipt(&record, /*idempotent*/ false);
        self.runs.insert(run_id, record);
        Ok(result)
    }

    pub fn expire_deadlines(&mut self, now_ms: u64) -> Result<usize, AgentRunError> {
        let mut changed = 0usize;
        for record in self.runs.values_mut() {
            if expire_record(record, now_ms)? {
                changed = changed
                    .checked_add(1)
                    .ok_or(AgentRunError::ArithmeticOverflow)?;
            }
        }
        Ok(changed)
    }

    pub fn begin_drain(&mut self, now_ms: u64, reason: &str) -> Result<usize, AgentRunError> {
        validate_cancel_reason(reason)?;
        self.accepting_runs = false;
        for record in self.runs.values_mut() {
            if expire_record(record, now_ms)? {
                continue;
            }
            match record.phase {
                RunPhase::Admitted | RunPhase::ContextAttached => {
                    record.phase = RunPhase::Cancelled;
                    record.cancel_reason = Some(reason.to_string());
                    advance_revision(record)?;
                }
                RunPhase::Dispatched => {
                    record.phase = RunPhase::Cancelling;
                    record.cancel_reason = Some(reason.to_string());
                    advance_revision(record)?;
                }
                RunPhase::Cancelling
                | RunPhase::Cancelled
                | RunPhase::Succeeded
                | RunPhase::Failed
                | RunPhase::Indeterminate => {}
            }
        }
        Ok(self.unresolved_run_count())
    }

    pub fn mark_unresolved_indeterminate(&mut self, reason: &str) -> Result<usize, AgentRunError> {
        validate_cancel_reason(reason)?;
        let mut changed = 0usize;
        for record in self.runs.values_mut() {
            if matches!(record.phase, RunPhase::Dispatched | RunPhase::Cancelling) {
                record.phase = RunPhase::Indeterminate;
                if record.cancel_reason.is_none() {
                    record.cancel_reason = Some(reason.to_string());
                }
                advance_revision(record)?;
                changed = changed
                    .checked_add(1)
                    .ok_or(AgentRunError::ArithmeticOverflow)?;
            }
        }
        Ok(changed)
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

    pub fn active_run_count(&self) -> usize {
        self.runs
            .values()
            .filter(|record| !record.phase.closed())
            .count()
    }

    pub fn unresolved_run_count(&self) -> usize {
        self.runs
            .values()
            .filter(|record| record.phase.unresolved_after_dispatch())
            .count()
    }
}

fn validate_snapshot(now_ms: u64, value: &RunSnapshot) -> Result<(), AgentRunError> {
    validate_snapshot_fields(value)?;
    if value.deadline_ms <= now_ms {
        return Err(AgentRunError::InvalidDeadline);
    }
    Ok(())
}

fn validate_snapshot_fields(value: &RunSnapshot) -> Result<(), AgentRunError> {
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
    if value.deadline_ms == 0 {
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
    if value.authority_epoch == 0 {
        return Err(AgentRunError::InvalidGeneration);
    }
    if value.deadline_ms == 0 {
        return Err(AgentRunError::InvalidDeadline);
    }
    Ok(())
}

fn validate_recovery(value: &RunRecovery) -> Result<(), AgentRunError> {
    validate_snapshot_fields(&value.snapshot)?;
    if value.revision == 0 {
        return Err(AgentRunError::StaleRevision);
    }
    validate_digest(&value.context_digest, "context")?;
    validate_digest(&value.compilation_receipt_digest, "compilation receipt")?;
    if let Some(reason) = value.cancel_reason.as_deref() {
        validate_cancel_reason(reason)?;
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

fn validate_cancel_reason(reason: &str) -> Result<(), AgentRunError> {
    if reason.trim().is_empty()
        || reason.len() > MAX_CANCEL_REASON_BYTES
        || reason.as_bytes().contains(&0)
    {
        return Err(AgentRunError::InvalidCancelReason);
    }
    Ok(())
}

fn require_revision(record: &RunRecord, expected_revision: u64) -> Result<(), AgentRunError> {
    if record.revision != expected_revision {
        return Err(AgentRunError::StaleRevision);
    }
    Ok(())
}

fn require_live_deadline(record: &RunRecord, now_ms: u64) -> Result<(), AgentRunError> {
    if record.snapshot.deadline_ms <= now_ms {
        Err(AgentRunError::DeadlineElapsed)
    } else {
        Ok(())
    }
}

fn expire_record(record: &mut RunRecord, now_ms: u64) -> Result<bool, AgentRunError> {
    if record.snapshot.deadline_ms > now_ms {
        return Ok(false);
    }
    match record.phase {
        RunPhase::Admitted | RunPhase::ContextAttached => {
            record.phase = RunPhase::Cancelled;
            record.cancel_reason = Some(DEADLINE_CANCEL_REASON.to_string());
            advance_revision(record)?;
            Ok(true)
        }
        RunPhase::Dispatched => {
            record.phase = RunPhase::Cancelling;
            record.cancel_reason = Some(DEADLINE_CANCEL_REASON.to_string());
            advance_revision(record)?;
            Ok(true)
        }
        RunPhase::Cancelling
        | RunPhase::Cancelled
        | RunPhase::Succeeded
        | RunPhase::Failed
        | RunPhase::Indeterminate => Ok(false),
    }
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
        authority_epoch: record.snapshot.authority_epoch,
        deadline_ms: record.snapshot.deadline_ms,
        cancel_reason: record.cancel_reason.clone(),
        terminal_observed: record.phase.terminal_observed(),
        idempotent,
    }
}

#[cfg(test)]
#[path = "lane_b_runtime_tests.rs"]
mod tests;
