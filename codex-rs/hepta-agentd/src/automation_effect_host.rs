//! Host-owned composition for final-use-authorized automation effects.
//!
//! The TaskFlow owner persists intent/attempt/reconciliation state. Agentd owns
//! the selected provider contract and final-use verifier. Control callers can
//! transport a signed grant and exact provider bytes, but they cannot select a
//! provider endpoint, destination, final-use scope, subject, or TaskFlow fence.

use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectFuture;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepObservation;
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
const MAX_AUTOMATION_EFFECT_REVOCATIONS_FILE_BYTES: u64 = 4 * 1024 * 1024;
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
    revocations_file: PathBuf,
    revocation_frontier: Arc<Mutex<FinalUseRevocations>>,
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
    final_use_revocations_file: PathBuf,
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

        if !config.final_use_revocations_file.is_absolute() {
            return Err(AgentdError::Invalid(
                "final_use_revocations_file must be absolute".to_string(),
            ));
        }
        let initial_revocations = read_revocations_file(&config.final_use_revocations_file)?;
        let frontier = initial_revocations.clone();

        let authority_root = identity
            .layout
            .automation_root()
            .join("final-use-authority");
        // The authority creates its own private directory and rejects links or
        // unsafe existing permissions; do not chmod a host-supplied path first.
        let authority = FinalUseAuthority::open_state_dir(
            &authority_root,
            config.final_use_signer_id,
            final_use_verifying_key,
            initial_revocations,
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
            revocations_file: config.final_use_revocations_file,
            revocation_frontier: Arc::new(Mutex::new(frontier)),
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
            .execute_authorized_taskflow_effect_async(
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
        if pending.destination_id != self.destination_id || pending.owner_agent_id != self.agent_id
        {
            return Err(AgentdError::GenerationFenced(
                "pending effect owner/destination differs from the configured host".to_string(),
            ));
        }
        let run = store
            .taskflow_run(run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        let fence = self.historical_fence(&run)?;
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
        let head = read_revocations_file(&self.revocations_file)?;
        let mut frontier = self.revocation_frontier.lock().map_err(|_| {
            AgentdError::Protocol(
                "automation effect revocation frontier lock is poisoned".to_string(),
            )
        })?;
        let observed = (head.authority_epoch, head.revision);
        let current = (frontier.authority_epoch, frontier.revision);
        if observed == current {
            if head != *frontier {
                return Err(AgentdError::GenerationFenced(
                    "automation effect revocation head changed without advancing revision"
                        .to_string(),
                ));
            }
            return Ok(());
        }
        if observed.0 < current.0 || (observed.0 == current.0 && observed.1 < current.1) {
            return Err(AgentdError::GenerationFenced(
                "automation effect revocation frontier rolled back".to_string(),
            ));
        }
        self.authority
            .update_revocations(head.clone())
            .map_err(|error| {
                AgentdError::GenerationFenced(format!(
                    "automation effect revocation refresh rejected: {error}"
                ))
            })?;
        *frontier = head;
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
        if run
            .lease_expires_at_ms
            .is_none_or(|expires_at| expires_at <= now_ms)
        {
            return Err(AgentdError::Protocol(
                "TaskFlow owner lease is not current".to_string(),
            ));
        }
        self.historical_fence(run)
    }

    // Observation of a started effect uses its complete historical owner
    // identity. An expired lease prevents dispatch, not read-only lookup and
    // settlement; uncertainty must never require reclaiming or sending again.
    fn historical_fence(
        &self,
        run: &codex_hepta_automation::TaskFlowRun,
    ) -> Result<TaskFlowFence, AgentdError> {
        if run.owner_agent_id != self.agent_id {
            return Err(AgentdError::GenerationFenced(
                "TaskFlow run is owned by a different Agent".to_string(),
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
        let occurrence = match pending.provider_key_version {
            1 => pending.run_id.clone(),
            2 => format!("{}:{}", pending.owner_agent_id, pending.run_id),
            _ => {
                return Err(AgentdError::Invalid(
                    "unsupported provider key version".to_string(),
                ));
            }
        };
        let key =
            ProviderEffectKey::for_operation(&self.provider_scope, &occurrence, &pending.step_id)
                .map_err(|error| {
                AgentdError::Invalid(format!("derive provider effect key: {error:?}"))
            })?;
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

impl AsyncAuthorizedEffectDriver for HttpAuthorizedEffectDriver {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            if request.intent.destination_id != self.destination_id {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            // The host's attested provider scope is a different contract from
            // the generic bridge's destination scope; both isolate the Agent.
            let key = ProviderEffectKey::for_operation(
                &self.provider_scope,
                &format!("{}:{}", request.owner_agent_id, request.intent.run_id),
                &request.intent.step_id,
            )
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            let provider_intent =
                ProviderEffectIntent::new(key, request.intent.payload_digest.clone());
            let dispatch = self
                .adapter
                .dispatch_with_payload(&provider_intent, request.wire_payload)
                .await;
            match dispatch {
                ProviderEffectDispatch::NotDispatched { .. } => {
                    Err(AuthorizedEffectDriverError::BeforeProviderContact)
                }
                dispatch => Ok(receipt_from_dispatch(&dispatch)),
            }
        })
    }
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

fn read_host_file(path: &Path) -> Result<AutomationEffectHostFileV1, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES,
        "automation effect host file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn read_revocations_file(path: &Path) -> Result<FinalUseRevocations, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_REVOCATIONS_FILE_BYTES,
        "automation effect revocations file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
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
    let mut file = fs::File::open(path)?;
    let opened = file.metadata()?;
    #[cfg(unix)]
    let unchanged = |other: &fs::Metadata| {
        use std::os::unix::fs::MetadataExt;
        other.dev() == metadata.dev()
            && other.ino() == metadata.ino()
            && other.len() == metadata.len()
            && other.mtime() == metadata.mtime()
            && other.mtime_nsec() == metadata.mtime_nsec()
            && other.ctime() == metadata.ctime()
            && other.ctime_nsec() == metadata.ctime_nsec()
    };
    #[cfg(not(unix))]
    let unchanged = |other: &fs::Metadata| {
        other.len() == metadata.len() && other.modified().ok() == metadata.modified().ok()
    };
    if !unchanged(&opened) {
        return Err(AgentdError::Invalid(format!(
            "{label} changed while opening"
        )));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(max_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = fs::symlink_metadata(path)?;
    if bytes.is_empty()
        || u64::try_from(bytes.len()).unwrap_or(u64::MAX) > max_bytes
        || !after.is_file()
        || !unchanged(&after)
        || !unchanged(&file.metadata()?)
    {
        return Err(AgentdError::Invalid(format!(
            "{label} changed while reading"
        )));
    }
    Ok(bytes)
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
    use codex_hepta_automation::TaskFlowReconcileOutcome;
    use codex_hepta_automation::TaskFlowStepObservation;
    use codex_hepta_automation::TaskFlowTransition;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::ProviderEffectKey;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use codex_hepta_fleet::AgentLifecycle;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;

    use super::*;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52";
    const WIRE: &[u8] = b"{\"effect\":\"deliver\"}";

    struct Fixture {
        _temp: tempfile::TempDir,
        registry: FleetRegistry,
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
                registry,
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

    #[tokio::test]
    async fn host_dispatches_exact_wire_payload_once() {
        let mut fixture = Fixture::new().await;
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

        // Serve on this same current-thread executor: a synchronous join in
        // the dispatch path would starve the socket and turn success unknown.
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("listen");
        let server_uri = format!("http://{}", listener.local_addr().expect("listen address"));
        let provider_key = ProviderEffectKey::for_operation(
            "provider/fixture-v1",
            &format!("{AGENT_ID}:{}", intent.run_id),
            &intent.step_id,
        )
        .expect("provider key");
        let provider_operation = Sha256Digest::for_bytes(b"provider-operation");
        let mut ack = serde_json::json!({
            "effect_key": provider_key.as_str(),
            "payload_sha256": intent.payload_digest.as_str(),
            "provider_operation_id_sha256": provider_operation.as_str(),
            "status": "accepted"
        });
        let expected_provider_key = provider_key.clone();
        let server_task = tokio::spawn(async move {
            for dispatch in [true, false] {
                let (mut stream, _) = listener.accept().await.expect("provider connection");
                let mut request = Vec::new();
                let body_start = loop {
                    let read = stream.read_buf(&mut request).await.expect("request bytes");
                    assert!(read > 0 && request.len() < 4096);
                    if let Some(start) = request.windows(4).position(|bytes| bytes == b"\r\n\r\n")
                        && request.len() >= start + 4 + if dispatch { WIRE.len() } else { 0 }
                    {
                        break start + 4;
                    }
                };
                let headers = std::str::from_utf8(&request[..body_start]).expect("request headers");
                assert!(headers.starts_with(if dispatch {
                    "POST /dispatch HTTP/1.1\r\n"
                } else {
                    "GET /status/"
                }));
                assert!(headers.contains(&format!(
                    "{PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER}: {}\r\n",
                    provider_key.as_str()
                )));
                assert_eq!(&request[body_start..], if dispatch { WIRE } else { b"" });
                ack["status"] = serde_json::json!(if dispatch { "accepted" } else { "completed" });
                let body = serde_json::to_vec(&ack).expect("ack bytes");
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                stream
                    .write_all(response.as_bytes())
                    .await
                    .expect("response headers");
                stream.write_all(&body).await.expect("response body");
            }
        });

        let contract_signer = SigningKey::from_bytes(&[23_u8; 32]);
        let final_use_signer = SigningKey::from_bytes(&[29_u8; 32]);
        let unsigned_provider_config = HttpProviderEffectConfig {
            dispatch_url: format!("{server_uri}/dispatch"),
            lookup_url_template: format!("{server_uri}/status/{{key}}"),
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
        let revocations_file = fixture
            .identity
            .layout
            .automation_root()
            .join("effect-revocations.json");
        fs::write(
            &revocations_file,
            serde_json::to_vec(&FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            })
            .expect("revocations json"),
        )
        .expect("write revocations file");
        fs::set_permissions(&revocations_file, fs::Permissions::from_mode(0o600))
            .expect("revocations file permissions");

        let host_file = fixture
            .identity
            .layout
            .automation_root()
            .join("effect-host.json");
        let host_json = serde_json::json!({
            "schema_version": 1,
            "provider_scope": "provider/fixture-v1",
            "destination_id": "provider:fixture",
            "final_use_scope_sha256": scope.as_str(),
            "dispatch_url": format!("{server_uri}/dispatch"),
            "lookup_url_template": format!("{server_uri}/status/{{key}}"),
            "headers": {},
            "timeout_ms": 2000,
            "contract_id": "agentd-product-effect-contract",
            "contract_sha256": contract_digest.as_str(),
            "contract_authority_epoch": 1,
            "contract_signature_hex": hex(&contract_signature),
            "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
            "final_use_signer_id": "automation-security-owner",
            "final_use_verifying_key_hex": hex(&final_use_signer.verifying_key().to_bytes()),
            "final_use_revocations_file": revocations_file
        });
        fs::write(
            &host_file,
            serde_json::to_vec(&host_json).expect("host json"),
        )
        .expect("write host file");
        fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600))
            .expect("host file permissions");

        let authority_root = fixture
            .identity
            .layout
            .automation_root()
            .join("final-use-authority");
        let linked_root = fixture
            .identity
            .layout
            .automation_root()
            .join("linked-authority");
        fs::create_dir(&linked_root).expect("linked authority directory");
        fs::set_permissions(&linked_root, fs::Permissions::from_mode(0o755))
            .expect("directory mode");
        std::os::unix::fs::symlink(&linked_root, &authority_root).expect("authority symlink");
        assert!(AgentdAutomationEffectHost::open(&fixture.identity, &host_file).is_err());
        assert_eq!(
            fs::metadata(&linked_root)
                .expect("directory metadata")
                .permissions()
                .mode()
                & 0o777,
            0o755
        );
        fs::remove_file(&authority_root).expect("remove authority symlink");

        let host =
            AgentdAutomationEffectHost::open(&fixture.identity, &host_file).expect("effect host");
        let grant = signed_final_use(&intent, now_ms, &final_use_signer);
        let initial = host
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
            initial.observation,
            Some(TaskFlowStepObservation::Indeterminate)
        );
        fixture.store.close().await;
        fixture.store = AutomationStore::open(&fixture.identity.layout)
            .await
            .expect("reopen effect owner");
        drop(host);
        let host = AgentdAutomationEffectHost::open(&fixture.identity, &host_file)
            .expect("reopen effect host");
        let expired_at = now_ms + 60_002;
        let run = fixture
            .store
            .taskflow_run(&intent.run_id)
            .await
            .expect("effect run")
            .expect("run");
        assert!(host.current_fence(&run, expired_at).is_err());
        let AgentdAutomationEffectReconcileOutcome::Observed(receipt) = host
            .reconcile(
                &fixture.store,
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                expired_at,
            )
            .await
            .expect("historical recovery after expiry and reopen")
        else {
            panic!("terminal provider observation expected")
        };
        assert_eq!(
            receipt.final_outcome,
            Some(TaskFlowReconcileOutcome::Succeeded)
        );
        let mut pending = fixture
            .store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .expect("durable provider identity")
            .expect("effect attempt");
        assert_eq!(
            host.provider_intent(&pending).expect("provider intent").key,
            expected_provider_key
        );
        pending.owner_agent_id =
            codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c53")
                .expect("different agent");
        assert_ne!(
            host.provider_intent(&pending)
                .expect("other tenant key")
                .key,
            expected_provider_key
        );
        pending.provider_key_version = 1;
        assert_eq!(
            host.provider_intent(&pending)
                .expect("historical lookup key")
                .key,
            ProviderEffectKey::for_operation(
                "provider/fixture-v1",
                &intent.run_id,
                &intent.step_id
            )
            .expect("legacy provider key")
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
        // Reusing a frontier with different content is a stale trusted head,
        // including when the command would otherwise return a terminal replay.
        let mut changed_head = host.authority.revocation_head().expect("revocation head");
        changed_head
            .revoked_grant_ids
            .insert(grant.grant.grant_id.clone());
        fs::write(
            &revocations_file,
            serde_json::to_vec(&changed_head).expect("changed head"),
        )
        .expect("replace revocation head");
        assert!(matches!(
            host.refresh_revocations(),
            Err(AgentdError::GenerationFenced(_))
        ));
        changed_head.revision += 1;
        fs::write(
            &revocations_file,
            serde_json::to_vec(&changed_head).expect("advanced head"),
        )
        .expect("advance revocation head");
        host.refresh_revocations()
            .expect("monotonic revocation update");
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
        server_task.await.expect("provider server");

        // Unpublishing the scheduler keeps exact-attempt reconciliation live,
        // while another physical dispatch still requires the live attachment.
        fixture
            .registry
            .compare_and_transition(&fixture.identity.agent_id, 0, AgentLifecycle::Starting)
            .expect("start Agent");
        let state =
            crate::AgentdState::new(fixture.identity.clone(), fixture.registry.clone(), 128)
                .expect("Agent state");
        let cognitive =
            codex_hepta_cognitive_store::DurableCognitiveStore::open(&fixture.identity.layout)
                .await
                .expect("cognitive owner");
        state
            .attach_cognitive_store(Arc::new(cognitive))
            .expect("cognitive attachment");
        state
            .mark_runtime_prerequisites_ready()
            .expect("runtime prerequisites");
        fixture
            .registry
            .compare_and_transition(&fixture.identity.agent_id, 1, AgentLifecycle::Running)
            .expect("running Agent");
        state.refresh_generation().expect("current generation");
        state.mark_app_server_ready().expect("App Server ready");
        state
            .attach_automation_store(fixture.store.clone())
            .expect("automation attachment");
        state
            .attach_automation_effect_host(Arc::new(host))
            .expect("effect host attachment");
        state
            .mark_automation_unavailable()
            .expect("unpublish scheduler");
        let recovered = state
            .response(
                20,
                1,
                crate::AgentdMethod::AutomationReconcileEffect {
                    run_id: intent.run_id.clone(),
                    step_id: intent.step_id.clone(),
                    attempt: intent.attempt,
                },
            )
            .await
            .expect("durable terminal recovery with scheduler detached");
        assert_eq!(
            recovered.payload,
            crate::AgentdPayload::AutomationEffectReconcile(
                crate::AutomationEffectReconcileSnapshot {
                    state: crate::AutomationEffectReconcileState::Terminal,
                    effect: Some(crate::AutomationEffectSnapshot {
                        run_id: receipt.run_id,
                        step_id: receipt.step_id,
                        attempt: receipt.attempt,
                        event_seq: receipt.event_seq,
                        receipt_digest: receipt.receipt_digest,
                        observation: crate::AutomationEffectObservation::Succeeded,
                    }),
                }
            )
        );
        let denied = state
            .response(
                21,
                1,
                crate::AgentdMethod::AutomationExecuteEffect {
                    intent,
                    wire_payload_hex: hex(WIRE),
                    signed_grant: grant,
                    command_id: "retired-execution".to_string(),
                },
            )
            .await
            .expect("typed unavailable dispatch");
        assert!(
            matches!(denied.payload, crate::AgentdPayload::Error { code, .. } if code == "automation_unavailable")
        );
    }
}
