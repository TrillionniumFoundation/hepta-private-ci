//! Agentd-owned canonical context delivery lifecycle.
//!
//! Raw canonical context bytes remain in process memory. Durable state contains
//! only bounded metadata, the construction-closed preparation archive, the
//! canonical provider intent/receipt, and canonical context-delivery evidence.
//! A restart after staging requires an exact recompile/restage. A restart after
//! dispatch keeps the attempt unresolved and blocks blind retry until a
//! canonical provider receipt is reconciled.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_context_compiler::ContextDeliveryPreparationV2;
use codex_hepta_context_compiler::ContextProviderDeliveryDecisionV2;
use codex_hepta_context_compiler::ContextProviderDeliveryVerifierV2;
use codex_hepta_context_compiler::observe_delivery;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_intelligence::PreparedPromptDeliveryV3;
use codex_hepta_intelligence::PromptRegistryCompiledContextV3;
use codex_hepta_intelligence::prepare_prompt_delivery_v3;
use codex_hepta_prompt_extension::PromptRuntimeContextV3;
use codex_hepta_prompt_extension::PromptRuntimeDispatchFutureV3;
use codex_hepta_prompt_extension::PromptRuntimeDispatchRecordV3;
use codex_hepta_prompt_extension::PromptRuntimeFinalUseFutureV3;
use codex_hepta_prompt_extension::PromptRuntimeFinalUseProofV3;
use codex_hepta_prompt_extension::PromptRuntimeFinalUseRequestV3;
use codex_hepta_prompt_extension::PromptRuntimeHostErrorV3;
use codex_hepta_prompt_extension::PromptRuntimeHostV3;
use codex_hepta_prompt_extension::PromptRuntimePrepareFutureV3;
use codex_hepta_prompt_extension::PromptRuntimePrepareRequestV3;
use codex_hepta_prompt_extension::PromptRuntimeRecordFutureV3;
use codex_hepta_prompt_extension::PromptRuntimeTerminalRecordV3;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const STORE_SCHEMA: u32 = 1;
const STATE_FILE: &str = "context-runtime-v3.json";
const NEXT_FILE: &str = "context-runtime-v3.next";
const LOCK_FILE: &str = "context-runtime-v3.lock";
const MAX_STATE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_STAGES: usize = 256;
const MAX_DISPATCHES: usize = 1024;
const MAX_TERMINALS: usize = 1024;
const PROVIDER_WITNESS_DOMAIN: &str = "codex:provider-context-final-use-witness:v1";
const DELIVERY_VERIFIER_DOMAIN: &[u8] = b"hepta.agentd.context-delivery-verifier.v3";
const DELIVERY_EVIDENCE_DOMAIN: &[u8] = b"hepta.agentd.context-delivery-evidence.v3";

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct TurnKey {
    thread_id: String,
    turn_id: String,
}

#[derive(Clone)]
struct LiveStage {
    compiled: Arc<PromptRegistryCompiledContextV3>,
    context: PromptRuntimeContextV3,
}

struct PreparedAttempt {
    key: TurnKey,
    prepared: PreparedPromptDeliveryV3,
    context: PromptRuntimeContextV3,
    proof: PromptRuntimeFinalUseProofV3,
}

