//! Explicit engineering HCSN registration under the existing Agentd effect owner.
//! Production registration requires the PQ authority composition and is refused
//! by this baseline; engineering registration is disabled in ordinary Agentd builds.
//! Exact request bytes are retained only inside the verified dispatch boundary;
//! a reopened host can query the same job without granting another launch.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;

use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::HcsnProcessSupervisor;
use codex_hepta_automation::HcsnProcessSupervisorConfig;
use codex_hepta_automation::HcsnTaskFlowActionV1;
use codex_hepta_automation::HcsnTaskFlowDriver;
use serde::Serialize;

use super::*;

const MAX_RETAINED_REQUEST_BYTES: u64 = 8 * crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES as u64;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct HcsnHostFileV2 {
    schema_version: u32,
    provider: HcsnProviderKind,
    authority_profile: HcsnAuthorityProfile,
    provider_scope: String,
    final_use_scope_sha256: String,
    final_use_signer_id: String,
    final_use_verifying_key_hex: String,
    final_use_revocations_file: PathBuf,
    python_executable: PathBuf,
    python_sha256: Sha256Digest,
    repository_root: PathBuf,
    supervisor_sha256: Sha256Digest,
    durable_root: PathBuf,
    timeout_ms: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum HcsnProviderKind {
    HcsnProcessV1,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum HcsnAuthorityProfile {
    EngineeringEd25519V1,
    ProductionMlDsa65V2,
}

#[derive(Clone, Debug)]
pub(super) struct HcsnProvider {
    provider_scope: String,
    config: HcsnProcessSupervisorConfig,
    requests_root: PathBuf,
}

#[derive(Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RetainedRequest {
    intent: AuthorizedEffectIntent,
    wire_payload: String,
}

pub(super) struct RetainedDriver {
    provider: HcsnProvider,
    driver: HcsnTaskFlowDriver<HcsnProcessSupervisor>,
}

impl AgentdAutomationEffectHost {
    pub(super) fn open_hcsn(
        identity: &AgentdIdentity,
        config: HcsnHostFileV2,
    ) -> Result<Self, AgentdError> {
        match config.authority_profile {
            HcsnAuthorityProfile::ProductionMlDsa65V2 => return Err(AgentdError::Invalid(
                "production HCSN registration requires the PQ owner authority, signed revocations, protected clock and external frontier; this baseline cannot register it".to_string(),
            )),
            HcsnAuthorityProfile::EngineeringEd25519V1 if !cfg!(test) => {
                return Err(AgentdError::Invalid(
                    "engineering HCSN registration is available only to the qualification test build".to_string(),
                ));
            }
            HcsnAuthorityProfile::EngineeringEd25519V1 => {}
        }
        if config.schema_version != 2 || config.timeout_ms == 0 || config.timeout_ms > 30_000 {
            return Err(AgentdError::Invalid(
                "invalid HCSN host schema or RPC deadline".to_string(),
            ));
        }
        let HcsnProviderKind::HcsnProcessV1 = config.provider;
        validate_host_identifier("provider_scope", &config.provider_scope)?;
        let final_use_scope_digest =
            Sha256Digest::parse(config.final_use_scope_sha256).map_err(AgentdError::Invalid)?;
        let verifying_key = decode_hex_array::<32>(
            &config.final_use_verifying_key_hex,
            "final_use_verifying_key_hex",
        )?;
        let revocations = read_revocations_file(&config.final_use_revocations_file)?;
        let frontier = (revocations.authority_epoch, revocations.revision);
        let supervisor_config = HcsnProcessSupervisorConfig {
            python_executable: config.python_executable,
            python_sha256: config.python_sha256,
            repository_root: config.repository_root,
            supervisor_sha256: config.supervisor_sha256,
            durable_root: config.durable_root,
            deadline: Duration::from_millis(config.timeout_ms),
        };
        HcsnProcessSupervisor::new(supervisor_config.clone()).map_err(|_| {
            AgentdError::Invalid("HCSN supervisor deployment pins rejected".to_string())
        })?;
        let requests_root = supervisor_config.durable_root.join("taskflow-requests");
        create_private_directory(&requests_root)?;
        let authority_root = identity
            .layout
            .automation_root()
            .join("final-use-authority");
        create_private_directory(&authority_root)?;
        let authority = FinalUseAuthority::open_state_dir(
            &authority_root,
            config.final_use_signer_id,
            verifying_key,
            revocations,
        )
        .map_err(|error| {
            AgentdError::Protocol(format!("open HCSN final-use authority: {error}"))
        })?;
        let provider = HcsnProvider {
            provider_scope: config.provider_scope.clone(),
            config: supervisor_config,
            requests_root,
        };
        Ok(Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: config.provider_scope.clone(),
            destination_id: config.provider_scope,
            final_use_scope_digest,
            authority,
            revocations_file: config.final_use_revocations_file,
            revocation_frontier: Arc::new(Mutex::new(frontier)),
            adapter: EffectProvider::Hcsn(provider),
        })
    }
}

