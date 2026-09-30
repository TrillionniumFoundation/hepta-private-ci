use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::env;
use std::fmt;
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
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_codex_adapter::PromptRuntimeFinalRequestV2;
use codex_hepta_codex_adapter::PromptRuntimeFinalTerminalV2;
use codex_hepta_codex_adapter::PromptRuntimeProviderTerminalV2;
use codex_hepta_codex_adapter::PromptRuntimeRequestKindV2;
use codex_hepta_codex_adapter::PromptRuntimeTransportV2;
use codex_hepta_context_compiler::ContextDeliveryPreparationV2;
use codex_hepta_context_compiler::ContextDeliveryReceiptV2;
use codex_hepta_context_compiler::ContextDeliveryRecoveryBindingV2;
use codex_hepta_context_compiler::ContextProviderDeliveryDecisionV2;
use codex_hepta_context_compiler::ContextProviderDeliveryVerifierV2;
use codex_hepta_context_compiler::ExactFinalRequestTokenizerV2;
use codex_hepta_context_compiler::FinalProviderRequestProofV2;
use codex_hepta_context_compiler::FinalRequestFramingVerifierV2;
use codex_hepta_context_compiler::FinalRequestTokenizerIdentityV2;
use codex_hepta_context_compiler::build_delivery_recovery_binding_v2;
use codex_hepta_context_compiler::observe_final_provider_delivery_v2;
use codex_hepta_context_compiler::observe_recovered_final_provider_delivery_v2;
use codex_hepta_context_compiler::prove_final_provider_request_v2;
use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_intelligence::PreparedPromptDeliveryV3;
use codex_hepta_intelligence::PromptRegistryCompiledContextV3;
use codex_hepta_intelligence::prepare_prompt_delivery_v3;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ContextSecurityRuntimeV3;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use tokio::process::Command;

mod framing_json;
mod lifecycle;
pub(crate) mod metrics;
mod settled_history;
mod terminal_state;
mod tokenizer_io;

use metrics::Phase;
use terminal_state::apply_observation;
use terminal_state::completion_reserve;
use terminal_state::legacy_observation_version;
use terminal_state::migrate_state;
use terminal_state::validate_terminal_size;
#[cfg(test)]
mod capacity_tests;
#[cfg(all(test, unix))]
mod registry_race_tests;
#[cfg(test)]
mod runtime_tests;
#[cfg(test)]
mod settled_history_tests;
#[cfg(all(test, unix))]
mod storage_hardening_tests;

const EXACT_DELIVERY_SCHEMA: u32 = 4;
const STATE_FILE: &str = "context-delivery-v2.json";
const NEXT_FILE: &str = "context-delivery-v2.next";
const LOCK_FILE: &str = "context-delivery-v2.lock";
const MAX_DURABLE_STATE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_RECOVERY_ARCHIVE_BYTES: usize = 64 * 1024;
const MAX_STAGED_CONTEXTS: usize = 256;
const MAX_ACTIVE_ATTEMPTS: usize = 64;
const MAX_PRE_SEND_RECORDS: usize = 4096;
const MAX_TERMINAL_RECORDS: usize = 4096;
const MAX_TERMINAL_OBSERVATIONS: usize = 4096;
const MAX_TOKENIZER_FILE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_TOKENIZER_STDOUT_BYTES: u64 = 64;
const TOKENIZER_TIMEOUT_MS_DEFAULT: u64 = 30_000;
const TOKENIZER_TIMEOUT_MS_MAX: u64 = 120_000;
const PROVIDER_EVIDENCE_VERIFIER_DOMAIN: &[u8] = b"hepta.context-provider-delivery-verifier.v2";
const PROVIDER_EVIDENCE_DOMAIN: &[u8] = b"hepta.context-provider-delivery-evidence.v2";

pub(crate) const HEPTA_CONTEXT_TOKENIZER_BIN_ENV: &str = "HEPTA_CONTEXT_TOKENIZER_BIN";
const TOKENIZER_BINARY_PIN_ENV: &str = "HEPTA_CONTEXT_TOKENIZER_BINARY_SHA256";
const TOKENIZER_VOCABULARY_PIN_ENV: &str = "HEPTA_CONTEXT_TOKENIZER_VOCABULARY_SHA256";
pub(crate) const HEPTA_CONTEXT_TOKENIZER_VERSION_ENV: &str = "HEPTA_CONTEXT_TOKENIZER_VERSION";
pub(crate) const HEPTA_CONTEXT_TOKENIZER_VOCAB_ENV: &str = "HEPTA_CONTEXT_TOKENIZER_VOCAB";
pub(crate) const HEPTA_CONTEXT_TOKENIZER_NORMALIZATION_ENV: &str =
    "HEPTA_CONTEXT_TOKENIZER_NORMALIZATION";
pub(crate) const HEPTA_CONTEXT_TOKENIZER_PROFILE_SHA256_ENV: &str =
    "HEPTA_CONTEXT_TOKENIZER_PROFILE_SHA256";
pub(crate) const HEPTA_CONTEXT_TOKENIZER_PROVIDER_ID_ENV: &str =
    "HEPTA_CONTEXT_TOKENIZER_PROVIDER_ID";
pub(crate) const HEPTA_CONTEXT_TOKENIZER_MODEL_ENV: &str = "HEPTA_CONTEXT_TOKENIZER_MODEL";
pub(crate) const HEPTA_CONTEXT_TOKENIZER_TIMEOUT_MS_ENV: &str =
    "HEPTA_CONTEXT_TOKENIZER_TIMEOUT_MS";

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ExactTurnKey {
    thread_id: String,
    turn_id: String,
}

#[derive(Clone)]
struct ActiveExactDelivery {
    started: Instant,
    compiled: Arc<PromptRegistryCompiledContextV3>,
    fresh: PreparedPromptDeliveryV3,
    final_request_proof: FinalProviderRequestProofV2,
    intent: ProviderInvocationIntent,
}

#[derive(Default)]
struct ExactRuntimeState {
    staged: BTreeMap<ExactTurnKey, Arc<PromptRegistryCompiledContextV3>>,
    preparing: BTreeSet<ExactTurnKey>,
    active: BTreeMap<String, ActiveExactDelivery>,
    durable: StoredExactDeliveryState,
}

pub(crate) struct AgentdExactContextDeliveryOwner {
    registry: Arc<Mutex<DurablePromptRegistry>>,
    security: Option<Arc<ContextSecurityRuntimeV3>>,
    state: Mutex<ExactRuntimeState>,
    tokenizer: Mutex<Option<Arc<TokenizerRuntimeConfig>>>,
    store: ExactDeliveryStore,
}

impl AgentdExactContextDeliveryOwner {
    pub(crate) fn open_product(
        directory: &Path,
        registry: Arc<Mutex<DurablePromptRegistry>>,
        security: Arc<ContextSecurityRuntimeV3>,
    ) -> Result<Self, ExactContextDeliveryError> {
        Self::open_inner(directory, registry, Some(security))
    }

    #[cfg(test)]
    pub(crate) fn open_for_qualification(
        directory: &Path,
        registry: Arc<Mutex<DurablePromptRegistry>>,
    ) -> Result<Self, ExactContextDeliveryError> {
        Self::open_inner(directory, registry, None)
    }

    fn open_inner(
        directory: &Path,
        registry: Arc<Mutex<DurablePromptRegistry>>,
        security: Option<Arc<ContextSecurityRuntimeV3>>,
    ) -> Result<Self, ExactContextDeliveryError> {
        let (store, durable) = ExactDeliveryStore::open(directory)?;
        Ok(Self {
            registry,
            security,
            state: Mutex::new(ExactRuntimeState {
                staged: BTreeMap::new(),
                preparing: BTreeSet::new(),
                active: BTreeMap::new(),
                durable,
            }),
            tokenizer: Mutex::new(None),
            store,
        })
    }

    fn require_external_security(&self) -> Result<(), ExactContextDeliveryError> {
        let Some(runtime) = &self.security else {
            // The only constructor without this runtime is cfg(test) and exists
            // solely for owner-local protocol fixtures. Product composition has
            // no process-local fallback.
            return Ok(());
        };
        runtime
            .capabilities()
            .map(|_| ())
            .map_err(|_| ExactContextDeliveryError::SecurityCapabilitiesUnavailable)
    }

