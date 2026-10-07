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
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use std::time::Instant;

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
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
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
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

use crate::AgentdError;
use crate::AgentdIdentity;

#[path = "automation_effect_host_pon_process.rs"]
mod pon_process;

#[cfg(all(test, unix))]
#[path = "automation_effect_host_pon_tests.rs"]
mod pon_lifecycle_tests;

const AUTOMATION_EFFECT_HOST_SCHEMA_VERSION: u32 = 1;
const MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES: u64 = 64 * 1024;
const MAX_AUTOMATION_EFFECT_REVOCATIONS_FILE_BYTES: u64 = 4 * 1024 * 1024;
const MAX_PROVIDER_HEADERS: usize = 64;
const AUTOMATION_EFFECT_HOST_PON_SCHEMA_VERSION: u32 = 2;
const PON_PROVIDER_KIND: &str = "trillionnium-pon-local-v1";
const MAX_PON_BINARY_BYTES: u64 = 256 * 1024 * 1024;
const MAX_PON_PROCESS_OUTPUT_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AutomationEffectHostFileV2 {
    schema_version: u32,
    provider_kind: String,
    provider_scope: String,
    destination_id: String,
    final_use_scope_sha256: String,
    chain_binary: PathBuf,
    chain_binary_sha256: String,
    chain_store: PathBuf,
    chain_state_backend: String,
    chain_genesis_time: u64,
    chain_evaluation_policy: String,
    chain_task_profile: String,
    chain_model_profile: String,
    chain_workers: u64,
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

enum AutomationEffectHostFile {
    Http(AutomationEffectHostFileV1),
    Pon(AutomationEffectHostFileV2),
}

#[derive(Clone)]
enum AgentdProviderEffectAdapter {
    Http(HttpProviderEffectAdapter),
    Pon(PonLocalProviderEffectAdapter),
}

impl std::fmt::Debug for AgentdProviderEffectAdapter {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Http(adapter) => formatter.debug_tuple("Http").field(adapter).finish(),
            Self::Pon(adapter) => formatter.debug_tuple("Pon").field(adapter).finish(),
        }
    }
}

impl ProviderEffectAdapter for AgentdProviderEffectAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        match self {
            Self::Http(adapter) => adapter.capability(),
            Self::Pon(adapter) => adapter.capability(),
        }
    }

    fn dispatch<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        match self {
            Self::Http(adapter) => adapter.dispatch(intent),
            Self::Pon(adapter) => adapter.dispatch(intent),
        }
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire_payload: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        match self {
            Self::Http(adapter) => adapter.dispatch_with_payload(intent, wire_payload),
            Self::Pon(adapter) => adapter.dispatch_with_payload(intent, wire_payload),
        }
    }

    fn lookup<'a>(
        &'a self,
        key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        match self {
            Self::Http(adapter) => adapter.lookup(key),
            Self::Pon(adapter) => adapter.lookup(key),
        }
    }

    fn lookup_for_intent<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        match self {
            Self::Http(adapter) => adapter.lookup_for_intent(intent),
            Self::Pon(adapter) => adapter.lookup_for_intent(intent),
        }
    }

    fn lookup_for_reconciliation<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire_payload: Option<&'a [u8]>,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        match self {
            Self::Http(adapter) => adapter.lookup_for_reconciliation(intent, wire_payload),
            Self::Pon(adapter) => adapter.lookup_for_reconciliation(intent, wire_payload),
        }
    }
}

#[derive(Clone)]
struct PonLocalProviderEffectAdapter {
    binary: PathBuf,
    binary_sha256: Sha256Digest,
    store: PathBuf,
    state_backend: String,
    genesis_time: u64,
    evaluation_policy: String,
    task_profile: String,
    model_profile: String,
    workers: u64,
    timeout: Duration,
}

impl std::fmt::Debug for PonLocalProviderEffectAdapter {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("PonLocalProviderEffectAdapter")
            .field("binary", &self.binary)
            .field("binary_sha256", &self.binary_sha256)
            .field("store", &self.store)
            .field("state_backend", &self.state_backend)
            .field("genesis_time", &self.genesis_time)
            .field("evaluation_policy", &self.evaluation_policy)
            .field("task_profile", &self.task_profile)
            .field("model_profile", &self.model_profile)
            .field("workers", &self.workers)
            .field("timeout", &self.timeout)
            .finish()
    }
}