#[derive(Default)]
struct LiveState {
    stages: BTreeMap<TurnKey, LiveStage>,
    prepared: BTreeMap<String, PreparedAttempt>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredStage {
    thread_id: String,
    turn_id: String,
    compilation_id: String,
    context_binding_digest: String,
    context_attachment_digest: String,
    context_payload_digest: String,
    source_binding_digest: String,
    execution_profile_digest: String,
    tokenization_proof_digest: String,
    serialized_token_count: u64,
    model: String,
    deadline_ms: u64,
}

impl StoredStage {
    fn key(&self) -> TurnKey {
        TurnKey {
            thread_id: self.thread_id.clone(),
            turn_id: self.turn_id.clone(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredProof {
    compilation_id: String,
    context_binding_digest: String,
    context_payload_digest: String,
    source_binding_digest: String,
    execution_profile_digest: String,
    tokenization_proof_digest: String,
    preparation_digest: String,
    authority_digest: String,
    serialized_token_count: u64,
    attempt_id: String,
    thread_id: String,
    turn_id: String,
    provider_id: String,
    model: String,
    prepared_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredDispatch {
    key: StoredTurnKey,
    proof: StoredProof,
    intent: ProviderInvocationIntent,
    preparation_archive: Vec<u8>,
    dispatched_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredTurnKey {
    thread_id: String,
    turn_id: String,
}

impl StoredTurnKey {
    fn runtime_key(&self) -> TurnKey {
        TurnKey {
            thread_id: self.thread_id.clone(),
            turn_id: self.turn_id.clone(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredTerminal {
    key: StoredTurnKey,
    receipt: ProviderInvocationReceipt,
    delivery_receipt_digest: String,
    delivery_evidence: Vec<u8>,
    observed_unix_ms: u64,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableState {
    schema: u32,
    stages: BTreeMap<String, StoredStage>,
    dispatches: BTreeMap<String, StoredDispatch>,
    terminals: BTreeMap<String, StoredTerminal>,
}

impl DurableState {
    fn empty() -> Self {
        Self {
            schema: STORE_SCHEMA,
            ..Self::default()
        }
    }
}

struct DurableStore {
    root: PathBuf,
    _lock: File,
}

pub struct AgentdPromptProductOwnerV3 {
    registry: Arc<Mutex<DurablePromptRegistry>>,
    live: Mutex<LiveState>,
    durable: Mutex<DurableState>,
    store: DurableStore,
    poisoned: AtomicBool,
}

impl std::fmt::Debug for AgentdPromptProductOwnerV3 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let live = self.live.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let durable = self
            .durable
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        formatter
            .debug_struct("AgentdPromptProductOwnerV3")
            .field("live_stages", &live.stages.len())
            .field("prepared_attempts", &live.prepared.len())
            .field("durable_stages", &durable.stages.len())
            .field("dispatches", &durable.dispatches.len())
            .field("terminals", &durable.terminals.len())
            .field("requires_reopen", &self.poisoned.load(Ordering::Acquire))
            .finish()
    }
}

#[derive(Debug)]
pub enum AgentdPromptProductErrorV3 {
    InvalidScope,
    InvalidContext,
    StageConflict,
    CapacityExceeded,
    RecompileRequired,
    IndeterminatePending,
    PreparedAttemptMissing,
    DispatchConflict,
    TerminalConflict,
    EvidenceMismatch,
    CorruptState,
    StateLocked,
    Unavailable,
    IndeterminateDurability,
    ReopenRequired,
    RegistryPoisoned,
    Product(String),
}

impl AgentdPromptProductErrorV3 {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidScope => "agentd_prompt_v3_invalid_scope",
            Self::InvalidContext => "agentd_prompt_v3_invalid_context",
            Self::StageConflict => "agentd_prompt_v3_stage_conflict",
            Self::CapacityExceeded => "agentd_prompt_v3_capacity_exceeded",
            Self::RecompileRequired => "agentd_prompt_v3_recompile_required",
            Self::IndeterminatePending => "agentd_prompt_v3_indeterminate_pending",
            Self::PreparedAttemptMissing => "agentd_prompt_v3_prepared_attempt_missing",
            Self::DispatchConflict => "agentd_prompt_v3_dispatch_conflict",
            Self::TerminalConflict => "agentd_prompt_v3_terminal_conflict",
            Self::EvidenceMismatch => "agentd_prompt_v3_evidence_mismatch",
            Self::CorruptState => "agentd_prompt_v3_corrupt_state",
            Self::StateLocked => "agentd_prompt_v3_state_locked",
            Self::Unavailable => "agentd_prompt_v3_unavailable",
            Self::IndeterminateDurability => "agentd_prompt_v3_indeterminate_durability",
            Self::ReopenRequired => "agentd_prompt_v3_reopen_required",
            Self::RegistryPoisoned => "agentd_prompt_v3_registry_poisoned",
            Self::Product(_) => "agentd_prompt_v3_product",
        }
    }
}

impl std::fmt::Display for AgentdPromptProductErrorV3 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}", self.code())
    }
}

impl std::error::Error for AgentdPromptProductErrorV3 {}

impl AgentdPromptProductOwnerV3 {
    pub fn open(
        registry: Arc<Mutex<DurablePromptRegistry>>,
        directory: &Path,
    ) -> Result<Self, AgentdPromptProductErrorV3> {
        let (store, state) = DurableStore::open(directory)?;
        validate_durable_state(&state)?;
        Ok(Self {
            registry,
            live: Mutex::new(LiveState::default()),
            durable: Mutex::new(state),
            store,
            poisoned: AtomicBool::new(false),
        })
    }

    pub fn stage(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        compiled: PromptRegistryCompiledContextV3,
    ) -> Result<crate::PromptRuntimeStageDisposition, AgentdPromptProductErrorV3> {
        self.ensure_available()?;
        validate_identity(thread_id)?;
        validate_identity(turn_id)?;
        validate_identity(model)?;
        compiled
            .validate()
            .map_err(|error| AgentdPromptProductErrorV3::Product(error.to_string()))?;
        if requested_deadline_ms == 0
            || model != compiled.execution_profile.provider_model
            || compiled.payload().is_empty()
        {
            return Err(AgentdPromptProductErrorV3::InvalidContext);
        }
        let bundle = std::str::from_utf8(compiled.payload())
            .map_err(|_| AgentdPromptProductErrorV3::InvalidContext)?;
        let deadline_ms = requested_deadline_ms.min(compiled.portfolio_valid_until_unix_ms());
        if deadline_ms == 0 {
            return Err(AgentdPromptProductErrorV3::InvalidContext);
        }
        let context = PromptRuntimeContextV3::new(
            compiled.compiled.receipt().compilation_id().clone(),
            compiled.attachment.attachment_digest(),
            compiled.attachment.payload_digest(),
            compiled.source_binding_digest(),
            compiled.execution_profile_digest(),
            compiled.tokenization_proof_digest(),
            compiled
                .serialized_context
                .receipt()
                .serialized_token_count(),
            model.to_owned(),
            deadline_ms,
            bundle.to_owned(),
        )
        .map_err(|_| AgentdPromptProductErrorV3::InvalidContext)?;
        let key = TurnKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        let stored = stored_stage(&key, &context);
        let stage_id = stage_id(&key);
        let disposition = self.commit_durable(|state| {
            if let Some(existing) = state.stages.get(&stage_id) {
                if existing != &stored {
                    return Err(AgentdPromptProductErrorV3::StageConflict);
                }
                return Ok(crate::PromptRuntimeStageDisposition::Unchanged);
            }
            if state.stages.len() >= MAX_STAGES {
                return Err(AgentdPromptProductErrorV3::CapacityExceeded);
            }
            state.stages.insert(stage_id, stored);
            Ok(crate::PromptRuntimeStageDisposition::Inserted)
        })?;
        let mut live = self
            .live
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        live.stages.insert(
            key,
            LiveStage {
                compiled: Arc::new(compiled),
                context,
            },
        );
        Ok(disposition)
    }

    pub fn reconcile_provider_receipt(
        &self,
        receipt: ProviderInvocationReceipt,
        observed_unix_ms: u64,
    ) -> Result<(), AgentdPromptProductErrorV3> {
        self.record_terminal_receipt(receipt, observed_unix_ms)
    }

    pub fn delivery_evidence(
        &self,
        attempt_id: &str,
    ) -> Result<Option<Vec<u8>>, AgentdPromptProductErrorV3> {
        self.ensure_available()?;
        let state = self
            .durable
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        Ok(state
            .terminals
            .get(attempt_id)
            .map(|terminal| terminal.delivery_evidence.clone()))
    }

    pub fn host(self: &Arc<Self>) -> Result<PromptRuntimeHostV3, AgentdPromptProductErrorV3> {
        let prepare_owner = Arc::clone(self);
        let final_use_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHostV3::new(
            move |request: PromptRuntimePrepareRequestV3| -> PromptRuntimePrepareFutureV3 {
                let owner = Arc::clone(&prepare_owner);
                Box::pin(async move { owner.prepare_context(request).map_err(host_error) })
            },
            move |request: PromptRuntimeFinalUseRequestV3| -> PromptRuntimeFinalUseFutureV3 {
                let owner = Arc::clone(&final_use_owner);
                Box::pin(async move { owner.prepare_final_use(request).map_err(host_error) })
            },
            move |record: PromptRuntimeDispatchRecordV3| -> PromptRuntimeDispatchFutureV3 {
                let owner = Arc::clone(&dispatch_owner);
                Box::pin(async move { owner.record_dispatch(record).map_err(host_error) })
            },
            move |record: PromptRuntimeTerminalRecordV3| -> PromptRuntimeRecordFutureV3 {
                let owner = Arc::clone(&record_owner);
                Box::pin(async move {
                    owner
                        .record_terminal_receipt(record.receipt, record.observed_unix_ms)
                        .map_err(host_error)
                })
            },
        )
        .map_err(|error| AgentdPromptProductErrorV3::Product(error.to_string()))
    }

    fn prepare_context(
        &self,
        request: PromptRuntimePrepareRequestV3,
    ) -> Result<Option<PromptRuntimeContextV3>, AgentdPromptProductErrorV3> {
        self.ensure_available()?;
        validate_identity(&request.thread_id)?;
        validate_identity(&request.turn_id)?;
        let key = TurnKey {
            thread_id: request.thread_id,
            turn_id: request.turn_id,
        };
        if self.has_unresolved_dispatch(&key)? {
            return Err(AgentdPromptProductErrorV3::IndeterminatePending);
        }
        let live = self
            .live
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        if let Some(stage) = live.stages.get(&key) {
            return Ok(Some(stage.context.clone()));
        }
        let durable = self
            .durable
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        if durable.stages.contains_key(&stage_id(&key)) {
            return Err(AgentdPromptProductErrorV3::RecompileRequired);
        }
        Ok(None)
    }

    fn prepare_final_use(
        &self,
        request: PromptRuntimeFinalUseRequestV3,
    ) -> Result<PromptRuntimeFinalUseProofV3, AgentdPromptProductErrorV3> {
        self.ensure_available()?;
        let key = TurnKey {
            thread_id: request.thread_id.clone(),
            turn_id: request.turn_id.clone(),
        };
        if self.has_unresolved_dispatch(&key)? {
            return Err(AgentdPromptProductErrorV3::IndeterminatePending);
        }
        let stage = self
            .live
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
            .stages
            .get(&key)
            .cloned()
            .ok_or(AgentdPromptProductErrorV3::RecompileRequired)?;
        if request.compilation_id != stage.context.compilation_id
            || request.context_binding_digest != stage.context.binding_digest()
            || request.context_attachment_digest != stage.context.context_attachment_digest
            || request.context_payload_digest != stage.context.context_payload_digest
            || request.source_binding_digest != stage.context.source_binding_digest
            || request.execution_profile_digest != stage.context.execution_profile_digest
            || request.tokenization_proof_digest != stage.context.tokenization_proof_digest
            || request.serialized_token_count != stage.context.serialized_token_count
            || request.model != stage.context.model
            || request.provider_id != stage.compiled.execution_profile.provider_id
        {
            return Err(AgentdPromptProductErrorV3::EvidenceMismatch);
        }
        let now = current_unix_ms()?;
        if now >= stage.context.deadline_ms {
            return Err(AgentdPromptProductErrorV3::InvalidContext);
        }
        let preparation_id = StableId::new(format!("context-preparation:v3:{}", request.attempt_id))
            .map_err(|_| AgentdPromptProductErrorV3::InvalidScope)?;
        let prepared = {
            let registry = self
                .registry
                .lock()
                .map_err(|_| AgentdPromptProductErrorV3::RegistryPoisoned)?;
            prepare_prompt_delivery_v3(&registry, &stage.compiled, now, preparation_id)
                .map_err(|error| AgentdPromptProductErrorV3::Product(error.to_string()))?
        };
        let proof = PromptRuntimeFinalUseProofV3 {
            compilation_id: request.compilation_id.clone(),
            context_binding_digest: request.context_binding_digest,
            context_payload_digest: request.context_payload_digest,
            source_binding_digest: request.source_binding_digest,
            execution_profile_digest: request.execution_profile_digest,
            tokenization_proof_digest: request.tokenization_proof_digest,
            preparation_digest: prepared.preparation.preparation_digest(),
            authority_digest: prepared.authority_digest(),
            serialized_token_count: request.serialized_token_count,
            attempt_id: request.attempt_id.clone(),
            thread_id: request.thread_id.clone(),
            turn_id: request.turn_id.clone(),
            provider_id: request.provider_id.clone(),
            model: request.model.clone(),
            prepared_unix_ms: now,
        };
        proof
            .validate_for(&request)
            .map_err(|_| AgentdPromptProductErrorV3::EvidenceMismatch)?;
        self.live
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
            .prepared
            .insert(
                request.attempt_id,
                PreparedAttempt {
                    key,
                    prepared,
                    context: stage.context,
                    proof: proof.clone(),
                },
            );
        Ok(proof)
    }

    fn record_dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV3,
    ) -> Result<(), AgentdPromptProductErrorV3> {
        self.ensure_available()?;
        record
            .intent
            .validate()
            .map_err(|_| AgentdPromptProductErrorV3::EvidenceMismatch)?;
        let attempt_id = record.intent.attempt_id.as_str().to_owned();
        if record.proof.attempt_id != record.intent.attempt_id.as_str()
            || record.context != self.context_for(&record.proof)?
        {
            return Err(AgentdPromptProductErrorV3::EvidenceMismatch);
        }
        let prepared = self
            .live
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
            .prepared
            .remove(&record.proof.attempt_id)
            .ok_or(AgentdPromptProductErrorV3::PreparedAttemptMissing)?;
        if prepared.proof != record.proof || prepared.context != record.context {
            return Err(AgentdPromptProductErrorV3::EvidenceMismatch);
        }
        validate_intent_binding(&record.intent, &prepared.context, &prepared.proof)?;
        let preparation_archive = prepared
            .prepared
            .preparation
            .canonical_archive_bytes()
            .map_err(|error| AgentdPromptProductErrorV3::Product(error.to_string()))?;
        let stored = StoredDispatch {
            key: StoredTurnKey {
                thread_id: prepared.key.thread_id,
                turn_id: prepared.key.turn_id,
            },
            proof: stored_proof(&record.proof),
            intent: record.intent,
            preparation_archive,
            dispatched_unix_ms: record.dispatched_unix_ms,
        };
        self.commit_durable(|state| {
            if let Some(existing) = state.dispatches.get(&attempt_id) {
                return if existing == &stored {
                    Ok(())
                } else {
                    Err(AgentdPromptProductErrorV3::DispatchConflict)
                };
            }
            if state.dispatches.len() >= MAX_DISPATCHES {
                return Err(AgentdPromptProductErrorV3::CapacityExceeded);
            }
            if unresolved_for_key(state, &stored.key) {
                return Err(AgentdPromptProductErrorV3::IndeterminatePending);
            }
            state.dispatches.insert(attempt_id, stored);
            Ok(())
        })
    }

    fn record_terminal_receipt(
        &self,
        receipt: ProviderInvocationReceipt,
        observed_unix_ms: u64,
    ) -> Result<(), AgentdPromptProductErrorV3> {
        self.ensure_available()?;
        receipt
            .validate()
            .map_err(|_| AgentdPromptProductErrorV3::EvidenceMismatch)?;
        if observed_unix_ms == 0 {
            return Err(AgentdPromptProductErrorV3::InvalidScope);
        }
        let attempt_id = receipt.attempt_id.as_str().to_owned();
        let dispatch = self
            .durable
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
            .dispatches
            .get(&attempt_id)
            .cloned()
            .ok_or(AgentdPromptProductErrorV3::PreparedAttemptMissing)?;
        if receipt.intent != dispatch.intent {
            return Err(AgentdPromptProductErrorV3::EvidenceMismatch);
        }
        let key = dispatch.key.runtime_key();
        let stage = self
            .live
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
            .stages
            .get(&key)
            .cloned()
            .ok_or(AgentdPromptProductErrorV3::RecompileRequired)?;
        if stage.context.context_payload_digest.to_string()
            != dispatch.proof.context_payload_digest
            || stage.context.source_binding_digest.to_string()
                != dispatch.proof.source_binding_digest
            || stage.context.execution_profile_digest.to_string()
                != dispatch.proof.execution_profile_digest
            || stage.context.tokenization_proof_digest.to_string()
                != dispatch.proof.tokenization_proof_digest
        {
            return Err(AgentdPromptProductErrorV3::EvidenceMismatch);
        }
        let preparation = ContextDeliveryPreparationV2::reopen_canonical_archive(
            &dispatch.preparation_archive,
            &stage.compiled.attachment,
            &stage.compiled.serialized_context,
            &stage.compiled.model_profile,
        )
        .map_err(|error| AgentdPromptProductErrorV3::Product(error.to_string()))?;
        let authority_digest = parse_digest(&dispatch.proof.authority_digest)?;
        let verifier = AgentdProviderDeliveryVerifierV3 {
            authority_digest,
            recorded_at_unix_ms: observed_unix_ms,
        };
        let delivery_id = StableId::new(format!("context-delivery:v3:{attempt_id}"))
            .map_err(|_| AgentdPromptProductErrorV3::InvalidScope)?;
        let delivery = observe_delivery(
            &preparation,
            &stage.compiled.attachment,
            &stage.compiled.serialized_context,
            &stage.compiled.model_profile,
            delivery_id,
            &receipt,
            &verifier,
            observed_unix_ms,
        )
        .map_err(|error| AgentdPromptProductErrorV3::Product(error.to_string()))?;
        let evidence = delivery
            .canonical_evidence_bytes()
            .map_err(|error| AgentdPromptProductErrorV3::Product(error.to_string()))?;
        let terminal = StoredTerminal {
            key: dispatch.key.clone(),
            receipt: receipt.clone(),
            delivery_receipt_digest: delivery.receipt_digest().to_string(),
            delivery_evidence: evidence,
            observed_unix_ms,
        };
        self.commit_durable(|state| {
            if let Some(existing) = state.terminals.get(&attempt_id) {
                return if existing == &terminal {
                    Ok(())
                } else {
                    Err(AgentdPromptProductErrorV3::TerminalConflict)
                };
            }
            if state.terminals.len() >= MAX_TERMINALS {
                return Err(AgentdPromptProductErrorV3::CapacityExceeded);
            }
            state.terminals.insert(attempt_id.clone(), terminal);
            if terminal_clears_stage(&receipt.terminal) {
                state.stages.remove(&stage_id(&key));
            }
            Ok(())
        })?;
        if terminal_clears_stage(&receipt.terminal) {
            self.live
                .lock()
                .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
                .stages
                .remove(&key);
        }
        Ok(())
    }

    fn context_for(
        &self,
        proof: &PromptRuntimeFinalUseProofV3,
    ) -> Result<PromptRuntimeContextV3, AgentdPromptProductErrorV3> {
        let key = TurnKey {
            thread_id: proof.thread_id.clone(),
            turn_id: proof.turn_id.clone(),
        };
        self.live
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
            .stages
            .get(&key)
            .map(|stage| stage.context.clone())
            .ok_or(AgentdPromptProductErrorV3::RecompileRequired)
    }

    fn has_unresolved_dispatch(
        &self,
        key: &TurnKey,
    ) -> Result<bool, AgentdPromptProductErrorV3> {
        let state = self
            .durable
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        Ok(unresolved_for_key(
            &state,
            &StoredTurnKey {
                thread_id: key.thread_id.clone(),
                turn_id: key.turn_id.clone(),
            },
        ))
    }

    fn ensure_available(&self) -> Result<(), AgentdPromptProductErrorV3> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(AgentdPromptProductErrorV3::ReopenRequired);
        }
        Ok(())
    }

    fn commit_durable<T>(
        &self,
        mutation: impl FnOnce(&mut DurableState) -> Result<T, AgentdPromptProductErrorV3>,
    ) -> Result<T, AgentdPromptProductErrorV3> {
        self.ensure_available()?;
        let mut current = self
            .durable
            .lock()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        let mut next = current.clone();
        let result = mutation(&mut next)?;
        validate_durable_state(&next)?;
        if next != *current {
            if let Err(error) = self.store.persist(&next) {
                if matches!(error, AgentdPromptProductErrorV3::IndeterminateDurability) {
                    self.poisoned.store(true, Ordering::Release);
                }
                return Err(error);
            }
            *current = next;
        }
        Ok(result)
    }
}

impl DurableStore {
    fn open(directory: &Path) -> Result<(Self, DurableState), AgentdPromptProductErrorV3> {
        std::fs::create_dir_all(directory)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        set_private_directory_permissions(directory)?;
        let lock_path = directory.join(LOCK_FILE);
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        set_private_file_permissions(&lock_path)?;
        lock.try_lock()
            .map_err(|_| AgentdPromptProductErrorV3::StateLocked)?;
        let store = Self {
            root: directory.to_path_buf(),
            _lock: lock,
        };
        let path = directory.join(STATE_FILE);
        if !path.exists() {
            return Ok((store, DurableState::empty()));
        }
        let mut bytes = Vec::new();
        File::open(path)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?
            .take(MAX_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
            return Err(AgentdPromptProductErrorV3::CorruptState);
        }
        let state = serde_json::from_slice(&bytes)
            .map_err(|_| AgentdPromptProductErrorV3::CorruptState)?;
        Ok((store, state))
    }

