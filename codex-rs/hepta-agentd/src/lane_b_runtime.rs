use std::collections::BTreeMap;

use codex_hepta_agent_protocol::CancellationDisposition;
use codex_hepta_agent_protocol::ContextAttachment;
use codex_hepta_agent_protocol::MAX_RUN_CANCEL_REASON_BYTES;
use codex_hepta_agent_protocol::RunPhase;
use codex_hepta_agent_protocol::RunReceipt;
use codex_hepta_agent_protocol::RunSnapshot;
use serde::Deserialize;
use serde::Serialize;

const MAX_ACTIVE_RUNS: usize = 256;
const MAX_RETAINED_RUNS: usize = 1_024;
const MAX_CANCELLATION_ACK_TIMEOUT_MS: u64 = 60_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RuntimeComposition {
    pub agent_id: String,
    pub supervisor_generation: u64,
    pub agentd_generation: u64,
    pub configuration_digest: String,
    pub ports_digest: String,
    pub cancellation_ack_timeout_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentRunError {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidGeneration,
    InvalidDeadline,
    InvalidCancellationAckTimeout,
    InvalidCancelReason,
    CapacityExceeded,
    Draining,
    RunNotFound,
    Conflict,
    InvalidTransition,
    StaleRevision,
    MixedSnapshot,
    ContextRequired,
    TerminalObservationRequired,
    DeadlineExceeded,
    ArithmeticOverflow,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct RunRecord {
    snapshot: RunSnapshot,
    revision: u64,
    phase: RunPhase,
    context_digest: Option<String>,
    compilation_receipt_digest: Option<String>,
    cancel_reason: Option<String>,
    cancellation_ack_deadline_ms: Option<u64>,
}

/// Owner-local Lane B coordinator for Agentd.
///
/// This type owns only recoverable run admission metadata and immutable snapshot
/// references. Codex remains the thread/turn execution owner, and product
/// domain stores remain with their canonical modules.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AgentRunCoordinator {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    draining: bool,
}

impl AgentRunCoordinator {
    pub fn compose_runtime(composition: RuntimeComposition) -> Result<Self, AgentRunError> {
        validate_composition(&composition)?;
        Ok(Self {
            composition,
            runs: BTreeMap::new(),
            draining: false,
        })
    }

    pub fn composition(&self) -> &RuntimeComposition {
        &self.composition
    }

    pub fn validate_recovered_state(&self) -> Result<(), AgentRunError> {
        validate_composition(&self.composition)?;
        if self.runs.len() > MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
        for (run_id, record) in &self.runs {
            if run_id != &record.snapshot.run_id || record.revision == 0 {
                return Err(AgentRunError::Conflict);
            }
            validate_snapshot(/* now_ms */ 0, &record.snapshot)?;
            if let Some(context_digest) = &record.context_digest {
                validate_digest(context_digest, "context")?;
            }
            if let Some(receipt_digest) = &record.compilation_receipt_digest {
                validate_digest(receipt_digest, "compilation receipt")?;
            }
            if let Some(reason) = &record.cancel_reason {
                validate_cancel_reason(reason)?;
            }
            if record
                .cancellation_ack_deadline_ms
                .is_some_and(|deadline| deadline == 0)
            {
                return Err(AgentRunError::InvalidCancellationAckTimeout);
            }
            if record.phase == RunPhase::Cancelling {
                if record.cancellation_ack_deadline_ms.is_none() {
                    return Err(AgentRunError::InvalidCancellationAckTimeout);
                }
            } else if record.cancellation_ack_deadline_ms.is_some() {
                return Err(AgentRunError::InvalidCancellationAckTimeout);
            }
        }
        Ok(())
    }

    /// Rebind a recovered ledger to the new process generation without
    /// redispatching any uncertain external effect.
    pub fn reconcile_after_restart(
        &mut self,
        composition: RuntimeComposition,
    ) -> Result<Vec<RunReceipt>, AgentRunError> {
        validate_composition(&composition)?;
        if self.composition.agent_id != composition.agent_id {
            return Err(AgentRunError::InvalidIdentity("agent"));
        }
        let changed = self.mark_unfinished(
            "agentd_restarted_before_dispatch",
            "agentd_restarted_after_dispatch",
        )?;
        self.composition = composition;
        self.draining = false;
        Ok(changed)
    }

    pub fn begin_drain(&mut self) {
        self.draining = true;
    }

    pub fn is_draining(&self) -> bool {
        self.draining
    }

    pub fn start_run(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_snapshot(now_ms, &snapshot)?;
        if let Some(current) = self.runs.get(&snapshot.run_id) {
            if current.snapshot == snapshot {
                return Ok(receipt(current, /* idempotent */ true));
            }
            return Err(AgentRunError::Conflict);
        }
        if self.draining {
            return Err(AgentRunError::Draining);
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
            cancellation_ack_deadline_ms: None,
        };
        let result = receipt(&record, /* idempotent */ false);
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
            return Ok(receipt(record, /* idempotent */ true));
        }
        require_revision(record, expected_revision)?;
        require_before_deadline(record, now_ms)?;
        if record.phase != RunPhase::Admitted {
            return Err(AgentRunError::InvalidTransition);
        }
        record.context_digest = Some(attachment.context_digest);
        record.compilation_receipt_digest = Some(attachment.compilation_receipt_digest);
        record.phase = RunPhase::ContextAttached;
        advance_revision(record)?;
        Ok(receipt(record, /* idempotent */ false))
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
            return Ok(receipt(record, /* idempotent */ true));
        }
        require_revision(record, expected_revision)?;
        require_before_deadline(record, now_ms)?;
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::ContextRequired);
        }
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;
        Ok(receipt(record, /* idempotent */ false))
    }

    pub fn cancel_run(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        reason: impl Into<String>,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentRunError> {
        validate_identity(run_id, "run")?;
        let reason = normalize_cancel_reason(reason.into())?;
        let cancellation_ack_deadline_ms = cancellation_ack_deadline(
            now_ms,
            self.composition.cancellation_ack_timeout_ms,
        )?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;

        if matches!(record.phase, RunPhase::Cancelling | RunPhase::Cancelled)
            && record.cancel_reason.as_deref() == Some(reason.as_str())
        {
            let disposition = if record.phase == RunPhase::Cancelling {
                CancellationDisposition::CancellingAfterDispatch
            } else {
                CancellationDisposition::AlreadyTerminal
            };
            return Ok((disposition, receipt(record, /* idempotent */ true)));
        }

        require_revision(record, expected_revision)?;
        let disposition = match record.phase {
            RunPhase::Admitted | RunPhase::ContextAttached => {
                record.phase = RunPhase::Cancelled;
                record.cancel_reason = Some(reason);
                record.cancellation_ack_deadline_ms = None;
                advance_revision(record)?;
                CancellationDisposition::CancelledBeforeDispatch
            }
            RunPhase::Dispatched => {
                record.phase = RunPhase::Cancelling;
                record.cancel_reason = Some(reason);
                record.cancellation_ack_deadline_ms = Some(cancellation_ack_deadline_ms);
                advance_revision(record)?;
                CancellationDisposition::CancellingAfterDispatch
            }
            RunPhase::Cancelling => return Err(AgentRunError::Conflict),
            RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed => {
                CancellationDisposition::AlreadyTerminal
            }
            RunPhase::Indeterminate => return Err(AgentRunError::TerminalObservationRequired),
        };
        Ok((disposition, receipt(record, /* idempotent */ false)))
    }

    pub fn expire_deadlines(&mut self, now_ms: u64) -> Result<Vec<RunReceipt>, AgentRunError> {
        let mut expired = Vec::new();
        let cancellation_ack_timeout_ms = self.composition.cancellation_ack_timeout_ms;
        for record in self.runs.values_mut() {
            if is_closed(record.phase) {
                continue;
            }
            if record.phase == RunPhase::Cancelling {
                if record
                    .cancellation_ack_deadline_ms
                    .is_some_and(|deadline| deadline <= now_ms)
                {
                    record.phase = RunPhase::Indeterminate;
                    record.cancellation_ack_deadline_ms = None;
                    advance_revision(record)?;
                    expired.push(receipt(record, /* idempotent */ false));
                }
                continue;
            }
            if record.phase == RunPhase::Indeterminate || record.snapshot.deadline_ms > now_ms {
                continue;
            }
            match record.phase {
                RunPhase::Admitted | RunPhase::ContextAttached => {
                    record.phase = RunPhase::Cancelled;
                    record.cancel_reason = Some("deadline_exceeded".to_string());
                    record.cancellation_ack_deadline_ms = None;
                    advance_revision(record)?;
                    expired.push(receipt(record, /* idempotent */ false));
                }
                RunPhase::Dispatched => {
                    record.phase = RunPhase::Cancelling;
                    record.cancel_reason = Some("deadline_exceeded".to_string());
                    record.cancellation_ack_deadline_ms =
                        Some(cancellation_ack_deadline(now_ms, cancellation_ack_timeout_ms)?);
                    advance_revision(record)?;
                    expired.push(receipt(record, /* idempotent */ false));
                }
                RunPhase::Cancelling
                | RunPhase::Indeterminate
                | RunPhase::Cancelled
                | RunPhase::Succeeded
                | RunPhase::Failed => {}
            }
        }
        Ok(expired)
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
            && ((terminal_observed && is_terminal_observed(phase))
                || (!terminal_observed && phase == RunPhase::Indeterminate))
        {
            return Ok(receipt(record, /* idempotent */ true));
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
            if !is_terminal_observed(phase) {
                return Err(AgentRunError::TerminalObservationRequired);
            }
        } else if phase != RunPhase::Indeterminate {
            return Err(AgentRunError::TerminalObservationRequired);
        }
        record.phase = phase;
        record.cancellation_ack_deadline_ms = None;
        advance_revision(record)?;
        Ok(receipt(record, /* idempotent */ false))
    }

    pub fn remove_closed_run(
        &mut self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self.runs.get(run_id).ok_or(AgentRunError::RunNotFound)?;
        require_revision(record, expected_revision)?;
        if !is_closed(record.phase) {
            return Err(AgentRunError::InvalidTransition);
        }
        let receipt = receipt(record, /* idempotent */ false);
        self.runs.remove(run_id);
        Ok(receipt)
    }

    pub fn run(&self, run_id: &str) -> Option<RunReceipt> {
        self.runs
            .get(run_id)
            .map(|record| receipt(record, /* idempotent */ false))
    }

    pub fn active_run_count(&self) -> usize {
        self.runs
            .values()
            .filter(|record| !is_closed(record.phase))
            .count()
    }

    /// Close safe pre-dispatch work and preserve post-dispatch uncertainty.
    pub fn mark_unfinished_for_shutdown(&mut self) -> Result<Vec<RunReceipt>, AgentRunError> {
        self.mark_unfinished(
            "agentd_shutdown_before_dispatch",
            "agentd_shutdown_after_dispatch",
        )
    }

    fn mark_unfinished(
        &mut self,
        before_dispatch_reason: &str,
        after_dispatch_reason: &str,
    ) -> Result<Vec<RunReceipt>, AgentRunError> {
        let mut changed = Vec::new();
        for record in self.runs.values_mut() {
            match record.phase {
                RunPhase::Admitted | RunPhase::ContextAttached => {
                    record.phase = RunPhase::Cancelled;
                    record.cancel_reason = Some(before_dispatch_reason.to_string());
                    advance_revision(record)?;
                    changed.push(receipt(record, /* idempotent */ false));
                }
                RunPhase::Dispatched | RunPhase::Cancelling => {
                    record.phase = RunPhase::Indeterminate;
                    record.cancellation_ack_deadline_ms = None;
                    if record.cancel_reason.is_none() {
                        record.cancel_reason = Some(after_dispatch_reason.to_string());
                    }
                    advance_revision(record)?;
                    changed.push(receipt(record, /* idempotent */ false));
                }
                RunPhase::Indeterminate => {
                    if record.cancel_reason.is_none() {
                        record.cancel_reason = Some(after_dispatch_reason.to_string());
                        advance_revision(record)?;
                        changed.push(receipt(record, /* idempotent */ false));
                    }
                }
                RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed => {}
            }
        }
        Ok(changed)
    }
}

