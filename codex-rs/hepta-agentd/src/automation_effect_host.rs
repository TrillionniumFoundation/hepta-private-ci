//! Host-owned composition for final-use-authorized automation effects.
//!
//! The TaskFlow owner persists intent/attempt/reconciliation state. Agentd owns
//! the selected provider contract and final-use verifier. Control callers can
//! transport a signed grant and exact provider bytes, but they cannot select a
//! provider endpoint, destination, final-use scope, subject, or TaskFlow fence.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use codex_hepta_automation::AuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseTrustKey;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_model_provider::HttpProviderEffectAdapter;
use codex_model_provider::HttpProviderEffectConfig;
use codex_model_provider::HttpProviderEffectContractAttestation;
use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authority_trust_host::AgentdFinalUseTrustStore;

const AUTOMATION_EFFECT_HOST_SCHEMA_VERSION: u32 = 2;
const MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES: u64 = 64 * 1024;
const MAX_AUTOMATION_EFFECT_REVOCATION_FEED_FILE_BYTES: u64 = 4 * 1024 * 1024;
const MAX_FINAL_USE_TRUST_KEYS: usize = 8;
const MAX_PROVIDER_HEADERS: usize = 64;

#[derive(Clone, Debug)]
pub(crate) enum AgentdAutomationEffectReconcileOutcome {
    Observed(TaskFlowStepReceipt),
    Indeterminate,
    ProvenAbsent,
}

#[derive(Clone)]
pub(crate) struct AgentdAutomationEffectHost {
    agent_id: codex_hepta_contracts::AgentId,
    provider_scope: String,
    destination_id: String,
    final_use_scope_digest: Sha256Digest,
    authority: FinalUseAuthority,
    authority_trust: Arc<AgentdFinalUseTrustStore>,
    revocation_feed_verifier: FinalUseRevocationFeedVerifier,
    revocation_feed_file: PathBuf,
    revocation_refresh: Arc<Mutex<()>>,
    adapter: HttpProviderEffectAdapter,
}

