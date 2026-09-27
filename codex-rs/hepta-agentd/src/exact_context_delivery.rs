use std::collections::BTreeMap;
use std::env;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_codex_adapter::PromptRuntimeFinalRequestV2;
use codex_hepta_codex_adapter::PromptRuntimeFinalTerminalV2;
use codex_hepta_codex_adapter::PromptRuntimeProviderTerminalV2;
use codex_hepta_codex_adapter::PromptRuntimeRequestKindV2;
use codex_hepta_codex_adapter::PromptRuntimeTransportV2;
use codex_hepta_context_compiler::ContextDeliveryPreparationV2;
use codex_hepta_context_compiler::ContextDeliveryReceiptV2;
use codex_hepta_context_compiler::ContextProviderDeliveryDecisionV2;
use codex_hepta_context_compiler::ContextProviderDeliveryVerifierV2;
use codex_hepta_context_compiler::ExactFinalRequestTokenizerV2;
use codex_hepta_context_compiler::FinalProviderRequestProofV2;
use codex_hepta_context_compiler::FinalRequestFramingVerifierV2;
use codex_hepta_context_compiler::FinalRequestTokenizerIdentityV2;
use codex_hepta_context_compiler::observe_final_provider_delivery_v2;
use codex_hepta_context_compiler::prove_final_provider_request_v2;
use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_intelligence::PromptRegistryCompiledContextV2;
use codex_hepta_intelligence::PromptRegistryDeliveryPreparationV2;
use codex_hepta_intelligence::prepare_prompt_registry_delivery_v2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::timeout;

const EXACT_DELIVERY_SCHEMA: u32 = 1;
const STATE_FILE: &str = "context-delivery-v2.json";
const NEXT_FILE: &str = "context-delivery-v2.next";
const LOCK_FILE: &str = "context-delivery-v2.lock";
const MAX_DURABLE_STATE_BYTES: u64 = 4 * 1024 * 1024;
const MAX_STAGED_CONTEXTS: usize = 256;
const MAX_ACTIVE_ATTEMPTS: usize = 64;
const MAX_PRE_SEND_RECORDS: usize = 4096;
const MAX_TERMINAL_RECORDS: usize = 4096;
const MAX_TOKENIZER_FILE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_TOKENIZER_STDOUT_BYTES: u64 = 64;
const TOKENIZER_TIMEOUT_MS_DEFAULT: u64 = 30_000;
const TOKENIZER_TIMEOUT_MS_MAX: u64 = 120_000;
const PROVIDER_EVIDENCE_VERIFIER_DOMAIN: &[u8] = b"hepta.context-provider-delivery-verifier.v2";
const PROVIDER_EVIDENCE_DOMAIN: &[u8] = b"hepta.context-provider-delivery-evidence.v2";

pub(crate) const HEPTA_CONTEXT_TOKENIZER_BIN_ENV: &str = "HEPTA_CONTEXT_TOKENIZER_BIN";
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
    compiled: PromptRegistryCompiledContextV2,
    fresh: PromptRegistryDeliveryPreparationV2,
    final_request_proof: FinalProviderRequestProofV2,
    intent: ProviderInvocationIntent,
}

#[derive(Default)]
struct ExactRuntimeState {
    staged: BTreeMap<ExactTurnKey, PromptRegistryCompiledContextV2>,
    active: BTreeMap<String, ActiveExactDelivery>,
    durable: StoredExactDeliveryState,
}

pub(crate) struct AgentdExactContextDeliveryOwner {
    registry: Arc<Mutex<DurablePromptRegistry>>,
    state: Mutex<ExactRuntimeState>,
    store: ExactDeliveryStore,
}

impl AgentdExactContextDeliveryOwner {
    pub(crate) fn open(
        directory: &Path,
        registry: Arc<Mutex<DurablePromptRegistry>>,
    ) -> Result<Self, ExactContextDeliveryError> {
        let (store, durable) = ExactDeliveryStore::open(directory)?;
        Ok(Self {
            registry,
            state: Mutex::new(ExactRuntimeState {
                staged: BTreeMap::new(),
                active: BTreeMap::new(),
                durable,
            }),
            store,
        })
    }

