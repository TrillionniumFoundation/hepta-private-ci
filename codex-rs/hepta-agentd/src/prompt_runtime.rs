//! Agentd-owned durable prompt runtime source for the embedded App Server.
//!
//! Staging accepts only the exact \`PromptRegistryCompiledContextV2\` produced
//! after optimizer exercise validation. Before a physical provider send,
//! runtime.codex records an exact dispatch claim here. A crash after that claim
//! but before terminal observation remains durably unresolved and blocks blind
//! retry until a terminal reconciliation is recorded.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_codex_adapter::PromptRuntimeAttachmentV1;
use codex_hepta_codex_adapter::PromptRuntimeDeveloperFragmentV1;
use codex_hepta_codex_adapter::PromptRuntimeDispatchFuture;
use codex_hepta_codex_adapter::PromptRuntimeDispatchRecordV1;
use codex_hepta_codex_adapter::PromptRuntimeHost;
use codex_hepta_codex_adapter::PromptRuntimeHostError;
use codex_hepta_codex_adapter::PromptRuntimePrepareFuture;
use codex_hepta_codex_adapter::PromptRuntimePrepareRequest;
use codex_hepta_codex_adapter::PromptRuntimeRecordFuture;
use codex_hepta_codex_adapter::PromptRuntimeTerminalOutcomeV1;
use codex_hepta_codex_adapter::PromptRuntimeTerminalRecordV1;
use codex_hepta_intelligence::PromptRegistryCompilationRequestV2;
use codex_hepta_intelligence::PromptRegistryCompiledContextV2;
use codex_hepta_intelligence::compile_prompt_registry_v2;
use codex_hepta_prompt_optimizer::canonical::EnumeratedPromptCandidatesV1;
use codex_hepta_prompt_optimizer::canonical::PromptEnumerationRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::enumerate_factors_v1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::PromptDeliveryObservationV1;
use codex_hepta_types::PromptDeliveryRejectReasonV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[path = "prompt_runtime_registry_lease.rs"]
mod registry_lease;
use registry_lease::PromptRegistryDeliveryLeaseV1;
use registry_lease::PromptRegistryLeaseItemV1;

#[path = "prompt_runtime_capacity.rs"]
mod capacity;