impl HcsnProvider {
    pub(super) fn driver(&self, operation: &str) -> Result<RetainedDriver, AgentdError> {
        let action = action_for_operation(operation)?;
        let supervisor = HcsnProcessSupervisor::new(self.config.clone()).map_err(|_| {
            AgentdError::Invalid("HCSN supervisor deployment pins rejected".to_string())
        })?;
        let driver = HcsnTaskFlowDriver::new(self.provider_scope.clone(), action, supervisor)
            .map_err(|_| AgentdError::Invalid("invalid HCSN provider scope".to_string()))?;
        Ok(RetainedDriver {
            provider: self.clone(),
            driver,
        })
    }

    pub(super) fn lookup(
        &self,
        pending: &AuthorizedEffectPending,
    ) -> AuthorizedProviderEffectLookup {
        if validate_private_directory(&self.requests_root).is_err() {
            return AuthorizedProviderEffectLookup::Unresolved;
        }
        let path = self
            .requests_root
            .join(format!("{}.json", pending.intent_digest.as_str()));
        let Ok(bytes) = read_retained_request(&path) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let Ok(saved) = serde_json::from_slice::<RetainedRequest>(&bytes) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        if saved.intent.digest().as_ref().ok() != Some(&pending.intent_digest)
            || saved.intent.run_id != pending.run_id
            || saved.intent.step_id != pending.step_id
            || saved.intent.attempt != pending.attempt
            || saved.intent.destination_id != pending.destination_id
            || saved.intent.payload_digest != pending.payload_digest
            || Sha256Digest::for_bytes(saved.wire_payload.as_bytes()) != pending.payload_digest
        {
            return AuthorizedProviderEffectLookup::Unresolved;
        }
        let Ok(mut driver) = self.driver(&saved.intent.operation_id) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        driver.driver.lookup(pending, saved.wire_payload.as_bytes())
    }
}

impl AuthorizedEffectDriver for RetainedDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        validate_private_directory(&self.provider.requests_root)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        let retained = RetainedRequest {
            intent: request.intent.clone(),
            wire_payload: String::from_utf8(request.wire_payload.to_vec())
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?,
        };
        let bytes = serde_json::to_vec(&retained)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        if bytes.len() as u64 > MAX_RETAINED_REQUEST_BYTES {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        let path = self
            .provider
            .requests_root
            .join(format!("{}.json", request.intent_digest.as_str()));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&path) {
            Ok(mut file) => {
                file.write_all(&bytes)
                    .and_then(|()| file.sync_all())
                    .and_then(|()| File::open(&self.provider.requests_root)?.sync_all())
                    .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let old = read_retained_request(&path)
                    .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
                if old != bytes {
                    return Err(AuthorizedEffectDriverError::BeforeProviderContact);
                }
            }
            Err(_) => return Err(AuthorizedEffectDriverError::BeforeProviderContact),
        }
        self.driver.dispatch(request)
    }
}

fn action_for_operation(operation: &str) -> Result<HcsnTaskFlowActionV1, AgentdError> {
    match operation {
        "hcsn.training.start" => Ok(HcsnTaskFlowActionV1::Start),
        "hcsn.training.cancel" => Ok(HcsnTaskFlowActionV1::Cancel),
        _ => Err(AgentdError::Invalid(
            "operation is not registered on the HCSN host".to_string(),
        )),
    }
}

fn create_private_directory(path: &Path) -> Result<(), AgentdError> {
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    match builder.create(path) {
        Ok(()) => File::open(
            path.parent()
                .ok_or_else(|| AgentdError::Invalid("missing parent".to_string()))?,
        )?
        .sync_all()?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error.into()),
    }
    validate_private_directory(path)
}

fn validate_private_directory(path: &Path) -> Result<(), AgentdError> {
    let metadata = fs::symlink_metadata(path)?;
    if path.canonicalize()? != path || !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(AgentdError::Invalid(
            "HCSN state root must be a canonical directory".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(
                "HCSN state root must be private".to_string(),
            ));
        }
    }
    Ok(())
}

fn read_retained_request(path: &Path) -> Result<Vec<u8>, AgentdError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if fs::symlink_metadata(path)?.nlink() != 1 {
            return Err(AgentdError::Invalid(
                "retained HCSN request must not be hardlinked".to_string(),
            ));
        }
    }
    read_protected_file(path, MAX_RETAINED_REQUEST_BYTES, "retained HCSN request")
}