    pub(crate) fn stage(
        &self,
        thread_id: &str,
        turn_id: &str,
        compiled: PromptRegistryCompiledContextV2,
    ) -> Result<(), ExactContextDeliveryError> {
        validate_runtime_id(thread_id, "thread id")?;
        validate_runtime_id(turn_id, "turn id")?;
        compiled
            .validate()
            .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        let key = ExactTurnKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        if state.durable.has_unresolved_for_turn(thread_id, turn_id) {
            return Err(ExactContextDeliveryError::RecoveryRequired);
        }
        if let Some(existing) = state.staged.get(&key) {
            return if existing == &compiled {
                Ok(())
            } else {
                Err(ExactContextDeliveryError::Conflict(
                    "a different compiled context is already staged for this turn",
                ))
            };
        }
        if state.staged.len() >= MAX_STAGED_CONTEXTS {
            return Err(ExactContextDeliveryError::Capacity);
        }
        state.staged.insert(key, compiled);
        Ok(())
    }

    pub(crate) async fn observe_final_request(
        self: Arc<Self>,
        request: PromptRuntimeFinalRequestV2,
    ) -> Result<(), ExactContextDeliveryError> {
        request.attempt.validate().map_err(|error| {
            ExactContextDeliveryError::Domain(format!(
                "{}: {}",
                error.reason_code(),
                error.detail()
            ))
        })?;
        let key = ExactTurnKey {
            thread_id: request.attempt.thread_id.clone(),
            turn_id: request.attempt.turn_id.clone(),
        };
        let compiled = {
            let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            if state
                .durable
                .terminals
                .contains_key(&request.attempt.attempt_id)
            {
                return Err(ExactContextDeliveryError::Conflict(
                    "terminal attempt cannot be dispatched again",
                ));
            }
            if state
                .durable
                .has_unresolved_attempt(&request.attempt.attempt_id)
            {
                return Err(ExactContextDeliveryError::RecoveryRequired);
            }
            state
                .staged
                .get(&key)
                .cloned()
                .ok_or(ExactContextDeliveryError::MissingStagedContext)?
        };
        validate_request_scope(&compiled, &request)?;
        let now_unix_ms = current_unix_ms()?;
        let suffix = Digest32::of_bytes(request.attempt.attempt_id.as_bytes()).to_string();
        let snapshot_id = stable_id(format!("context-snapshot:{suffix}"))?;
        let preparation_id = stable_id(format!("context-preparation:{suffix}"))?;
        let fresh = {
            let registry = self.registry.lock().unwrap_or_else(PoisonError::into_inner);
            prepare_prompt_registry_delivery_v2(
                &registry,
                &compiled,
                now_unix_ms,
                snapshot_id,
                preparation_id,
            )
            .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?
        };
        fresh
            .validate_for(&compiled)
            .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;

        let tokenizer = TokenizerRuntimeConfig::load(&request, &compiled)?;
        let token_count = tokenizer.count(&request.canonical_request).await?;
        let bound_tokenizer = BoundFinalRequestTokenizer {
            identity: tokenizer.identity,
            request_digest: Digest32::of_bytes(&request.canonical_request),
            token_count,
        };
        let framing_policy = ResponsesJsonFramingPolicy::new(
            &request.attempt.provider_id,
            &request.attempt.model,
            request.attempt.provider_config_digest,
            request.attempt.endpoint_digest,
        )?;
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
        .map_err(|error| ExactContextDeliveryError::Domain(error.to_string()))?;
        let intent = provider_intent(&request.attempt)?;
        let pre_send =
            StoredPreSend::new(&request, &fresh, &final_request_proof, &intent, now_unix_ms)?;
        let active = ActiveExactDelivery {
            compiled,
            fresh,
            final_request_proof,
            intent,
        };
        self.commit_pre_send(request.attempt.attempt_id.clone(), pre_send, active)
    }