    fn persist(&self, state: &DurableState) -> Result<(), AgentdPromptProductErrorV3> {
        let bytes = serde_json::to_vec(state)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
            return Err(AgentdPromptProductErrorV3::CapacityExceeded);
        }
        let next_path = self.root.join(NEXT_FILE);
        let state_path = self.root.join(STATE_FILE);
        let mut next = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&next_path)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        set_private_file_permissions(&next_path)?;
        next.write_all(&bytes)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        next.sync_all()
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        std::fs::rename(&next_path, &state_path)
            .map_err(|_| AgentdPromptProductErrorV3::Unavailable)?;
        set_private_file_permissions(&state_path)?;
        sync_directory(&self.root)
    }
}

struct AgentdProviderDeliveryVerifierV3 {
    authority_digest: Digest32,
    recorded_at_unix_ms: u64,
}

impl ContextProviderDeliveryVerifierV2 for AgentdProviderDeliveryVerifierV3 {
    fn verifier_digest(&self) -> Digest32 {
        Digest32::of_bytes(DELIVERY_VERIFIER_DOMAIN)
    }

    fn verify_delivery(
        &self,
        receipt: &ProviderInvocationReceipt,
        preparation: &ContextDeliveryPreparationV2,
    ) -> Result<ContextProviderDeliveryDecisionV2, String> {
        receipt.validate()?;
        let binding = &receipt.intent.binding;
        let input = binding
            .ephemeral_input_sha256
            .as_ref()
            .ok_or_else(|| "context input digest missing".to_owned())?;
        let witness = binding
            .ephemeral_input_witness_sha256
            .as_ref()
            .ok_or_else(|| "context witness digest missing".to_owned())?;
        let expected = context_witness_digest(receipt, self.authority_digest)?;
        if witness.as_str() != expected {
            return Err("context witness does not authenticate the preparation authority".to_owned());
        }
        if input.as_str() != preparation.payload_digest().to_string() {
            return Err("context input digest does not bind the prepared payload".to_owned());
        }
        let receipt_bytes = receipt.canonical_wire_bytes()?;
        let mut evidence = DELIVERY_EVIDENCE_DOMAIN.to_vec();
        evidence.extend_from_slice(preparation.preparation_digest().as_array());
        evidence.extend_from_slice(self.authority_digest.as_array());
        evidence.extend_from_slice(&receipt_bytes);
        Ok(ContextProviderDeliveryDecisionV2 {
            evidence_digest: Digest32::of_bytes(&evidence),
            recorded_at_unix_ms: self.recorded_at_unix_ms,
        })
    }
}