    pub(crate) async fn observe_final_request(
        self: Arc<Self>,
        request: PromptRuntimeFinalRequestV2,
    ) -> Result<(), ExactContextDeliveryError> {
        let started = Instant::now();
        let _request_time = self.measure(Phase::RequestPreparation);
        self.require_external_security()?;
        self.store.ensure_available()?;
        request
            .attempt
            .validate()
            .map_err(|_| ExactContextDeliveryError::InvalidIdentity)?;
        let key = ExactTurnKey {
            thread_id: request.attempt.thread_id.clone(),
            turn_id: request.attempt.turn_id.clone(),
        };
        let (compiled, _reservation) = self.reserve_preparation(&key)?;
        validate_request_scope(&compiled, &request)?;
        let started_unix_ms = current_unix_ms()?;
        check_send_time(
            started_unix_ms,
            started_unix_ms,
            request.attachment.deadline_ms,
        )?;
        let tokenizer = self.tokenizer_for(&request, &compiled)?;
        let token_count = tokenizer
            .count(&request.canonical_request, &self.store.metrics)
            .await?;
        let bound_tokenizer = BoundFinalRequestTokenizer {
            identity: tokenizer.identity.clone(),
            request_digest: Digest32::of_bytes(&request.canonical_request),
            token_count,
        };
        let framing_policy = ResponsesJsonFramingPolicy::new(
            &request.attempt.provider_id,
            &request.attempt.model,
            request.attempt.provider_config_digest,
            request.attempt.endpoint_digest,
        )?;

        // No await after this point. The registry owner serializes revocation
        // against the durable authorization commit. A revocation already
        // committed during tokenization is observed here, not hidden behind a
        // pre-tokenization snapshot. Revocation after authorization is a
        // transport-owner cancellation concern, not an exactly-once claim.
        let registry_wait = self.measure(Phase::RegistryWait);
        let registry = self
            .registry
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        drop(registry_wait);
        let final_proof_time = self.measure(Phase::FinalProof);
        let now_unix_ms = current_unix_ms()?;
        check_send_time(started_unix_ms, now_unix_ms, request.attachment.deadline_ms)?;
        if now_unix_ms < compiled.authority_observed_unix_ms() {
            return Err(ExactContextDeliveryError::Clock);
        }
        let suffix = Digest32::of_bytes(request.attempt.attempt_id.as_bytes()).to_string();
        let fresh = prepare_prompt_delivery_v3(
            &registry,
            &compiled,
            now_unix_ms,
            stable_id(format!("context-preparation:{suffix}"))?,
        )
        .map_err(|_| ExactContextDeliveryError::AdmissionChanged)?;
        let final_request_proof = prove_final_provider_request_v2(
            &fresh.preparation,
            &compiled.attachment,
            &compiled.serialized_context,
            &compiled.model_profile,
            request.attempt.provider_wire_semantic_digest,
            &request.canonical_request,
            &framing_policy,
            &bound_tokenizer,
        )
        .map_err(|_| ExactContextDeliveryError::InvalidProof)?;
        let intent = provider_intent(&request.attempt)?;
        let recovery = build_delivery_recovery_binding_v2(
            &fresh.preparation,
            &compiled.attachment,
            &compiled.serialized_context,
            &compiled.model_profile,
            &final_request_proof,
            &intent,
        )
        .map_err(|_| ExactContextDeliveryError::InvalidProof)?;
        check_send_time(
            now_unix_ms,
            current_unix_ms()?,
            request.attachment.deadline_ms,
        )?;
        let pre_send = StoredPreSend::new(
            &request,
            &fresh,
            &final_request_proof,
            &intent,
            &recovery,
            now_unix_ms,
        )?;
        drop(final_proof_time);
        self.commit_pre_send(
            request.attempt.attempt_id.clone(),
            pre_send,
            ActiveExactDelivery {
                started,
                compiled,
                fresh,
                final_request_proof,
                intent,
            },
        )?;
        // Expiry during fsync must refuse transport while retaining the claim.
        check_send_time(
            now_unix_ms,
            current_unix_ms()?,
            request.attachment.deadline_ms,
        )?;
        drop(registry);
        Ok(())
    }

    fn reserve_preparation(
        self: &Arc<Self>,
        key: &ExactTurnKey,
    ) -> Result<
        (Arc<PromptRegistryCompiledContextV3>, PreparationReservation),
        ExactContextDeliveryError,
    > {
        self.store.ensure_available()?;
        let mut state = self
            .state
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        if state
            .durable
            .has_unresolved_for_turn(&key.thread_id, &key.turn_id)
            || state.preparing.contains(key)
        {
            return Err(ExactContextDeliveryError::RecoveryRequired);
        }
        if state.active.len().saturating_add(state.preparing.len()) >= MAX_ACTIVE_ATTEMPTS {
            return Err(ExactContextDeliveryError::Capacity);
        }
        let compiled = state
            .staged
            .get(key)
            .cloned()
            .ok_or(ExactContextDeliveryError::MissingStagedContext)?;
        state.preparing.insert(key.clone());
        Ok((
            compiled,
            PreparationReservation {
                owner: Arc::clone(self),
                key: key.clone(),
            },
        ))
    }

    fn tokenizer_for(
        &self,
        request: &PromptRuntimeFinalRequestV2,
        compiled: &PromptRegistryCompiledContextV3,
    ) -> Result<Arc<TokenizerRuntimeConfig>, ExactContextDeliveryError> {
        let mut configured = self
            .tokenizer
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        let configuration_phase = if configured.is_none() {
            Phase::TokenizerColdConfiguration
        } else {
            Phase::TokenizerWarmConfiguration
        };
        let _configuration_time = self.measure(configuration_phase);
        if configured.is_none() {
            *configured = Some(Arc::new(TokenizerRuntimeConfig::load(request, compiled)?));
        }
        let tokenizer = configured
            .as_ref()
            .ok_or(ExactContextDeliveryError::TokenizerConfiguration)?;
        tokenizer
            .identity
            .validate_for(&compiled.model_profile)
            .map_err(|_| ExactContextDeliveryError::TokenizerIdentity)?;
        let profile = &compiled.execution_profile.tokenizer;
        if tokenizer.provider_id != request.attempt.provider_id
            || tokenizer.model != request.attempt.model
            || tokenizer.provider_id != compiled.execution_profile.provider_id
            || tokenizer.model != compiled.execution_profile.provider_model
            || tokenizer.version != profile.version
            || tokenizer.identity.tokenizer_binary_digest() != profile.binary_digest
            || tokenizer.identity.vocabulary_digest() != profile.vocabulary_digest
            || tokenizer.identity.normalization_policy_digest()
                != profile.normalization_policy_digest
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        Ok(Arc::clone(tokenizer))
    }

    pub(crate) async fn observe_final_terminal(
        &self,
        terminal: PromptRuntimeFinalTerminalV2,
    ) -> Result<(), ExactContextDeliveryError> {
        self.store.ensure_available()?;
        let terminal_observation_digest = terminal_observation_digest(&terminal)?;
        let recovery_archive = {
            let state = self
                .state
                .lock()
                .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
            if state.active.contains_key(&terminal.attempt.attempt_id) {
                None
            } else if state
                .durable
                .has_unresolved_attempt(&terminal.attempt.attempt_id)
            {
                Some(
                    state
                        .durable
                        .pre_sends
                        .get(&terminal.attempt.attempt_id)
                        .and_then(|record| record.recovery_archive.clone())
                        .ok_or(ExactContextDeliveryError::RecoveryRequired)?,
                )
            } else {
                None
            }
        };
        if let Some(archive) = recovery_archive {
            return self.observe_recovered_terminal(
                terminal,
                terminal_observation_digest,
                &archive,
            );
        }
        let active = {
            let state = self
                .state
                .lock()
                .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
            if let Some(active) = state.active.get(&terminal.attempt.attempt_id) {
                active.clone()
            } else if let Some(existing) = state.durable.terminals.get(&terminal.attempt.attempt_id)
            {
                let observed_digest = if existing.observation_version == 2 {
                    terminal_observation_digest_legacy(&terminal)?
                } else {
                    terminal_observation_digest
                };
                return if existing.terminal_observation_digest == observed_digest.into_array()
                    && existing.is_final()
                {
                    Ok(())
                } else {
                    Err(ExactContextDeliveryError::Conflict(
                        "duplicate terminal observation differs from durable receipt",
                    ))
                };
            } else if let Some(existing) = state
                .durable
                .settled_attempts
                .get(&terminal.attempt.attempt_id)
            {
                let observed_digest = if existing.observation_version == 2 {
                    terminal_observation_digest_legacy(&terminal)?
                } else {
                    terminal_observation_digest
                };
                return if existing.terminal_observation_digest == observed_digest.into_array() {
                    Ok(())
                } else {
                    Err(ExactContextDeliveryError::Conflict(
                        "duplicate terminal observation differs from settled tombstone",
                    ))
                };
            } else if settled_history::has_checkpointed_attempt(
                &state.durable,
                &terminal.attempt.attempt_id,
            ) {
                return Err(ExactContextDeliveryError::RecoveryRequired);
            } else if state
                .durable
                .has_unresolved_attempt(&terminal.attempt.attempt_id)
            {
                return Err(ExactContextDeliveryError::RecoveryRequired);
            } else {
                return Err(ExactContextDeliveryError::MissingActiveAttempt);
            }
        };
        if terminal.attempt != exact_attempt_from_intent(&active.intent, &terminal.attempt)?
            || terminal.attachment.context_attachment_digest
                != active.compiled.attachment.attachment_digest()
            || terminal.attachment.context_payload_digest
                != active
                    .compiled
                    .serialized_context
                    .receipt()
                    .payload_digest()
        {
            return Err(ExactContextDeliveryError::Conflict(
                "provider terminal does not match the active exact attempt",
            ));
        }
        let provider_terminal = provider_terminal(terminal.terminal.clone())?;
        let receipt = ProviderInvocationReceipt::new(active.intent.clone(), provider_terminal);
        receipt
            .validate()
            .map_err(ExactContextDeliveryError::Domain)?;
        let verifier = ExactProviderDeliveryVerifier::new(
            active.intent.clone(),
            active.final_request_proof.proof_digest(),
            terminal.observed_unix_ms,
        );
        let delivery_id = stable_id(format!(
            "context-delivery:{}",
            Digest32::of_bytes(terminal.attempt.attempt_id.as_bytes())
        ))?;
        let context_receipt = observe_final_provider_delivery_v2(
            &active.fresh.preparation,
            &active.compiled.attachment,
            &active.compiled.serialized_context,
            &active.compiled.model_profile,
            &active.final_request_proof,
            delivery_id,
            &receipt,
            &verifier,
            terminal.observed_unix_ms,
        )
        .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        let stored = StoredTerminal::new(
            &terminal,
            &receipt,
            &context_receipt,
            active.final_request_proof.proof_digest(),
            terminal.observed_unix_ms,
        )?;
        self.commit_terminal(&terminal.attempt.attempt_id, stored)
    }

