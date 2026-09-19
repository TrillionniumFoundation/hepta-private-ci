use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

const MAX_ACTIVE_RUNS: usize = 256;
const MAX_RETAINED_RUNS: usize = 1_024;
const MAX_CANCELLATION_REASON_BYTES: usize = 512;
const MAX_CANCELLATION_ACK_TIMEOUT_MS: u64 = 60_000;
const MIN_RUN_RECOVERY_SCHEMA_VERSION: u32 = 1;
pub const RUN_RECOVERY_SCHEMA_VERSION: u32 = 2;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
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

    fn externally_uncertain(self) -> bool {
        matches!(
            self,
            Self::Dispatched | Self::Cancelling | Self::Indeterminate
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeComposition {
    pub agent_id: String,
    pub supervisor_generation: u64,
    pub agentd_generation: u64,
    pub configuration_digest: String,
    pub ports_digest: String,
    #[serde(default)]
    pub cancellation_ack_timeout_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunSnapshot {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunReceipt {
    pub run_id: String,
    pub revision: u64,
    pub phase: RunPhase,
    pub context_digest: Option<String>,
    pub cancellation_reason: Option<String>,
    pub cancellation_ack_deadline_ms: Option<u64>,
    pub terminal_observed: bool,
    pub idempotent: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CancellationDisposition {
    CancelledBeforeDispatch,
    CancellingAfterDispatch,
    AlreadyTerminal,
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum AgentRunError {
    #[error("invalid {0} identity")]
    InvalidIdentity(&'static str),
    #[error("invalid {0} digest")]
    InvalidDigest(&'static str),
    #[error("invalid generation or authority epoch")]
    InvalidGeneration,
    #[error("invalid or expired deadline")]
    InvalidDeadline,
    #[error("run deadline has elapsed")]
    DeadlineExceeded,
    #[error("invalid cancellation reason")]
    InvalidCancellationReason,
    #[error("run capacity exceeded")]
    CapacityExceeded,
    #[error("run not found")]
    RunNotFound,
    #[error("operation conflicts with retained run semantics")]
    Conflict,
    #[error("invalid run lifecycle transition")]
    InvalidTransition,
    #[error("stale run revision")]
    StaleRevision,
    #[error("context attachment does not bind the complete frozen run tuple")]
    MixedSnapshot,
    #[error("context attachment is required before dispatch")]
    ContextRequired,
    #[error("terminal owner observation is required")]
    TerminalObservationRequired,
    #[error("run revision overflow")]
    ArithmeticOverflow,
    #[error("invalid recovery state")]
    InvalidRecoveryState,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RunRecord {
    snapshot: RunSnapshot,
    revision: u64,
    phase: RunPhase,
    context_digest: Option<String>,
    compilation_receipt_digest: Option<String>,
    cancellation_reason: Option<String>,
    #[serde(default)]
    cancellation_ack_deadline_ms: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunRecoveryState {
    pub schema_version: u32,
    pub composition: RuntimeComposition,
    records: Vec<RunRecord>,
}

/// Owner-local Lane B coordinator for Agentd.
///
/// This type owns only bounded lifecycle admission and immutable snapshot
/// references. Codex remains the thread/turn execution owner, and durable
/// product-domain facts remain with their canonical modules.
#[derive(Clone, Debug)]
pub struct AgentRunCoordinator {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
}

impl AgentRunCoordinator {
    pub fn compose_runtime(composition: RuntimeComposition) -> Result<Self, AgentRunError> {
        validate_composition(&composition)?;
        Ok(Self {
            composition,
            runs: BTreeMap::new(),
        })
    }

    pub fn restore_runtime(
        composition: RuntimeComposition,
        recovery: RunRecoveryState,
        now_ms: u64,
    ) -> Result<Self, AgentRunError> {
        validate_composition(&composition)?;
        if !(MIN_RUN_RECOVERY_SCHEMA_VERSION..=RUN_RECOVERY_SCHEMA_VERSION)
            .contains(&recovery.schema_version)
            || recovery.records.len() > MAX_RETAINED_RUNS
            || recovery.composition.agent_id != composition.agent_id
            || recovery.composition.configuration_digest != composition.configuration_digest
            || recovery.composition.ports_digest != composition.ports_digest
            || recovery.composition.supervisor_generation > composition.supervisor_generation
            || recovery.composition.agentd_generation > composition.agentd_generation
        {
            return Err(AgentRunError::InvalidRecoveryState);
        }
        let recovery_schema_version = recovery.schema_version;
        if recovery_schema_version == 1 && recovery.composition.cancellation_ack_timeout_ms != 0 {
            return Err(AgentRunError::InvalidRecoveryState);
        }
        let generation_changed = recovery.composition.supervisor_generation
            != composition.supervisor_generation
            || recovery.composition.agentd_generation != composition.agentd_generation;

        let mut runs = BTreeMap::new();
        for mut record in recovery.records {
            validate_recovery_record(&record, recovery_schema_version)?;
            if runs.contains_key(&record.snapshot.run_id) {
                return Err(AgentRunError::InvalidRecoveryState);
            }

            match record.phase {
                RunPhase::Admitted | RunPhase::ContextAttached if generation_changed => {
                    record.phase = RunPhase::Cancelled;
                    record.cancellation_reason =
                        Some("generation_changed_during_restart".to_string());
                    record.cancellation_ack_deadline_ms = None;
                    advance_revision(&mut record)?;
                }
                RunPhase::Admitted | RunPhase::ContextAttached
                    if record.snapshot.deadline_ms <= now_ms =>
                {
                    record.phase = RunPhase::Cancelled;
                    record.cancellation_reason =
                        Some("deadline_exceeded_during_restart".to_string());
                    record.cancellation_ack_deadline_ms = None;
                    advance_revision(&mut record)?;
                }
                RunPhase::Dispatched | RunPhase::Cancelling => {
                    // The process cannot prove whether a prior App Server turn
                    // reached a terminal state. Never redispatch after restart,
                    // including when the supervisor assigned a newer generation.
                    record.phase = RunPhase::Indeterminate;
                    record.cancellation_ack_deadline_ms = None;
                    advance_revision(&mut record)?;
                }
                _ => {}
            }
            runs.insert(record.snapshot.run_id.clone(), record);
        }

        let coordinator = Self { composition, runs };
        if coordinator.active_run_count() > MAX_ACTIVE_RUNS {
            return Err(AgentRunError::InvalidRecoveryState);
        }
        Ok(coordinator)
    }

    pub fn composition(&self) -> &RuntimeComposition {
        &self.composition
    }

    pub fn recovery_state(&self) -> RunRecoveryState {
        RunRecoveryState {
            schema_version: RUN_RECOVERY_SCHEMA_VERSION,
            composition: self.composition.clone(),
            records: self.runs.values().cloned().collect(),
        }
    }

    pub fn start_run(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_snapshot_shape(&snapshot)?;
        if let Some(current) = self.runs.get(&snapshot.run_id) {
            if current.snapshot == snapshot {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
        if snapshot.deadline_ms <= now_ms {
            return Err(AgentRunError::InvalidDeadline);
        }
        if self.active_run_count() >= MAX_ACTIVE_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
        if self.runs.len() >= MAX_RETAINED_RUNS {
            // Closed rows are lifecycle recovery metadata, not an unbounded
            // historical ledger. Compact one deterministic closed identity
            // before rejecting healthy long-running owners at the retention
            // ceiling. Explicit RunRemoveClosed remains an eager cleanup path.
            let closed_run_id = self
                .runs
                .iter()
                .find_map(|(run_id, record)| record.phase.closed().then(|| run_id.clone()))
                .ok_or(AgentRunError::CapacityExceeded)?;
            self.runs.remove(&closed_run_id);
        }
        let record = RunRecord {
            snapshot: snapshot.clone(),
            revision: 1,
            phase: RunPhase::Admitted,
            context_digest: None,
            compilation_receipt_digest: None,
            cancellation_reason: None,
            cancellation_ack_deadline_ms: None,
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
        if record.snapshot.deadline_ms <= now_ms {
            return Err(AgentRunError::DeadlineExceeded);
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
        if record.snapshot.deadline_ms <= now_ms {
            return Err(AgentRunError::DeadlineExceeded);
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
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        reason: &str,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_cancellation_reason(reason)?;
        let cancellation_ack_timeout_ms = self.composition.cancellation_ack_timeout_ms;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;

        if matches!(record.phase, RunPhase::Cancelled | RunPhase::Cancelling) {
            if record.cancellation_reason.as_deref() != Some(reason) {
                return Err(AgentRunError::Conflict);
            }
            let disposition = if record.phase == RunPhase::Cancelling {
                CancellationDisposition::CancellingAfterDispatch
            } else {
                CancellationDisposition::AlreadyTerminal
            };
            return Ok((disposition, receipt(record, /*idempotent*/ true)));
        }

        require_revision(record, expected_revision)?;
        let disposition = match record.phase {
            RunPhase::Admitted | RunPhase::ContextAttached => {
                record.phase = RunPhase::Cancelled;
                record.cancellation_reason = Some(reason.to_string());
                record.cancellation_ack_deadline_ms = None;
                advance_revision(record)?;
                CancellationDisposition::CancelledBeforeDispatch
            }
            RunPhase::Dispatched => {
                record.phase = RunPhase::Cancelling;
                record.cancellation_reason = Some(reason.to_string());
                record.cancellation_ack_deadline_ms = Some(
                    now_ms
                        .checked_add(cancellation_ack_timeout_ms)
                        .ok_or(AgentRunError::ArithmeticOverflow)?,
                );
                advance_revision(record)?;
                CancellationDisposition::CancellingAfterDispatch
            }
            RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed => {
                CancellationDisposition::AlreadyTerminal
            }
            RunPhase::Cancelling => unreachable!("handled above"),
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
        if !record.phase.externally_uncertain() {
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
        record.cancellation_ack_deadline_ms = None;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Apply elapsed deadlines even when no caller is actively mutating a run.
    ///
    /// Pre-dispatch work is safely cancelled locally. Once dispatch may have
    /// happened, deadline expiry becomes a cancellation intent and still
    /// requires an execution-owner terminal observation.
    pub fn enforce_deadlines(&mut self, now_ms: u64) -> Result<Vec<RunReceipt>, AgentRunError> {
        let cancellation_ack_timeout_ms = self.composition.cancellation_ack_timeout_ms;
        let mut changed = Vec::new();
        for record in self.runs.values_mut() {
            if record.phase == RunPhase::Cancelling
                && record
                    .cancellation_ack_deadline_ms
                    .is_some_and(|deadline| deadline <= now_ms)
            {
                record.phase = RunPhase::Indeterminate;
                record.cancellation_ack_deadline_ms = None;
                advance_revision(record)?;
                changed.push(receipt(record, /*idempotent*/ false));
                continue;
            }

            if record.snapshot.deadline_ms > now_ms {
                continue;
            }
            match record.phase {
                RunPhase::Admitted | RunPhase::ContextAttached => {
                    record.phase = RunPhase::Cancelled;
                    record.cancellation_reason = Some("deadline_exceeded".to_string());
                    record.cancellation_ack_deadline_ms = None;
                    advance_revision(record)?;
                    changed.push(receipt(record, /*idempotent*/ false));
                }
                RunPhase::Dispatched => {
                    record.phase = RunPhase::Cancelling;
                    record.cancellation_reason = Some("deadline_exceeded".to_string());
                    record.cancellation_ack_deadline_ms = Some(
                        now_ms
                            .checked_add(cancellation_ack_timeout_ms)
                            .ok_or(AgentRunError::ArithmeticOverflow)?,
                    );
                    advance_revision(record)?;
                    changed.push(receipt(record, /*idempotent*/ false));
                }
                RunPhase::Cancelling
                | RunPhase::Cancelled
                | RunPhase::Succeeded
                | RunPhase::Failed
                | RunPhase::Indeterminate => {}
            }
        }
        Ok(changed)
    }

    pub fn begin_drain(&mut self, reason: &str) -> Result<Vec<RunReceipt>, AgentRunError> {
        validate_cancellation_reason(reason)?;
        let mut changed = Vec::new();
        for record in self.runs.values_mut() {
            match record.phase {
                RunPhase::Admitted | RunPhase::ContextAttached => {
                    record.phase = RunPhase::Cancelled;
                    record.cancellation_reason = Some(reason.to_string());
                    record.cancellation_ack_deadline_ms = None;
                    advance_revision(record)?;
                    changed.push(receipt(record, /*idempotent*/ false));
                }
                RunPhase::Dispatched => {
                    // Graceful drain is not an interrupt. Keep the external
                    // execution state unchanged and wait for its owner to
                    // report terminality. Shutdown timeout will preserve any
                    // remaining uncertainty as Indeterminate.
                }
                RunPhase::Cancelling
                | RunPhase::Cancelled
                | RunPhase::Succeeded
                | RunPhase::Failed
                | RunPhase::Indeterminate => {}
            }
        }
        Ok(changed)
    }

    /// Before process exit, preserve any still-unobserved external outcome as
    /// indeterminate. This state is durable/recoverable and must never be
    /// replayed as a fresh dispatch after restart.
    pub fn mark_unobserved_external_indeterminate(
        &mut self,
    ) -> Result<Vec<RunReceipt>, AgentRunError> {
        let mut changed = Vec::new();
        for record in self.runs.values_mut() {
            if matches!(record.phase, RunPhase::Dispatched | RunPhase::Cancelling) {
                record.phase = RunPhase::Indeterminate;
                record.cancellation_ack_deadline_ms = None;
                advance_revision(record)?;
                changed.push(receipt(record, /*idempotent*/ false));
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

    pub fn pending_external_run_count(&self) -> usize {
        self.runs
            .values()
            .filter(|record| record.phase.externally_uncertain())
            .count()
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
        return Err(AgentRunError::InvalidDeadline);
    }
    Ok(())
}

fn validate_snapshot_shape(value: &RunSnapshot) -> Result<(), AgentRunError> {
    validate_identity(&value.run_id, "run")?;
    for (digest, field) in [
        (&value.request_digest, "request"),
        (&value.objective_digest, "objective"),
        (&value.body_digest, "body"),
        (&value.artifact_set_digest, "artifact set"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.authority_epoch == 0 || value.deadline_ms == 0 {
        return Err(AgentRunError::InvalidGeneration);
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

fn validate_recovery_record(
    record: &RunRecord,
    recovery_schema_version: u32,
) -> Result<(), AgentRunError> {
    validate_snapshot_shape(&record.snapshot)?;
    if record.revision == 0 {
        return Err(AgentRunError::InvalidRecoveryState);
    }
    if let Some(reason) = record.cancellation_reason.as_deref() {
        validate_cancellation_reason(reason)?;
    }
    if recovery_schema_version >= 2 {
        if record.phase == RunPhase::Cancelling {
            if record.cancellation_ack_deadline_ms.is_none() {
                return Err(AgentRunError::InvalidRecoveryState);
            }
        } else if record.cancellation_ack_deadline_ms.is_some() {
            return Err(AgentRunError::InvalidRecoveryState);
        }
    } else if record.cancellation_ack_deadline_ms.is_some() {
        return Err(AgentRunError::InvalidRecoveryState);
    }
    match record.phase {
        RunPhase::Admitted => {
            if record.context_digest.is_some() || record.compilation_receipt_digest.is_some() {
                return Err(AgentRunError::InvalidRecoveryState);
            }
        }
        RunPhase::ContextAttached
        | RunPhase::Dispatched
        | RunPhase::Cancelling
        | RunPhase::Succeeded
        | RunPhase::Failed
        | RunPhase::Indeterminate => {
            if record.context_digest.is_none() || record.compilation_receipt_digest.is_none() {
                return Err(AgentRunError::InvalidRecoveryState);
            }
        }
        RunPhase::Cancelled => {}
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

fn validate_cancellation_reason(value: &str) -> Result<(), AgentRunError> {
    if value.trim().is_empty()
        || value.len() > MAX_CANCELLATION_REASON_BYTES
        || value.as_bytes().contains(&0)
    {
        return Err(AgentRunError::InvalidCancellationReason);
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
        cancellation_reason: record.cancellation_reason.clone(),
        cancellation_ack_deadline_ms: record.cancellation_ack_deadline_ms,
        terminal_observed: record.phase.terminal_observed(),
        idempotent,
    }
}

#[cfg(test)]
#[path = "lane_b_runtime_tests.rs"]
mod tests;