fn context_witness_digest(
    receipt: &ProviderInvocationReceipt,
    authority_digest: Digest32,
) -> Result<String, String> {
    let binding = &receipt.intent.binding;
    let input = binding
        .ephemeral_input_sha256
        .as_ref()
        .ok_or_else(|| "context input digest missing".to_owned())?;
    let (previous_presence, previous_sha256) = match &binding.previous_response_id_sha256 {
        Some(digest) => ("present", digest.as_str()),
        None => ("absent", ""),
    };
    Ok(digest_parts([
        PROVIDER_WITNESS_DOMAIN,
        receipt.intent.attempt_nonce_sha256.as_str(),
        binding.thread_id.as_str(),
        binding.turn_id.as_str(),
        binding.host_request_binding_id_sha256.as_str(),
        transport_name(binding.transport),
        binding.logical_request_sha256.as_str(),
        binding.wire_semantic_sha256.as_str(),
        previous_presence,
        previous_sha256,
        if binding.generate { "generate" } else { "no_generate" },
        &authority_digest.to_string(),
        input.as_str(),
    ]))
}

fn validate_intent_binding(
    intent: &ProviderInvocationIntent,
    context: &PromptRuntimeContextV3,
    proof: &PromptRuntimeFinalUseProofV3,
) -> Result<(), AgentdPromptProductErrorV3> {
    intent
        .validate()
        .map_err(|_| AgentdPromptProductErrorV3::EvidenceMismatch)?;
    let binding = &intent.binding;
    if binding.thread_id != proof.thread_id
        || binding.turn_id != proof.turn_id
        || binding.provider_id != proof.provider_id
        || binding.model != proof.model
        || binding.ephemeral_input_sha256.as_ref().map(|value| value.as_str())
            != Some(context.context_payload_digest.to_string().as_str())
        || binding.ephemeral_input_witness_sha256.is_none()
    {
        return Err(AgentdPromptProductErrorV3::EvidenceMismatch);
    }
    Ok(())
}