    fn observe_recovered_terminal(
        &self,
        terminal: PromptRuntimeFinalTerminalV2,
        terminal_observation_digest: Digest32,
        archive: &[u8],
    ) -> Result<(), ExactContextDeliveryError> {
        let _recovery_time = self.measure(Phase::RecoveredReconciliation);
        let recovery = ContextDeliveryRecoveryBindingV2::reopen_canonical_archive(archive)
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        exact_attempt_from_intent(recovery.provider_intent(), &terminal.attempt)?;
        if terminal.attachment.context_attachment_digest != recovery.attachment_digest()
            || terminal.attachment.context_payload_digest != recovery.payload_digest()
        {
            return Err(ExactContextDeliveryError::Conflict(
                "recovered terminal does not match durable context identity",
            ));
        }
        let receipt = ProviderInvocationReceipt::new(
            recovery.provider_intent().clone(),
            provider_terminal(terminal.terminal.clone())?,
        );
        receipt
            .validate()
            .map_err(ExactContextDeliveryError::Domain)?;
        let verifier = ExactProviderDeliveryVerifier::new(
            recovery.provider_intent().clone(),
            recovery.final_request_proof_digest(),
            terminal.observed_unix_ms,
        );
        let context_receipt = observe_recovered_final_provider_delivery_v2(
            &recovery,
            stable_id(format!(
                "context-delivery:{}",
                Digest32::of_bytes(terminal.attempt.attempt_id.as_bytes())
            ))?,
            &receipt,
            &verifier,
            terminal.observed_unix_ms,
        )
        .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        let stored = StoredTerminal {
            observation_version: 3,
            provider_receipt: Some(receipt.clone()),
            attempt_id: terminal.attempt.attempt_id.clone(),
            terminal_observation_digest: terminal_observation_digest.into_array(),
            provider_receipt_digest: Digest32::of_bytes(
                &receipt
                    .canonical_wire_bytes()
                    .map_err(ExactContextDeliveryError::Domain)?,
            )
            .into_array(),
            context_delivery_receipt_digest: context_receipt.receipt_digest().into_array(),
            final_request_proof_digest: recovery.final_request_proof_digest().into_array(),
            disposition: format!("{:?}", context_receipt.disposition()),
            observed_unix_ms: terminal.observed_unix_ms,
        };
        self.commit_terminal(&terminal.attempt.attempt_id, stored)
    }

    fn commit_pre_send(
        &self,
        attempt_id: String,
        stored: StoredPreSend,
        active: ActiveExactDelivery,
    ) -> Result<(), ExactContextDeliveryError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        self.store.ensure_available()?;
        if state.durable.pre_sends.contains_key(&attempt_id)
            || settled_history::has_seen_attempt(&state.durable, &attempt_id)
            || state
                .durable
                .has_unresolved_for_turn(&stored.thread_id, &stored.turn_id)
        {
            return Err(ExactContextDeliveryError::RecoveryRequired);
        }
        if state.active.len() >= MAX_ACTIVE_ATTEMPTS
            || state.durable.pre_sends.len() >= MAX_PRE_SEND_RECORDS
        {
            return Err(ExactContextDeliveryError::Capacity);
        }
        let mut next = state.durable.clone();
        next.pre_sends.insert(attempt_id.clone(), stored);
        let _persistence_time = self.measure(Phase::PreSendPersistence);
        self.store.persist_reserving(&next, completion_reserve(&next)?)?;
        state.durable = next;
        state.active.insert(attempt_id, active);
        Ok(())
    }

    fn commit_terminal(
        &self,
        attempt_id: &str,
        stored: StoredTerminal,
    ) -> Result<(), ExactContextDeliveryError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        self.store.ensure_available()?;
        if let Some(settled) = state.durable.settled_attempts.get(attempt_id) {
            return if settled.matches_terminal(&stored) {
                Ok(())
            } else {
                Err(ExactContextDeliveryError::Conflict(
                    "settled terminal observation differs from durable tombstone",
                ))
            };
        }
        if settled_history::has_checkpointed_attempt(&state.durable, attempt_id) {
            return Err(ExactContextDeliveryError::RecoveryRequired);
        }
        let Some(pre_send) = state.durable.pre_sends.get(attempt_id) else {
            return Err(ExactContextDeliveryError::MissingPreSendEvidence);
        };
        if pre_send.final_request_proof_digest != stored.final_request_proof_digest {
            return Err(ExactContextDeliveryError::Conflict(
                "terminal receipt does not bind the durable pre-send proof",
            ));
        }
        validate_terminal_size(&stored)?;
        let turn = ExactTurnKey {
            thread_id: pre_send.thread_id.clone(),
            turn_id: pre_send.turn_id.clone(),
        };
        let mut next = state.durable.clone();
        let is_final = stored.is_final();
        if !apply_observation(&mut next, stored)? {
            return Ok(());
        }
        if is_final {
            settled_history::settle_final_attempt(&mut next, attempt_id)?;
        }
        let _persistence_time = self.measure(Phase::TerminalPersistence);
        // Nonfinal observations cannot spend space reserved for final receipts.
        // A final atomically consumes its reservation and replaces raw provider
        // and recovery material with one compact deny-all tombstone.
        let reserve = if is_final { 0 } else { completion_reserve(&next)? };
        self.store.persist_reserving(&next, reserve)?;
        state.durable = next;
        if is_final {
            if let Some(active) = state.active.remove(attempt_id) {
                self.store
                    .metrics
                    .record(Phase::LiveAttemptCompletion, active.started.elapsed());
            }
            lifecycle::retire_completed_stage(&mut state, &turn);
        }
        Ok(())
    }
}

struct PreparationReservation {
    owner: Arc<AgentdExactContextDeliveryOwner>,
    key: ExactTurnKey,
}

impl Drop for PreparationReservation {
    fn drop(&mut self) {
        if let Ok(mut state) = self.owner.state.lock() {
            state.preparing.remove(&self.key);
            lifecycle::retire_completed_stage(&mut state, &self.key);
        }
    }
}

fn check_send_time(
    started: u64,
    current: u64,
    deadline: u64,
) -> Result<(), ExactContextDeliveryError> {
    if started == 0 || current < started {
        return Err(ExactContextDeliveryError::Clock);
    }
    if deadline == 0 || current >= deadline {
        return Err(ExactContextDeliveryError::Expired);
    }
    Ok(())
}

#[derive(Clone, Debug)]
struct ResponsesJsonFramingPolicy {
    expected_model: String,
    verifier_digest: Digest32,
}

impl ResponsesJsonFramingPolicy {
    fn new(
        provider_id: &str,
        model: &str,
        provider_config_digest: Digest32,
        endpoint_digest: Digest32,
    ) -> Result<Self, ExactContextDeliveryError> {
        if provider_id.is_empty()
            || model.is_empty()
            || provider_config_digest.is_zero()
            || endpoint_digest.is_zero()
        {
            return Err(ExactContextDeliveryError::InvalidIdentity);
        }
        let mut bytes = b"hepta.responses-json-framing-verifier.v2".to_vec();
        push_framing_text(&mut bytes, provider_id);
        push_framing_text(&mut bytes, model);
        bytes.extend_from_slice(provider_config_digest.as_array());
        bytes.extend_from_slice(endpoint_digest.as_array());
        Ok(Self {
            expected_model: model.to_owned(),
            verifier_digest: Digest32::of_bytes(&bytes),
        })
    }
}