impl std::fmt::Debug for AgentdAutomationEffectHost {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AgentdAutomationEffectHost")
            .field("agent_id", &self.agent_id)
            .field("provider_scope", &self.provider_scope)
            .field("destination_id", &self.destination_id)
            .field("final_use_scope_digest", &self.final_use_scope_digest)
            .field("adapter", &self.adapter)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FinalUseTrustKeyFileV1 {
    key_id: String,
    verifying_key_hex: String,
    not_before_authority_epoch: u64,
    not_after_authority_epoch: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AutomationEffectHostFileV2 {
    schema_version: u32,
    provider_scope: String,
    destination_id: String,
    final_use_scope_sha256: String,
    dispatch_url: String,
    lookup_url_template: String,
    #[serde(default)]
    headers: BTreeMap<String, String>,
    timeout_ms: u64,
    contract_id: String,
    contract_sha256: String,
    contract_authority_epoch: u64,
    contract_signature_hex: String,
    contract_verifying_key_hex: String,
    final_use_signer_id: String,
    final_use_issuer_keys: Vec<FinalUseTrustKeyFileV1>,
    final_use_revocation_distributor_id: String,
    final_use_revocation_keys: Vec<FinalUseTrustKeyFileV1>,
    final_use_revocation_feed_file: PathBuf,
    final_use_trust_root: PathBuf,
}

impl AgentdAutomationEffectHost {
    pub(crate) fn open(identity: &AgentdIdentity, path: &Path) -> Result<Self, AgentdError> {
        let config = read_host_file(path)?;
        if config.schema_version != AUTOMATION_EFFECT_HOST_SCHEMA_VERSION {
            return Err(AgentdError::Invalid(
                "unsupported automation effect host schema".to_string(),
            ));
        }
        validate_host_identifier("provider_scope", &config.provider_scope)?;
        validate_host_identifier("destination_id", &config.destination_id)?;
        if config.timeout_ms == 0 || config.timeout_ms > 30_000 {
            return Err(AgentdError::Invalid(
                "automation effect timeout_ms must be 1..=30000".to_string(),
            ));
        }
        if config.headers.len() > MAX_PROVIDER_HEADERS {
            return Err(AgentdError::Invalid(
                "automation effect provider header bound exceeded".to_string(),
            ));
        }

        let final_use_scope_digest = Sha256Digest::parse(config.final_use_scope_sha256.clone())
            .map_err(AgentdError::Invalid)?;
        let declared_contract_digest =
            Sha256Digest::parse(config.contract_sha256.clone()).map_err(AgentdError::Invalid)?;
        let contract_signature =
            decode_hex_array::<64>(&config.contract_signature_hex, "contract_signature_hex")?;
        let contract_verifying_key = decode_hex_array::<32>(
            &config.contract_verifying_key_hex,
            "contract_verifying_key_hex",
        )?;
        let final_use_issuer_keys = issuer_trust_keys(&config.final_use_issuer_keys)?;
        let final_use_revocation_keys = control_trust_keys(&config.final_use_revocation_keys)?;

        let mut headers = HeaderMap::new();
        for (name, value) in config.headers {
            let name = HeaderName::from_bytes(name.as_bytes()).map_err(|error| {
                AgentdError::Invalid(format!("invalid provider header name: {error}"))
            })?;
            let value = HeaderValue::from_bytes(value.as_bytes()).map_err(|error| {
                AgentdError::Invalid(format!("invalid provider header value: {error}"))
            })?;
            headers.append(name, value);
        }

        let attestation = HttpProviderEffectContractAttestation::verify_signed(
            config.contract_id.clone(),
            declared_contract_digest,
            config.contract_authority_epoch,
            &contract_signature,
            &contract_verifying_key,
        )
        .map_err(AgentdError::Invalid)?;
        let provider_config = HttpProviderEffectConfig {
            dispatch_url: config.dispatch_url,
            lookup_url_template: config.lookup_url_template,
            headers,
            timeout: Duration::from_millis(config.timeout_ms),
            contract_id: config.contract_id,
            attestation: Some(attestation),
        };
        let adapter =
            HttpProviderEffectAdapter::new(provider_config).map_err(AgentdError::Invalid)?;

        if !config.final_use_revocation_feed_file.is_absolute()
            || !config.final_use_trust_root.is_absolute()
        {
            return Err(AgentdError::Invalid(
                "final_use_revocation_feed_file and final_use_trust_root must be absolute"
                    .to_string(),
            ));
        }
        let revocation_feed_verifier = FinalUseRevocationFeedVerifier::new_with_keys(
            config.final_use_revocation_distributor_id,
            final_use_revocation_keys,
        )
        .map_err(|error| {
            AgentdError::Invalid(format!("invalid final-use revocation trust: {error}"))
        })?;
        let signed_update = read_revocation_feed_file(&config.final_use_revocation_feed_file)?;
        let authority_root = identity
            .layout
            .automation_root()
            .join("final-use-authority");
        let local_authority_uninitialized = authority_state_uninitialized(&authority_root)?;
        fs::create_dir_all(&authority_root)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&authority_root, fs::Permissions::from_mode(0o700))?;
        }

        let authority_trust = Arc::new(AgentdFinalUseTrustStore::open(
            &config.final_use_trust_root,
            &identity.home_root,
            &config.final_use_signer_id,
        )?);
        let now_unix_ms = authority_trust.now_unix_ms().map_err(|error| {
            AgentdError::Protocol(format!("sample protected final-use clock: {error}"))
        })?;
        revocation_feed_verifier
            .verify(&signed_update, now_unix_ms)
            .map_err(|error| {
                AgentdError::GenerationFenced(format!(
                    "initial signed final-use revocation feed rejected: {error}"
                ))
            })?;
        let initial_revocations = signed_update.update.head.clone();
        let initial_frontier =
            FinalUseFrontier::for_initial_head(&initial_revocations).map_err(|error| {
                AgentdError::Invalid(format!("invalid initial final-use frontier: {error}"))
            })?;
        authority_trust.ensure_initial_frontier(initial_frontier, local_authority_uninitialized)?;
        let clock: Arc<dyn AuthorityClock> = authority_trust.clone();
        let frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> =
            authority_trust.clone();
        let authority = FinalUseAuthority::recover_state_dir_with_issuer_keys(
            &authority_root,
            config.final_use_signer_id,
            final_use_issuer_keys,
            initial_revocations,
            clock,
            frontier_store,
        )
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "open production automation final-use authority state: {error}"
            ))
        })?;

        let host = Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: config.provider_scope,
            destination_id: config.destination_id,
            final_use_scope_digest,
            authority,
            authority_trust,
            revocation_feed_verifier,
            revocation_feed_file: config.final_use_revocation_feed_file,
            revocation_refresh: Arc::new(Mutex::new(())),
            adapter,
        };
        // Recover the old durable head first, then authenticate and commit the
        // current feed through the same entry used before every effect.
        host.refresh_revocations()?;
        Ok(host)
    }

    pub(crate) async fn execute(
        &self,
        store: &AutomationStore,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: &SignedFinalUseGrant,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AgentdError> {
        self.validate_intent(intent, wire_payload)?;
        self.refresh_revocations()?;
        if let Some(receipt) = store
            .read_authorized_taskflow_effect_receipt(intent, command_id)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read terminal effect receipt: {error}"))
            })?
        {
            return Ok(receipt);
        }
        let run = store
            .taskflow_run(&intent.run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        let fence = self.current_fence(&run, now_ms)?;
        let binding = intent
            .final_use_binding()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let mut driver = HttpAuthorizedEffectDriver {
            adapter: self.adapter.clone(),
            provider_scope: self.provider_scope.clone(),
            destination_id: self.destination_id.clone(),
        };
        store
            .execute_authorized_taskflow_effect(
                &self.authority,
                &mut driver,
                intent,
                wire_payload,
                &fence,
                signed_grant,
                &binding,
                command_id,
                now_ms,
            )
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("automation authorized effect dispatch: {error}"))
            })
    }

    pub(crate) async fn reconcile(
        &self,
        store: &AutomationStore,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        now_ms: u64,
    ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
        let pending = store
            .authorized_taskflow_effect_attempt(run_id, step_id, attempt)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read pending authorized effect: {error}"))
            })?
            .ok_or_else(|| {
                AgentdError::Invalid("authorized effect is not pending reconciliation".to_string())
            })?;
        if pending.destination_id != self.destination_id {
            return Err(AgentdError::GenerationFenced(
                "pending effect destination differs from the configured provider".to_string(),
            ));
        }
        let run = store
            .taskflow_run(run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        let fence = self.current_fence(&run, now_ms)?;
        if let Some(local) = store
            .settle_authorized_taskflow_effect_observation(run_id, step_id, attempt, &fence)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "settle durable authorized effect observation: {error}"
                ))
            })?
        {
            match local {
                AuthorizedEffectRecoveryResult::Observed(receipt)
                    if receipt.observation != Some(TaskFlowStepObservation::Indeterminate) =>
                {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Observed(receipt));
                }
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    return Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent);
                }
                AuthorizedEffectRecoveryResult::Observed(_) => {}
            }
        }
        let provider_intent = self.provider_intent(&pending)?;
        match self.adapter.lookup_for_intent(&provider_intent).await {
            ProviderEffectLookup::Ack(ack) => {
                let Some(receipt) = terminal_receipt_from_ack(&ack) else {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
                };
                match store
                    .recover_authorized_taskflow_effect(
                        run_id,
                        step_id,
                        attempt,
                        &fence,
                        AuthorizedEffectRecovery::Observed(receipt),
                        now_ms,
                    )
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!(
                            "reconcile authorized effect terminal observation: {error}"
                        ))
                    })? {
                    AuthorizedEffectRecoveryResult::Observed(receipt) => {
                        Ok(AgentdAutomationEffectReconcileOutcome::Observed(receipt))
                    }
                    AuthorizedEffectRecoveryResult::ProvenAbsent => Err(AgentdError::Protocol(
                        "status lookup cannot manufacture provider absence".to_string(),
                    )),
                }
            }
            ProviderEffectLookup::Conflict { .. } => Err(AgentdError::Protocol(
                "provider reports a same-key payload conflict".to_string(),
            )),
            ProviderEffectLookup::NotFound | ProviderEffectLookup::Unknown => {
                Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate)
            }
        }
    }

    fn refresh_revocations(&self) -> Result<(), AgentdError> {
        let _refresh = self.revocation_refresh.lock().map_err(|_| {
            AgentdError::Protocol(
                "automation effect revocation refresh lock is poisoned".to_string(),
            )
        })?;
        let signed = read_revocation_feed_file(&self.revocation_feed_file)?;
        let now_unix_ms = self.authority_trust.now_unix_ms().map_err(|error| {
            AgentdError::Protocol(format!("sample protected final-use clock: {error}"))
        })?;
        self.revocation_feed_verifier
            .verify(&signed, now_unix_ms)
            .map_err(|error| {
                AgentdError::GenerationFenced(format!(
                    "automation effect signed revocation feed rejected: {error}"
                ))
            })?;
        let current = self.authority.revocation_head().map_err(|error| {
            AgentdError::Protocol(format!("read automation revocation head: {error}"))
        })?;
        if current == signed.update.head {
            return Ok(());
        }
        self.revocation_feed_verifier
            .apply(&self.authority, &signed, now_unix_ms)
            .map_err(|error| {
                AgentdError::GenerationFenced(format!(
                    "automation effect revocation refresh rejected: {error}"
                ))
            })?;
        Ok(())
    }

    fn validate_intent(
        &self,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
    ) -> Result<(), AgentdError> {
        if wire_payload.is_empty() || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES {
            return Err(AgentdError::Invalid(
                "automation effect wire payload is empty or too large".to_string(),
            ));
        }
        if intent.subject_id != self.agent_id.as_str()
            || intent.destination_id != self.destination_id
            || intent.final_use_scope_digest != self.final_use_scope_digest
        {
            return Err(AgentdError::GenerationFenced(
                "automation effect intent is outside the host-owned subject/destination/scope"
                    .to_string(),
            ));
        }
        if Sha256Digest::for_bytes(wire_payload) != intent.payload_digest {
            return Err(AgentdError::Invalid(
                "automation effect wire payload digest mismatch".to_string(),
            ));
        }
        Ok(())
    }

    fn current_fence(
        &self,
        run: &codex_hepta_automation::TaskFlowRun,
        now_ms: u64,
    ) -> Result<TaskFlowFence, AgentdError> {
        if run.owner_agent_id != self.agent_id {
            return Err(AgentdError::GenerationFenced(
                "TaskFlow run is owned by a different Agent".to_string(),
            ));
        }
        if run
            .lease_expires_at_ms
            .is_none_or(|expires_at| expires_at <= now_ms)
        {
            return Err(AgentdError::Protocol(
                "TaskFlow owner lease is not current".to_string(),
            ));
        }
        TaskFlowFence::new(
            run.owner_agent_id.clone(),
            run.owner_id
                .clone()
                .ok_or_else(|| AgentdError::Protocol("TaskFlow owner id is missing".to_string()))?,
            run.owner_epoch.ok_or_else(|| {
                AgentdError::Protocol("TaskFlow owner epoch is missing".to_string())
            })?,
            run.generation.ok_or_else(|| {
                AgentdError::Protocol("TaskFlow owner generation is missing".to_string())
            })?,
            run.fencing_token.clone().ok_or_else(|| {
                AgentdError::Protocol("TaskFlow fencing token is missing".to_string())
            })?,
        )
        .map_err(|error| AgentdError::Protocol(format!("rebuild TaskFlow fence: {error}")))
    }

    fn provider_intent(
        &self,
        pending: &AuthorizedEffectPending,
    ) -> Result<ProviderEffectIntent, AgentdError> {
        let key = ProviderEffectKey::for_operation(
            &self.provider_scope,
            &pending.run_id,
            &pending.step_id,
        )
        .map_err(|error| AgentdError::Invalid(format!("derive provider effect key: {error:?}")))?;
        Ok(ProviderEffectIntent::new(
            key,
            pending.payload_digest.clone(),
        ))
    }
}

