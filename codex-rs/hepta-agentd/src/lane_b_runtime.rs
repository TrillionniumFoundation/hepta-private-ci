use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
#[cfg(unix)]
use std::os::fd::AsRawFd;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use codex_hepta_agent_components::learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;
use codex_hepta_agent_components::types::Digest32;

const MAX_SUPPORTED_ACTIVE_RUNS: usize = 256;
const MAX_RETAINED_RUNS: usize = 1_024;
const DURABLE_RUN_STORE_SCHEMA_VERSION: u32 = 2;
const MAX_DURABLE_RUN_STORE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_CANCEL_REASON_BYTES: usize = 512;
const CANCEL_ACK_TIMEOUT_MS: u64 = 3_000;
const DEADLINE_CANCEL_REASON: &str = "deadline_elapsed";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunPhase {
    Admitted,
    ContextAttached,
    Dispatched,
    /// The exact dispatch was durably prepared by both owners, but the worker
    /// proved that no external effect boundary was crossed.
    AbortedBeforeEffect,
    Cancelling,
    Cancelled,
    Succeeded,
    Failed,
    Indeterminate,
}

impl RunPhase {
    fn closed(self) -> bool {
        matches!(
            self,
            Self::AbortedBeforeEffect | Self::Cancelled | Self::Succeeded | Self::Failed
        )
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RuntimeComposition {
    pub agent_id: String,
    pub supervisor_generation: u64,
    pub agentd_generation: u64,
    pub configuration_digest: String,
    pub ports_digest: String,
    pub max_active_runs: usize,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RunSnapshot {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: String,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ContextAttachment {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: String,
    pub deadline_ms: u64,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RunRecovery {
    pub snapshot: RunSnapshot,
    pub revision: u64,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
    pub cancel_reason: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RunReceipt {
    pub run_id: String,
    pub revision: u64,
    pub phase: RunPhase,
    pub context_digest: Option<String>,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: String,
    pub deadline_ms: u64,
    pub cancel_reason: Option<String>,
    pub cancel_ack_deadline_ms: Option<u64>,
    pub compilation_receipt_digest: Option<String>,
    /// Exact runtime.codex request/dispatch binding committed before the
    /// physical effect boundary. Legacy callers leave this empty and therefore
    /// cannot use the exact pre-effect abort transition.
    pub dispatch_binding_digest: Option<String>,
    /// Commitment to the live worker's non-serializable abort nonce. Agentd
    /// records it at the same transition that records Dispatched.
    pub pre_effect_abort_commitment_digest: Option<String>,
    /// Durable proof identity accepted by Agentd for a definitely-unsent
    /// dispatch. This is deliberately not a provider terminal observation.
    pub pre_effect_abort_proof_digest: Option<String>,
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
    InvalidRunStart(&'static str),
    Persistence(String),
}

impl std::fmt::Display for AgentRunError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentRunError {}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct RunRecord {
    snapshot: RunSnapshot,
    revision: u64,
    phase: RunPhase,
    context_digest: Option<String>,
    compilation_receipt_digest: Option<String>,
    dispatch_binding_digest: Option<String>,
    pre_effect_abort_commitment_digest: Option<String>,
    pre_effect_abort_proof_digest: Option<String>,
    cancel_reason: Option<String>,
    cancel_ack_deadline_ms: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableRunTombstoneV1 {
    snapshot: RunSnapshot,
    receipt: RunReceipt,
    record_sha256: String,
    removed_at_store_revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableRunStoreV1 {
    schema_version: u32,
    store_revision: u64,
    previous_store_sha256: Option<String>,
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    tombstones: BTreeMap<String, DurableRunTombstoneV1>,
    accepting_runs: bool,
    max_active_runs: usize,
}

/// Owner-local Lane B coordinator for Agentd.
///
/// This type owns only run admission and immutable snapshot references. Codex
/// remains the thread/turn execution owner, and domain stores remain with their
/// canonical modules. Recovery can only rehydrate a previously-dispatched run
/// as indeterminate; it can never authorize redispatch.
#[derive(Clone, Debug)]
pub struct AgentRunCoordinator {
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    accepting_runs: bool,
    max_active_runs: usize,
    durable_path: Option<PathBuf>,
    durable_store_revision: u64,
    committed_store_sha256: Option<String>,
    tombstones: BTreeMap<String, DurableRunTombstoneV1>,
}

impl AgentRunCoordinator {
    pub fn compose_runtime(composition: RuntimeComposition) -> Result<Self, AgentRunError> {
        validate_identity(&composition.agent_id, "agent")?;
        validate_digest(&composition.configuration_digest, "configuration")?;
        validate_digest(&composition.ports_digest, "ports")?;
        if composition.supervisor_generation == 0 || composition.agentd_generation == 0 {
            return Err(AgentRunError::InvalidGeneration);
        }
        if !(1..=MAX_SUPPORTED_ACTIVE_RUNS).contains(&composition.max_active_runs) {
            return Err(AgentRunError::CapacityExceeded);
        }
        let max_active_runs = composition.max_active_runs;
        Ok(Self {
            composition,
            runs: BTreeMap::new(),
            accepting_runs: true,
            max_active_runs,
            durable_path: None,
            durable_store_revision: 0,
            committed_store_sha256: None,
            tombstones: BTreeMap::new(),
        })
    }

    /// Open the product run owner from a crash-consistent snapshot. The exact
    /// runtime composition is part of the durable identity, so a different
    /// Agent/generation/configuration cannot adopt this store.
    pub fn open_durable(
        composition: RuntimeComposition,
        durable_path: PathBuf,
    ) -> Result<Self, AgentRunError> {
        if !durable_path.is_absolute() {
            return Err(AgentRunError::Persistence(
                "durable run store path must be absolute".to_string(),
            ));
        }
        let parent = durable_path.parent().ok_or_else(|| {
            AgentRunError::Persistence("durable run store has no parent".to_string())
        })?;
        fs::create_dir_all(parent).map_err(|error| {
            AgentRunError::Persistence(format!("create durable run store parent: {error}"))
        })?;
        let _lock = DurableRunStoreLock::acquire(&durable_path)?;
        if let Some(store) = load_durable_run_store(&durable_path)? {
            validate_durable_run_store(&store, &composition)?;
            let committed_store_sha256 = durable_run_store_sha256(&store)?;
            return Ok(Self {
                composition,
                runs: store.runs,
                accepting_runs: store.accepting_runs,
                max_active_runs: store.max_active_runs,
                durable_path: Some(durable_path),
                durable_store_revision: store.store_revision,
                committed_store_sha256: Some(committed_store_sha256),
                tombstones: store.tombstones,
            });
        }
        drop(_lock);
        let mut coordinator = Self::compose_runtime(composition)?;
        coordinator.durable_path = Some(durable_path);
        coordinator.persist()?;
        Ok(coordinator)
    }

    /// Publish the complete owner state before a product RPC is acknowledged.
    /// The lock serializes writers and `store_revision` fences stale processes.
    pub fn persist(&mut self) -> Result<(), AgentRunError> {
        let Some(path) = self.durable_path.clone() else {
            return Ok(());
        };
        let _lock = DurableRunStoreLock::acquire(&path)?;
        let on_disk = load_durable_run_store(&path)?;
        let observed_revision = on_disk.as_ref().map_or(0, |store| store.store_revision);
        let observed_store_sha256 = on_disk.as_ref().map(durable_run_store_sha256).transpose()?;
        if observed_revision != self.durable_store_revision
            || observed_store_sha256 != self.committed_store_sha256
        {
            return Err(AgentRunError::Persistence(format!(
                "stale durable run writer: expected revision {} and digest {:?}, observed revision {observed_revision} and digest {observed_store_sha256:?}",
                self.durable_store_revision, self.committed_store_sha256,
            )));
        }
        if let Some(store) = on_disk.as_ref()
            && store.composition != self.composition
        {
            return Err(AgentRunError::Persistence(
                "durable run store composition changed".to_string(),
            ));
        }
        let next_revision = self
            .durable_store_revision
            .checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        let store = DurableRunStoreV1 {
            schema_version: DURABLE_RUN_STORE_SCHEMA_VERSION,
            store_revision: next_revision,
            previous_store_sha256: observed_store_sha256,
            composition: self.composition.clone(),
            runs: self.runs.clone(),
            tombstones: self.tombstones.clone(),
            accepting_runs: self.accepting_runs,
            max_active_runs: self.max_active_runs,
        };
        validate_durable_run_store(&store, &self.composition)?;
        let committed_store_sha256 = durable_run_store_sha256(&store)?;
        atomic_replace_durable_run_store(&path, &store)?;
        self.durable_store_revision = next_revision;
        self.committed_store_sha256 = Some(committed_store_sha256);
        Ok(())
    }

    /// Persist a fully prepared candidate and publish it to in-process readers
    /// only after the durable store accepted the exact preceding revision.
    /// On every error `self` remains byte-for-byte at its last committed state.
    pub(crate) fn publish_candidate<T>(
        &mut self,
        mut candidate: Self,
        value: T,
    ) -> Result<T, AgentRunError> {
        if candidate.composition != self.composition
            || candidate.durable_path != self.durable_path
            || candidate.durable_store_revision != self.durable_store_revision
        {
            return Err(AgentRunError::Persistence(
                "durable run candidate did not originate from the current owner revision"
                    .to_string(),
            ));
        }
        candidate.persist()?;
        *self = candidate;
        Ok(value)
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
        if self.tombstones.contains_key(&snapshot.run_id) {
            return Err(AgentRunError::Conflict);
        }
        if let Some(current) = self.runs.get(&snapshot.run_id) {
            if current.snapshot == snapshot {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
        if !self.accepting_runs {
            return Err(AgentRunError::AdmissionClosed);
        }
        if self.active_run_count() >= self.max_active_runs
            || self.runs.len().saturating_add(self.tombstones.len()) >= MAX_RETAINED_RUNS
        {
            return Err(AgentRunError::CapacityExceeded);
        }
        let record = RunRecord {
            snapshot: snapshot.clone(),
            revision: 1,
            phase: RunPhase::Admitted,
            context_digest: None,
            compilation_receipt_digest: None,
            dispatch_binding_digest: None,
            pre_effect_abort_commitment_digest: None,
            pre_effect_abort_proof_digest: None,
            cancel_reason: None,
            cancel_ack_deadline_ms: None,
        };
        let result = receipt(&record, /*idempotent*/ false);
        self.runs.insert(snapshot.run_id, record);
        Ok(result)
    }

    /// Admit one durable run-start record only after the product owner has
    /// revalidated its authentication/currentness against the live trust
    /// frontier. This method deliberately does not authenticate raw records.
    /// It only fixes the canonical durable-owner -> daemon-owner projection.
    pub(crate) fn start_revalidated_run_start(
        &mut self,
        now_ms: u64,
        record: &RunStartRecordV1,
    ) -> Result<RunReceipt, AgentRunError> {
        if record.objective_function_v1_digest.is_zero()
            || record.objective_function_v1_bytes.is_empty()
        {
            return Err(AgentRunError::InvalidRunStart(
                "canonical ObjectiveFunctionV1 identity",
            ));
        }
        if record.disposition != RunStartObjectiveDispositionV1::Compiled {
            return Err(AgentRunError::InvalidRunStart("objective disposition"));
        }
        if record.admission.authority.grants_any() {
            return Err(AgentRunError::InvalidRunStart("authority"));
        }
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        self.start_run(
            now_ms,
            RunSnapshot {
                run_id: record.snapshot.run_id.to_string(),
                request_digest: record.admission.admitted_source_digest.to_string(),
                objective_digest: record.snapshot.objective_digest.to_string(),
                body_digest: record.runtime_body_digest.to_string(),
                artifact_set_digest: record.snapshot.artifact_set_digest.to_string(),
                authority_epoch: record.snapshot.authority_epoch,
                generation: record.snapshot.generation,
                fence_digest: record.snapshot.fence_digest.to_string(),
                deadline_ms,
            },
        )
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
            || attachment.generation != record.snapshot.generation
            || attachment.fence_digest != record.snapshot.fence_digest
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

    /// Legacy dispatch transition. It remains for compatibility, but because it
    /// carries no exact external binding it cannot later prove a pre-effect
    /// abort across the owner boundary.
    pub fn mark_dispatched(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mark_dispatched_inner(now_ms, run_id, expected_revision, None, None)
    }

    /// Commit the exact runtime.codex dispatch identity and the live worker's
    /// nonce commitment at the Agentd owner.
    pub fn mark_dispatched_bound(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_binding_digest: String,
        pre_effect_abort_commitment_digest: String,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_digest(&dispatch_binding_digest, "dispatch binding")?;
        validate_digest(
            &pre_effect_abort_commitment_digest,
            "pre-effect abort commitment",
        )?;
        self.mark_dispatched_inner(
            now_ms,
            run_id,
            expected_revision,
            Some(dispatch_binding_digest),
            Some(pre_effect_abort_commitment_digest),
        )
    }

    fn mark_dispatched_inner(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_binding_digest: Option<String>,
        pre_effect_abort_commitment_digest: Option<String>,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        if dispatch_binding_digest.is_some() != pre_effect_abort_commitment_digest.is_some() {
            return Err(AgentRunError::InvalidTransition);
        }
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Dispatched {
            return if record.dispatch_binding_digest == dispatch_binding_digest
                && record.pre_effect_abort_commitment_digest == pre_effect_abort_commitment_digest
            {
                Ok(receipt(record, /*idempotent*/ true))
            } else {
                Err(AgentRunError::Conflict)
            };
        }
        require_revision(record, expected_revision)?;
        require_live_deadline(record, now_ms)?;
        if record.phase == RunPhase::Indeterminate {
            return Err(AgentRunError::InvalidTransition);
        }
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::ContextRequired);
        }
        record.dispatch_binding_digest = dispatch_binding_digest;
        record.pre_effect_abort_commitment_digest = pre_effect_abort_commitment_digest;
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Close a bound dispatch as definitely unsent without inventing a
    /// provider terminal observation. The nonce opens the commitment stored by
    /// mark_dispatched_bound, and the proof additionally binds the reason.
    pub fn abort_before_effect(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        dispatch_binding_digest: &str,
        abort_nonce_hex: &str,
        proof_digest: &str,
        reason: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_digest(dispatch_binding_digest, "dispatch binding")?;
        validate_digest(proof_digest, "pre-effect abort proof")?;
        validate_cancel_reason(reason)?;
        let nonce = decode_abort_nonce_hex(abort_nonce_hex)?;
        let expected_commitment =
            pre_effect_abort_commitment(run_id, dispatch_binding_digest, &nonce);
        let expected_proof =
            pre_effect_abort_proof(run_id, dispatch_binding_digest, &nonce, reason);
        if expected_proof != proof_digest {
            return Err(AgentRunError::Conflict);
        }

        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::AbortedBeforeEffect {
            let same = record.dispatch_binding_digest.as_deref() == Some(dispatch_binding_digest)
                && record.pre_effect_abort_commitment_digest.as_deref()
                    == Some(expected_commitment.as_str())
                && record.pre_effect_abort_proof_digest.as_deref() == Some(proof_digest)
                && record.cancel_reason.as_deref() == Some(reason);
            return if same {
                Ok(receipt(record, /*idempotent*/ true))
            } else {
                Err(AgentRunError::Conflict)
            };
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Dispatched {
            return Err(AgentRunError::InvalidTransition);
        }
        if record.dispatch_binding_digest.as_deref() != Some(dispatch_binding_digest)
            || record.pre_effect_abort_commitment_digest.as_deref()
                != Some(expected_commitment.as_str())
        {
            return Err(AgentRunError::Conflict);
        }
        record.phase = RunPhase::AbortedBeforeEffect;
        record.pre_effect_abort_proof_digest = Some(proof_digest.to_string());
        record.cancel_reason = Some(reason.to_string());
        record.cancel_ack_deadline_ms = None;
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
                record.cancel_ack_deadline_ms = Some(cancel_ack_deadline(now_ms)?);
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
            RunPhase::AbortedBeforeEffect
            | RunPhase::Cancelled
            | RunPhase::Succeeded
            | RunPhase::Failed => {
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
        record.cancel_ack_deadline_ms = None;
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
        if self.active_run_count() >= self.max_active_runs
            || self.runs.len().saturating_add(self.tombstones.len()) >= MAX_RETAINED_RUNS
        {
            return Err(AgentRunError::CapacityExceeded);
        }
        let record = RunRecord {
            snapshot: recovery.snapshot,
            revision: recovery.revision,
            phase: RunPhase::Indeterminate,
            context_digest: Some(recovery.context_digest),
            compilation_receipt_digest: Some(recovery.compilation_receipt_digest),
            dispatch_binding_digest: None,
            pre_effect_abort_commitment_digest: None,
            pre_effect_abort_proof_digest: None,
            cancel_reason: recovery.cancel_reason,
            cancel_ack_deadline_ms: None,
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
                    record.cancel_ack_deadline_ms = Some(cancel_ack_deadline(now_ms)?);
                    advance_revision(record)?;
                }
                RunPhase::AbortedBeforeEffect
                | RunPhase::Cancelling
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
                record.cancel_ack_deadline_ms = None;
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
        if let Some(tombstone) = self.tombstones.get(run_id) {
            if tombstone.receipt.revision != expected_revision {
                return Err(AgentRunError::StaleRevision);
            }
            let mut receipt = tombstone.receipt.clone();
            receipt.idempotent = true;
            return Ok(receipt);
        }
        let record = self.runs.get(run_id).ok_or(AgentRunError::RunNotFound)?;
        require_revision(record, expected_revision)?;
        if !record.phase.closed() {
            return Err(AgentRunError::InvalidTransition);
        }
        let receipt = receipt(record, /*idempotent*/ false);
        let snapshot = record.snapshot.clone();
        let record_sha256 = durable_run_tombstone_sha256(&snapshot, &receipt)?;
        let removed_at_store_revision = self
            .durable_store_revision
            .checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        self.tombstones.insert(
            run_id.to_string(),
            DurableRunTombstoneV1 {
                snapshot,
                receipt: receipt.clone(),
                record_sha256,
                removed_at_store_revision,
            },
        );
        self.runs.remove(run_id);
        Ok(receipt)
    }

    pub fn run(&self, run_id: &str) -> Option<RunReceipt> {
        self.runs
            .get(run_id)
            .map(|record| receipt(record, /*idempotent*/ false))
            .or_else(|| {
                self.tombstones.get(run_id).map(|tombstone| {
                    let mut receipt = tombstone.receipt.clone();
                    receipt.idempotent = false;
                    receipt
                })
            })
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

struct DurableRunStoreLock {
    file: File,
}

impl DurableRunStoreLock {
    fn acquire(store_path: &Path) -> Result<Self, AgentRunError> {
        let lock_path = store_path.with_extension("lock");
        let file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|error| {
                AgentRunError::Persistence(format!("open durable run store lock: {error}"))
            })?;
        #[cfg(unix)]
        {
            // SAFETY: flock receives a valid owned file descriptor. The file is
            // retained by this guard until Drop releases the advisory lock.
            let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) };
            if result != 0 {
                return Err(AgentRunError::Persistence(format!(
                    "lock durable run store: {}",
                    std::io::Error::last_os_error()
                )));
            }
        }
        Ok(Self { file })
    }
}

impl Drop for DurableRunStoreLock {
    fn drop(&mut self) {
        #[cfg(unix)]
        {
            // SAFETY: this guard still owns the descriptor locked in acquire.
            let _ = unsafe { libc::flock(self.file.as_raw_fd(), libc::LOCK_UN) };
        }
    }
}

fn load_durable_run_store(path: &Path) -> Result<Option<DurableRunStoreV1>, AgentRunError> {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(AgentRunError::Persistence(format!(
                "open durable run store: {error}"
            )));
        }
    };
    let length = file
        .metadata()
        .map_err(|error| AgentRunError::Persistence(format!("stat durable run store: {error}")))?
        .len();
    if length == 0 || length > MAX_DURABLE_RUN_STORE_BYTES {
        return Err(AgentRunError::Persistence(
            "durable run store size is invalid".to_string(),
        ));
    }
    let capacity = usize::try_from(length).map_err(|_| {
        AgentRunError::Persistence("durable run store length exceeds usize".to_string())
    })?;
    let mut bytes = Vec::with_capacity(capacity);
    file.read_to_end(&mut bytes)
        .map_err(|error| AgentRunError::Persistence(format!("read durable run store: {error}")))?;
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|error| AgentRunError::Persistence(format!("decode durable run store: {error}")))
}

fn validate_durable_run_store(
    store: &DurableRunStoreV1,
    expected_composition: &RuntimeComposition,
) -> Result<(), AgentRunError> {
    if store.schema_version != DURABLE_RUN_STORE_SCHEMA_VERSION
        || store.store_revision == 0
        || &store.composition != expected_composition
        || store.max_active_runs != expected_composition.max_active_runs
        || !(1..=MAX_SUPPORTED_ACTIVE_RUNS).contains(&store.max_active_runs)
        || store.runs.len().saturating_add(store.tombstones.len()) > MAX_RETAINED_RUNS
    {
        return Err(AgentRunError::Persistence(
            "durable run store identity or bounds are invalid".to_string(),
        ));
    }
    match (store.store_revision, store.previous_store_sha256.as_deref()) {
        (1, None) => {}
        (1, Some(_)) | (_, None) => {
            return Err(AgentRunError::Persistence(
                "durable run store predecessor binding is invalid".to_string(),
            ));
        }
        (_, Some(digest)) => validate_digest(digest, "durable previous store")?,
    }
    let mut active = 0usize;
    for (run_id, record) in &store.runs {
        validate_snapshot_fields(&record.snapshot)?;
        if run_id != &record.snapshot.run_id || record.revision == 0 {
            return Err(AgentRunError::Persistence(
                "durable run record identity is invalid".to_string(),
            ));
        }
        if record.context_digest.is_some() != record.compilation_receipt_digest.is_some() {
            return Err(AgentRunError::Persistence(
                "durable run context binding is partial".to_string(),
            ));
        }
        if matches!(
            record.phase,
            RunPhase::ContextAttached
                | RunPhase::Dispatched
                | RunPhase::AbortedBeforeEffect
                | RunPhase::Cancelling
                | RunPhase::Succeeded
                | RunPhase::Failed
                | RunPhase::Indeterminate
        ) && record.context_digest.is_none()
        {
            return Err(AgentRunError::Persistence(
                "durable post-context run omitted context binding".to_string(),
            ));
        }
        if record.dispatch_binding_digest.is_some()
            != record.pre_effect_abort_commitment_digest.is_some()
        {
            return Err(AgentRunError::Persistence(
                "durable bound dispatch is partial".to_string(),
            ));
        }
        if record.pre_effect_abort_proof_digest.is_some()
            != (record.phase == RunPhase::AbortedBeforeEffect)
        {
            return Err(AgentRunError::Persistence(
                "durable pre-effect abort proof has an invalid phase".to_string(),
            ));
        }
        if record.phase == RunPhase::AbortedBeforeEffect
            && (record.dispatch_binding_digest.is_none()
                || record.pre_effect_abort_commitment_digest.is_none()
                || record.cancel_reason.is_none())
        {
            return Err(AgentRunError::Persistence(
                "durable pre-effect abort is incomplete".to_string(),
            ));
        }
        if let Some(value) = record.context_digest.as_deref() {
            validate_digest(value, "context")?;
        }
        if let Some(value) = record.compilation_receipt_digest.as_deref() {
            validate_digest(value, "compilation receipt")?;
        }
        if let Some(value) = record.dispatch_binding_digest.as_deref() {
            validate_digest(value, "dispatch binding")?;
        }
        if let Some(value) = record.pre_effect_abort_commitment_digest.as_deref() {
            validate_digest(value, "pre-effect abort commitment")?;
        }
        if let Some(value) = record.pre_effect_abort_proof_digest.as_deref() {
            validate_digest(value, "pre-effect abort proof")?;
        }
        if let Some(reason) = record.cancel_reason.as_deref() {
            validate_cancel_reason(reason)?;
        }
        if !record.phase.closed() {
            active = active
                .checked_add(1)
                .ok_or(AgentRunError::ArithmeticOverflow)?;
        }
    }
    for (run_id, tombstone) in &store.tombstones {
        if store.runs.contains_key(run_id)
            || run_id != &tombstone.snapshot.run_id
            || run_id != &tombstone.receipt.run_id
            || tombstone.receipt.revision == 0
            || !tombstone.receipt.phase.closed()
            || tombstone.receipt.terminal_observed != tombstone.receipt.phase.terminal_observed()
            || tombstone.removed_at_store_revision == 0
            || tombstone.removed_at_store_revision > store.store_revision
        {
            return Err(AgentRunError::Persistence(
                "durable run tombstone identity or phase is invalid".to_string(),
            ));
        }
        validate_snapshot_fields(&tombstone.snapshot)?;
        validate_digest(&tombstone.record_sha256, "durable run tombstone")?;
        if tombstone.record_sha256
            != durable_run_tombstone_sha256(&tombstone.snapshot, &tombstone.receipt)?
        {
            return Err(AgentRunError::Persistence(
                "durable run tombstone digest changed".to_string(),
            ));
        }
        for (value, field) in [
            (
                tombstone.receipt.context_digest.as_deref(),
                "tombstone context",
            ),
            (
                tombstone.receipt.compilation_receipt_digest.as_deref(),
                "tombstone compilation receipt",
            ),
            (
                tombstone.receipt.dispatch_binding_digest.as_deref(),
                "tombstone dispatch binding",
            ),
            (
                tombstone
                    .receipt
                    .pre_effect_abort_commitment_digest
                    .as_deref(),
                "tombstone abort commitment",
            ),
            (
                tombstone.receipt.pre_effect_abort_proof_digest.as_deref(),
                "tombstone abort proof",
            ),
        ] {
            if let Some(value) = value {
                validate_digest(value, field)?;
            }
        }
        if let Some(reason) = tombstone.receipt.cancel_reason.as_deref() {
            validate_cancel_reason(reason)?;
        }
    }
    if active > store.max_active_runs {
        return Err(AgentRunError::Persistence(
            "durable active run count exceeds capacity".to_string(),
        ));
    }
    Ok(())
}

fn durable_run_store_sha256(store: &DurableRunStoreV1) -> Result<String, AgentRunError> {
    let encoded = serde_json::to_vec(store).map_err(|error| {
        AgentRunError::Persistence(format!("encode durable run store digest: {error}"))
    })?;
    let mut bytes = b"hepta.runtime.codex.agentd-run-store.v2\0".to_vec();
    bytes.extend_from_slice(&encoded);
    Ok(Digest32::of_bytes(&bytes).to_string())
}

fn durable_run_tombstone_sha256(
    snapshot: &RunSnapshot,
    receipt: &RunReceipt,
) -> Result<String, AgentRunError> {
    let encoded = serde_json::to_vec(&(snapshot, receipt)).map_err(|error| {
        AgentRunError::Persistence(format!("encode durable run tombstone: {error}"))
    })?;
    let mut bytes = b"hepta.runtime.codex.agentd-run-tombstone.v1\0".to_vec();
    bytes.extend_from_slice(&encoded);
    Ok(Digest32::of_bytes(&bytes).to_string())
}

fn atomic_replace_durable_run_store(
    path: &Path,
    store: &DurableRunStoreV1,
) -> Result<(), AgentRunError> {
    let bytes = serde_json::to_vec(store).map_err(|error| {
        AgentRunError::Persistence(format!("encode durable run store: {error}"))
    })?;
    if bytes.is_empty()
        || u64::try_from(bytes.len()).map_err(|_| AgentRunError::ArithmeticOverflow)?
            > MAX_DURABLE_RUN_STORE_BYTES
    {
        return Err(AgentRunError::Persistence(
            "encoded durable run store exceeds its bound".to_string(),
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| AgentRunError::Persistence("durable run store has no parent".to_string()))?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| {
            AgentRunError::Persistence("durable run store filename is invalid".to_string())
        })?;
    let temp_path = parent.join(format!(
        ".{file_name}.{}.{}.tmp",
        std::process::id(),
        store.store_revision
    ));
    match fs::remove_file(&temp_path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(AgentRunError::Persistence(format!(
                "remove stale durable run temp: {error}"
            )));
        }
    }
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp_path)
        .map_err(|error| AgentRunError::Persistence(format!("create durable run temp: {error}")))?;
    let write_result = (|| {
        file.write_all(&bytes)?;
        file.sync_all()?;
        fs::rename(&temp_path, path)?;
        #[cfg(unix)]
        File::open(parent)?.sync_all()?;
        Ok::<(), std::io::Error>(())
    })();
    if let Err(error) = write_result {
        let _ = fs::remove_file(&temp_path);
        return Err(AgentRunError::Persistence(format!(
            "publish durable run store: {error}"
        )));
    }
    Ok(())
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
        (&value.fence_digest, "fence"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.authority_epoch == 0 || value.generation == 0 {
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
        (&value.fence_digest, "fence"),
        (&value.context_digest, "context"),
        (&value.compilation_receipt_digest, "compilation receipt"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.authority_epoch == 0 || value.generation == 0 {
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
    if record.phase == RunPhase::Cancelling
        && record
            .cancel_ack_deadline_ms
            .is_some_and(|deadline| deadline <= now_ms)
    {
        record.phase = RunPhase::Indeterminate;
        record.cancel_ack_deadline_ms = None;
        advance_revision(record)?;
        return Ok(true);
    }
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
            record.cancel_ack_deadline_ms = Some(cancel_ack_deadline(now_ms)?);
            advance_revision(record)?;
            Ok(true)
        }
        RunPhase::AbortedBeforeEffect
        | RunPhase::Cancelling
        | RunPhase::Cancelled
        | RunPhase::Succeeded
        | RunPhase::Failed
        | RunPhase::Indeterminate => Ok(false),
    }
}

fn cancel_ack_deadline(now_ms: u64) -> Result<u64, AgentRunError> {
    now_ms
        .checked_add(CANCEL_ACK_TIMEOUT_MS)
        .ok_or(AgentRunError::ArithmeticOverflow)
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
        generation: record.snapshot.generation,
        fence_digest: record.snapshot.fence_digest.clone(),
        deadline_ms: record.snapshot.deadline_ms,
        cancel_reason: record.cancel_reason.clone(),
        cancel_ack_deadline_ms: record.cancel_ack_deadline_ms,
        compilation_receipt_digest: record.compilation_receipt_digest.clone(),
        dispatch_binding_digest: record.dispatch_binding_digest.clone(),
        pre_effect_abort_commitment_digest: record.pre_effect_abort_commitment_digest.clone(),
        pre_effect_abort_proof_digest: record.pre_effect_abort_proof_digest.clone(),
        terminal_observed: record.phase.terminal_observed(),
        idempotent,
    }
}

const PRE_EFFECT_ABORT_COMMITMENT_DOMAIN: &[u8] =
    b"hepta.runtime.codex.pre-effect-abort.commitment.v1";
const PRE_EFFECT_ABORT_PROOF_DOMAIN: &[u8] = b"hepta.runtime.codex.pre-effect-abort.proof.v1";

fn pre_effect_abort_commitment(
    run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
) -> String {
    framed_abort_digest(
        PRE_EFFECT_ABORT_COMMITMENT_DOMAIN,
        run_id,
        dispatch_binding_digest,
        nonce,
        None,
    )
}

fn pre_effect_abort_proof(
    run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
    reason: &str,
) -> String {
    framed_abort_digest(
        PRE_EFFECT_ABORT_PROOF_DOMAIN,
        run_id,
        dispatch_binding_digest,
        nonce,
        Some(reason),
    )
}

fn framed_abort_digest(
    domain: &[u8],
    run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
    reason: Option<&str>,
) -> String {
    let mut bytes = Vec::new();
    push_abort_part(&mut bytes, domain);
    push_abort_part(&mut bytes, run_id.as_bytes());
    push_abort_part(&mut bytes, dispatch_binding_digest.as_bytes());
    push_abort_part(&mut bytes, nonce);
    if let Some(reason) = reason {
        push_abort_part(&mut bytes, reason.as_bytes());
    }
    Digest32::of_bytes(&bytes).to_string()
}

fn push_abort_part(output: &mut Vec<u8>, value: &[u8]) {
    let length = u64::try_from(value.len()).expect("bounded runtime.codex abort field");
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
}

fn decode_abort_nonce_hex(value: &str) -> Result<[u8; 32], AgentRunError> {
    if value.len() != 64 {
        return Err(AgentRunError::InvalidDigest("pre-effect abort nonce"));
    }
    let mut decoded = Vec::with_capacity(32);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = abort_hex_nibble(pair[0])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        let low = abort_hex_nibble(pair[1])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        decoded.push((high << 4) | low);
    }
    decoded
        .try_into()
        .map_err(|_| AgentRunError::InvalidDigest("pre-effect abort nonce"))
}

fn abort_hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[cfg(test)]
#[path = "lane_b_runtime_tests.rs"]
mod tests;