impl FinalRequestFramingVerifierV2 for ResponsesJsonFramingPolicy {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_final_request(
        &self,
        canonical_request: &[u8],
        canonical_context_payload: &[u8],
    ) -> Result<(), String> {
        let context = std::str::from_utf8(canonical_context_payload)
            .map_err(|_| "canonical context payload is not UTF-8".to_owned())?;
        if context.is_empty() {
            return Err("canonical context payload is empty".to_owned());
        }
        let value = framing_json::parse(canonical_request)?;
        let object = value
            .as_object()
            .ok_or_else(|| "provider request root is not an object".to_owned())?;
        if object.get("model").and_then(serde_json::Value::as_str)
            != Some(self.expected_model.as_str())
        {
            return Err("provider request model does not match the bound model".to_owned());
        }
        let messages = object
            .get("input")
            .and_then(serde_json::Value::as_array)
            .ok_or_else(|| "context_typed_input_required".to_owned())?;
        let exact_slots = messages
            .iter()
            .filter(|message| {
                message.get("role").and_then(serde_json::Value::as_str) == Some("developer")
                    && message
                        .get("content")
                        .and_then(serde_json::Value::as_array)
                        .is_some_and(|parts| {
                            parts.len() == 1
                                && parts[0].get("type").and_then(serde_json::Value::as_str)
                                    == Some("input_text")
                                && parts[0].get("text").and_then(serde_json::Value::as_str)
                                    == Some(context)
                        })
            })
            .count();
        if exact_slots != 1 {
            return Err("context_exact_developer_slot_required".to_owned());
        }
        let occurrences = count_context_occurrences(&value, context)?;
        if occurrences != 1 {
            return Err(format!(
                "canonical context must occur in exactly one JSON string, observed {occurrences}"
            ));
        }
        Ok(())
    }
}

fn count_context_occurrences(value: &serde_json::Value, context: &str) -> Result<usize, String> {
    match value {
        serde_json::Value::String(text) => Ok(text.match_indices(context).count()),
        serde_json::Value::Array(values) => values.iter().try_fold(0_usize, |total, value| {
            total
                .checked_add(count_context_occurrences(value, context)?)
                .ok_or_else(|| "context occurrence count overflow".to_owned())
        }),
        serde_json::Value::Object(values) => {
            values.iter().try_fold(0_usize, |total, (key, value)| {
                if key.contains(context) {
                    return Err("context_in_object_key".to_owned());
                }
                total
                    .checked_add(count_context_occurrences(value, context)?)
                    .ok_or_else(|| "context occurrence count overflow".to_owned())
            })
        }
        _ => Ok(0),
    }
}

fn push_framing_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[derive(Clone)]
struct TokenizerRuntimeConfig {
    binary: PathBuf,
    vocabulary: PathBuf,
    provider_id: String,
    model: String,
    version: String,
    normalization: String,
    timeout: Duration,
    identity: FinalRequestTokenizerIdentityV2,
}

impl TokenizerRuntimeConfig {
    fn load(
        request: &PromptRuntimeFinalRequestV2,
        compiled: &PromptRegistryCompiledContextV3,
    ) -> Result<Self, ExactContextDeliveryError> {
        let profile = &compiled.execution_profile;
        let binary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_BIN_ENV, true)?;
        let vocabulary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_VOCAB_ENV, false)?;
        let provider_id = bounded_env(HEPTA_CONTEXT_TOKENIZER_PROVIDER_ID_ENV, 512)?;
        let model = bounded_env(HEPTA_CONTEXT_TOKENIZER_MODEL_ENV, 512)?;
        let version = bounded_env(HEPTA_CONTEXT_TOKENIZER_VERSION_ENV, 256)?;
        let normalization = bounded_env(HEPTA_CONTEXT_TOKENIZER_NORMALIZATION_ENV, 256)?;
        if provider_id != request.attempt.provider_id
            || model != request.attempt.model
            || provider_id != profile.provider_id
            || model != profile.provider_model
            || version != profile.tokenizer.version
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        let declared = Digest32::from_str(&bounded_env(
            HEPTA_CONTEXT_TOKENIZER_PROFILE_SHA256_ENV,
            64,
        )?)
        .map_err(|_| ExactContextDeliveryError::TokenizerIdentity)?;
        if declared != profile.tokenizer.tokenizer_digest
            || declared != compiled.model_profile.tokenizer_digest
            || Digest32::of_bytes(provider_id.as_bytes())
                != compiled.model_profile.provider_id_digest
            || Digest32::of_bytes(model.as_bytes()) != compiled.model_profile.provider_model_digest
            || Digest32::of_bytes(normalization.as_bytes())
                != profile.tokenizer.normalization_policy_digest
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        let binary_digest = hash_bounded_file(&binary)?;
        let vocabulary_digest = hash_bounded_file(&vocabulary)?;
        let binary_pin = Digest32::from_str(&bounded_env(TOKENIZER_BINARY_PIN_ENV, 64)?)
            .map_err(|_| ExactContextDeliveryError::TokenizerIdentity)?;
        let vocabulary_pin = Digest32::from_str(&bounded_env(TOKENIZER_VOCABULARY_PIN_ENV, 64)?)
            .map_err(|_| ExactContextDeliveryError::TokenizerIdentity)?;
        if binary_pin.is_zero()
            || vocabulary_pin.is_zero()
            || binary_pin != binary_digest
            || vocabulary_pin != vocabulary_digest
            || binary_digest != profile.tokenizer.binary_digest
            || vocabulary_digest != profile.tokenizer.vocabulary_digest
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        let timeout_ms = match env::var(HEPTA_CONTEXT_TOKENIZER_TIMEOUT_MS_ENV) {
            Ok(value) => value
                .parse::<u64>()
                .ok()
                .filter(|value| *value > 0 && *value <= TOKENIZER_TIMEOUT_MS_MAX)
                .ok_or(ExactContextDeliveryError::TokenizerConfiguration)?,
            Err(env::VarError::NotPresent) => TOKENIZER_TIMEOUT_MS_DEFAULT,
            Err(env::VarError::NotUnicode(_)) => {
                return Err(ExactContextDeliveryError::TokenizerConfiguration);
            }
        };
        let identity = FinalRequestTokenizerIdentityV2::new(
            Digest32::of_bytes(provider_id.as_bytes()),
            Digest32::of_bytes(model.as_bytes()),
            declared,
            binary_digest,
            Digest32::of_bytes(version.as_bytes()),
            vocabulary_digest,
            Digest32::of_bytes(normalization.as_bytes()),
        )
        .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        Ok(Self {
            binary,
            vocabulary,
            provider_id,
            model,
            version,
            normalization,
            timeout: Duration::from_millis(timeout_ms),
            identity,
        })
    }

    async fn count(
        &self,
        request: &[u8],
        metrics: &metrics::Metrics,
    ) -> Result<u64, ExactContextDeliveryError> {
        {
            let _artifact_time = metrics.measure(Phase::TokenizerArtifacts);
            self.verify_artifacts()?;
        }
        let mut command = Command::new(&self.binary);
        command
            .arg("--provider")
            .arg(&self.provider_id)
            .arg("--model")
            .arg(&self.model)
            .arg("--version")
            .arg(&self.version)
            .arg("--vocabulary")
            .arg(&self.vocabulary)
            .arg("--normalization")
            .arg(&self.normalization);
        let process_time = metrics.measure(Phase::TokenizerProcess);
        let output = tokenizer_io::run(
            &mut command,
            request,
            self.timeout,
            MAX_TOKENIZER_STDOUT_BYTES,
        )
        .await?;
        drop(process_time);
        // These checks detect drift; immutable mounts/runtime qualification are
        // still required to exclude adversarial replace-and-restore races.
        {
            let _artifact_time = metrics.measure(Phase::TokenizerArtifacts);
            self.verify_artifacts()?;
        }
        parse_token_count(&output)
    }

    fn verify_artifacts(&self) -> Result<(), ExactContextDeliveryError> {
        if hash_bounded_file(&self.binary)? != self.identity.tokenizer_binary_digest()
            || hash_bounded_file(&self.vocabulary)? != self.identity.vocabulary_digest()
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        Ok(())
    }
}

struct BoundFinalRequestTokenizer {
    identity: FinalRequestTokenizerIdentityV2,
    request_digest: Digest32,
    token_count: u64,
}

impl ExactFinalRequestTokenizerV2 for BoundFinalRequestTokenizer {
    fn identity(&self) -> &FinalRequestTokenizerIdentityV2 {
        &self.identity
    }

    fn count_final_request_tokens(&self, canonical_request: &[u8]) -> Result<u64, String> {
        if Digest32::of_bytes(canonical_request) != self.request_digest || self.token_count == 0 {
            return Err("token count is not bound to this final request".to_owned());
        }
        Ok(self.token_count)
    }
}

struct ExactProviderDeliveryVerifier {
    expected_intent: ProviderInvocationIntent,
    final_request_proof_digest: Digest32,
    recorded_at_unix_ms: u64,
    verifier_digest: Digest32,
}

impl ExactProviderDeliveryVerifier {
    fn new(
        expected_intent: ProviderInvocationIntent,
        final_request_proof_digest: Digest32,
        recorded_at_unix_ms: u64,
    ) -> Self {
        let mut bytes = PROVIDER_EVIDENCE_VERIFIER_DOMAIN.to_vec();
        bytes.extend_from_slice(final_request_proof_digest.as_array());
        bytes.extend_from_slice(expected_intent.attempt_id.as_str().as_bytes());
        Self {
            expected_intent,
            final_request_proof_digest,
            recorded_at_unix_ms,
            verifier_digest: Digest32::of_bytes(&bytes),
        }
    }
}