struct HttpAuthorizedEffectDriver {
    adapter: HttpProviderEffectAdapter,
    provider_scope: String,
    destination_id: String,
}

impl AuthorizedEffectDriver for HttpAuthorizedEffectDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        if request.intent.destination_id != self.destination_id {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        let key = ProviderEffectKey::for_operation(
            &self.provider_scope,
            &request.intent.run_id,
            &request.intent.step_id,
        )
        .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        let provider_intent = ProviderEffectIntent::new(key, request.intent.payload_digest.clone());
        let adapter = self.adapter.clone();
        let wire_payload = request.wire_payload.to_vec();
        let spawn = thread::Builder::new()
            .name("hepta-automation-provider-effect".to_string())
            .spawn(move || {
                let runtime = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(_) => return ProviderThreadOutcome::BeforeContact,
                };
                ProviderThreadOutcome::Dispatch(
                    runtime
                        .block_on(adapter.dispatch_with_payload(&provider_intent, &wire_payload)),
                )
            })
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        match spawn.join() {
            Ok(ProviderThreadOutcome::BeforeContact) => {
                Err(AuthorizedEffectDriverError::BeforeProviderContact)
            }
            Ok(ProviderThreadOutcome::Dispatch(ProviderEffectDispatch::NotDispatched {
                ..
            })) => Err(AuthorizedEffectDriverError::BeforeProviderContact),
            Ok(ProviderThreadOutcome::Dispatch(dispatch)) => Ok(receipt_from_dispatch(&dispatch)),
            Err(_) => Ok(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Indeterminate,
                receipt_digest: Sha256Digest::for_bytes(
                    b"hepta.agentd.provider-effect.worker-panic.v1",
                ),
            }),
        }
    }
}