enum PonInvocation {
    BeforeStart,
    Unknown,
    Value(Value),
}

impl PonLocalProviderEffectAdapter {
    fn block_digest(value: &Value) -> Option<Sha256Digest> {
        let block = value
            .get("result")?
            .get("block")?
            .as_str()?;
        if block.len() != 64
            || !block
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return None;
        }
        let mut binding = b"trillionnium.pon.block.v1\0".to_vec();
        binding.extend_from_slice(block.as_bytes());
        Some(Sha256Digest::for_bytes(&binding))
    }

    fn validate_paths(&self) -> Result<(), ()> {
        verify_pinned_binary(&self.binary, &self.binary_sha256).map_err(|_| ())?;
        let canonical_store = self.store.canonicalize().map_err(|_| ())?;
        if canonical_store != self.store || !canonical_store.is_dir() {
            return Err(());
        }
        let database = self.store.join("native.sqlite");
        let metadata = fs::symlink_metadata(&database).map_err(|_| ())?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(());
        }
        Ok(())
    }

    fn command(&self, operation: &str) -> Command {
        let mut command = Command::new(&self.binary);
        command
            .arg(operation)
            .arg("--development")
            .arg("--store")
            .arg(&self.store)
            .arg("--state-backend")
            .arg(&self.state_backend)
            .arg("--genesis-time")
            .arg(self.genesis_time.to_string())
            .arg("--evaluation-policy")
            .arg(&self.evaluation_policy)
            .arg("--task-profile")
            .arg(&self.task_profile)
            .arg("--model-profile")
            .arg(&self.model_profile)
            .arg("--workers")
            .arg(self.workers.to_string())
            .arg("--packet-stdin")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        command
    }

    fn invoke(&self, operation: &str, wire_payload: &[u8]) -> PonInvocation {
        let Some(deadline) = Instant::now().checked_add(self.timeout) else {
            return PonInvocation::BeforeStart;
        };
        if wire_payload.len() > 1024 * 1024 || self.validate_paths().is_err() {
            return PonInvocation::BeforeStart;
        }
        let Ok(runtime) = tokio::runtime::Handle::try_current() else {
            return PonInvocation::BeforeStart;
        };
        // Provider methods enter here via their existing spawn_blocking scope.
        // Hash/path verification is not preemptible, but no child may start if
        // it consumed the original deadline. The entire pipe exchange uses the
        // same deadline; stdout and stderr limits are equally authoritative.
        match runtime.block_on(pon_process::run(
            self.command(operation),
            wire_payload,
            deadline,
            MAX_PON_PROCESS_OUTPUT_BYTES,
        )) {
            pon_process::Outcome::BeforeStart => PonInvocation::BeforeStart,
            pon_process::Outcome::Unknown => PonInvocation::Unknown,
            pon_process::Outcome::Complete(stdout) => match serde_json::from_slice(&stdout) {
                Ok(value) => PonInvocation::Value(value),
                Err(_) => PonInvocation::Unknown,
            },
        }
    }

    fn dispatch_blocking(
        &self,
        intent: ProviderEffectIntent,
        wire_payload: Vec<u8>,
    ) -> ProviderEffectDispatch {
        if Sha256Digest::for_bytes(&wire_payload) != intent.payload_sha256 {
            return ProviderEffectDispatch::NotDispatched {
                reason_code: "pon_packet_payload_binding_invalid".to_string(),
            };
        }
        match self.invoke("submit", &wire_payload) {
            PonInvocation::BeforeStart => ProviderEffectDispatch::NotDispatched {
                reason_code: "pon_local_owner_unavailable_before_start".to_string(),
            },
            PonInvocation::Unknown => ProviderEffectDispatch::Unknown,
            PonInvocation::Value(value) => {
                let Some(operation) = Self::block_digest(&value) else {
                    return ProviderEffectDispatch::Unknown;
                };
                ProviderEffectDispatch::Ack(ProviderEffectAck::new(
                    intent.key,
                    intent.payload_sha256,
                    operation,
                    ProviderEffectAckStatus::Completed,
                ))
            }
        }
    }

    fn observe_blocking(
        &self,
        intent: ProviderEffectIntent,
        wire_payload: Vec<u8>,
    ) -> Option<crate::AutomationEffectChainObservation> {
        if Sha256Digest::for_bytes(&wire_payload) != intent.payload_sha256 {
            return None;
        }
        let PonInvocation::Value(value) = self.invoke("packet-status", &wire_payload) else {
            return None;
        };
        parse_pon_chain_observation(&value)
    }

    fn lookup_blocking(
        &self,
        intent: ProviderEffectIntent,
        wire_payload: Vec<u8>,
    ) -> ProviderEffectLookup {
        if Sha256Digest::for_bytes(&wire_payload) != intent.payload_sha256 {
            return ProviderEffectLookup::Conflict {
                observed_payload_sha256: Some(Sha256Digest::for_bytes(&wire_payload)),
            };
        }
        let PonInvocation::Value(value) = self.invoke("packet-status", &wire_payload) else {
            return ProviderEffectLookup::Unknown;
        };
        let Some(observation) = parse_pon_chain_observation(&value) else {
            return ProviderEffectLookup::Unknown;
        };
        if !observation.stored_exact {
            // Local absence cannot prove NotDispatched on another peer and must
            // never authorize a second physical send.
            return ProviderEffectLookup::Unknown;
        }
        let Some(operation) = Self::block_digest(&value) else {
            return ProviderEffectLookup::Unknown;
        };
        ProviderEffectLookup::Ack(ProviderEffectAck::new(
            intent.key,
            intent.payload_sha256,
            operation,
            ProviderEffectAckStatus::Completed,
        ))
    }
}