impl ContextProviderDeliveryVerifierV2 for ExactProviderDeliveryVerifier {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_delivery(
        &self,
        receipt: &ProviderInvocationReceipt,
        preparation: &ContextDeliveryPreparationV2,
    ) -> Result<ContextProviderDeliveryDecisionV2, String> {
        receipt.validate()?;
        if receipt.intent != self.expected_intent || self.final_request_proof_digest.is_zero() {
            return Err("provider receipt does not bind the exact admitted attempt".to_owned());
        }
        let mut bytes = PROVIDER_EVIDENCE_DOMAIN.to_vec();
        bytes.extend_from_slice(preparation.preparation_digest().as_array());
        bytes.extend_from_slice(self.final_request_proof_digest.as_array());
        bytes.extend_from_slice(&receipt.canonical_wire_bytes()?);
        Ok(ContextProviderDeliveryDecisionV2 {
            evidence_digest: Digest32::of_bytes(&bytes),
            recorded_at_unix_ms: self.recorded_at_unix_ms,
        })
    }
}

fn provider_intent(
    attempt: &codex_hepta_codex_adapter::PromptRuntimeExactAttemptV2,
) -> Result<ProviderInvocationIntent, ExactContextDeliveryError> {
    if attempt.request_kind != PromptRuntimeRequestKindV2::Turn
        || attempt.transport != PromptRuntimeTransportV2::Http
        || !attempt.generate
    {
        return Err(ExactContextDeliveryError::Conflict(
            "context delivery requires a generating HTTP turn",
        ));
    }
    let binding = ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: attempt.thread_id.clone(),
        turn_id: attempt.turn_id.clone(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(
            attempt.request_binding_id.as_bytes(),
        ),
        request_kind: ProviderRequestKind::Turn,
        provider_id: attempt.provider_id.clone(),
        provider_config_sha256: sha256(attempt.provider_config_digest)?,
        model: attempt.model.clone(),
        transport: ProviderTransport::Http,
        endpoint_sha256: sha256(attempt.endpoint_digest)?,
        logical_request_sha256: sha256(attempt.logical_request_digest)?,
        wire_semantic_sha256: sha256(attempt.provider_wire_semantic_digest)?,
        ephemeral_input_sha256: attempt.ephemeral_input_digest.map(sha256).transpose()?,
        ephemeral_input_witness_sha256: attempt
            .ephemeral_input_witness_digest
            .map(sha256)
            .transpose()?,
        previous_response_id_sha256: attempt
            .previous_response_id_digest
            .map(sha256)
            .transpose()?,
        generate: true,
    };
    let intent = ProviderInvocationIntent::for_host_attempt_id(&attempt.attempt_id, binding);
    intent
        .validate()
        .map_err(ExactContextDeliveryError::Domain)?;
    Ok(intent)
}

fn provider_terminal(
    terminal: PromptRuntimeProviderTerminalV2,
) -> Result<ProviderTerminal, ExactContextDeliveryError> {
    Ok(match terminal {
        PromptRuntimeProviderTerminalV2::Completed {
            response_id_digest,
            response_items_digest,
            token_usage_digest,
            end_turn,
        } => ProviderTerminal::Completed {
            response_id_sha256: sha256(response_id_digest)?,
            response_items_sha256: sha256(response_items_digest)?,
            token_usage_sha256: sha256(token_usage_digest)?,
            end_turn,
        },
        PromptRuntimeProviderTerminalV2::CompletedUnary {
            response_items_digest,
        } => ProviderTerminal::CompletedUnary {
            response_items_sha256: sha256(response_items_digest)?,
        },
        PromptRuntimeProviderTerminalV2::Rejected { reason_code } => {
            ProviderTerminal::Rejected { reason_code }
        }
        PromptRuntimeProviderTerminalV2::NotDispatched { reason_code } => {
            ProviderTerminal::NotDispatched { reason_code }
        }
        PromptRuntimeProviderTerminalV2::Indeterminate {
            reason_code,
            partial_response_digest,
        } => ProviderTerminal::Indeterminate {
            reason_code,
            partial_response_sha256: partial_response_digest.map(sha256).transpose()?,
        },
    })
}

fn terminal_observation_digest(
    terminal: &PromptRuntimeFinalTerminalV2,
) -> Result<Digest32, ExactContextDeliveryError> {
    let intent = provider_intent(&terminal.attempt)?;
    let provider_terminal = provider_terminal(terminal.terminal.clone())?;
    let receipt = ProviderInvocationReceipt::new(intent, provider_terminal);
    let mut bytes = b"hepta.context-runtime-terminal-observation.v3".to_vec();
    bytes.extend_from_slice(
        &receipt
            .canonical_wire_bytes()
            .map_err(ExactContextDeliveryError::Domain)?,
    );
    bytes.extend_from_slice(terminal.attachment.context_attachment_digest.as_array());
    bytes.extend_from_slice(terminal.attachment.context_payload_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn terminal_observation_digest_legacy(
    terminal: &PromptRuntimeFinalTerminalV2,
) -> Result<Digest32, ExactContextDeliveryError> {
    let receipt = ProviderInvocationReceipt::new(
        provider_intent(&terminal.attempt)?,
        provider_terminal(terminal.terminal.clone())?,
    );
    let mut bytes = b"hepta.context-runtime-terminal-observation.v2".to_vec();
    bytes.extend_from_slice(
        &receipt
            .canonical_wire_bytes()
            .map_err(ExactContextDeliveryError::Domain)?,
    );
    bytes.extend_from_slice(terminal.attachment.context_attachment_digest.as_array());
    bytes.extend_from_slice(terminal.attachment.context_payload_digest.as_array());
    bytes.extend_from_slice(&terminal.observed_unix_ms.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn exact_attempt_from_intent(
    intent: &ProviderInvocationIntent,
    observed: &codex_hepta_codex_adapter::PromptRuntimeExactAttemptV2,
) -> Result<codex_hepta_codex_adapter::PromptRuntimeExactAttemptV2, ExactContextDeliveryError> {
    let expected = provider_intent(observed)?;
    if &expected != intent {
        return Err(ExactContextDeliveryError::Conflict(
            "terminal attempt semantics changed after pre-send proof",
        ));
    }
    Ok(observed.clone())
}

fn validate_request_scope(
    compiled: &PromptRegistryCompiledContextV3,
    request: &PromptRuntimeFinalRequestV2,
) -> Result<(), ExactContextDeliveryError> {
    if request.attachment.compilation_id != *compiled.compiled.receipt().compilation_id()
        || request.attachment.context_attachment_digest != compiled.attachment.attachment_digest()
        || request.attachment.context_payload_digest
            != compiled.serialized_context.receipt().payload_digest()
        || request.attachment.model != request.attempt.model
        || request.canonical_request.is_empty()
        || request.canonical_request.len()
            > codex_hepta_context_compiler::MAX_FINAL_PROVIDER_REQUEST_BYTES_V2
    {
        return Err(ExactContextDeliveryError::Conflict(
            "final request is outside the staged context scope",
        ));
    }
    Ok(())
}

fn parse_token_count(output: &[u8]) -> Result<u64, ExactContextDeliveryError> {
    let text = std::str::from_utf8(output)
        .map_err(|_| ExactContextDeliveryError::TokenizerRejected)?
        .trim();
    if text.is_empty() || text.len() > 20 || !text.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(ExactContextDeliveryError::TokenizerRejected);
    }
    text.parse::<u64>()
        .ok()
        .filter(|value| *value > 0)
        .ok_or(ExactContextDeliveryError::TokenizerRejected)
}

fn bounded_env(
    name: &'static str,
    maximum_bytes: usize,
) -> Result<String, ExactContextDeliveryError> {
    let value = env::var(name).map_err(|_| ExactContextDeliveryError::TokenizerConfiguration)?;
    if value.is_empty() || value.len() > maximum_bytes || value.as_bytes().contains(&0) {
        return Err(ExactContextDeliveryError::TokenizerConfiguration);
    }
    Ok(value)
}

fn absolute_regular_file(
    name: &'static str,
    require_executable: bool,
) -> Result<PathBuf, ExactContextDeliveryError> {
    let path = PathBuf::from(bounded_env(name, 4096)?);
    if !path.is_absolute() {
        return Err(ExactContextDeliveryError::TokenizerConfiguration);
    }
    let metadata = std::fs::symlink_metadata(&path)
        .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ExactContextDeliveryError::TokenizerConfiguration);
    }
    #[cfg(unix)]
    if require_executable {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o111 == 0 {
            return Err(ExactContextDeliveryError::TokenizerConfiguration);
        }
    }
    Ok(path)
}

fn hash_bounded_file(path: &Path) -> Result<Digest32, ExactContextDeliveryError> {
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_TOKENIZER_FILE_BYTES
    {
        return Err(ExactContextDeliveryError::TokenizerConfiguration);
    }
    let mut file = File::open(path).map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
    let mut digest = sha2::Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(u64::try_from(count).unwrap_or(u64::MAX))
            .ok_or(ExactContextDeliveryError::TokenizerConfiguration)?;
        if total > MAX_TOKENIZER_FILE_BYTES {
            return Err(ExactContextDeliveryError::TokenizerConfiguration);
        }
        digest.update(&buffer[..count]);
    }
    Digest32::from_str(&format!("{:x}", digest.finalize()))
        .map_err(|_| ExactContextDeliveryError::TokenizerIdentity)
}