fn validate_durable_state(state: &DurableState) -> Result<(), AgentdPromptProductErrorV3> {
    if state.schema != STORE_SCHEMA
        || state.stages.len() > MAX_STAGES
        || state.dispatches.len() > MAX_DISPATCHES
        || state.terminals.len() > MAX_TERMINALS
    {
        return Err(AgentdPromptProductErrorV3::CorruptState);
    }
    for (stage_id_value, stage) in &state.stages {
        validate_identity(&stage.thread_id)?;
        validate_identity(&stage.turn_id)?;
        validate_identity(&stage.model)?;
        if *stage_id_value != stage_id(&stage.key())
            || stage.serialized_token_count == 0
            || stage.deadline_ms == 0
        {
            return Err(AgentdPromptProductErrorV3::CorruptState);
        }
        for value in [
            &stage.context_binding_digest,
            &stage.context_attachment_digest,
            &stage.context_payload_digest,
            &stage.source_binding_digest,
            &stage.execution_profile_digest,
            &stage.tokenization_proof_digest,
        ] {
            parse_digest(value)?;
        }
    }
    for (attempt_id, dispatch) in &state.dispatches {
        dispatch
            .intent
            .validate()
            .map_err(|_| AgentdPromptProductErrorV3::CorruptState)?;
        if attempt_id != dispatch.intent.attempt_id.as_str()
            || dispatch.proof.attempt_id != *attempt_id
            || dispatch.preparation_archive.is_empty()
            || dispatch.dispatched_unix_ms == 0
        {
            return Err(AgentdPromptProductErrorV3::CorruptState);
        }
    }
    for (attempt_id, terminal) in &state.terminals {
        terminal
            .receipt
            .validate()
            .map_err(|_| AgentdPromptProductErrorV3::CorruptState)?;
        if attempt_id != terminal.receipt.attempt_id.as_str()
            || !state.dispatches.contains_key(attempt_id)
            || terminal.delivery_evidence.is_empty()
            || terminal.observed_unix_ms == 0
        {
            return Err(AgentdPromptProductErrorV3::CorruptState);
        }
        parse_digest(&terminal.delivery_receipt_digest)?;
    }
    let mut unresolved = BTreeMap::<StoredTurnKey, String>::new();
    for (attempt_id, dispatch) in &state.dispatches {
        let is_unresolved = state.terminals.get(attempt_id).is_none_or(|terminal| {
            matches!(terminal.receipt.terminal, ProviderTerminal::Indeterminate { .. })
        });
        if is_unresolved
            && unresolved
                .insert(dispatch.key.clone(), attempt_id.clone())
                .is_some()
        {
            return Err(AgentdPromptProductErrorV3::CorruptState);
        }
    }
    Ok(())
}

