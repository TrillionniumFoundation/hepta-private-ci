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
use std::time::Duration;

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProviderEffectTaskFlowDriver;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
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
    revocation_frontier: Arc<Mutex<(u64, u64)>>,
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
        let frontier = (
            initial_revocations.authority_epoch,
            initial_revocations.revision,
        );

        let authority_root = identity
            .layout
            .automation_root()
            .join("final-use-authority");
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
        let mut driver =
            ProviderEffectTaskFlowDriver::new(self.destination_id.clone(), self.adapter.clone())
                .map_err(|error| {
                    AgentdError::Protocol(format!(
                        "configure automation provider-effect bridge: {error}"
                    ))
                })?;
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

        let driver =
            ProviderEffectTaskFlowDriver::new(self.destination_id.clone(), self.adapter.clone())
                .map_err(|error| {
                    AgentdError::Protocol(format!(
                        "configure automation provider-effect lookup bridge: {error}"
                    ))
                })?;
        match driver.lookup(&pending).await {
            AuthorizedProviderEffectLookup::Observed(receipt) => {
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
                        "terminal provider observation cannot become proven absent".to_string(),
                    )),
                }
            }
            AuthorizedProviderEffectLookup::ProvenAbsent { proof_digest } => {
                match store
                    .recover_authorized_taskflow_effect(
                        run_id,
                        step_id,
                        attempt,
                        &fence,
                        AuthorizedEffectRecovery::ProvenAbsent { proof_digest },
                        now_ms,
                    )
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!(
                            "reconcile authorized effect proven absence: {error}"
                        ))
                    })? {
                    AuthorizedEffectRecoveryResult::ProvenAbsent => {
                        Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent)
                    }
                    AuthorizedEffectRecoveryResult::Observed(_) => Err(AgentdError::Protocol(
                        "provider absence proof cannot manufacture terminal effect".to_string(),
                    )),
                }
            }
            AuthorizedProviderEffectLookup::Unresolved => {
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
        if observed == *frontier {
            return Ok(());
        }
        if observed.0 < frontier.0 || (observed.0 == frontier.0 && observed.1 < frontier.1) {
            return Err(AgentdError::GenerationFenced(
                "automation effect revocation frontier rolled back".to_string(),
            ));
        }
        self.authority.update_revocations(head).map_err(|error| {
            AgentdError::GenerationFenced(format!(
                "automation effect revocation refresh rejected: {error}"
            ))
        })?;
        *frontier = observed;
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
    use codex_hepta_contracts::ProviderEffectKey;
    use codex_hepta_contracts::SignedFinalUseGrant;
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
        let logical_effect_id = format!("taskflow:{}:{}", intent.run_id, intent.step_id);
        let provider_key =
            ProviderEffectKey::for_logical_effect(&intent.destination_id, &logical_effect_id)
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
        server.verify().await;
    }
}