fn sha256(digest: Digest32) -> Result<Sha256Digest, ExactContextDeliveryError> {
    Sha256Digest::parse(digest.to_string()).map_err(ExactContextDeliveryError::Domain)
}

fn stable_id(value: String) -> Result<StableId, ExactContextDeliveryError> {
    StableId::new(value).map_err(|_| ExactContextDeliveryError::InvalidIdentity)
}

fn validate_runtime_id(value: &str, _label: &'static str) -> Result<(), ExactContextDeliveryError> {
    if value.is_empty() || value.len() > 512 || value.as_bytes().contains(&0) {
        return Err(ExactContextDeliveryError::InvalidIdentity);
    }
    Ok(())
}

fn current_unix_ms() -> Result<u64, ExactContextDeliveryError> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| ExactContextDeliveryError::Clock)?;
    u64::try_from(duration.as_millis()).map_err(|_| ExactContextDeliveryError::Clock)
}

#[derive(Clone, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredExactDeliveryState {
    schema: u32,
    #[serde(default)]
    pre_sends: BTreeMap<String, StoredPreSend>,
    #[serde(default)]
    terminals: BTreeMap<String, StoredTerminal>,
    #[serde(default)]
    observations: BTreeMap<String, StoredTerminal>,
    #[serde(default)]
    settled_attempts: BTreeMap<String, settled_history::SettledAttempt>,
    #[serde(default)]
    settlement_checkpoint: settled_history::SettlementCheckpoint,
}

impl StoredExactDeliveryState {
    fn has_unresolved_attempt(&self, attempt_id: &str) -> bool {
        self.pre_sends.contains_key(attempt_id)
            && !self
                .terminals
                .get(attempt_id)
                .is_some_and(StoredTerminal::is_final)
    }

    fn has_unresolved_for_turn(&self, thread_id: &str, turn_id: &str) -> bool {
        self.pre_sends.iter().any(|(attempt_id, record)| {
            record.thread_id == thread_id
                && record.turn_id == turn_id
                && self.has_unresolved_attempt(attempt_id)
        })
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredPreSend {
    thread_id: String,
    turn_id: String,
    attempt_id: String,
    provider_intent_digest: [u8; 32],
    authority_snapshot_digest: [u8; 32],
    preparation_binding_digest: [u8; 32],
    preparation_digest: [u8; 32],
    final_request_proof_digest: [u8; 32],
    provider_request_digest: [u8; 32],
    provider_wire_semantic_digest: [u8; 32],
    tokenizer_identity_digest: [u8; 32],
    tokenization_receipt_digest: [u8; 32],
    token_count: u64,
    segment_map_digest: [u8; 32],
    recorded_unix_ms: u64,
    #[serde(default)]
    recovery_binding_digest: [u8; 32],
    #[serde(default)]
    recovery_archive: Option<Vec<u8>>,
}

impl StoredPreSend {
    fn new(
        request: &PromptRuntimeFinalRequestV2,
        fresh: &PreparedPromptDeliveryV3,
        proof: &FinalProviderRequestProofV2,
        intent: &ProviderInvocationIntent,
        recovery: &ContextDeliveryRecoveryBindingV2,
        recorded_unix_ms: u64,
    ) -> Result<Self, ExactContextDeliveryError> {
        let recovery_archive = recovery
            .canonical_archive_bytes()
            .map_err(|_| ExactContextDeliveryError::InvalidProof)?;
        if recovery_archive.is_empty() || recovery_archive.len() > MAX_RECOVERY_ARCHIVE_BYTES {
            return Err(ExactContextDeliveryError::Capacity);
        }
        Ok(Self {
            thread_id: request.attempt.thread_id.clone(),
            turn_id: request.attempt.turn_id.clone(),
            attempt_id: request.attempt.attempt_id.clone(),
            provider_intent_digest: Digest32::of_bytes(
                &intent
                    .canonical_wire_bytes()
                    .map_err(ExactContextDeliveryError::Domain)?,
            )
            .into_array(),
            authority_snapshot_digest: fresh.preparation.admission_snapshot_digest().into_array(),
            preparation_binding_digest: fresh.preparation_binding_digest().into_array(),
            preparation_digest: fresh.preparation.preparation_digest().into_array(),
            final_request_proof_digest: proof.proof_digest().into_array(),
            provider_request_digest: proof.provider_request_digest().into_array(),
            provider_wire_semantic_digest: proof.provider_wire_semantic_digest().into_array(),
            tokenizer_identity_digest: proof
                .tokenization()
                .tokenizer_identity()
                .identity_digest()
                .into_array(),
            tokenization_receipt_digest: proof.tokenization().receipt_digest().into_array(),
            token_count: proof.tokenization().token_count(),
            segment_map_digest: proof.segment_map_digest().into_array(),
            recorded_unix_ms,
            recovery_binding_digest: recovery.binding_digest().into_array(),
            recovery_archive: Some(recovery_archive),
        })
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredTerminal {
    #[serde(default = "legacy_observation_version")]
    observation_version: u32,
    #[serde(default)]
    provider_receipt: Option<ProviderInvocationReceipt>,
    attempt_id: String,
    terminal_observation_digest: [u8; 32],
    provider_receipt_digest: [u8; 32],
    context_delivery_receipt_digest: [u8; 32],
    final_request_proof_digest: [u8; 32],
    disposition: String,
    observed_unix_ms: u64,
}

impl StoredTerminal {
    fn new(
        runtime_terminal: &PromptRuntimeFinalTerminalV2,
        provider_receipt: &ProviderInvocationReceipt,
        context_receipt: &ContextDeliveryReceiptV2,
        final_request_proof_digest: Digest32,
        observed_unix_ms: u64,
    ) -> Result<Self, ExactContextDeliveryError> {
        Ok(Self {
            observation_version: 3,
            provider_receipt: Some(provider_receipt.clone()),
            attempt_id: runtime_terminal.attempt.attempt_id.clone(),
            terminal_observation_digest: terminal_observation_digest(runtime_terminal)?
                .into_array(),
            provider_receipt_digest: Digest32::of_bytes(
                &provider_receipt
                    .canonical_wire_bytes()
                    .map_err(ExactContextDeliveryError::Domain)?,
            )
            .into_array(),
            context_delivery_receipt_digest: context_receipt.receipt_digest().into_array(),
            final_request_proof_digest: final_request_proof_digest.into_array(),
            disposition: format!("{:?}", context_receipt.disposition()),
            observed_unix_ms,
        })
    }
}

#[cfg(unix)]
#[derive(Clone, Copy)]
struct RootIdentity {
    device: u64,
    inode: u64,
    owner: u32,
}

struct ExactDeliveryStore {
    root: PathBuf,
    metrics: metrics::Metrics,
    poisoned: AtomicBool,
    #[cfg(unix)]
    root_identity: RootIdentity,
    _lock: File,
}

impl ExactDeliveryStore {
    fn open(
        directory: &Path,
    ) -> Result<(Self, StoredExactDeliveryState), ExactContextDeliveryError> {
        let opened_at = Instant::now();
        prepare_directory(directory)?;
        #[cfg(unix)]
        let root_identity = private_directory_identity(directory)?;
        reject_existing_next(directory)?;
        let lock_path = directory.join(LOCK_FILE);
        #[cfg(unix)]
        let owner = root_identity.owner;
        #[cfg(not(unix))]
        let owner = 0;
        let lock = open_private_lock(&lock_path, owner)?;
        lock.try_lock()
            .map_err(|_| ExactContextDeliveryError::StateLocked)?;
        let store = Self {
            root: directory.to_path_buf(),
            metrics: metrics::Metrics::default(),
            poisoned: AtomicBool::new(false),
            #[cfg(unix)]
            root_identity,
            _lock: lock,
        };
        let path = directory.join(STATE_FILE);
        let Some(mut state_file) = open_existing_private_file(&path, owner)? else {
            store.metrics.record(Phase::StoreOpen, opened_at.elapsed());
            return Ok((
                store,
                StoredExactDeliveryState {
                    schema: EXACT_DELIVERY_SCHEMA,
                    ..StoredExactDeliveryState::default()
                },
            ));
        };
        let mut bytes = Vec::new();
        state_file
            .take(MAX_DURABLE_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        let mut state: StoredExactDeliveryState =
            serde_json::from_slice(&bytes).map_err(|_| ExactContextDeliveryError::CorruptState)?;
        migrate_state(&mut state)?;
        validate_stored_state(&state)?;
        store.metrics.record(Phase::StoreOpen, opened_at.elapsed());
        Ok((store, state))
    }

    fn ensure_available(&self) -> Result<(), ExactContextDeliveryError> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(ExactContextDeliveryError::ReopenRequired);
        }
        if self.root_identity_matches().is_err() {
            self.poisoned.store(true, Ordering::Release);
            return Err(ExactContextDeliveryError::ReopenRequired);
        }
        Ok(())
    }

    #[cfg(unix)]
    fn root_identity_matches(&self) -> Result<(), ExactContextDeliveryError> {
        let observed = private_directory_identity(&self.root)?;
        if observed.device != self.root_identity.device
            || observed.inode != self.root_identity.inode
            || observed.owner != self.root_identity.owner
        {
            return Err(ExactContextDeliveryError::ReopenRequired);
        }
        Ok(())
    }

    #[cfg(not(unix))]
    fn root_identity_matches(&self) -> Result<(), ExactContextDeliveryError> {
        let metadata = std::fs::symlink_metadata(&self.root)
            .map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(ExactContextDeliveryError::ReopenRequired);
        }
        Ok(())
    }

    #[cfg(test)]
    fn persist(&self, state: &StoredExactDeliveryState) -> Result<(), ExactContextDeliveryError> {
        self.persist_with_sync(state, sync_directory)
    }

    fn persist_reserving(
        &self,
        state: &StoredExactDeliveryState,
        reserved_bytes: u64,
    ) -> Result<(), ExactContextDeliveryError> {
        self.persist_with_capacity(state, reserved_bytes, sync_directory)
    }

    #[cfg(test)]
    fn persist_with_sync(
        &self,
        state: &StoredExactDeliveryState,
        sync: impl FnOnce(&Path) -> Result<(), ExactContextDeliveryError>,
    ) -> Result<(), ExactContextDeliveryError> {
        self.persist_with_capacity(state, /*reserved_bytes*/ 0, sync)
    }

    fn persist_with_capacity(
        &self,
        state: &StoredExactDeliveryState,
        reserved_bytes: u64,
        sync: impl FnOnce(&Path) -> Result<(), ExactContextDeliveryError>,
    ) -> Result<(), ExactContextDeliveryError> {
        self.ensure_available()?;
        let result = self.persist_inner(state, reserved_bytes, sync);
        if matches!(
            result,
            Err(
                ExactContextDeliveryError::IndeterminateDurability
                    | ExactContextDeliveryError::ReopenRequired
            )
        ) {
            self.poisoned.store(true, Ordering::Release);
        }
        result
    }

    fn persist_inner(
        &self,
        state: &StoredExactDeliveryState,
        reserved_bytes: u64,
        sync: impl FnOnce(&Path) -> Result<(), ExactContextDeliveryError>,
    ) -> Result<(), ExactContextDeliveryError> {
        let encoding_time = self.metrics.measure(Phase::StoreEncoding);
        validate_stored_state(state)?;
        let bytes =
            serde_json::to_vec(state).map_err(|_| ExactContextDeliveryError::Unavailable)?;
        if u64::try_from(bytes.len())
            .ok()
            .and_then(|length| length.checked_add(reserved_bytes))
            .is_none_or(|required| required > MAX_DURABLE_STATE_BYTES)
        {
            return Err(ExactContextDeliveryError::Capacity);
        }
        drop(encoding_time);

        self.root_identity_matches()?;
        let state_path = self.root.join(STATE_FILE);
        validate_optional_private_file(&state_path, self.expected_owner())?;
        let next_path = self.root.join(NEXT_FILE);
        reject_existing_path(&next_path)?;

        let file_time = self.metrics.measure(Phase::StoreFileSync);
        let mut next = create_private_file(&next_path, self.expected_owner())?;
        next.write_all(&bytes)
            .and_then(|()| next.sync_all())
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        drop(file_time);

        self.root_identity_matches()?;
        validate_optional_private_file(&state_path, self.expected_owner())?;
        std::fs::rename(&next_path, &state_path)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        if self.root_identity_matches().is_err()
            || validate_required_private_file(&state_path, self.expected_owner()).is_err()
        {
            return Err(ExactContextDeliveryError::IndeterminateDurability);
        }
        let _directory_time = self.metrics.measure(Phase::StoreDirectorySync);
        sync(&self.root)?;
        if self.root_identity_matches().is_err() {
            return Err(ExactContextDeliveryError::IndeterminateDurability);
        }
        Ok(())
    }

    #[cfg(unix)]
    const fn expected_owner(&self) -> u32 {
        self.root_identity.owner
    }

    #[cfg(not(unix))]
    const fn expected_owner(&self) -> u32 {
        0
    }
}

fn prepare_directory(path: &Path) -> Result<(), ExactContextDeliveryError> {
    let existed = match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(ExactContextDeliveryError::Unavailable);
            }
            true
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(_) => return Err(ExactContextDeliveryError::Unavailable),
    };
    if !existed {
        std::fs::create_dir_all(path).map_err(|_| ExactContextDeliveryError::Unavailable)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
                .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        }
    }
    #[cfg(unix)]
    private_directory_identity(path)?;
    #[cfg(not(unix))]
    {
        let metadata =
            std::fs::symlink_metadata(path).map_err(|_| ExactContextDeliveryError::Unavailable)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(ExactContextDeliveryError::Unavailable);
        }
    }
    Ok(())
}