fn unresolved_for_key(state: &DurableState, key: &StoredTurnKey) -> bool {
    state.dispatches.iter().any(|(attempt_id, dispatch)| {
        &dispatch.key == key
            && state.terminals.get(attempt_id).is_none_or(|terminal| {
                matches!(terminal.receipt.terminal, ProviderTerminal::Indeterminate { .. })
            })
    })
}

fn terminal_clears_stage(terminal: &ProviderTerminal) -> bool {
    matches!(
        terminal,
        ProviderTerminal::Completed { .. }
            | ProviderTerminal::CompletedUnary { .. }
            | ProviderTerminal::Rejected { .. }
    )
}

fn stored_stage(key: &TurnKey, context: &PromptRuntimeContextV3) -> StoredStage {
    StoredStage {
        thread_id: key.thread_id.clone(),
        turn_id: key.turn_id.clone(),
        compilation_id: context.compilation_id.to_string(),
        context_binding_digest: context.binding_digest().to_string(),
        context_attachment_digest: context.context_attachment_digest.to_string(),
        context_payload_digest: context.context_payload_digest.to_string(),
        source_binding_digest: context.source_binding_digest.to_string(),
        execution_profile_digest: context.execution_profile_digest.to_string(),
        tokenization_proof_digest: context.tokenization_proof_digest.to_string(),
        serialized_token_count: context.serialized_token_count,
        model: context.model.clone(),
        deadline_ms: context.deadline_ms,
    }
}