enum ProviderThreadOutcome {
    BeforeContact,
    Dispatch(ProviderEffectDispatch),
}

fn receipt_from_dispatch(dispatch: &ProviderEffectDispatch) -> AuthorizedEffectProviderReceipt {
    let outcome = match dispatch {
        ProviderEffectDispatch::Ack(ack) => match ack.status {
            ProviderEffectAckStatus::Completed => AuthorizedEffectOutcome::Succeeded,
            ProviderEffectAckStatus::Rejected => AuthorizedEffectOutcome::Failed,
            ProviderEffectAckStatus::Accepted => AuthorizedEffectOutcome::Indeterminate,
        },
        ProviderEffectDispatch::Rejected { .. } => AuthorizedEffectOutcome::Failed,
        ProviderEffectDispatch::Unknown => AuthorizedEffectOutcome::Indeterminate,
        ProviderEffectDispatch::NotDispatched { .. } => AuthorizedEffectOutcome::Indeterminate,
    };
    AuthorizedEffectProviderReceipt {
        outcome,
        receipt_digest: serialized_observation_digest(
            b"hepta.agentd.provider-effect.dispatch.v1\0",
            dispatch,
        ),
    }
}

fn terminal_receipt_from_ack(ack: &ProviderEffectAck) -> Option<AuthorizedEffectProviderReceipt> {
    let outcome = match ack.status {
        ProviderEffectAckStatus::Completed => AuthorizedEffectOutcome::Succeeded,
        ProviderEffectAckStatus::Rejected => AuthorizedEffectOutcome::Failed,
        ProviderEffectAckStatus::Accepted => return None,
    };
    Some(AuthorizedEffectProviderReceipt {
        outcome,
        receipt_digest: serialized_observation_digest(
            b"hepta.agentd.provider-effect.lookup.v1\0",
            ack,
        ),
    })
}