#[cfg(unix)]
fn private_directory_identity(path: &Path) -> Result<RootIdentity, ExactContextDeliveryError> {
    use std::os::unix::fs::MetadataExt;

    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| ExactContextDeliveryError::ReopenRequired)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.mode() & 0o777 != 0o700
    {
        return Err(ExactContextDeliveryError::ReopenRequired);
    }
    Ok(RootIdentity {
        device: metadata.dev(),
        inode: metadata.ino(),
        owner: metadata.uid(),
    })
}

fn reject_existing_next(directory: &Path) -> Result<(), ExactContextDeliveryError> {
    reject_existing_path(&directory.join(NEXT_FILE))
}

fn reject_existing_path(path: &Path) -> Result<(), ExactContextDeliveryError> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => Err(ExactContextDeliveryError::Unavailable),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(ExactContextDeliveryError::Unavailable),
    }
}

fn open_private_lock(path: &Path, expected_owner: u32) -> Result<File, ExactContextDeliveryError> {
    #[cfg(unix)]
    let file = {
        use std::os::unix::fs::OpenOptionsExt;
        OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?
    };
    #[cfg(not(unix))]
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)
        .map_err(|_| ExactContextDeliveryError::Unavailable)?;
    validate_private_file_handle(&file, expected_owner)?;
    Ok(file)
}

fn open_existing_private_file(
    path: &Path,
    expected_owner: u32,
) -> Result<Option<File>, ExactContextDeliveryError> {
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(ExactContextDeliveryError::Unavailable),
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Err(ExactContextDeliveryError::Unavailable);
        }
        Ok(_) => {}
    }
    #[cfg(unix)]
    let file = {
        use std::os::unix::fs::OpenOptionsExt;
        OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?
    };
    #[cfg(not(unix))]
    let file = OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(|_| ExactContextDeliveryError::Unavailable)?;
    validate_private_file_handle(&file, expected_owner)?;
    Ok(Some(file))
}

fn create_private_file(
    path: &Path,
    expected_owner: u32,
) -> Result<File, ExactContextDeliveryError> {
    #[cfg(unix)]
    let file = {
        use std::os::unix::fs::OpenOptionsExt;
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?
    };
    #[cfg(not(unix))]
    let file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|_| ExactContextDeliveryError::Unavailable)?;
    validate_private_file_handle(&file, expected_owner)?;
    Ok(file)
}

fn validate_optional_private_file(
    path: &Path,
    expected_owner: u32,
) -> Result<(), ExactContextDeliveryError> {
    if let Some(file) = open_existing_private_file(path, expected_owner)? {
        drop(file);
    }
    Ok(())
}

fn validate_required_private_file(
    path: &Path,
    expected_owner: u32,
) -> Result<(), ExactContextDeliveryError> {
    let file = open_existing_private_file(path, expected_owner)?
        .ok_or(ExactContextDeliveryError::Unavailable)?;
    drop(file);
    Ok(())
}

fn validate_private_file_handle(
    file: &File,
    expected_owner: u32,
) -> Result<(), ExactContextDeliveryError> {
    let metadata = file
        .metadata()
        .map_err(|_| ExactContextDeliveryError::Unavailable)?;
    if !metadata.is_file() {
        return Err(ExactContextDeliveryError::Unavailable);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o777 != 0o600
            || metadata.nlink() != 1
            || metadata.uid() != expected_owner
        {
            return Err(ExactContextDeliveryError::Unavailable);
        }
    }
    #[cfg(not(unix))]
    let _ = expected_owner;
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), ExactContextDeliveryError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| ExactContextDeliveryError::IndeterminateDurability)
}