    pub(crate) async fn observe_final_terminal(
        &self,
        terminal: PromptRuntimeFinalTerminalV2,
    ) -> Result<(), ExactContextDeliveryError> {
        let terminal_observation_digest = terminal_observation_digest(&terminal)?;
        let active = {
            let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some(active) = state.active.get(&terminal.attempt.attempt_id) {
                active.clone()
            } else if let Some(existing) = state.durable.terminals.get(&terminal.attempt.attempt_id)
            {
                return if existing.terminal_observation_digest
                    == terminal_observation_digest.into_array()
                {
                    Ok(())
                } else {
                    Err(ExactContextDeliveryError::Conflict(
                        "duplicate terminal observation differs from durable receipt",
                    ))
                };
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
        let provider_terminal = provider_terminal(terminal.terminal)?;
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

    fn commit_pre_send(
        &self,
        attempt_id: String,
        stored: StoredPreSend,
        active: ActiveExactDelivery,
    ) -> Result<(), ExactContextDeliveryError> {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(existing) = state.durable.pre_sends.get(&attempt_id) {
            if existing != &stored {
                return Err(ExactContextDeliveryError::Conflict(
                    "attempt id already binds different pre-send evidence",
                ));
            }
            if let Some(existing_active) = state.active.get(&attempt_id) {
                if existing_active.final_request_proof != active.final_request_proof
                    || existing_active.intent != active.intent
                {
                    return Err(ExactContextDeliveryError::Conflict(
                        "attempt id already has different active evidence",
                    ));
                }
                return Ok(());
            }
            return if state.durable.terminals.contains_key(&attempt_id) {
                Err(ExactContextDeliveryError::Conflict(
                    "terminal attempt cannot be re-armed",
                ))
            } else {
                Err(ExactContextDeliveryError::RecoveryRequired)
            };
        }
        if state.active.len() >= MAX_ACTIVE_ATTEMPTS
            || state.durable.pre_sends.len() >= MAX_PRE_SEND_RECORDS
        {
            return Err(ExactContextDeliveryError::Capacity);
        }
        let mut next = state.durable.clone();
        next.pre_sends.insert(attempt_id.clone(), stored);
        self.store.persist(&next)?;
        state.durable = next;
        state.active.insert(attempt_id, active);
        Ok(())
    }

    fn commit_terminal(
        &self,
        attempt_id: &str,
        stored: StoredTerminal,
    ) -> Result<(), ExactContextDeliveryError> {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        let Some(pre_send) = state.durable.pre_sends.get(attempt_id) else {
            return Err(ExactContextDeliveryError::MissingPreSendEvidence);
        };
        if pre_send.final_request_proof_digest != stored.final_request_proof_digest {
            return Err(ExactContextDeliveryError::Conflict(
                "terminal receipt does not bind the durable pre-send proof",
            ));
        }
        if let Some(existing) = state.durable.terminals.get(attempt_id) {
            return if existing == &stored {
                Ok(())
            } else {
                Err(ExactContextDeliveryError::Conflict(
                    "attempt id already binds a different terminal receipt",
                ))
            };
        }
        if state.durable.terminals.len() >= MAX_TERMINAL_RECORDS {
            return Err(ExactContextDeliveryError::Capacity);
        }
        let mut next = state.durable.clone();
        next.terminals.insert(attempt_id.to_owned(), stored);
        self.store.persist(&next)?;
        state.durable = next;
        state.active.remove(attempt_id);
        Ok(())
    }
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
        let value: serde_json::Value = serde_json::from_slice(canonical_request)
            .map_err(|error| format!("provider request is not valid JSON: {error}"))?;
        let object = value
            .as_object()
            .ok_or_else(|| "provider request root is not an object".to_owned())?;
        if object.get("model").and_then(serde_json::Value::as_str)
            != Some(self.expected_model.as_str())
        {
            return Err("provider request model does not match the bound model".to_owned());
        }
        if !object.contains_key("input") && !object.contains_key("instructions") {
            return Err("provider request has no typed model-input field".to_owned());
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
        serde_json::Value::Object(values) => values.values().try_fold(0_usize, |total, value| {
            total
                .checked_add(count_context_occurrences(value, context)?)
                .ok_or_else(|| "context occurrence count overflow".to_owned())
        }),
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
        compiled: &PromptRegistryCompiledContextV2,
    ) -> Result<Self, ExactContextDeliveryError> {
        let binary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_BIN_ENV, true)?;
        let vocabulary = absolute_regular_file(HEPTA_CONTEXT_TOKENIZER_VOCAB_ENV, false)?;
        let provider_id = bounded_env(HEPTA_CONTEXT_TOKENIZER_PROVIDER_ID_ENV, 512)?;
        let model = bounded_env(HEPTA_CONTEXT_TOKENIZER_MODEL_ENV, 512)?;
        let version = bounded_env(HEPTA_CONTEXT_TOKENIZER_VERSION_ENV, 256)?;
        let normalization = bounded_env(HEPTA_CONTEXT_TOKENIZER_NORMALIZATION_ENV, 256)?;
        if provider_id != request.attempt.provider_id || model != request.attempt.model {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        let declared = Digest32::from_str(&bounded_env(
            HEPTA_CONTEXT_TOKENIZER_PROFILE_SHA256_ENV,
            64,
        )?)
        .map_err(|_| ExactContextDeliveryError::TokenizerIdentity)?;
        if declared != compiled.model_profile.tokenizer_digest
            || Digest32::of_bytes(provider_id.as_bytes())
                != compiled.model_profile.provider_id_digest
            || Digest32::of_bytes(model.as_bytes()) != compiled.model_profile.provider_model_digest
        {
            return Err(ExactContextDeliveryError::TokenizerIdentity);
        }
        let binary_digest = hash_bounded_file(&binary)?;
        let vocabulary_digest = hash_bounded_file(&vocabulary)?;
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

    async fn count(&self, request: &[u8]) -> Result<u64, ExactContextDeliveryError> {
        let mut child = Command::new(&self.binary)
            .arg("--provider")
            .arg(&self.provider_id)
            .arg("--model")
            .arg(&self.model)
            .arg("--version")
            .arg(&self.version)
            .arg("--vocabulary")
            .arg(&self.vocabulary)
            .arg("--normalization")
            .arg(&self.normalization)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or(ExactContextDeliveryError::TokenizerUnavailable)?;
        let mut stdout = child
            .stdout
            .take()
            .ok_or(ExactContextDeliveryError::TokenizerUnavailable)?;
        stdin
            .write_all(request)
            .await
            .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
        drop(stdin);
        let execution = async {
            let mut output = Vec::new();
            stdout
                .take(MAX_TOKENIZER_STDOUT_BYTES + 1)
                .read_to_end(&mut output)
                .await
                .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
            let status = child
                .wait()
                .await
                .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
            Ok::<_, ExactContextDeliveryError>((status, output))
        };
        let (status, output) = timeout(self.timeout, execution)
            .await
            .map_err(|_| ExactContextDeliveryError::TokenizerTimeout)??;
        if !status.success()
            || u64::try_from(output.len()).unwrap_or(u64::MAX) > MAX_TOKENIZER_STDOUT_BYTES
        {
            return Err(ExactContextDeliveryError::TokenizerRejected);
        }
        parse_token_count(&output)
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
    compiled: &PromptRegistryCompiledContextV2,
    request: &PromptRuntimeFinalRequestV2,
) -> Result<(), ExactContextDeliveryError> {
    if request.attachment.compilation_id != *compiled.compiled.receipt().compilation_id()
        || request.attachment.context_attachment_digest != compiled.attachment.attachment_digest()
        || request.attachment.context_payload_digest
            != compiled.serialized_context.receipt().payload_digest()
        || request.attachment.model != request.attempt.model
        || request.canonical_request.is_empty()
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
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?
        .take(MAX_TOKENIZER_FILE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_TOKENIZER_FILE_BYTES {
        return Err(ExactContextDeliveryError::TokenizerConfiguration);
    }
    Ok(Digest32::of_bytes(&bytes))
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
    #[serde(default = "exact_delivery_schema")]
    schema: u32,
    #[serde(default)]
    pre_sends: BTreeMap<String, StoredPreSend>,
    #[serde(default)]
    terminals: BTreeMap<String, StoredTerminal>,
}

const fn exact_delivery_schema() -> u32 {
    EXACT_DELIVERY_SCHEMA
}

impl StoredExactDeliveryState {
    fn has_unresolved_attempt(&self, attempt_id: &str) -> bool {
        self.pre_sends.contains_key(attempt_id) && !self.terminals.contains_key(attempt_id)
    }

    fn has_unresolved_for_turn(&self, thread_id: &str, turn_id: &str) -> bool {
        self.pre_sends.iter().any(|(attempt_id, record)| {
            record.thread_id == thread_id
                && record.turn_id == turn_id
                && !self.terminals.contains_key(attempt_id)
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
    registry_snapshot_digest: [u8; 32],
    final_use_materialization_digest: [u8; 32],
    preparation_digest: [u8; 32],
    final_request_proof_digest: [u8; 32],
    provider_request_digest: [u8; 32],
    provider_wire_semantic_digest: [u8; 32],
    tokenizer_identity_digest: [u8; 32],
    tokenization_receipt_digest: [u8; 32],
    token_count: u64,
    segment_map_digest: [u8; 32],
    recorded_unix_ms: u64,
}

impl StoredPreSend {
    fn new(
        request: &PromptRuntimeFinalRequestV2,
        fresh: &PromptRegistryDeliveryPreparationV2,
        proof: &FinalProviderRequestProofV2,
        intent: &ProviderInvocationIntent,
        recorded_unix_ms: u64,
    ) -> Result<Self, ExactContextDeliveryError> {
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
            registry_snapshot_digest: fresh.registry_snapshot_digest.into_array(),
            final_use_materialization_digest: fresh.final_use_materialization_digest.into_array(),
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
        })
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredTerminal {
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

struct ExactDeliveryStore {
    root: PathBuf,
    _lock: File,
}

impl ExactDeliveryStore {
    fn open(
        directory: &Path,
    ) -> Result<(Self, StoredExactDeliveryState), ExactContextDeliveryError> {
        prepare_directory(directory)?;
        let lock_path = directory.join(LOCK_FILE);
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        set_private_file_permissions(&lock_path)?;
        lock.try_lock()
            .map_err(|_| ExactContextDeliveryError::StateLocked)?;
        let store = Self {
            root: directory.to_path_buf(),
            _lock: lock,
        };
        let path = directory.join(STATE_FILE);
        if !path.exists() {
            return Ok((
                store,
                StoredExactDeliveryState {
                    schema: EXACT_DELIVERY_SCHEMA,
                    ..StoredExactDeliveryState::default()
                },
            ));
        }
        let mut bytes = Vec::new();
        File::open(&path)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?
            .take(MAX_DURABLE_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        let state: StoredExactDeliveryState =
            serde_json::from_slice(&bytes).map_err(|_| ExactContextDeliveryError::CorruptState)?;
        validate_stored_state(&state)?;
        Ok((store, state))
    }

    fn persist(&self, state: &StoredExactDeliveryState) -> Result<(), ExactContextDeliveryError> {
        validate_stored_state(state)?;
        let bytes =
            serde_json::to_vec(state).map_err(|_| ExactContextDeliveryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(ExactContextDeliveryError::Capacity);
        }
        let next_path = self.root.join(NEXT_FILE);
        let mut next = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&next_path)
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        set_private_file_permissions(&next_path)?;
        next.write_all(&bytes)
            .and_then(|()| next.sync_all())
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        std::fs::rename(&next_path, self.root.join(STATE_FILE))
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        sync_directory(&self.root)
    }
}

fn validate_stored_state(
    state: &StoredExactDeliveryState,
) -> Result<(), ExactContextDeliveryError> {
    if state.schema != EXACT_DELIVERY_SCHEMA
        || state.pre_sends.len() > MAX_PRE_SEND_RECORDS
        || state.terminals.len() > MAX_TERMINAL_RECORDS
        || state
            .terminals
            .keys()
            .any(|attempt| !state.pre_sends.contains_key(attempt))
        || state.pre_sends.iter().any(|(attempt, record)| {
            attempt != &record.attempt_id
                || attempt.is_empty()
                || record.preparation_digest == [0; 32]
                || record.final_request_proof_digest == [0; 32]
                || record.provider_request_digest == [0; 32]
                || record.token_count == 0
        })
        || state.terminals.iter().any(|(attempt, record)| {
            attempt != &record.attempt_id
                || record.terminal_observation_digest == [0; 32]
                || record.provider_receipt_digest == [0; 32]
                || record.context_delivery_receipt_digest == [0; 32]
        })
    {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    Ok(())
}

fn prepare_directory(path: &Path) -> Result<(), ExactContextDeliveryError> {
    std::fs::create_dir_all(path).map_err(|_| ExactContextDeliveryError::Unavailable)?;
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| ExactContextDeliveryError::Unavailable)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(ExactContextDeliveryError::Unavailable);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
    }
    Ok(())
}

fn set_private_file_permissions(path: &Path) -> Result<(), ExactContextDeliveryError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
    }
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), ExactContextDeliveryError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| ExactContextDeliveryError::IndeterminateDurability)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum ExactContextDeliveryError {
    Unavailable,
    StateLocked,
    CorruptState,
    IndeterminateDurability,
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
    Domain(String),
}

impl ExactContextDeliveryError {
    pub(crate) const fn reason_code(&self) -> &'static str {
        match self {
            Self::Unavailable => "context_delivery_v2_unavailable",
            Self::StateLocked => "context_delivery_v2_state_locked",
            Self::CorruptState => "context_delivery_v2_corrupt_state",
            Self::IndeterminateDurability => "context_delivery_v2_indeterminate_durability",
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
            Self::Domain(_) => "context_delivery_v2_domain_rejected",
        }
    }
}

impl fmt::Display for ExactContextDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Conflict(detail) => write!(formatter, "{}: {detail}", self.reason_code()),
            Self::Domain(detail) => write!(formatter, "{}: {detail}", self.reason_code()),
            _ => formatter.write_str(self.reason_code()),
        }
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
            "instructions": String::from_utf8(context.to_vec()).expect("utf8"),
            "input": []
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

    fn stored_pre_send(thread_id: &str, turn_id: &str, attempt_id: &str) -> super::StoredPreSend {
        super::StoredPreSend {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
            attempt_id: attempt_id.to_owned(),
            provider_intent_digest: [1; 32],
            registry_snapshot_digest: [2; 32],
            final_use_materialization_digest: [3; 32],
            preparation_digest: [4; 32],
            final_request_proof_digest: [5; 32],
            provider_request_digest: [6; 32],
            provider_wire_semantic_digest: [7; 32],
            tokenizer_identity_digest: [8; 32],
            tokenization_receipt_digest: [9; 32],
            token_count: 11,
            segment_map_digest: [10; 32],
            recorded_unix_ms: 12,
        }
    }

    fn stored_terminal(attempt_id: &str) -> super::StoredTerminal {
        super::StoredTerminal {
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
            tokenizer.count(request).await.expect("tokenizer count"),
            u64::try_from(request.len()).expect("length")
        );
    }
}