fn serialized_observation_digest(domain: &[u8], value: &impl serde::Serialize) -> Sha256Digest {
    let mut bytes = domain.to_vec();
    if let Ok(encoded) = serde_json::to_vec(value) {
        bytes.extend_from_slice(&encoded);
    } else {
        bytes.extend_from_slice(b"serialization-unavailable");
    }
    Sha256Digest::for_bytes(&bytes)
}

fn read_host_file(path: &Path) -> Result<AutomationEffectHostFileV2, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES,
        "automation effect host file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn read_revocation_feed_file(path: &Path) -> Result<SignedFinalUseRevocationUpdate, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_REVOCATION_FEED_FILE_BYTES,
        "automation effect signed revocation feed file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn issuer_trust_keys(
    configured: &[FinalUseTrustKeyFileV1],
) -> Result<Vec<FinalUseIssuerTrustKey>, AgentdError> {
    validate_trust_key_count(configured)?;
    configured
        .iter()
        .map(|key| {
            validate_host_identifier("final-use issuer key id", &key.key_id)?;
            Ok(FinalUseIssuerTrustKey {
                key_id: key.key_id.clone(),
                verifying_key: decode_hex_array::<32>(
                    &key.verifying_key_hex,
                    "final-use issuer verifying key",
                )?,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            })
        })
        .collect()
}

fn control_trust_keys(
    configured: &[FinalUseTrustKeyFileV1],
) -> Result<Vec<FinalUseTrustKey>, AgentdError> {
    validate_trust_key_count(configured)?;
    configured
        .iter()
        .map(|key| {
            validate_host_identifier("final-use revocation key id", &key.key_id)?;
            Ok(FinalUseTrustKey {
                key_id: key.key_id.clone(),
                verifying_key: decode_hex_array::<32>(
                    &key.verifying_key_hex,
                    "final-use revocation verifying key",
                )?,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            })
        })
        .collect()
}

fn validate_trust_key_count(configured: &[FinalUseTrustKeyFileV1]) -> Result<(), AgentdError> {
    if configured.is_empty() || configured.len() > MAX_FINAL_USE_TRUST_KEYS {
        return Err(AgentdError::Invalid(
            "final-use trust-key ring must contain 1..=8 keys".to_string(),
        ));
    }
    Ok(())
}

fn authority_state_uninitialized(root: &Path) -> Result<bool, AgentdError> {
    if !root.exists() {
        return Ok(true);
    }
    let metadata = fs::symlink_metadata(root)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(AgentdError::Invalid(
            "automation final-use authority root is not a safe directory".to_string(),
        ));
    }
    Ok(!root.join("authority.lock").exists()
        && !root.join("authority.json").exists()
        && !root.join("authority.claims").exists())
}

fn read_protected_file(path: &Path, max_bytes: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
    if !path.is_absolute() {
        return Err(AgentdError::Invalid(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(AgentdError::Invalid(format!(
            "{label} must be canonical and symlink-free"
        )));
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a regular non-symlink file"
        )));
    }
    if metadata.len() == 0 || metadata.len() > max_bytes {
        return Err(AgentdError::Invalid(format!(
            "{label} is empty or too large"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must not be group/world accessible"
            )));
        }
    }
    Ok(fs::read(path)?)
}

fn validate_host_identifier(label: &str, value: &str) -> Result<(), AgentdError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a bounded identifier"
        )));
    }
    Ok(())
}

fn decode_hex_array<const N: usize>(value: &str, label: &str) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 {
        return Err(AgentdError::Invalid(format!(
            "{label} must contain exactly {} hex characters",
            N * 2
        )));
    }
    let mut output = [0_u8; N];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = hex_nibble(pair[0])
            .ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
        let low = hex_nibble(pair[1])
            .ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
        output[index] = (high << 4) | low;
    }
    Ok(output)
}

fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

#[cfg(all(test, unix))]
mod tests {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_automation::AuthorizedEffectIntent;
    use codex_hepta_automation::TaskFlowCommand;
    use codex_hepta_automation::TaskFlowDefinition;
    use codex_hepta_automation::TaskFlowEdgeSpec;
    use codex_hepta_automation::TaskFlowNodeKind;
    use codex_hepta_automation::TaskFlowNodeSpec;
    use codex_hepta_automation::TaskFlowStepObservation;
    use codex_hepta_automation::TaskFlowTransition;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocationUpdate;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::ProviderEffectKey;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use wiremock::Mock;
    use wiremock::MockServer;
    use wiremock::ResponseTemplate;
    use wiremock::matchers::body_bytes;
    use wiremock::matchers::header;
    use wiremock::matchers::method;
    use wiremock::matchers::path;