impl AgentdProviderEffectAdapter {
    async fn current_chain_observation(
        &self,
        intent: &ProviderEffectIntent,
        wire_payload: Option<&[u8]>,
    ) -> Option<crate::AutomationEffectChainObservation> {
        let Self::Pon(adapter) = self else {
            return None;
        };
        let wire_payload = wire_payload?.to_vec();
        let adapter = adapter.clone();
        let intent = intent.clone();
        tokio::task::spawn_blocking(move || adapter.observe_blocking(intent, wire_payload))
            .await
            .ok()
            .flatten()
    }
}

fn lower_hex_32(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn parse_pon_chain_observation(value: &Value) -> Option<crate::AutomationEffectChainObservation> {
    let result = value.get("result")?;
    if result.get("schema")?.as_str()? != "pon-native-exact-packet-observation-v2"
        || result.get("local_target_only")?.as_bool()? != true
        || result.get("global_absence_authority")?.as_bool()? != false
        || result.get("confirmation_authority")?.as_bool()? != false
        || result.get("finality_authority")?.as_bool()? != false
        || result.get("execution_authority")?.as_bool()? != false
        || result.get("production_activation")?.as_bool()? != false
    {
        return None;
    }
    let block_id = result.get("block")?.as_str()?.to_string();
    let active_tip = result.get("active_tip")?.as_str()?.to_string();
    if !lower_hex_32(&block_id) || !lower_hex_32(&active_tip) {
        return None;
    }
    let stored_exact = result.get("stored_exact")?.as_bool()?;
    let active_chain_member = result.get("active_chain_member")?.as_bool()?;
    let block_height = match result.get("block_height")? {
        Value::Null => None,
        value => Some(value.as_u64()?),
    };
    let active_depth = match result.get("active_depth")? {
        Value::Null => None,
        value => Some(value.as_u64()?),
    };
    let active_tip_height = result.get("active_tip_height")?.as_u64()?;
    let owner_generation = result.get("generation")?.as_u64()?;
    if owner_generation == 0
        || (!stored_exact
            && (block_height.is_some() || active_chain_member || active_depth.is_some()))
        || (stored_exact && block_height.is_none())
        || (active_chain_member != active_depth.is_some())
        || block_height.is_some_and(|height| height > active_tip_height && active_chain_member)
    {
        return None;
    }
    let expected_depth = if active_chain_member {
        active_tip_height.checked_sub(block_height?)
    } else {
        None
    };
    if active_depth != expected_depth
        || (block_id == active_tip && !active_chain_member)
        || (active_chain_member
            && ((block_id == active_tip) != (block_height == Some(active_tip_height))))
    {
        return None;
    }
    Some(crate::AutomationEffectChainObservation {
        schema_version: 1,
        block_id,
        stored_exact,
        block_height,
        active_tip,
        active_tip_height,
        active_chain_member,
        active_depth,
        owner_generation,
        local_target_only: true,
        global_absence_authority: false,
        confirmation_authority: false,
        finality_authority: false,
        execution_authority: false,
    })
}

impl ProviderEffectAdapter for PonLocalProviderEffectAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "pon_exact_packet_bytes_required".to_string(),
            }
        })
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire_payload: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        if wire_payload.len() > 1024 * 1024 {
            return Box::pin(async {
                ProviderEffectDispatch::NotDispatched {
                    reason_code: "pon_exact_packet_too_large".to_string(),
                }
            });
        }
        let adapter = self.clone();
        let intent = intent.clone();
        let wire_payload = wire_payload.to_vec();
        Box::pin(async move {
            tokio::task::spawn_blocking(move || adapter.dispatch_blocking(intent, wire_payload))
                .await
                .unwrap_or(ProviderEffectDispatch::Unknown)
        })
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }

    fn lookup_for_reconciliation<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire_payload: Option<&'a [u8]>,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        let Some(wire_payload) = wire_payload else {
            return Box::pin(async { ProviderEffectLookup::Unknown });
        };
        if wire_payload.len() > 1024 * 1024 {
            return Box::pin(async { ProviderEffectLookup::Unknown });
        }
        let adapter = self.clone();
        let intent = intent.clone();
        let wire_payload = wire_payload.to_vec();
        Box::pin(async move {
            tokio::task::spawn_blocking(move || adapter.lookup_blocking(intent, wire_payload))
                .await
                .unwrap_or(ProviderEffectLookup::Unknown)
        })
    }
}