fn validate_composition(value: &RuntimeComposition) -> Result<(), AgentRunError> {
    validate_identity(&value.agent_id, "agent")?;
    validate_digest(&value.configuration_digest, "configuration")?;
    validate_digest(&value.ports_digest, "ports")?;
    if value.supervisor_generation == 0 || value.agentd_generation == 0 {
        return Err(AgentRunError::InvalidGeneration);
    }
    if !(1..=MAX_CANCELLATION_ACK_TIMEOUT_MS).contains(&value.cancellation_ack_timeout_ms) {
        return Err(AgentRunError::InvalidCancellationAckTimeout);
    }
    Ok(())
}

fn cancellation_ack_deadline(
    now_ms: u64,
    timeout_ms: u64,
) -> Result<u64, AgentRunError> {
    now_ms
        .checked_add(timeout_ms)
        .ok_or(AgentRunError::ArithmeticOverflow)
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
    if value.authority_epoch == 0 || value.deadline_ms == 0 {
        return Err(AgentRunError::InvalidGeneration);
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

fn normalize_cancel_reason(reason: String) -> Result<String, AgentRunError> {
    let reason = reason.trim().to_string();
    validate_cancel_reason(&reason)?;
    Ok(reason)
}

fn validate_cancel_reason(reason: &str) -> Result<(), AgentRunError> {
    if reason.is_empty()
        || reason.len() > MAX_RUN_CANCEL_REASON_BYTES
        || reason.chars().any(char::is_control)
    {
        return Err(AgentRunError::InvalidCancelReason);
    }
    Ok(())
}

fn require_before_deadline(record: &RunRecord, now_ms: u64) -> Result<(), AgentRunError> {
    if now_ms >= record.snapshot.deadline_ms {
        return Err(AgentRunError::DeadlineExceeded);
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

fn is_closed(phase: RunPhase) -> bool {
    matches!(
        phase,
        RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed
    )
}

fn is_terminal_observed(phase: RunPhase) -> bool {
    matches!(
        phase,
        RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed
    )
}

fn receipt(record: &RunRecord, idempotent: bool) -> RunReceipt {
    RunReceipt {
        run_id: record.snapshot.run_id.clone(),
        revision: record.revision,
        phase: record.phase,
        context_digest: record.context_digest.clone(),
        terminal_observed: is_terminal_observed(record.phase),
        idempotent,
        cancel_reason: record.cancel_reason.clone(),
        cancellation_ack_deadline_ms: record.cancellation_ack_deadline_ms,
    }
}

#[cfg(test)]
#[path = "lane_b_runtime_tests.rs"]
mod tests;