#[derive(Clone, Eq, PartialEq)]
pub(crate) enum ExactContextDeliveryError {
    Unavailable,
    StateLocked,
    CorruptState,
    IndeterminateDurability,
    ReopenRequired,
    AdmissionChanged,
    InvalidProof,
    Expired,
    Capacity,
    MissingStagedContext,
    MissingActiveAttempt,
    MissingPreSendEvidence,
    RecoveryRequired,
    Conflict(&'static str),
    InvalidIdentity,
    Clock,
    TokenizerConfiguration,
    TokenizerIdentity,
    TokenizerUnavailable,
    TokenizerTimeout,
    TokenizerRejected,
    SecurityCapabilitiesUnavailable,
    Domain(String),
}

impl ExactContextDeliveryError {
    pub(crate) const fn reason_code(&self) -> &'static str {
        match self {
            Self::Unavailable => "context_delivery_v2_unavailable",
            Self::StateLocked => "context_delivery_v2_state_locked",
            Self::CorruptState => "context_delivery_v2_corrupt_state",
            Self::IndeterminateDurability => "context_delivery_v2_indeterminate_durability",
            Self::ReopenRequired => "context_delivery_v2_reopen_required",
            Self::AdmissionChanged => "context_delivery_v2_admission_changed",
            Self::InvalidProof => "context_delivery_v2_invalid_proof",
            Self::Expired => "context_delivery_v2_expired",
            Self::Capacity => "context_delivery_v2_capacity",
            Self::MissingStagedContext => "context_delivery_v2_staged_context_missing",
            Self::MissingActiveAttempt => "context_delivery_v2_active_attempt_missing",
            Self::MissingPreSendEvidence => "context_delivery_v2_pre_send_evidence_missing",
            Self::RecoveryRequired => "context_delivery_v2_recovery_required",
            Self::Conflict(_) => "context_delivery_v2_conflict",
            Self::InvalidIdentity => "context_delivery_v2_identity_invalid",
            Self::Clock => "context_delivery_v2_clock_invalid",
            Self::TokenizerConfiguration => "context_delivery_v2_tokenizer_unconfigured",
            Self::TokenizerIdentity => "context_delivery_v2_tokenizer_identity_mismatch",
            Self::TokenizerUnavailable => "context_delivery_v2_tokenizer_unavailable",
            Self::TokenizerTimeout => "context_delivery_v2_tokenizer_timeout",
            Self::TokenizerRejected => "context_delivery_v2_tokenizer_rejected",
            Self::SecurityCapabilitiesUnavailable => {
                "context_delivery_v3_external_security_unavailable"
            }
            Self::Domain(_) => "context_delivery_v2_domain_rejected",
        }
    }
}

impl fmt::Display for ExactContextDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.reason_code())
    }
}

impl fmt::Debug for ExactContextDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.reason_code())
    }
}

impl std::error::Error for ExactContextDeliveryError {}

#[cfg(test)]
mod tests {
    use super::ExactContextDeliveryError;
    use super::ResponsesJsonFramingPolicy;
    use super::parse_token_count;
    use codex_hepta_context_compiler::FinalRequestFramingVerifierV2;
    use codex_hepta_types::Digest32;

    #[test]
    fn exact_tokenizer_output_is_strict_decimal() {
        assert_eq!(parse_token_count(b"42\n"), Ok(42));
        assert_eq!(
            parse_token_count(b"estimate=42"),
            Err(ExactContextDeliveryError::TokenizerRejected)
        );
        assert_eq!(
            parse_token_count(b"0"),
            Err(ExactContextDeliveryError::TokenizerRejected)
        );
    }

    #[test]
    fn framing_policy_accepts_one_bound_context_and_rejects_aliases() {
        let policy = ResponsesJsonFramingPolicy::new(
            "provider",
            "model",
            Digest32::of_bytes(b"config"),
            Digest32::of_bytes(b"endpoint"),
        )
        .expect("policy");
        let context = br#"{\"schema\":\"hepta.context-bundle.v2\"}"#;
        let request = serde_json::json!({
            "model": "model",
            "input": [{"role": "developer", "content": [{"type": "input_text", "text": String::from_utf8(context.to_vec()).expect("utf8")}]}]
        });
        let request = serde_json::to_vec(&request).expect("request");
        policy
            .verify_final_request(&request, context)
            .expect("single context");

        let duplicate = serde_json::json!({
            "model": "model",
            "instructions": String::from_utf8(context.to_vec()).expect("utf8"),
            "input": [String::from_utf8(context.to_vec()).expect("utf8")]
        });
        let duplicate = serde_json::to_vec(&duplicate).expect("request");
        assert!(policy.verify_final_request(&duplicate, context).is_err());

        let wrong_model = serde_json::json!({
            "model": "other",
            "instructions": String::from_utf8(context.to_vec()).expect("utf8"),
            "input": []
        });
        let wrong_model = serde_json::to_vec(&wrong_model).expect("request");
        assert!(policy.verify_final_request(&wrong_model, context).is_err());
    }

    pub(super) fn stored_pre_send(
        thread_id: &str,
        turn_id: &str,
        attempt_id: &str,
    ) -> super::StoredPreSend {
        super::StoredPreSend {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
            attempt_id: attempt_id.to_owned(),
            provider_intent_digest: [1; 32],
            authority_snapshot_digest: [2; 32],
            preparation_binding_digest: [3; 32],
            preparation_digest: [4; 32],
            final_request_proof_digest: [5; 32],
            provider_request_digest: [6; 32],
            provider_wire_semantic_digest: [7; 32],
            tokenizer_identity_digest: [8; 32],
            tokenization_receipt_digest: [9; 32],
            token_count: 11,
            segment_map_digest: [10; 32],
            recorded_unix_ms: 12,
            recovery_binding_digest: [0; 32],
            recovery_archive: None,
        }
    }

    pub(super) fn stored_terminal(attempt_id: &str) -> super::StoredTerminal {
        super::StoredTerminal {
            observation_version: 2,
            provider_receipt: None,
            attempt_id: attempt_id.to_owned(),
            terminal_observation_digest: [11; 32],
            provider_receipt_digest: [12; 32],
            context_delivery_receipt_digest: [13; 32],
            final_request_proof_digest: [5; 32],
            disposition: "Delivered".to_owned(),
            observed_unix_ms: 14,
        }
    }

    #[test]
    fn unresolved_pre_send_survives_reopen_and_blocks_turn_retry() {
        let directory = tempfile::tempdir().expect("tempdir");
        let (store, mut state) = super::ExactDeliveryStore::open(directory.path()).expect("open");
        state.pre_sends.insert(
            "attempt-a".to_owned(),
            stored_pre_send("thread-a", "turn-a", "attempt-a"),
        );
        store.persist(&state).expect("persist");
        drop(store);

        let (_store, reopened) = super::ExactDeliveryStore::open(directory.path()).expect("reopen");
        assert!(reopened.has_unresolved_attempt("attempt-a"));
        assert!(reopened.has_unresolved_for_turn("thread-a", "turn-a"));

        let mut resolved = reopened.clone();
        resolved
            .terminals
            .insert("attempt-a".to_owned(), stored_terminal("attempt-a"));
        assert!(!resolved.has_unresolved_attempt("attempt-a"));
        assert!(!resolved.has_unresolved_for_turn("thread-a", "turn-a"));
        super::validate_stored_state(&resolved).expect("valid resolved state");
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn exact_tokenizer_subprocess_receives_unicode_and_control_bytes() {
        use std::os::unix::fs::PermissionsExt;

        let directory = tempfile::tempdir().expect("tempdir");
        let binary = directory.path().join("tokenizer.py");
        let vocabulary = directory.path().join("vocab.txt");
        std::fs::write(
            &binary,
            "#!/usr/bin/env python3\nimport sys\ndata=sys.stdin.buffer.read()\nprint(len(data))\n",
        )
        .expect("write tokenizer");
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o700)).expect("chmod");
        std::fs::write(&vocabulary, b"fixture-vocabulary").expect("write vocab");
        let identity = codex_hepta_context_compiler::FinalRequestTokenizerIdentityV2::new(
            Digest32::of_bytes(b"provider"),
            Digest32::of_bytes(b"model"),
            Digest32::of_bytes(b"declared-tokenizer"),
            super::hash_bounded_file(&binary).expect("binary digest"),
            Digest32::of_bytes(b"fixture-v1"),
            super::hash_bounded_file(&vocabulary).expect("vocab digest"),
            Digest32::of_bytes(b"no-normalization"),
        )
        .expect("identity");
        let tokenizer = super::TokenizerRuntimeConfig {
            binary,
            vocabulary,
            provider_id: "provider".to_owned(),
            model: "model".to_owned(),
            version: "fixture-v1".to_owned(),
            normalization: "no-normalization".to_owned(),
            timeout: std::time::Duration::from_secs(5),
            identity,
        };
        let request = "{\"model\":\"model\",\"input\":\"政策🧪\\ncontrol:\\u0001\"}".as_bytes();
        assert_eq!(
            tokenizer
                .count(request, &super::metrics::Metrics::default())
                .await
                .expect("tokenizer count"),
            u64::try_from(request.len()).expect("length")
        );
    }
}