fn verify_pinned_binary(path: &Path, expected: &Sha256Digest) -> Result<(), AgentdError> {
    if !path.is_absolute() {
        return Err(AgentdError::Invalid(
            "PoN binary path must be absolute".to_string(),
        ));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(AgentdError::Invalid(
            "PoN binary must be canonical and symlink-free".to_string(),
        ));
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_PON_BINARY_BYTES
    {
        return Err(AgentdError::Invalid(
            "PoN binary identity is invalid".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o022 != 0 || metadata.permissions().mode() & 0o111 == 0
        {
            return Err(AgentdError::Invalid(
                "PoN binary permissions are unsafe".to_string(),
            ));
        }
    }
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let digest = hasher.finalize();
    let observed = Sha256Digest::parse(format!("{digest:x}")).map_err(AgentdError::Invalid)?;
    if &observed != expected {
        return Err(AgentdError::GenerationFenced(
            "PoN binary digest changed".to_string(),
        ));
    }
    Ok(())
}

fn pon_contract_digest(config: &AutomationEffectHostFileV2) -> Result<Sha256Digest, AgentdError> {
    let value = serde_json::json!({
        "schema":"hepta-agentd-pon-provider-contract-v1",
        "provider_kind":config.provider_kind,
        "provider_scope":config.provider_scope,
        "destination_id":config.destination_id,
        "chain_binary":config.chain_binary,
        "chain_binary_sha256":config.chain_binary_sha256,
        "chain_store":config.chain_store,
        "chain_state_backend":config.chain_state_backend,
        "chain_genesis_time":config.chain_genesis_time,
        "chain_evaluation_policy":config.chain_evaluation_policy,
        "chain_task_profile":config.chain_task_profile,
        "chain_model_profile":config.chain_model_profile,
        "chain_workers":config.chain_workers,
        "timeout_ms":config.timeout_ms,
    });
    let mut bytes = b"hepta.agentd.pon-provider-contract.v1\0".to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(&value)?);
    Ok(Sha256Digest::for_bytes(&bytes))
}

#[derive(Clone, Debug)]
pub(crate) enum AgentdAutomationEffectReconcileOutcome {
    Observed {
        receipt: TaskFlowStepReceipt,
        chain: Option<crate::AutomationEffectChainObservation>,
    },
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
    // Serialize refreshes; the existing durable authority owns the only head.
    revocation_refresh: Arc<Mutex<()>>,
    adapter: AgentdProviderEffectAdapter,
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
        let config = match read_host_file(path)? {
            AutomationEffectHostFile::Http(config) => config,
            AutomationEffectHostFile::Pon(config) => return Self::open_pon(identity, config),
        };
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
            revocation_refresh: Arc::new(Mutex::new(())),
            adapter: AgentdProviderEffectAdapter::Http(adapter),
        })
    }

    fn open_pon(
        identity: &AgentdIdentity,
        config: AutomationEffectHostFileV2,
    ) -> Result<Self, AgentdError> {
        if config.schema_version != AUTOMATION_EFFECT_HOST_PON_SCHEMA_VERSION
            || config.provider_kind != PON_PROVIDER_KIND
        {
            return Err(AgentdError::Invalid(
                "unsupported PoN automation effect host schema".to_string(),
            ));
        }
        validate_host_identifier("provider_scope", &config.provider_scope)?;
        validate_host_identifier("destination_id", &config.destination_id)?;
        validate_host_identifier("chain_evaluation_policy", &config.chain_evaluation_policy)?;
        validate_host_identifier("chain_task_profile", &config.chain_task_profile)?;
        validate_host_identifier("chain_model_profile", &config.chain_model_profile)?;
        if !matches!(
            config.chain_state_backend.as_str(),
            "legacy-v2" | "authenticated-v1"
        ) || config.chain_genesis_time == 0
            || !(1..=64).contains(&config.chain_workers)
            || config.timeout_ms == 0
            || config.timeout_ms > 30_000
        {
            return Err(AgentdError::Invalid(
                "PoN automation effect host limits are invalid".to_string(),
            ));
        }
        let final_use_scope_digest = Sha256Digest::parse(config.final_use_scope_sha256.clone())
            .map_err(AgentdError::Invalid)?;
        let binary_digest = Sha256Digest::parse(config.chain_binary_sha256.clone())
            .map_err(AgentdError::Invalid)?;
        verify_pinned_binary(&config.chain_binary, &binary_digest)?;
        if !config.chain_store.is_absolute()
            || config.chain_store.canonicalize()? != config.chain_store
            || !config.chain_store.join("native.sqlite").is_file()
        {
            return Err(AgentdError::Invalid(
                "PoN store must be an existing canonical Node namespace".to_string(),
            ));
        }
        let declared_contract_digest =
            Sha256Digest::parse(config.contract_sha256.clone()).map_err(AgentdError::Invalid)?;
        if pon_contract_digest(&config)? != declared_contract_digest {
            return Err(AgentdError::Invalid(
                "PoN provider contract digest mismatch".to_string(),
            ));
        }
        let contract_signature =
            decode_hex_array::<64>(&config.contract_signature_hex, "contract_signature_hex")?;
        let contract_verifying_key = decode_hex_array::<32>(
            &config.contract_verifying_key_hex,
            "contract_verifying_key_hex",
        )?;
        HttpProviderEffectContractAttestation::verify_signed(
            config.contract_id.clone(),
            declared_contract_digest,
            config.contract_authority_epoch,
            &contract_signature,
            &contract_verifying_key,
        )
        .map_err(AgentdError::Invalid)?;

        if !config.final_use_revocations_file.is_absolute() {
            return Err(AgentdError::Invalid(
                "final_use_revocations_file must be absolute".to_string(),
            ));
        }
        let initial_revocations = read_revocations_file(&config.final_use_revocations_file)?;
        let final_use_verifying_key = decode_hex_array::<32>(
            &config.final_use_verifying_key_hex,
            "final_use_verifying_key_hex",
        )?;
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
        let adapter = PonLocalProviderEffectAdapter {
            binary: config.chain_binary,
            binary_sha256: binary_digest,
            store: config.chain_store,
            state_backend: config.chain_state_backend,
            genesis_time: config.chain_genesis_time,
            evaluation_policy: config.chain_evaluation_policy,
            task_profile: config.chain_task_profile,
            model_profile: config.chain_model_profile,
            workers: config.chain_workers,
            timeout: Duration::from_millis(config.timeout_ms),
        };
        Ok(Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: config.provider_scope,
            destination_id: config.destination_id,
            final_use_scope_digest,
            authority,
            revocations_file: config.final_use_revocations_file,
            revocation_refresh: Arc::new(Mutex::new(())),
            adapter: AgentdProviderEffectAdapter::Pon(adapter),
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
        let mut driver = AgentdAuthorizedEffectDriver {
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
                    let provider_intent = self.provider_intent(&pending)?;
                    let chain = self
                        .adapter
                        .current_chain_observation(
                            &provider_intent,
                            pending.wire_payload.as_deref(),
                        )
                        .await;
                    return Ok(AgentdAutomationEffectReconcileOutcome::Observed { receipt, chain });
                }
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    return Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent);
                }
                AuthorizedEffectRecoveryResult::Observed(_) => {}
            }
        }
        let provider_intent = self.provider_intent(&pending)?;
        match self
            .adapter
            .lookup_for_reconciliation(&provider_intent, pending.wire_payload.as_deref())
            .await
        {
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
                        let chain = self
                            .adapter
                            .current_chain_observation(
                                &provider_intent,
                                pending.wire_payload.as_deref(),
                            )
                            .await;
                        Ok(AgentdAutomationEffectReconcileOutcome::Observed { receipt, chain })
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
        // A numeric (epoch, revision) cache cannot detect same-head content
        // drift or a head advanced through another clone of the authority.
        // Keep only refresh serialization here, never a second trust frontier.
        let _refresh = self.revocation_refresh.lock().map_err(|_| {
            AgentdError::Protocol(
                "automation effect revocation refresh lock is poisoned".to_string(),
            )
        })?;
        let head = read_revocations_file(&self.revocations_file)?;
        let current = self.authority.revocation_head().map_err(|error| {
            AgentdError::GenerationFenced(format!(
                "automation effect revocation head unavailable: {error}"
            ))
        })?;
        if head == current {
            return Ok(());
        }
        // The authority atomically enforces revision monotonicity, complete
        // revocation-set inclusion, entered-effect fencing and durable writes.
        // A changed head with unchanged numbers reaches that check and rejects.
        self.authority.update_revocations(head).map_err(|error| {
            AgentdError::GenerationFenced(format!(
                "automation effect revocation refresh rejected: {error}"
            ))
        })
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
        let expected = ProviderEffectKey::for_operation(
            &self.provider_scope,
            &pending.run_id,
            &pending.step_id,
        )
        .map_err(|error| AgentdError::Invalid(format!("derive provider effect key: {error:?}")))?;
        let key = match pending.provider_effect_key.as_ref() {
            Some(durable) if durable == &expected => durable.clone(),
            Some(_) => {
                return Err(AgentdError::GenerationFenced(
                    "pending effect provider key differs from the current host configuration"
                        .to_string(),
                ));
            }
            None => expected,
        };
        Ok(ProviderEffectIntent::new(
            key,
            pending.payload_digest.clone(),
        ))
    }
}