fn stored_proof(proof: &PromptRuntimeFinalUseProofV3) -> StoredProof {
    StoredProof {
        compilation_id: proof.compilation_id.to_string(),
        context_binding_digest: proof.context_binding_digest.to_string(),
        context_payload_digest: proof.context_payload_digest.to_string(),
        source_binding_digest: proof.source_binding_digest.to_string(),
        execution_profile_digest: proof.execution_profile_digest.to_string(),
        tokenization_proof_digest: proof.tokenization_proof_digest.to_string(),
        preparation_digest: proof.preparation_digest.to_string(),
        authority_digest: proof.authority_digest.to_string(),
        serialized_token_count: proof.serialized_token_count,
        attempt_id: proof.attempt_id.clone(),
        thread_id: proof.thread_id.clone(),
        turn_id: proof.turn_id.clone(),
        provider_id: proof.provider_id.clone(),
        model: proof.model.clone(),
        prepared_unix_ms: proof.prepared_unix_ms,
    }
}

fn stage_id(key: &TurnKey) -> String {
    digest_parts([
        "hepta.agentd.context-stage.v3",
        key.thread_id.as_str(),
        key.turn_id.as_str(),
    ])
}

fn parse_digest(value: &str) -> Result<Digest32, AgentdPromptProductErrorV3> {
    let digest = Digest32::from_str(value)
        .map_err(|_| AgentdPromptProductErrorV3::CorruptState)?;
    if digest.is_zero() {
        return Err(AgentdPromptProductErrorV3::CorruptState);
    }
    Ok(digest)
}