    use super::*;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52";
    const WIRE: &[u8] = b"{\"effect\":\"deliver\"}";

    struct Fixture {
        _temp: tempfile::TempDir,
        identity: AgentdIdentity,
        store: AutomationStore,
    }

    impl Fixture {
        async fn new() -> Self {
            let temp = tempfile::tempdir().expect("temp root");
            let root = temp.path().canonicalize().expect("canonical temp root");
            let fleet_path = root.join("fleet");
            let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
            let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
            let workspace = root.join("workspace");
            fs::create_dir(&workspace).expect("workspace");
            let workspace = workspace.canonicalize().expect("canonical workspace");
            let agent_id = codex_hepta_contracts::AgentId::parse(AGENT_ID).expect("agent id");
            let resources = ResourceBudget::local_default();
            let manifest = AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(workspace.clone(), &fleet_root).expect("workspace binding"),
                resources.clone(),
            )
            .expect("manifest");
            let layout = registry.register(manifest).expect("register agent").layout;
            let identity = AgentdIdentity {
                agent_id: agent_id.clone(),
                layout: layout.clone(),
                spawn_generation: 1,
                fleet_root: fleet_path,
                workspace,
                resources,
                home_root: layout.home_root().to_path_buf(),
                run_root: layout.run_root().to_path_buf(),
                control_socket: layout.agentd_control_socket().to_path_buf(),
                app_server_socket: layout.app_server_socket().to_path_buf(),
            };
            let store = AutomationStore::open(&layout)
                .await
                .expect("automation store");
            Self {
                _temp: temp,
                identity,
                store,
            }
        }
    }

    fn definition() -> TaskFlowDefinition {
        TaskFlowDefinition::new(
            "agentd-product-effect",
            1,
            "effect",
            vec![
                TaskFlowNodeSpec::effect("effect", "provider.deliver", "provider-key-v1"),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("effect", "success"),
                TaskFlowEdgeSpec::new("effect", "failure"),
            ],
            vec!["provider.deliver".to_string()],
            Sha256Digest::for_bytes(b"agentd-product-effect-policy"),
        )
        .expect("definition")
    }

    fn effect_intent(scope: &Sha256Digest) -> AuthorizedEffectIntent {
        AuthorizedEffectIntent {
            run_id: "agentd-product-effect-run".to_string(),
            step_id: "effect".to_string(),
            attempt: 1,
            operation_id: "provider.deliver".to_string(),
            subject_id: AGENT_ID.to_string(),
            destination_id: "provider:fixture".to_string(),
            payload_digest: Sha256Digest::for_bytes(WIRE),
            final_use_scope_digest: scope.clone(),
            policy_generation: 1,
            expected_predecessor_digest: None,
            dependencies: Vec::new(),
            compensation_for: None,
        }
    }

    async fn prepare_effect(
        fixture: &Fixture,
        now_ms: u64,
        intent: &AuthorizedEffectIntent,
    ) -> TaskFlowFence {
        let definition = definition();
        let fence = TaskFlowFence::new(
            fixture.identity.agent_id.clone(),
            "agentd-product-effect-owner",
            1,
            1,
            "agentd-product-effect-fence",
        )
        .expect("fence");
        fixture
            .store
            .register_taskflow_definition(&definition, &fence, now_ms)
            .await
            .expect("register definition");
        fixture
            .store
            .create_taskflow_run(
                &intent.run_id,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "thread-product-effect",
                now_ms,
            )
            .await
            .expect("create run");
        let claimed = fixture
            .store
            .claim_taskflow_run(&intent.run_id, &fence, now_ms + 1, 60_000)
            .await
            .expect("claim run");
        fixture
            .store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    &intent.run_id,
                    "agentd-product-effect-start",
                    fence.clone(),
                    claimed.revision,
                    TaskFlowTransition::Start,
                    now_ms + 2,
                )
                .expect("start command"),
            )
            .await
            .expect("start run");
        let digest = intent.digest().expect("intent digest");
        fixture
            .store
            .prepare_taskflow_step(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                &fence,
                &digest,
                &intent.payload_digest,
                "agentd-product-effect-prepare",
                now_ms + 3,
            )
            .await
            .expect("prepare step");
        fixture
            .store
            .claim_taskflow_step(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                &fence,
                &digest,
                &intent.payload_digest,
                "agentd-product-effect-claim",
                now_ms + 4,
            )
            .await
            .expect("claim step");
        fence
    }

    fn signed_final_use(
        intent: &AuthorizedEffectIntent,
        now_ms: u64,
        signing_key: &SigningKey,
    ) -> SignedFinalUseGrant {
        let binding = intent.final_use_binding().expect("final-use binding");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "automation-security-owner".to_string(),
            authority_epoch: 9,
            grant_id: "agentd-product-effect-grant".to_string(),
            nonce: digest_bytes_for_test(&Sha256Digest::for_bytes(b"agentd-product-effect-nonce")),
            binding,
            not_before_unix_ms: now_ms.saturating_sub(1_000),
            expires_at_unix_ms: now_ms + 30_000,
        };
        let signature = signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }

    fn digest_bytes_for_test(digest: &Sha256Digest) -> [u8; 32] {
        decode_hex_array::<32>(digest.as_str(), "digest").expect("digest bytes")
    }

    fn hex(bytes: &[u8]) -> String {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut output = String::with_capacity(bytes.len() * 2);
        for byte in bytes {
            output.push(char::from(HEX[usize::from(byte >> 4)]));
            output.push(char::from(HEX[usize::from(byte & 0x0f)]));
        }
        output
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn host_dispatches_exact_wire_payload_once() {
        let fixture = Fixture::new().await;
        let now_ms = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("wall clock")
                .as_millis(),
        )
        .expect("millis");
        let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
        let intent = effect_intent(&scope);
        prepare_effect(&fixture, now_ms, &intent).await;

        let server = MockServer::start().await;
        let provider_key = ProviderEffectKey::for_operation(
            "provider/fixture-v1",
            &intent.run_id,
            &intent.step_id,
        )
        .expect("provider key");
        let provider_operation = Sha256Digest::for_bytes(b"provider-operation");
        let ack = serde_json::json!({
            "effect_key": provider_key.as_str(),
            "payload_sha256": intent.payload_digest.as_str(),
            "provider_operation_id_sha256": provider_operation.as_str(),
            "status": "completed"
        });
        Mock::given(method("POST"))
            .and(path("/dispatch"))
            .and(header(
                PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER,
                provider_key.as_str(),
            ))
            .and(body_bytes(WIRE.to_vec()))
            .respond_with(ResponseTemplate::new(200).set_body_json(ack))
            .expect(1)
            .mount(&server)
            .await;

        let contract_signer = SigningKey::from_bytes(&[23_u8; 32]);
        let final_use_signer = SigningKey::from_bytes(&[29_u8; 32]);
        let unsigned_provider_config = HttpProviderEffectConfig {
            dispatch_url: format!("{}/dispatch", server.uri()),
            lookup_url_template: format!("{}/status/{{key}}", server.uri()),
            headers: HeaderMap::new(),
            timeout: Duration::from_secs(2),
            contract_id: "agentd-product-effect-contract".to_string(),
            attestation: None,
        };
        let contract_digest = unsigned_provider_config
            .contract_sha256()
            .expect("contract digest");
        let statement = HttpProviderEffectContractAttestation::statement_for(
            "agentd-product-effect-contract",
            &contract_digest,
            1,
        );
        let contract_signature = contract_signer.sign(&statement).to_bytes();
        let revocation_signer = SigningKey::from_bytes(&[31_u8; 32]);
        let revocation_update = FinalUseRevocationUpdate::new(
            "automation-revocation-distributor".to_string(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            now_ms.saturating_sub(1_000),
            now_ms + 60_000,
        );
        let signed_revocation_update = SignedFinalUseRevocationUpdate {
            signature: revocation_signer
                .sign(
                    &revocation_update
                        .signing_bytes()
                        .expect("revocation signing bytes"),
                )
                .to_bytes()
                .to_vec(),
            update: revocation_update,
        };
        let revocation_feed_file = fixture
            .identity
            .layout
            .automation_root()
            .join("effect-revocation-feed.json");
        fs::write(
            &revocation_feed_file,
            serde_json::to_vec(&signed_revocation_update).expect("signed revocation json"),
        )
        .expect("write signed revocation file");
        fs::set_permissions(&revocation_feed_file, fs::Permissions::from_mode(0o600))
            .expect("signed revocation file permissions");
        let authority_trust_root = fixture._temp.path().join("external-authority-trust");
        fs::create_dir(&authority_trust_root).expect("create external authority trust root");
        fs::set_permissions(&authority_trust_root, fs::Permissions::from_mode(0o700))
            .expect("external authority trust permissions");
        let authority_trust_root = authority_trust_root
            .canonicalize()
            .expect("canonical authority trust root");

        let host_file = fixture
            .identity
            .layout
            .automation_root()
            .join("effect-host.json");
        let host_json = serde_json::json!({
            "schema_version": 2,
            "provider_scope": "provider/fixture-v1",
            "destination_id": "provider:fixture",
            "final_use_scope_sha256": scope.as_str(),
            "dispatch_url": format!("{}/dispatch", server.uri()),
            "lookup_url_template": format!("{}/status/{{key}}", server.uri()),
            "headers": {},
            "timeout_ms": 2000,
            "contract_id": "agentd-product-effect-contract",
            "contract_sha256": contract_digest.as_str(),
            "contract_authority_epoch": 1,
            "contract_signature_hex": hex(&contract_signature),
            "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
            "final_use_signer_id": "automation-security-owner",
            "final_use_issuer_keys": [{
                "key_id": "issuer-2026-a",
                "verifying_key_hex": hex(&final_use_signer.verifying_key().to_bytes()),
                "not_before_authority_epoch": 1,
                "not_after_authority_epoch": u64::MAX
            }],
            "final_use_revocation_distributor_id": "automation-revocation-distributor",
            "final_use_revocation_keys": [{
                "key_id": "revocation-2026-a",
                "verifying_key_hex": hex(&revocation_signer.verifying_key().to_bytes()),
                "not_before_authority_epoch": 1,
                "not_after_authority_epoch": u64::MAX
            }],
            "final_use_revocation_feed_file": revocation_feed_file,
            "final_use_trust_root": authority_trust_root
        });
        fs::write(
            &host_file,
            serde_json::to_vec(&host_json).expect("host json"),
        )
        .expect("write host file");
        fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600))
            .expect("host file permissions");

        let host =
            AgentdAutomationEffectHost::open(&fixture.identity, &host_file).expect("effect host");
        let grant = signed_final_use(&intent, now_ms, &final_use_signer);
        let receipt = host
            .execute(
                &fixture.store,
                &intent,
                WIRE,
                &grant,
                "agentd-product-effect-dispatch",
                now_ms + 5,
            )
            .await
            .expect("effect dispatch");
        assert_eq!(
            receipt.observation,
            Some(TaskFlowStepObservation::Succeeded)
        );

        let replay = host
            .execute(
                &fixture.store,
                &intent,
                WIRE,
                &grant,
                "agentd-product-effect-dispatch",
                now_ms + 6,
            )
            .await
            .expect("settled replay");
        assert_eq!(replay.receipt_digest, receipt.receipt_digest);
        // A terminal read is not permission to substitute bytes or command
        // identity, even though the live lease has already been cleared.
        let mut substituted = intent.clone();
        substituted.operation_id.push_str("-substitution");
        assert!(
            host.execute(
                &fixture.store,
                &substituted,
                WIRE,
                &grant,
                "agentd-product-effect-dispatch",
                now_ms + 7
            )
            .await
            .is_err()
        );
        assert!(
            host.execute(
                &fixture.store,
                &intent,
                WIRE,
                &grant,
                "different-command",
                now_ms + 7
            )
            .await
            .is_err()
        );
        assert!(
            host.execute(
                &fixture.store,
                &intent,
                b"different-wire",
                &grant,
                "agentd-product-effect-dispatch",
                now_ms + 7
            )
            .await
            .is_err()
        );
        let witness = fixture
            .store
            .authorized_taskflow_effect_authority_witness(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
            )
            .await
            .expect("durable witness query")
            .expect("durable entry witness");
        drop(host);
        let mut newer = signed_revocation_update.clone();
        newer.update.head.revision = 2;
        newer
            .update
            .head
            .revoked_grant_ids
            .insert(grant.grant.grant_id.clone());
        let refreshed_now_ms = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("current feed time")
                .as_millis(),
        )
        .expect("feed milliseconds");
        newer.update.issued_at_unix_ms = refreshed_now_ms.saturating_sub(1_000);
        newer.update.expires_at_unix_ms = refreshed_now_ms + 60_000;
        newer.signature = revocation_signer
            .sign(
                &newer
                    .update
                    .signing_bytes()
                    .expect("updated feed signing bytes"),
            )
            .to_bytes()
            .to_vec();
        fs::write(
            &revocation_feed_file,
            serde_json::to_vec(&newer).expect("updated feed JSON"),
        )
        .expect("advance signed feed during host downtime");
        let recovered = AgentdAutomationEffectHost::open(&fixture.identity, &host_file)
            .expect("recover original frontier then apply newer signed feed");
        assert_eq!(
            recovered.authority.revocation_head().unwrap(),
            newer.update.head
        );
        assert_eq!(
            fixture
                .store
                .authorized_taskflow_effect_authority_witness(
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                )
                .await
                .expect("recovered witness query"),
            Some(witness)
        );
        let recovered_receipt = recovered
            .execute(
                &fixture.store,
                &intent,
                WIRE,
                &grant,
                "agentd-product-effect-dispatch",
                now_ms + 8,
            )
            .await
            .expect("observe original terminal outcome after recovery");
        assert_eq!(recovered_receipt.receipt_digest, receipt.receipt_digest);
        server.verify().await;
    }
}