pub const AGENTD_PROMPT_REGISTRY_MAX_RECORDS: usize = 16_384;
const MAX_STAGED_TURNS: usize = 256;
const MAX_DISPATCH_RECORDS: usize = 1024;
const MAX_TERMINAL_RECORDS: usize = 1024;
const MAX_DURABLE_STATE_BYTES: u64 = 8 * 1024 * 1024;
const PROMPT_RUNTIME_CAPABILITY_ID: &str = "agentd.prompt-runtime";
const PROMPT_RUNTIME_SCHEMA: u32 = 1;
const REGISTRY_LEASE_DOMAIN: &[u8] = b"hepta.agentd.prompt-registry-delivery-lease.v1\0";
const STATE_FILE: &str = "prompt-runtime.json";
const NEXT_FILE: &str = "prompt-runtime.next";
const LOCK_FILE: &str = "prompt-runtime.lock";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeStageDisposition {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdPromptRuntimeError {
    InvalidTurnId,
    InvalidModel,
    InvalidDeadline,
    SourceValidationFailed,
    GenerationFenced,
    EmptySelection,
    UnsupportedPromptRole,
    PayloadNotUtf8,
    CapacityExceeded,
    StageConflict,
    DispatchConflict,
    TerminalWithoutDispatch,
    TerminalBindingMismatch,
    TerminalConflict,
    IndeterminatePending,
    StatePoisoned,
    CorruptState,
    StateLocked,
    Unavailable,
    IndeterminateDurability,
    ReopenRequired,
    Adapter(String),
}

impl fmt::Display for AgentdPromptRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentdPromptRuntimeError {}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct PromptRuntimeKey {
    thread_id: String,
    turn_id: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct PromptRuntimeState {
    staged: BTreeMap<PromptRuntimeKey, PromptRuntimeAttachmentV1>,
    registry_leases: BTreeMap<PromptRuntimeKey, PromptRegistryDeliveryLeaseV1>,
    dispatch_records: BTreeMap<String, PromptRuntimeDispatchRecordV1>,
    dispatch_order: VecDeque<String>,
    terminal_records: BTreeMap<String, PromptRuntimeTerminalRecordV1>,
    terminal_order: VecDeque<String>,
}

/// Long-lived Agentd owner shared with the embedded App Server.
pub struct AgentdPromptRuntimeOwner {
    state: Mutex<PromptRuntimeState>,
    store: Option<PromptRuntimeStore>,
    poisoned: AtomicBool,
}

impl Default for AgentdPromptRuntimeOwner {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Debug for AgentdPromptRuntimeOwner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        formatter
            .debug_struct("AgentdPromptRuntimeOwner")
            .field("staged_turns", &state.staged.len())
            .field("dispatch_records", &state.dispatch_records.len())
            .field("terminal_records", &state.terminal_records.len())
            .field("durable", &self.store.is_some())
            .field("requires_reopen", &self.poisoned.load(Ordering::Acquire))
            .finish()
    }
}

impl AgentdPromptRuntimeOwner {
    #[must_use]
    pub fn new() -> Self {
        Self {
            state: Mutex::new(PromptRuntimeState::default()),
            store: None,
            poisoned: AtomicBool::new(false),
        }
    }

    pub fn open_state_dir(directory: &Path) -> Result<Self, AgentdPromptRuntimeError> {
        let (store, state) = PromptRuntimeStore::open(directory)?;
        validate_state(&state)?;
        Ok(Self {
            state: Mutex::new(state),
            store: Some(store),
            poisoned: AtomicBool::new(false),
        })
    }

    #[must_use]
    pub fn requires_reopen(&self) -> bool {
        self.poisoned.load(Ordering::Acquire)
    }

    /// Stage one exact optimizer-exercised/registry-dereferenced context for a
    /// real Codex turn. Only DeveloperInstruction is activated in this profile.
    pub fn stage_compiled_prompt_context(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        portfolio: &SelectedPromptPortfolioV1,
        compiled: &PromptRegistryCompiledContextV2,
    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptRuntimeError> {
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        validate_model(model)?;
        if requested_deadline_ms == 0 {
            return Err(AgentdPromptRuntimeError::InvalidDeadline);
        }
        compiled
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        if compiled.selected_deliveries.is_empty() {
            return Err(AgentdPromptRuntimeError::EmptySelection);
        }

        let mut effective_deadline_ms =
            requested_deadline_ms.min(portfolio.receipt.valid_until_unix_ms);
        if effective_deadline_ms == 0 {
            return Err(AgentdPromptRuntimeError::InvalidDeadline);
        }
        let mut fragments = Vec::with_capacity(compiled.selected_deliveries.len());
        for delivery in &compiled.selected_deliveries {
            if delivery.binding.role != PromptRoleV2::DeveloperInstruction {
                return Err(AgentdPromptRuntimeError::UnsupportedPromptRole);
            }
            if let Some(expires_unix_ms) = delivery.binding.expires_unix_ms {
                if expires_unix_ms == 0 {
                    return Err(AgentdPromptRuntimeError::InvalidDeadline);
                }
                effective_deadline_ms = effective_deadline_ms.min(expires_unix_ms);
            }
            let text = std::str::from_utf8(&delivery.payload)
                .map_err(|_| AgentdPromptRuntimeError::PayloadNotUtf8)?;
            fragments.push(
                PromptRuntimeDeveloperFragmentV1::new(text.to_owned())
                    .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?,
            );
        }

        let attachment = PromptRuntimeAttachmentV1::new(
            compiled.compiled.receipt().compilation_id().clone(),
            compiled.attachment.attachment_digest(),
            compiled.attachment.payload_digest(),
            model.to_owned(),
            effective_deadline_ms,
            fragments,
        )
        .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?;
        let registry_lease =
            PromptRegistryDeliveryLeaseV1::from_compiled(portfolio, compiled, &attachment)?;

        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        self.commit_state(|state| {
            if let Some(existing) = state.staged.get(&key) {
                return if existing == &attachment
                    && state.registry_leases.get(&key) == Some(&registry_lease)
                {
                    Ok(PromptRuntimeStageDisposition::Unchanged)
                } else {
                    Err(AgentdPromptRuntimeError::StageConflict)
                };
            }
            if state
                .dispatch_records
                .values()
                .any(|record| dispatch_key(record) == key)
            {
                return Err(AgentdPromptRuntimeError::StageConflict);
            }
            if state.staged.len() >= MAX_STAGED_TURNS {
                return Err(AgentdPromptRuntimeError::CapacityExceeded);
            }
            state.staged.insert(key.clone(), attachment);
            state.registry_leases.insert(key, registry_lease);
            Ok(PromptRuntimeStageDisposition::Inserted)
        })
    }

    /// Explicit cleanup for aborted turns is permitted only when no provider
    /// attempt is unresolved. Unknown possible dispatch must be reconciled.
    pub fn clear_turn(
        &self,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<bool, AgentdPromptRuntimeError> {
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        self.commit_state(|state| {
            if has_unresolved_dispatch(state, &key) {
                return Err(AgentdPromptRuntimeError::IndeterminatePending);
            }
            let removed = state.staged.remove(&key).is_some();
            state.registry_leases.remove(&key);
            Ok(removed)
        })
    }

    pub fn terminal_record(
        &self,
        attempt_id: &str,
    ) -> Result<Option<PromptRuntimeTerminalRecordV1>, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .terminal_records
            .get(attempt_id)
            .cloned())
    }

    pub fn dispatch_record(
        &self,
        attempt_id: &str,
    ) -> Result<Option<PromptRuntimeDispatchRecordV1>, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .dispatch_records
            .get(attempt_id)
            .cloned())
    }

    pub fn staged_count(&self) -> Result<usize, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        Ok(self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?
            .staged
            .len())
    }

    fn ensure_available(&self) -> Result<(), AgentdPromptRuntimeError> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(AgentdPromptRuntimeError::ReopenRequired);
        }
        Ok(())
    }

    fn commit_state<T>(
        &self,
        mutation: impl FnOnce(&mut PromptRuntimeState) -> Result<T, AgentdPromptRuntimeError>,
    ) -> Result<T, AgentdPromptRuntimeError> {
        self.ensure_available()?;
        let mut current = self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?;
        let mut next = current.clone();
        let result = mutation(&mut next)?;
        validate_state(&next)?;
        if next != *current {
            if let Some(store) = &self.store {
                match store.persist(&next) {
                    Ok(()) => {}
                    Err(AgentdPromptRuntimeError::IndeterminateDurability) => {
                        self.poisoned.store(true, Ordering::Release);
                        return Err(AgentdPromptRuntimeError::IndeterminateDurability);
                    }
                    Err(error) => return Err(error),
                }
            }
            *current = next;
        }
        Ok(result)
    }

    fn prepare_source(
        &self,
        request: PromptRuntimePrepareRequest,
    ) -> Result<
        Option<(
            PromptRuntimeAttachmentV1,
            Option<PromptRegistryDeliveryLeaseV1>,
        )>,
        AgentdPromptRuntimeError,
    > {
        self.ensure_available()?;
        validate_thread_id(&request.thread_id)?;
        validate_turn_id(&request.turn_id)?;
        let key = PromptRuntimeKey {
            thread_id: request.thread_id,
            turn_id: request.turn_id,
        };
        let state = self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?;
        if has_unresolved_dispatch(&state, &key) {
            return Err(AgentdPromptRuntimeError::IndeterminatePending);
        }
        if !state.staged.contains_key(&key)
            && state
                .dispatch_records
                .values()
                .any(|dispatch| dispatch_key(dispatch) == key)
        {
            // A completed or explicitly cleared turn is not an unconfigured
            // prompt turn. Returning None would silently bypass its history.
            return Err(AgentdPromptRuntimeError::StageConflict);
        }
        Ok(state.staged.get(&key).cloned().map(|attachment| {
            let lease = state.registry_leases.get(&key).cloned();
            (attachment, lease)
        }))
    }

    #[cfg(test)]
    fn prepare(
        &self,
        request: PromptRuntimePrepareRequest,
    ) -> Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError> {
        self.prepare_source(request)
            .map(|value| value.map(|(attachment, _)| attachment))
            .map_err(host_error)
    }

    fn source_for_dispatch(
        &self,
        record: &PromptRuntimeDispatchRecordV1,
    ) -> Result<
        (
            PromptRuntimeAttachmentV1,
            Option<PromptRegistryDeliveryLeaseV1>,
        ),
        AgentdPromptRuntimeError,
    > {
        self.ensure_available()?;
        let key = dispatch_key(record);
        let state = self
            .state
            .lock()
            .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)?;
        if has_unresolved_dispatch(&state, &key) {
            return Err(AgentdPromptRuntimeError::IndeterminatePending);
        }
        let attachment = state
            .staged
            .get(&key)
            .cloned()
            .ok_or(AgentdPromptRuntimeError::TerminalBindingMismatch)?;
        if !dispatch_matches_attachment(record, &attachment) {
            return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
        }
        Ok((attachment, state.registry_leases.get(&key).cloned()))
    }

    fn record_dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
        record.validate().map_err(|error| {
            PromptRuntimeHostError::new("agentd_prompt_runtime_dispatch_invalid", error.to_string())
        })?;
        self.commit_state(|state| {
            if let Some(existing) = state.dispatch_records.get(&record.attempt_id) {
                return if existing == &record {
                    Ok(())
                } else {
                    Err(AgentdPromptRuntimeError::DispatchConflict)
                };
            }
            let key = dispatch_key(&record);
            if has_unresolved_dispatch(state, &key) {
                return Err(AgentdPromptRuntimeError::IndeterminatePending);
            }
            let Some(staged) = state.staged.get(&key) else {
                return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
            };
            if !dispatch_matches_attachment(&record, staged) {
                return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
            }
            if state.dispatch_records.len() >= MAX_DISPATCH_RECORDS {
                return Err(AgentdPromptRuntimeError::CapacityExceeded);
            }
            state
                .dispatch_records
                .insert(record.attempt_id.clone(), record.clone());
            state.dispatch_order.push_back(record.attempt_id);
            Ok(())
        })
        .map_err(host_error)
    }

    fn record(&self, record: PromptRuntimeTerminalRecordV1) -> Result<(), PromptRuntimeHostError> {
        record.validate().map_err(|error| {
            PromptRuntimeHostError::new("agentd_prompt_runtime_terminal_invalid", error.to_string())
        })?;
        self.commit_state(|state| {
            let Some(dispatch) = state.dispatch_records.get(&record.attempt_id) else {
                return Err(AgentdPromptRuntimeError::TerminalWithoutDispatch);
            };
            if !terminal_matches_dispatch(&record, dispatch) {
                return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
            }

            let key = dispatch_key(dispatch);
            if let Some(existing) = state.terminal_records.get(&record.attempt_id) {
                if existing == &record {
                    return Ok(());
                }
                if existing.outcome != PromptRuntimeTerminalOutcomeV1::Indeterminate
                    || !matches!(
                        record.outcome,
                        PromptRuntimeTerminalOutcomeV1::Delivered
                            | PromptRuntimeTerminalOutcomeV1::Rejected
                    )
                    || record.observed_unix_ms < existing.observed_unix_ms
                {
                    return Err(AgentdPromptRuntimeError::TerminalConflict);
                }
                state
                    .terminal_records
                    .insert(record.attempt_id.clone(), record.clone());
                if terminal_clears_stage(&record) {
                    state.staged.remove(&key);
                    state.registry_leases.remove(&key);
                }
                return Ok(());
            }

            if state.terminal_records.len() >= MAX_TERMINAL_RECORDS {
                return Err(AgentdPromptRuntimeError::CapacityExceeded);
            }
            state
                .terminal_records
                .insert(record.attempt_id.clone(), record.clone());
            state.terminal_order.push_back(record.attempt_id.clone());
            if terminal_clears_stage(&record) {
                state.staged.remove(&key);
                state.registry_leases.remove(&key);
            }
            Ok(())
        })
        .map_err(host_error)
    }

    #[cfg(test)]
    fn fail_directory_sync_after_rename_once(&self) {
        if let Some(store) = &self.store {
            store
                .fail_directory_sync_after_rename_once
                .store(true, Ordering::Release);
        }
    }
}