struct AgentdAuthorizedEffectDriver {
    adapter: AgentdProviderEffectAdapter,
    provider_scope: String,
    destination_id: String,
}

impl AuthorizedEffectDriver for AgentdAuthorizedEffectDriver {
    fn recovery_key(
        &self,
        intent: &AuthorizedEffectIntent,
    ) -> Result<ProviderEffectKey, AuthorizedEffectDriverError> {
        if intent.destination_id != self.destination_id {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        ProviderEffectKey::for_operation(&self.provider_scope, &intent.run_id, &intent.step_id)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)
    }

    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        if request.intent.destination_id != self.destination_id {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        let expected = self.recovery_key(request.intent)?;
        if request.provider_effect_key != &expected {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        let provider_intent = ProviderEffectIntent::new(
            request.provider_effect_key.clone(),
            request.intent.payload_digest.clone(),
        );
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

fn read_host_file(path: &Path) -> Result<AutomationEffectHostFile, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES,
        "automation effect host file",
    )?;
    let value: Value = serde_json::from_slice(&bytes)?;
    match value.get("schema_version").and_then(Value::as_u64) {
        Some(version) if version == AUTOMATION_EFFECT_HOST_SCHEMA_VERSION as u64 => Ok(
            AutomationEffectHostFile::Http(serde_json::from_value(value)?),
        ),
        Some(version) if version == AUTOMATION_EFFECT_HOST_PON_SCHEMA_VERSION as u64 => Ok(
            AutomationEffectHostFile::Pon(serde_json::from_value(value)?),
        ),
        _ => Err(AgentdError::Invalid(
            "unsupported automation effect host schema".to_string(),
        )),
    }
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

    #[test]
    fn pon_chain_observation_keeps_reorg_state_separate_from_terminal_effect() {
        let block = "11".repeat(32);
        let tip = "22".repeat(32);
        let value = serde_json::json!({
            "result": {
                "schema": "pon-native-exact-packet-observation-v2",
                "block": block,
                "stored_exact": true,
                "block_height": 7,
                "active_tip": tip,
                "active_tip_height": 11,
                "active_chain_member": false,
                "active_depth": null,
                "generation": 9,
                "local_target_only": true,
                "global_absence_authority": false,
                "confirmation_authority": false,
                "finality_authority": false,
                "execution_authority": false,
                "production_activation": false
            }
        });
        let observation = parse_pon_chain_observation(&value).expect("valid reorg observation");
        assert!(observation.stored_exact);
        assert!(!observation.active_chain_member);
        assert_eq!(observation.active_depth, None);
        assert!(!observation.confirmation_authority);
        assert!(!observation.finality_authority);

        let mut invalid = value.clone();
        invalid["result"]["confirmation_authority"] = Value::Bool(true);
        assert!(parse_pon_chain_observation(&invalid).is_none());

        let mut inconsistent = value;
        inconsistent["result"]["active_chain_member"] = Value::Bool(true);
        assert!(parse_pon_chain_observation(&inconsistent).is_none());
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
        let trusted_head = host.authority.revocation_head().expect("trusted head");
        let trusted_frontier = host.authority.frontier().expect("trusted frontier");
        let mut changed_same_revision = trusted_head.clone();
        changed_same_revision
            .revoked_grant_ids
            .insert(grant.grant.grant_id.clone());
        fs::write(
            &revocations_file,
            serde_json::to_vec(&changed_same_revision).expect("changed head json"),
        )
        .expect("write conflicting same-revision head");
        assert!(matches!(
            host.execute(
                &fixture.store,
                &intent,
                WIRE,
                &grant,
                "agentd-product-effect-dispatch",
                now_ms + 5,
            )
            .await,
            Err(AgentdError::GenerationFenced(_))
        ));
        assert_eq!(host.authority.revocation_head().unwrap(), trusted_head);
        assert_eq!(host.authority.frontier().unwrap(), trusted_frontier);
        assert_eq!(host.authority.capacity().unwrap().used_nonces, 0);
        assert!(server.received_requests().await.unwrap().is_empty());
        fs::write(
            &revocations_file,
            serde_json::to_vec(&trusted_head).expect("restore head json"),
        )
        .expect("restore exact trusted head");
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
        let durable_attempt = fixture
            .store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .expect("read durable provider attempt")
            .expect("provider attempt");
        assert_eq!(
            durable_attempt.provider_effect_key.as_ref(),
            Some(&provider_key)
        );
        assert_eq!(durable_attempt.wire_payload.as_deref(), Some(WIRE));

        // Another trusted handle may advance the existing durable owner.
        // A host-local numeric cache must not accept the old on-disk feed.
        let mut advanced_head = trusted_head.clone();
        advanced_head.revision += 1;
        advanced_head
            .revoked_grant_ids
            .insert(grant.grant.grant_id.clone());
        host.authority
            .update_revocations(advanced_head.clone())
            .expect("trusted authority advance");
        let advanced_frontier = host.authority.frontier().unwrap();
        assert!(matches!(
            host.clone().refresh_revocations(),
            Err(AgentdError::GenerationFenced(_))
        ));
        assert_eq!(host.authority.frontier().unwrap(), advanced_frontier);
        fs::write(
            &revocations_file,
            serde_json::to_vec(&advanced_head).expect("advanced head json"),
        )
        .expect("publish the exact advanced head");
        host.clone()
            .refresh_revocations()
            .expect("current cloned host");
        // Removing a revocation fails with either the same or a newer revision.
        // Neither refusal changes the durable head or refunds the used nonce.
        for revision in [advanced_head.revision, advanced_head.revision + 1] {
            let mut removed = advanced_head.clone();
            removed.revision = revision;
            removed.revoked_grant_ids.clear();
            fs::write(
                &revocations_file,
                serde_json::to_vec(&removed).expect("removed head json"),
            )
            .expect("write invalid revocation removal");
            assert!(matches!(
                host.refresh_revocations(),
                Err(AgentdError::GenerationFenced(_))
            ));
            assert_eq!(host.authority.revocation_head().unwrap(), advanced_head);
            assert_eq!(host.authority.frontier().unwrap(), advanced_frontier);
            assert_eq!(host.authority.capacity().unwrap().used_nonces, 1);
        }
        fs::write(
            &revocations_file,
            serde_json::to_vec(&advanced_head).expect("restore advanced json"),
        )
        .expect("restore advanced head");
        // A now-revoked grant does not erase the already completed effect. The
        // identical terminal read below still returns its original receipt.
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
