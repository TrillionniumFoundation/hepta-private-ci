//! Host-owned composition for final-use-authorized automation effects.
//!
//! The TaskFlow owner persists intent/attempt/reconciliation state. Agentd owns
//! the selected provider contract and final-use verifier. Control callers can
//! transport a signed grant and exact provider bytes, but they cannot select a
//! provider endpoint, destination, final-use scope, subject, or TaskFlow fence.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::sync::Arc;
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
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_model_provider::HttpProviderEffectAdapter;
use codex_model_provider::HttpProviderEffectConfig;
use codex_model_provider::HttpProviderEffectContractAttestation;
use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;

const AUTOMATION_EFFECT_HOST_SCHEMA_VERSION: u32 = 1;
const MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES: u64 = 64 * 1024;
const MAX_AUTOMATION_EFFECT_WIRE_BYTES: usize = 32 * 1024;
const MAX_PROVIDER_HEADERS: usize = 64;

#[derive(Clone)]
pub(crate) struct AgentdAutomationEffectHost {
    agent_id: codex_hepta_contracts::AgentId,
    provider_scope: String,
    destination_id: String,
    final_use_scope_digest: Sha256Digest,
    authority: FinalUseAuthority,
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

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AutomationEffectHostFileV1 {
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
    final_use_verifying_key_hex: String,
    final_use_revocations: FinalUseRevocations,
}

impl AgentdAutomationEffectHost {
    pub(crate) fn open(
        identity: &AgentdIdentity,
        path: &Path,
    ) -> Result<Self, AgentdError> {
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

        let final_use_scope_digest =
            Sha256Digest::parse(config.final_use_scope_sha256.clone())
                .map_err(AgentdError::Invalid)?;
        let declared_contract_digest = Sha256Digest::parse(config.contract_sha256.clone())
            .map_err(AgentdError::Invalid)?;
        let contract_signature = decode_hex_array::<64>(
            &config.contract_signature_hex,
            "contract_signature_hex",
        )?;
        let contract_verifying_key = decode_hex_array::<32>(
            &config.contract_verifying_key_hex,
            "contract_verifying_key_hex",
        )?;
        let final_use_verifying_key = decode_hex_array::<32>(
            &config.final_use_verifying_key_hex,
            "final_use_verifying_key_hex",
        )?;

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

        let authority_root = identity.layout.automation_root().join("final-use-authority");
        fs::create_dir_all(&authority_root)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&authority_root, fs::Permissions::from_mode(0o700))?;
        }
        let authority = FinalUseAuthority::open_state_dir(
            &authority_root,
            config.final_use_signer_id,
            final_use_verifying_key,
            config.final_use_revocations,
        )
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "open automation final-use authority state: {error}"
            ))
        })?;

        Ok(Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: config.provider_scope,
            destination_id: config.destination_id,
            final_use_scope_digest,
            authority,
            adapter,
        })
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
        let run = store
            .taskflow_run(&intent.run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| AgentdError::Invalid("effect TaskFlow run does not exist".to_string()))?;
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
    ) -> Result<Option<TaskFlowStepReceipt>, AgentdError> {
        let pending = store
            .authorized_taskflow_effect_pending(run_id, step_id, attempt)
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
            .ok_or_else(|| AgentdError::Invalid("effect TaskFlow run does not exist".to_string()))?;
        let fence = self.current_fence(&run, now_ms)?;
        let provider_intent = self.provider_intent(&pending)?;
        match self.adapter.lookup_for_intent(&provider_intent).await {
            ProviderEffectLookup::Ack(ack) => {
                let Some(receipt) = terminal_receipt_from_ack(&ack) else {
                    return Ok(None);
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
                    })?
                {
                    AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(Some(receipt)),
                    AuthorizedEffectRecoveryResult::ProvenAbsent => Err(AgentdError::Protocol(
                        "status lookup cannot manufacture provider absence".to_string(),
                    )),
                }
            }
            ProviderEffectLookup::Conflict { .. } => Err(AgentdError::Protocol(
                "provider reports a same-key payload conflict".to_string(),
            )),
            ProviderEffectLookup::NotFound | ProviderEffectLookup::Unknown => Ok(None),
        }
    }

    fn validate_intent(
        &self,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
    ) -> Result<(), AgentdError> {
        if wire_payload.is_empty() || wire_payload.len() > MAX_AUTOMATION_EFFECT_WIRE_BYTES {
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
        if run.lease_expires_at_ms.is_none_or(|expires_at| expires_at <= now_ms) {
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
        Ok(ProviderEffectIntent::new(key, pending.payload_digest.clone()))
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
                ProviderThreadOutcome::Dispatch(runtime.block_on(
                    adapter.dispatch_with_payload(&provider_intent, &wire_payload),
                ))
            })
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        match spawn.join() {
            Ok(ProviderThreadOutcome::BeforeContact) => {
                Err(AuthorizedEffectDriverError::BeforeProviderContact)
            }
            Ok(ProviderThreadOutcome::Dispatch(ProviderEffectDispatch::NotDispatched {
                ..
            })) => Err(AuthorizedEffectDriverError::BeforeProviderContact),
            Ok(ProviderThreadOutcome::Dispatch(dispatch)) => {
                Ok(receipt_from_dispatch(&dispatch))
            }
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

fn serialized_observation_digest(
    domain: &[u8],
    value: &impl serde::Serialize,
) -> Sha256Digest {
    let mut bytes = domain.to_vec();
    if let Ok(encoded) = serde_json::to_vec(value) {
        bytes.extend_from_slice(&encoded);
    } else {
        bytes.extend_from_slice(b"serialization-unavailable");
    }
    Sha256Digest::for_bytes(&bytes)
}

fn read_host_file(path: &Path) -> Result<AutomationEffectHostFileV1, AgentdError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Invalid(
            "automation effect host file must be a regular non-symlink file".to_string(),
        ));
    }
    if metadata.len() == 0 || metadata.len() > MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES {
        return Err(AgentdError::Invalid(
            "automation effect host file is empty or too large".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(
                "automation effect host file must not be group/world accessible".to_string(),
            ));
        }
    }
    let bytes = fs::read(path)?;
    Ok(serde_json::from_slice(&bytes)?)
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

fn decode_hex_array<const N: usize>(
    value: &str,
    label: &str,
) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 {
        return Err(AgentdError::Invalid(format!(
            "{label} must contain exactly {} hex characters",
            N * 2
        )));
    }
    let mut output = [0_u8; N];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = hex_nibble(pair[0]).ok_or_else(|| {
            AgentdError::Invalid(format!("{label} contains non-hex data"))
        })?;
        let low = hex_nibble(pair[1]).ok_or_else(|| {
            AgentdError::Invalid(format!("{label} contains non-hex data"))
        })?;
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