#[derive(Debug)]
pub enum AgentdPromptPipelineError {
    RegistryOpen(String),
    RuntimeOpen(AgentdPromptRuntimeError),
    StatePoisoned,
    CandidateSource(String),
    Compilation(String),
    Stage(AgentdPromptRuntimeError),
}

impl fmt::Display for AgentdPromptPipelineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentdPromptPipelineError {}

/// Named Agentd composition owner for the canonical prompt-intervention path.
///
/// This facade owns no alternate optimizer or model loop. It opens the
/// authoritative durable registry, derives the optimizer candidate source from
/// that exact owner, validates canonical optimizer receipts through
/// \`compile_prompt_registry_v2\`, and stages the resulting exact realization
/// bytes into the same PromptRuntimeHost consumed by the embedded App Server.
pub struct AgentdPromptPipelineOwner {
    registry: Mutex<DurablePromptRegistry>,
    runtime: Arc<AgentdPromptRuntimeOwner>,
}

impl fmt::Debug for AgentdPromptPipelineOwner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdPromptPipelineOwner")
            .field("runtime", &self.runtime)
            .finish_non_exhaustive()
    }
}

impl AgentdPromptPipelineOwner {
    pub fn open_state_dirs(
        registry_directory: &Path,
        registry_recovery_checkpoint: Option<&Path>,
        registry_recovery_owner_id: &str,
        runtime_directory: &Path,
        maximum_registry_records: usize,
    ) -> Result<Self, AgentdPromptPipelineError> {
        let registry = match registry_recovery_checkpoint {
            Some(checkpoint) => DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
                registry_directory,
                checkpoint,
                registry_recovery_owner_id,
                maximum_registry_records,
            ),
            None => {
                DurablePromptRegistry::open_state_dir(registry_directory, maximum_registry_records)
            }
        }
        .map_err(|error| AgentdPromptPipelineError::RegistryOpen(error.to_string()))?;
        let runtime = AgentdPromptRuntimeOwner::open_state_dir(runtime_directory)
            .map_err(AgentdPromptPipelineError::RuntimeOpen)?;
        Ok(Self {
            registry: Mutex::new(registry),
            runtime: Arc::new(runtime),
        })
    }

    #[must_use]
    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {
        Arc::clone(&self.runtime)
    }

    /// Compose the only product prompt host. Preparation checks current source
    /// state for early rejection; dispatch repeats the check while holding the
    /// registry owner lock through durable dispatch-claim publication. A
    /// revocation ordered before this claim therefore blocks the physical send.
    pub fn host(
        self: &Arc<Self>,
        current_generation: impl Fn() -> Result<(), AgentdPromptRuntimeError> + Send + Sync + 'static,
    ) -> Result<PromptRuntimeHost, AgentdPromptRuntimeError> {
        let generation = Arc::new(current_generation);
        let prepare_generation = Arc::clone(&generation);
        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new(
            PROMPT_RUNTIME_CAPABILITY_ID,
            move |request: PromptRuntimePrepareRequest| -> PromptRuntimePrepareFuture {
                let owner = Arc::clone(&prepare_owner);
                let generation = Arc::clone(&prepare_generation);
                Box::pin(async move {
                    generation().map_err(host_error)?;
                    owner.prepare_for_provider(request)
                })
            },
            move |record: PromptRuntimeDispatchRecordV1| -> PromptRuntimeDispatchFuture {
                let owner = Arc::clone(&dispatch_owner);
                let generation = Arc::clone(&generation);
                Box::pin(async move {
                    owner.admit_provider_dispatch_with_fence(record, || generation())
                })
            },
            move |record: PromptRuntimeTerminalRecordV1| -> PromptRuntimeRecordFuture {
                let owner = Arc::clone(&record_owner);
                Box::pin(async move { owner.runtime.record(record) })
            },
        )
        .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))
    }

    fn prepare_for_provider(
        &self,
        request: PromptRuntimePrepareRequest,
    ) -> Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError> {
        let Some((attachment, lease)) = self.runtime.prepare_source(request).map_err(host_error)?
        else {
            return Ok(None);
        };
        let lease = lease.ok_or_else(|| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_lease_missing",
                "staged prompt predates registry-currentness enforcement and cannot be sent",
            )
        })?;
        let registry = self.registry.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_state_poisoned",
                "prompt registry owner lock is poisoned",
            )
        })?;
        let now_unix_ms = current_unix_ms().map_err(host_error)?;
        lease
            .validate_current(&registry, &attachment, now_unix_ms)
            .map_err(host_error)?;
        Ok(Some(attachment))
    }

    #[cfg(test)]
    fn admit_provider_dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
        self.admit_provider_dispatch_with_fence(record, || Ok(()))
    }

    fn admit_provider_dispatch_with_fence(
        &self,
        record: PromptRuntimeDispatchRecordV1,
        current_generation: impl Fn() -> Result<(), AgentdPromptRuntimeError>,
    ) -> Result<(), PromptRuntimeHostError> {
        record.validate().map_err(|error| {
            PromptRuntimeHostError::new("agentd_prompt_runtime_dispatch_invalid", error.to_string())
        })?;
        let (attachment, lease) = self
            .runtime
            .source_for_dispatch(&record)
            .map_err(host_error)?;
        let lease = lease.ok_or_else(|| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_lease_missing",
                "staged prompt predates registry-currentness enforcement and cannot be sent",
            )
        })?;
        // Keep this owner lock until the durable dispatch claim succeeds. All
        // registry lifecycle writes use the same mutex, defining the send versus
        // revocation order without a query-then-send gap.
        let registry = self.registry.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_state_poisoned",
                "prompt registry owner lock is poisoned",
            )
        })?;
        // Check the existing Agentd/Fleet lifecycle under the same registry
        // fence; a live factor is not permission for a retired Agent generation.
        current_generation().map_err(host_error)?;
        // The caller timestamp precedes async scheduling and lock acquisition.
        // Re-read time under the registry lock, including queued expiry; a clock
        // rollback must not make an old dispatch claim current again.
        let now_unix_ms = current_unix_ms().map_err(host_error)?;
        if now_unix_ms < record.dispatched_unix_ms {
            return Err(host_error(AgentdPromptRuntimeError::InvalidDeadline));
        }
        lease
            .validate_current(&registry, &attachment, now_unix_ms)
            .map_err(host_error)?;
        // A duplicate durable record is useful for observation deduplication,
        // but never a second permission to cross the physical send boundary.
        // Serialize this decision with all product admissions using this lock.
        if self
            .runtime
            .dispatch_record(&record.attempt_id)
            .map_err(host_error)?
            .is_some()
        {
            return Err(host_error(AgentdPromptRuntimeError::IndeterminatePending));
        }
        self.runtime.record_dispatch(record.clone())?;
        // fsync and publication can themselves wait beyond the deadline or an
        // Agent-generation fence. We are still inside the physical policy hook:
        // no provider send has been permitted yet, so this is a definite local
        // NotDispatched observation, never fabricated provider success.
        let generation_after_commit = current_generation();
        let observed_unix_ms = current_unix_ms().map_err(host_error)?;
        if observed_unix_ms < record.dispatched_unix_ms {
            // With an untrusted clock relationship retain the unresolved claim;
            // do not fabricate a future terminal timestamp to resolve it.
            return Err(host_error(AgentdPromptRuntimeError::InvalidDeadline));
        }
        let rejected = generation_after_commit.err().or_else(|| {
            (observed_unix_ms >= lease.valid_until_unix_ms)
                .then_some(AgentdPromptRuntimeError::InvalidDeadline)
        });
        if let Some(error) = rejected {
            self.runtime.record(PromptRuntimeTerminalRecordV1 {
                compilation_id: record.compilation_id,
                context_attachment_digest: record.context_attachment_digest,
                context_payload_digest: record.context_payload_digest,
                source_binding_digest: record.source_binding_digest,
                thread_id: record.thread_id,
                turn_id: record.turn_id,
                attempt_id: record.attempt_id,
                request_binding_id: record.request_binding_id,
                provider_request_digest: record.provider_request_digest,
                outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched,
                end_turn: None,
                terminal_reason_code: Some("prompt_final_admission_expired_or_fenced".to_owned()),
                delivery_observation: None,
                observed_unix_ms,
            })?;
            return Err(host_error(error));
        }
        Ok(())
    }

    /// Enumerate candidates from this owner's exact current durable registry.
    pub fn enumerate_candidates(
        &self,
        request: PromptEnumerationRequestV1,
    ) -> Result<EnumeratedPromptCandidatesV1, AgentdPromptPipelineError> {
        let registry = self
            .registry
            .lock()
            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?;
        let current = registry
            .registry()
            .map_err(|error| AgentdPromptPipelineError::CandidateSource(error.to_string()))?;
        enumerate_factors_v1(current, request)
            .map_err(|error| AgentdPromptPipelineError::CandidateSource(error.to_string()))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn compile_and_stage(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        portfolio: &SelectedPromptPortfolioV1,
        exercise_request: &PromptExerciseRequestV1,
        compilation_request: PromptRegistryCompilationRequestV2,
    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptPipelineError> {
        let compiled = {
            let registry = self
                .registry
                .lock()
                .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?;
            compile_prompt_registry_v2(&registry, portfolio, exercise_request, compilation_request)
                .map_err(|error| AgentdPromptPipelineError::Compilation(error.to_string()))?
        };
        self.runtime
            .stage_compiled_prompt_context(
                thread_id,
                turn_id,
                model,
                requested_deadline_ms,
                portfolio,
                &compiled,
            )
            .map_err(AgentdPromptPipelineError::Stage)
    }
}

fn terminal_clears_stage(record: &PromptRuntimeTerminalRecordV1) -> bool {
    matches!(record.outcome, PromptRuntimeTerminalOutcomeV1::Rejected)
        || (record.outcome == PromptRuntimeTerminalOutcomeV1::Delivered
            && record.end_turn == Some(true))
}

fn dispatch_key(record: &PromptRuntimeDispatchRecordV1) -> PromptRuntimeKey {
    PromptRuntimeKey {
        thread_id: record.thread_id.clone(),
        turn_id: record.turn_id.clone(),
    }
}

fn terminal_key(record: &PromptRuntimeTerminalRecordV1) -> PromptRuntimeKey {
    PromptRuntimeKey {
        thread_id: record.thread_id.clone(),
        turn_id: record.turn_id.clone(),
    }
}

fn dispatch_matches_attachment(
    dispatch: &PromptRuntimeDispatchRecordV1,
    attachment: &PromptRuntimeAttachmentV1,
) -> bool {
    dispatch.compilation_id == attachment.compilation_id
        && dispatch.context_attachment_digest == attachment.context_attachment_digest
        && dispatch.context_payload_digest == attachment.context_payload_digest
        && dispatch.source_binding_digest == attachment.source_binding_digest
}

fn terminal_matches_dispatch(
    terminal: &PromptRuntimeTerminalRecordV1,
    dispatch: &PromptRuntimeDispatchRecordV1,
) -> bool {
    terminal.compilation_id == dispatch.compilation_id
        && terminal.context_attachment_digest == dispatch.context_attachment_digest
        && terminal.context_payload_digest == dispatch.context_payload_digest
        && terminal.source_binding_digest == dispatch.source_binding_digest
        && terminal.thread_id == dispatch.thread_id
        && terminal.turn_id == dispatch.turn_id
        && terminal.attempt_id == dispatch.attempt_id
        && terminal.request_binding_id == dispatch.request_binding_id
        && terminal.provider_request_digest == dispatch.provider_request_digest
}

fn has_unresolved_dispatch(state: &PromptRuntimeState, key: &PromptRuntimeKey) -> bool {
    state.dispatch_records.values().any(|dispatch| {
        if &dispatch_key(dispatch) != key {
            return false;
        }
        match state.terminal_records.get(&dispatch.attempt_id) {
            None => true,
            Some(terminal) => terminal.outcome == PromptRuntimeTerminalOutcomeV1::Indeterminate,
        }
    })
}

fn validate_state(state: &PromptRuntimeState) -> Result<(), AgentdPromptRuntimeError> {
    if state.staged.len() > MAX_STAGED_TURNS
        || state.registry_leases.len() > state.staged.len()
        || state.dispatch_records.len() > MAX_DISPATCH_RECORDS
        || state.terminal_records.len() > MAX_TERMINAL_RECORDS
        || state.dispatch_order.len() != state.dispatch_records.len()
        || state.terminal_order.len() != state.terminal_records.len()
    {
        return Err(AgentdPromptRuntimeError::CorruptState);
    }
    for attachment in state.staged.values() {
        attachment
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
    }
    for (key, lease) in &state.registry_leases {
        let attachment = state
            .staged
            .get(key)
            .ok_or(AgentdPromptRuntimeError::CorruptState)?;
        lease
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
        if lease.attachment_source_binding_digest != attachment.source_binding_digest {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
    }

    let dispatch_order = state
        .dispatch_order
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let terminal_order = state
        .terminal_order
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    if dispatch_order.len() != state.dispatch_order.len()
        || terminal_order.len() != state.terminal_order.len()
        || state
            .dispatch_records
            .keys()
            .any(|attempt| !dispatch_order.contains(attempt))
        || state
            .terminal_records
            .keys()
            .any(|attempt| !terminal_order.contains(attempt))
    {
        return Err(AgentdPromptRuntimeError::CorruptState);
    }

    let finalized_keys = state
        .terminal_records
        .values()
        .filter(|terminal| terminal_clears_stage(terminal))
        .map(terminal_key)
        .collect::<BTreeSet<_>>();
    let mut unresolved_keys = BTreeSet::new();
    for dispatch in state.dispatch_records.values() {
        dispatch
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
        let key = dispatch_key(dispatch);
        let terminal = state.terminal_records.get(&dispatch.attempt_id);
        if let Some(terminal) = terminal {
            terminal
                .validate()
                .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
            if !terminal_matches_dispatch(terminal, dispatch) {
                return Err(AgentdPromptRuntimeError::CorruptState);
            }
        }
        let unresolved = terminal.is_none()
            || terminal.is_some_and(|value| {
                value.outcome == PromptRuntimeTerminalOutcomeV1::Indeterminate
            });
        if unresolved && finalized_keys.contains(&key) {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        if finalized_keys.contains(&key) && state.staged.contains_key(&key) {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        // Explicit cleanup of a definitively observed, non-final turn is safe:
        // its retained dispatch history prevents restaging or a no-prompt retry.
        // Possible sends still require their original stage for reconciliation.
        let stage_required = unresolved || state.staged.contains_key(&key);
        if stage_required {
            let Some(staged) = state.staged.get(&key) else {
                return Err(AgentdPromptRuntimeError::CorruptState);
            };
            if !dispatch_matches_attachment(dispatch, staged) {
                return Err(AgentdPromptRuntimeError::CorruptState);
            }
        }
        if unresolved && !unresolved_keys.insert(key) {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
    }
    for terminal in state.terminal_records.values() {
        if !state.dispatch_records.contains_key(&terminal.attempt_id) {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        if terminal_key(terminal)
            != dispatch_key(
                state
                    .dispatch_records
                    .get(&terminal.attempt_id)
                    .ok_or(AgentdPromptRuntimeError::CorruptState)?,
            )
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
    }
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredPromptRuntimeState {
    schema: u32,
    staged: Vec<StoredStage>,
    dispatches: Vec<StoredDispatch>,
    terminals: Vec<StoredTerminal>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredStage {
    thread_id: String,
    turn_id: String,
    attachment: StoredAttachment,
    /// Schema-1 states written before currentness enforcement omit this field.
    /// They remain inspectable but the product host refuses to send them.
    #[serde(default)]
    registry_lease: Option<StoredRegistryLease>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredRegistryLease {
    compile_snapshot_digest: [u8; 32],
    compatible_set_digest: [u8; 32],
    portfolio_receipt_digest: [u8; 32],
    generation_vector_digest: [u8; 32],
    model_tuple: StoredPromptModelTuple,
    valid_until_unix_ms: u64,
    attachment_source_binding_digest: [u8; 32],
    selected: Vec<StoredRegistryLeaseItem>,
    lease_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredPromptModelTuple {
    model_id: String,
    model_version: String,
    model_digest: [u8; 32],
    tokenizer_digest: [u8; 32],
    template_digest: [u8; 32],
    tool_schema_digest: [u8; 32],
    context_profile_digest: [u8; 32],
    locale_id: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredRegistryLeaseItem {
    factor_id: String,
    realization_id: String,
    binding_digest: [u8; 32],
    payload_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredAttachment {
    compilation_id: String,
    context_attachment_digest: [u8; 32],
    context_payload_digest: [u8; 32],
    model: String,
    deadline_ms: u64,
    developer_fragments: Vec<String>,
    source_binding_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredDispatch {
    compilation_id: String,
    context_attachment_digest: [u8; 32],
    context_payload_digest: [u8; 32],
    source_binding_digest: [u8; 32],
    thread_id: String,
    turn_id: String,
    attempt_id: String,
    request_binding_id: String,
    provider_request_digest: [u8; 32],
    dispatched_unix_ms: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredTerminal {
    compilation_id: String,
    context_attachment_digest: [u8; 32],
    context_payload_digest: [u8; 32],
    source_binding_digest: [u8; 32],
    thread_id: String,
    turn_id: String,
    attempt_id: String,
    request_binding_id: String,
    provider_request_digest: [u8; 32],
    outcome: u8,
    end_turn: Option<bool>,
    terminal_reason_code: Option<String>,
    delivery_observation: Option<StoredObservation>,
    observed_unix_ms: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredObservation {
    compilation_id: String,
    provider_request_digest: [u8; 32],
    delivered: bool,
    rejected_reason: Option<String>,
    observed_token_positions: Option<Vec<u32>>,
    truncation_observed: bool,
}

struct PromptRuntimeStore {
    root: PathBuf,
    _lock: File,
    #[cfg(test)]
    metadata_limit: std::sync::atomic::AtomicU64,
    #[cfg(test)]
    fail_directory_sync_after_rename_once: AtomicBool,
}

impl PromptRuntimeStore {
    fn open(directory: &Path) -> Result<(Self, PromptRuntimeState), AgentdPromptRuntimeError> {
        prepare_state_directory(directory)?;
        let lock_path = directory.join(LOCK_FILE);
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        set_private_file_permissions(&lock_path)?;
        lock.try_lock()
            .map_err(|_| AgentdPromptRuntimeError::StateLocked)?;
        let store = Self {
            root: directory.to_path_buf(),
            _lock: lock,
            #[cfg(test)]
            metadata_limit: std::sync::atomic::AtomicU64::new(MAX_DURABLE_STATE_BYTES),
            #[cfg(test)]
            fail_directory_sync_after_rename_once: AtomicBool::new(false),
        };
        let state_path = directory.join(STATE_FILE);
        if !state_path.exists() {
            return Ok((store, PromptRuntimeState::default()));
        }
        let mut bytes = Vec::new();
        File::open(&state_path)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?
            .take(MAX_DURABLE_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        let stored: StoredPromptRuntimeState =
            serde_json::from_slice(&bytes).map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
        let state = restore_state(stored)?;
        Ok((store, state))
    }

    fn persist(&self, state: &PromptRuntimeState) -> Result<(), AgentdPromptRuntimeError> {
        let stored = stored_state(state);
        let bytes =
            serde_json::to_vec(&stored).map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        #[cfg(test)]
        let limit = self.metadata_limit.load(Ordering::Acquire);
        #[cfg(not(test))]
        let limit = MAX_DURABLE_STATE_BYTES;
        capacity::admit(state, bytes.len(), limit)?;
        let next_path = self.root.join(NEXT_FILE);
        let mut next = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&next_path)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        set_private_file_permissions(&next_path)?;
        next.write_all(&bytes)
            .and_then(|()| next.sync_all())
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        std::fs::rename(&next_path, self.root.join(STATE_FILE))
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        #[cfg(test)]
        if self
            .fail_directory_sync_after_rename_once
            .swap(false, Ordering::AcqRel)
        {
            return Err(AgentdPromptRuntimeError::IndeterminateDurability);
        }
        sync_state_directory(&self.root)
    }
}

fn stored_state(state: &PromptRuntimeState) -> StoredPromptRuntimeState {
    StoredPromptRuntimeState {
        schema: PROMPT_RUNTIME_SCHEMA,
        staged: state
            .staged
            .iter()
            .map(|(key, attachment)| StoredStage {
                thread_id: key.thread_id.clone(),
                turn_id: key.turn_id.clone(),
                attachment: stored_attachment(attachment),
                registry_lease: state.registry_leases.get(key).map(stored_registry_lease),
            })
            .collect(),
        dispatches: state
            .dispatch_order
            .iter()
            .filter_map(|attempt| state.dispatch_records.get(attempt))
            .map(stored_dispatch)
            .collect(),
        terminals: state
            .terminal_order
            .iter()
            .filter_map(|attempt| state.terminal_records.get(attempt))
            .map(stored_terminal)
            .collect(),
    }
}

fn restore_state(
    stored: StoredPromptRuntimeState,
) -> Result<PromptRuntimeState, AgentdPromptRuntimeError> {
    if stored.schema != PROMPT_RUNTIME_SCHEMA
        || stored.staged.len() > MAX_STAGED_TURNS
        || stored.dispatches.len() > MAX_DISPATCH_RECORDS
        || stored.terminals.len() > MAX_TERMINAL_RECORDS
    {
        return Err(AgentdPromptRuntimeError::CorruptState);
    }
    let mut state = PromptRuntimeState::default();
    for stored_stage in stored.staged {
        let key = PromptRuntimeKey {
            thread_id: stored_stage.thread_id,
            turn_id: stored_stage.turn_id,
        };
        let attachment = restore_attachment(stored_stage.attachment)?;
        let registry_lease = stored_stage
            .registry_lease
            .map(restore_registry_lease)
            .transpose()?;
        if state.staged.insert(key.clone(), attachment).is_some() {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        if let Some(lease) = registry_lease
            && state.registry_leases.insert(key, lease).is_some()
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
    }
    for stored_dispatch in stored.dispatches {
        let dispatch = restore_dispatch(stored_dispatch)?;
        let attempt = dispatch.attempt_id.clone();
        if state
            .dispatch_records
            .insert(attempt.clone(), dispatch)
            .is_some()
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        state.dispatch_order.push_back(attempt);
    }
    for stored_terminal in stored.terminals {
        let terminal = restore_terminal(stored_terminal)?;
        let attempt = terminal.attempt_id.clone();
        if state
            .terminal_records
            .insert(attempt.clone(), terminal)
            .is_some()
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        state.terminal_order.push_back(attempt);
    }
    validate_state(&state)?;
    Ok(state)
}

fn stored_registry_lease(value: &PromptRegistryDeliveryLeaseV1) -> StoredRegistryLease {
    StoredRegistryLease {
        compile_snapshot_digest: value.compile_snapshot_digest.into_array(),
        compatible_set_digest: value.compatible_set_digest.into_array(),
        portfolio_receipt_digest: value.portfolio_receipt_digest.into_array(),
        generation_vector_digest: value.generation_vector_digest.into_array(),
        model_tuple: StoredPromptModelTuple {
            model_id: value.model_tuple.model_id.to_string(),
            model_version: value.model_tuple.model_version.clone(),
            model_digest: value.model_tuple.model_digest.into_array(),
            tokenizer_digest: value.model_tuple.tokenizer_digest.into_array(),
            template_digest: value.model_tuple.template_digest.into_array(),
            tool_schema_digest: value.model_tuple.tool_schema_digest.into_array(),
            context_profile_digest: value.model_tuple.context_profile_digest.into_array(),
            locale_id: value.model_tuple.locale_id.to_string(),
        },
        valid_until_unix_ms: value.valid_until_unix_ms,
        attachment_source_binding_digest: value.attachment_source_binding_digest.into_array(),
        selected: value
            .selected
            .iter()
            .map(|item| StoredRegistryLeaseItem {
                factor_id: item.factor_id.to_string(),
                realization_id: item.realization_id.to_string(),
                binding_digest: item.binding_digest.into_array(),
                payload_digest: item.payload_digest.into_array(),
            })
            .collect(),
        lease_digest: value.lease_digest.into_array(),
    }
}

fn restore_registry_lease(
    stored: StoredRegistryLease,
) -> Result<PromptRegistryDeliveryLeaseV1, AgentdPromptRuntimeError> {
    let value = PromptRegistryDeliveryLeaseV1 {
        compile_snapshot_digest: Digest32::from_array(stored.compile_snapshot_digest),
        compatible_set_digest: Digest32::from_array(stored.compatible_set_digest),
        portfolio_receipt_digest: Digest32::from_array(stored.portfolio_receipt_digest),
        generation_vector_digest: Digest32::from_array(stored.generation_vector_digest),
        model_tuple: PromptModelTupleV2 {
            model_id: parse_id(stored.model_tuple.model_id)?,
            model_version: stored.model_tuple.model_version,
            model_digest: Digest32::from_array(stored.model_tuple.model_digest),
            tokenizer_digest: Digest32::from_array(stored.model_tuple.tokenizer_digest),
            template_digest: Digest32::from_array(stored.model_tuple.template_digest),
            tool_schema_digest: Digest32::from_array(stored.model_tuple.tool_schema_digest),
            context_profile_digest: Digest32::from_array(stored.model_tuple.context_profile_digest),
            locale_id: parse_id(stored.model_tuple.locale_id)?,
        },
        valid_until_unix_ms: stored.valid_until_unix_ms,
        attachment_source_binding_digest: Digest32::from_array(
            stored.attachment_source_binding_digest,
        ),
        selected: stored
            .selected
            .into_iter()
            .map(|item| {
                Ok(PromptRegistryLeaseItemV1 {
                    factor_id: parse_id(item.factor_id)?,
                    realization_id: parse_id(item.realization_id)?,
                    binding_digest: Digest32::from_array(item.binding_digest),
                    payload_digest: Digest32::from_array(item.payload_digest),
                })
            })
            .collect::<Result<Vec<_>, AgentdPromptRuntimeError>>()?,
        lease_digest: Digest32::from_array(stored.lease_digest),
    };
    value
        .validate()
        .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
    Ok(value)
}

fn stored_attachment(value: &PromptRuntimeAttachmentV1) -> StoredAttachment {
    StoredAttachment {
        compilation_id: value.compilation_id.to_string(),
        context_attachment_digest: value.context_attachment_digest.into_array(),
        context_payload_digest: value.context_payload_digest.into_array(),
        model: value.model.clone(),
        deadline_ms: value.deadline_ms,
        developer_fragments: value
            .developer_fragments
            .iter()
            .map(|fragment| fragment.text.clone())
            .collect(),
        source_binding_digest: value.source_binding_digest.into_array(),
    }
}

fn restore_attachment(
    stored: StoredAttachment,
) -> Result<PromptRuntimeAttachmentV1, AgentdPromptRuntimeError> {
    let fragments = stored
        .developer_fragments
        .into_iter()
        .map(|text| {
            PromptRuntimeDeveloperFragmentV1::new(text)
                .map_err(|_| AgentdPromptRuntimeError::CorruptState)
        })
        .collect::<Result<Vec<_>, _>>()?;
    let attachment = PromptRuntimeAttachmentV1::new(
        parse_id(stored.compilation_id)?,
        Digest32::from_array(stored.context_attachment_digest),
        Digest32::from_array(stored.context_payload_digest),
        stored.model,
        stored.deadline_ms,
        fragments,
    )
    .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
    if attachment.source_binding_digest != Digest32::from_array(stored.source_binding_digest) {
        return Err(AgentdPromptRuntimeError::CorruptState);
    }
    Ok(attachment)
}

fn stored_dispatch(value: &PromptRuntimeDispatchRecordV1) -> StoredDispatch {
    StoredDispatch {
        compilation_id: value.compilation_id.to_string(),
        context_attachment_digest: value.context_attachment_digest.into_array(),
        context_payload_digest: value.context_payload_digest.into_array(),
        source_binding_digest: value.source_binding_digest.into_array(),
        thread_id: value.thread_id.clone(),
        turn_id: value.turn_id.clone(),
        attempt_id: value.attempt_id.clone(),
        request_binding_id: value.request_binding_id.clone(),
        provider_request_digest: value.provider_request_digest.into_array(),
        dispatched_unix_ms: value.dispatched_unix_ms,
    }
}

fn restore_dispatch(
    stored: StoredDispatch,
) -> Result<PromptRuntimeDispatchRecordV1, AgentdPromptRuntimeError> {
    let value = PromptRuntimeDispatchRecordV1 {
        compilation_id: parse_id(stored.compilation_id)?,
        context_attachment_digest: Digest32::from_array(stored.context_attachment_digest),
        context_payload_digest: Digest32::from_array(stored.context_payload_digest),
        source_binding_digest: Digest32::from_array(stored.source_binding_digest),
        thread_id: stored.thread_id,
        turn_id: stored.turn_id,
        attempt_id: stored.attempt_id,
        request_binding_id: stored.request_binding_id,
        provider_request_digest: Digest32::from_array(stored.provider_request_digest),
        dispatched_unix_ms: stored.dispatched_unix_ms,
    };
    value
        .validate()
        .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
    Ok(value)
}

fn stored_terminal(value: &PromptRuntimeTerminalRecordV1) -> StoredTerminal {
    StoredTerminal {
        compilation_id: value.compilation_id.to_string(),
        context_attachment_digest: value.context_attachment_digest.into_array(),
        context_payload_digest: value.context_payload_digest.into_array(),
        source_binding_digest: value.source_binding_digest.into_array(),
        thread_id: value.thread_id.clone(),
        turn_id: value.turn_id.clone(),
        attempt_id: value.attempt_id.clone(),
        request_binding_id: value.request_binding_id.clone(),
        provider_request_digest: value.provider_request_digest.into_array(),
        outcome: terminal_outcome_code(value.outcome),
        end_turn: value.end_turn,
        terminal_reason_code: value.terminal_reason_code.clone(),
        delivery_observation: value.delivery_observation.as_ref().map(stored_observation),
        observed_unix_ms: value.observed_unix_ms,
    }
}

fn restore_terminal(
    stored: StoredTerminal,
) -> Result<PromptRuntimeTerminalRecordV1, AgentdPromptRuntimeError> {
    let value = PromptRuntimeTerminalRecordV1 {
        compilation_id: parse_id(stored.compilation_id)?,
        context_attachment_digest: Digest32::from_array(stored.context_attachment_digest),
        context_payload_digest: Digest32::from_array(stored.context_payload_digest),
        source_binding_digest: Digest32::from_array(stored.source_binding_digest),
        thread_id: stored.thread_id,
        turn_id: stored.turn_id,
        attempt_id: stored.attempt_id,
        request_binding_id: stored.request_binding_id,
        provider_request_digest: Digest32::from_array(stored.provider_request_digest),
        outcome: decode_terminal_outcome(stored.outcome)?,
        end_turn: stored.end_turn,
        terminal_reason_code: stored.terminal_reason_code,
        delivery_observation: stored
            .delivery_observation
            .map(restore_observation)
            .transpose()?,
        observed_unix_ms: stored.observed_unix_ms,
    };
    value
        .validate()
        .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
    Ok(value)
}

fn stored_observation(value: &PromptDeliveryObservationV1) -> StoredObservation {
    StoredObservation {
        compilation_id: value.compilation_id.to_string(),
        provider_request_digest: value.provider_request_digest.into_array(),
        delivered: value.delivered,
        rejected_reason: value
            .rejected_reason
            .as_ref()
            .map(|reason| reason.as_str().to_owned()),
        observed_token_positions: value.observed_token_positions.clone(),
        truncation_observed: value.truncation_observed,
    }
}

fn restore_observation(
    stored: StoredObservation,
) -> Result<PromptDeliveryObservationV1, AgentdPromptRuntimeError> {
    let rejected_reason = stored
        .rejected_reason
        .map(|reason| {
            PromptDeliveryRejectReasonV1::new(parse_id(reason)?)
                .map_err(|_| AgentdPromptRuntimeError::CorruptState)
        })
        .transpose()?;
    let value = PromptDeliveryObservationV1 {
        compilation_id: parse_id(stored.compilation_id)?,
        provider_request_digest: Digest32::from_array(stored.provider_request_digest),
        delivered: stored.delivered,
        rejected_reason,
        observed_token_positions: stored.observed_token_positions,
        truncation_observed: stored.truncation_observed,
    };
    value
        .validate()
        .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
    Ok(value)
}

const fn terminal_outcome_code(value: PromptRuntimeTerminalOutcomeV1) -> u8 {
    match value {
        PromptRuntimeTerminalOutcomeV1::Delivered => 0,
        PromptRuntimeTerminalOutcomeV1::Rejected => 1,
        PromptRuntimeTerminalOutcomeV1::NotDispatched => 2,
        PromptRuntimeTerminalOutcomeV1::Indeterminate => 3,
    }
}

fn decode_terminal_outcome(
    value: u8,
) -> Result<PromptRuntimeTerminalOutcomeV1, AgentdPromptRuntimeError> {
    match value {
        0 => Ok(PromptRuntimeTerminalOutcomeV1::Delivered),
        1 => Ok(PromptRuntimeTerminalOutcomeV1::Rejected),
        2 => Ok(PromptRuntimeTerminalOutcomeV1::NotDispatched),
        3 => Ok(PromptRuntimeTerminalOutcomeV1::Indeterminate),
        _ => Err(AgentdPromptRuntimeError::CorruptState),
    }
}

fn parse_id(value: String) -> Result<StableId, AgentdPromptRuntimeError> {
    StableId::new(value).map_err(|_| AgentdPromptRuntimeError::CorruptState)
}

fn prepare_state_directory(path: &Path) -> Result<(), AgentdPromptRuntimeError> {
    if let Err(error) = std::fs::create_dir(path)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(AgentdPromptRuntimeError::Unavailable);
    }
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(AgentdPromptRuntimeError::CorruptState);
    }
    set_private_directory_permissions(path)
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) -> Result<(), AgentdPromptRuntimeError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| AgentdPromptRuntimeError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) -> Result<(), AgentdPromptRuntimeError> {
    Ok(())
}

#[cfg(unix)]
fn set_private_file_permissions(path: &Path) -> Result<(), AgentdPromptRuntimeError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .map_err(|_| AgentdPromptRuntimeError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_file_permissions(_path: &Path) -> Result<(), AgentdPromptRuntimeError> {
    Ok(())
}

#[cfg(unix)]
fn sync_state_directory(path: &Path) -> Result<(), AgentdPromptRuntimeError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| AgentdPromptRuntimeError::IndeterminateDurability)
}

#[cfg(not(unix))]
fn sync_state_directory(_path: &Path) -> Result<(), AgentdPromptRuntimeError> {
    Ok(())
}

fn current_unix_ms() -> Result<u64, AgentdPromptRuntimeError> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdPromptRuntimeError::Unavailable)?
        .as_millis();
    u64::try_from(value).map_err(|_| AgentdPromptRuntimeError::Unavailable)
}

fn push_runtime_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn validate_thread_id(thread_id: &str) -> Result<(), AgentdPromptRuntimeError> {
    if thread_id.is_empty() || thread_id.len() > 256 || thread_id.as_bytes().contains(&0) {
        return Err(AgentdPromptRuntimeError::InvalidTurnId);
    }
    Ok(())
}

fn validate_turn_id(turn_id: &str) -> Result<(), AgentdPromptRuntimeError> {
    if turn_id.is_empty() || turn_id.len() > 256 || turn_id.as_bytes().contains(&0) {
        return Err(AgentdPromptRuntimeError::InvalidTurnId);
    }
    Ok(())
}

fn validate_model(model: &str) -> Result<(), AgentdPromptRuntimeError> {
    if model.is_empty() || model.len() > 256 || model.as_bytes().contains(&0) {
        return Err(AgentdPromptRuntimeError::InvalidModel);
    }
    Ok(())
}

fn host_error(error: AgentdPromptRuntimeError) -> PromptRuntimeHostError {
    PromptRuntimeHostError::new("agentd_prompt_runtime_error", error.to_string())
}

#[cfg(test)]
#[path = "prompt_runtime_tests.rs"]
mod tests;