fn validate_identity(value: &str) -> Result<(), AgentdPromptProductErrorV3> {
    if value.is_empty() || value.len() > 512 || value.as_bytes().contains(&0) {
        return Err(AgentdPromptProductErrorV3::InvalidScope);
    }
    Ok(())
}

fn current_unix_ms() -> Result<u64, AgentdPromptProductErrorV3> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| AgentdPromptProductErrorV3::Unavailable)
        .and_then(|duration| {
            u64::try_from(duration.as_millis())
                .map_err(|_| AgentdPromptProductErrorV3::Unavailable)
        })
}

fn transport_name(transport: ProviderTransport) -> &'static str {
    transport.as_str()
}

fn digest_parts<'a>(parts: impl IntoIterator<Item = &'a str>) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn host_error(error: AgentdPromptProductErrorV3) -> PromptRuntimeHostErrorV3 {
    PromptRuntimeHostErrorV3::new(error.code(), error.to_string())
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) -> Result<(), AgentdPromptProductErrorV3> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| AgentdPromptProductErrorV3::Unavailable)
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) -> Result<(), AgentdPromptProductErrorV3> {
    Ok(())
}

#[cfg(unix)]
fn set_private_file_permissions(path: &Path) -> Result<(), AgentdPromptProductErrorV3> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .map_err(|_| AgentdPromptProductErrorV3::Unavailable)
}

#[cfg(not(unix))]
fn set_private_file_permissions(_path: &Path) -> Result<(), AgentdPromptProductErrorV3> {
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), AgentdPromptProductErrorV3> {
    #[cfg(unix)]
    {
        File::open(path)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| AgentdPromptProductErrorV3::IndeterminateDurability)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Ok(())
    }
}
