use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_paths::HeptaStateRoot;
use codex_hepta_runtime::HeptaRuntime;

use crate::composition::LOCAL_ENDPOINT_ID;
use crate::composition::LocalRuntimeBackend;
use crate::composition::NATIVE_PROTOCOL_VERSION;
use crate::platform_adapter::DurablePlatformAdapter;
use crate::platform_adapter::NativePlatform;
use crate::platform_adapter::OsCommandExecutor;
use crate::platform_adapter::PlatformPolicy;
use crate::security::SignedGrantVerifier;
use crate::security::SystemDetachedSignatureVerifier;
use crate::session_store::OpaqueSessionStore;
use crate::session_store::SystemSessionStore;
use crate::shell_runtime::EndpointManifest;
use crate::shell_runtime::NativeShellRuntime;
use crate::shell_runtime::PlatformAction;
use crate::shell_runtime::PlatformRequest;
use crate::shell_runtime::PlatformStatus;
use crate::shell_runtime::SessionKey;
use crate::shell_runtime::ViewInput;
use crate::updater::SystemArtifactDigest;
use crate::updater::SystemPlatformArtifactVerifier;
use crate::updater::TransactionalUpdater;
use crate::updater::UpdateCandidate;
use crate::updater::UpdateDisposition;
use crate::updater::UpdateVerifier;

const PRODUCT_MODULES: &[&str] = &["runtime.agentd", "ui.control", "ui.native"];
const PRODUCT_UPDATE_CHANNEL: &str = "stable";

type ProductShell = NativeShellRuntime<
    LocalRuntimeBackend,
    DurablePlatformAdapter<OsCommandExecutor>,
    SignedGrantVerifier<SystemDetachedSignatureVerifier>,
>;
type ProductUpdateVerifier = UpdateVerifier<
    SystemDetachedSignatureVerifier,
    SystemDetachedSignatureVerifier,
    SystemArtifactDigest,
    SystemPlatformArtifactVerifier,
>;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct NativeCapabilitySet {
    pub open_path: bool,
    pub reveal_path: bool,
    pub copy_text: bool,
    pub notify: bool,
}

impl NativeCapabilitySet {
    fn actions(self) -> impl Iterator<Item = PlatformAction> {
        [
            self.open_path.then_some(PlatformAction::OpenPath),
            self.reveal_path.then_some(PlatformAction::RevealPath),
            self.copy_text.then_some(PlatformAction::CopyText),
            self.notify.then_some(PlatformAction::Notify),
        ]
        .into_iter()
        .flatten()
    }
}

#[derive(Clone, Debug)]
pub struct NativeProductConfig {
    pub manifest_digest: String,
    pub grant_public_key: PathBuf,
    pub release_public_key: PathBuf,
    pub selection_public_key: PathBuf,
    pub effect_journal: PathBuf,
    pub update_journal: PathBuf,
    pub active_artifact: PathBuf,
    pub rollback_artifact: PathBuf,
    pub stage_artifact: PathBuf,
    pub windows_dpapi_session_path: PathBuf,
    pub capabilities: NativeCapabilitySet,
    pub persist_session_reference: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NativeAction {
    OpenPath,
    RevealPath,
    CopyText,
    Notify,
}

impl NativeAction {
    fn internal(self) -> PlatformAction {
        match self {
            Self::OpenPath => PlatformAction::OpenPath,
            Self::RevealPath => PlatformAction::RevealPath,
            Self::CopyText => PlatformAction::CopyText,
            Self::Notify => PlatformAction::Notify,
        }
    }
}

#[derive(Clone, Debug)]
pub struct NativeActionRequest {
    pub operation_id: String,
    pub action: NativeAction,
    pub resource: String,
    pub displayed_revision: u64,
    pub payload_digest: String,
    pub signed_grant: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NativeActionStatus {
    Rejected,
    Indeterminate,
    Succeeded,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeActionReceipt {
    pub operation_id: String,
    pub status: NativeActionStatus,
    pub terminal_observed: bool,
    pub outcome_digest: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeSnapshot {
    pub platform: &'static str,
    pub runtime_status: &'static str,
    pub session_id: String,
    pub session_generation: u64,
    pub view_generation: u64,
    pub view_revision: u64,
    pub schema_version: i64,
    pub integrity_verified: bool,
    pub authority_closed: bool,
    pub modules: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct NativeUpdateRequest {
    pub package_path: PathBuf,
    pub package_digest: String,
    pub predecessor_digest: String,
    pub evidence_digest: String,
    pub producer_id: String,
    pub selector_id: String,
    pub release_signature_path: PathBuf,
    pub selection_signature_path: PathBuf,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NativeUpdateStatus {
    RestartRequired,
    Confirmed,
    RolledBack,
    Quarantined,
}

pub struct NativeProduct {
    runtime: Arc<HeptaRuntime>,
    shell: ProductShell,
    session: SessionKey,
    session_store: SystemSessionStore,
    update_verifier: ProductUpdateVerifier,
    updater: TransactionalUpdater<SystemArtifactDigest>,
    manifest_digest: String,
    view_revision: u64,
    persist_session_reference: bool,
}

impl NativeProduct {
    pub async fn open_from_env(config: NativeProductConfig) -> Result<Self> {
        validate_digest(&config.manifest_digest, "manifest digest")?;
        let platform = NativePlatform::current();
        if platform == NativePlatform::Unsupported {
            bail!("ui.native supports Windows, macOS and Linux only");
        }
        let state_root = HeptaStateRoot::from_env()?;
        let runtime = Arc::new(HeptaRuntime::open_existing(state_root).await?);
        let backend =
            LocalRuntimeBackend::new(Arc::clone(&runtime), config.manifest_digest.clone())?;
        let platform_adapter = DurablePlatformAdapter::open(
            platform,
            PlatformPolicy::allow(config.capabilities.actions()),
            OsCommandExecutor,
            config.effect_journal,
        )?;
        let grant_verifier = SignedGrantVerifier::new(SystemDetachedSignatureVerifier::new(
            platform,
            config.grant_public_key,
        )?);
        let mut shell = NativeShellRuntime::new(backend, platform_adapter, grant_verifier);
        let session = shell.connect_runtime(EndpointManifest {
            endpoint_id: LOCAL_ENDPOINT_ID.to_string(),
            manifest_digest: config.manifest_digest.clone(),
            protocol_version: NATIVE_PROTOCOL_VERSION,
        })?;

        let session_store = SystemSessionStore::new(
            platform,
            "hepta.native".to_string(),
            "runtime.session".to_string(),
            config.windows_dpapi_session_path,
        )?;
        if config.persist_session_reference {
            let current_reference = format!("{}:{}", session.session_id, session.generation);
            if session_store.load()?.as_deref() != Some(current_reference.as_str()) {
                session_store.save(&current_reference)?;
            }
        }

        let release_signatures =
            SystemDetachedSignatureVerifier::new(platform, config.release_public_key)?;
        let selection_signatures =
            SystemDetachedSignatureVerifier::new(platform, config.selection_public_key)?;
        let update_verifier = UpdateVerifier::new(
            release_signatures,
            selection_signatures,
            SystemArtifactDigest,
            SystemPlatformArtifactVerifier,
            PRODUCT_UPDATE_CHANNEL.to_string(),
            platform,
            std::env::consts::ARCH.to_string(),
            NATIVE_PROTOCOL_VERSION,
        )?;
        let updater = TransactionalUpdater::open(
            SystemArtifactDigest,
            config.active_artifact,
            config.rollback_artifact,
            config.stage_artifact,
            config.update_journal,
        )?;

        let mut product = Self {
            runtime,
            shell,
            session,
            session_store,
            update_verifier,
            updater,
            manifest_digest: config.manifest_digest,
            view_revision: 0,
            persist_session_reference: config.persist_session_reference,
        };
        product.refresh()?;
        Ok(product)
    }

    pub fn refresh(&mut self) -> Result<NativeSnapshot> {
        let status = self.runtime.status();
        self.view_revision = self
            .view_revision
            .checked_add(1)
            .context("native view revision overflow")?;
        let view_generation = status
            .state
            .runtime_snapshot_generation
            .checked_add(1)
            .context("native view generation overflow")?;
        let modules = PRODUCT_MODULES
            .iter()
            .map(|value| (*value).to_string())
            .collect::<Vec<_>>();
        self.shell.render_runtime_view(ViewInput {
            session: self.session.clone(),
            generation: view_generation,
            revision: self.view_revision,
            digest: self.manifest_digest.clone(),
            modules: modules.clone(),
        })?;
        Ok(NativeSnapshot {
            platform: platform_name(NativePlatform::current()),
            runtime_status: status.status,
            session_id: self.session.session_id.clone(),
            session_generation: self.session.generation,
            view_generation,
            view_revision: self.view_revision,
            schema_version: status.state.schema_version,
            integrity_verified: status.state.integrity_binding_present,
            authority_closed: !status.authority.telegram
                && !status.authority.outbound
                && !status.authority.model_invocation
                && !status.authority.operator_mutation
                && !status.authority.enforce
                && !status.authority.promotion
                && !status.authority.retirement
                && !status.authority.automatic_transition,
            modules,
        })
    }

    pub fn request_platform_action(
        &mut self,
        request: NativeActionRequest,
    ) -> Result<NativeActionReceipt> {
        let receipt = self.shell.request_platform_capability(PlatformRequest {
            operation_id: request.operation_id,
            action: request.action.internal(),
            resource: request.resource,
            displayed_revision: request.displayed_revision,
            payload_digest: request.payload_digest,
            grant: request.signed_grant,
        })?;
        Ok(NativeActionReceipt {
            operation_id: receipt.operation_id,
            status: match receipt.status {
                PlatformStatus::Rejected => NativeActionStatus::Rejected,
                PlatformStatus::Indeterminate => NativeActionStatus::Indeterminate,
                PlatformStatus::Succeeded => NativeActionStatus::Succeeded,
                PlatformStatus::Failed => NativeActionStatus::Failed,
            },
            terminal_observed: receipt.terminal_observed,
            outcome_digest: receipt.outcome_digest,
        })
    }

    pub fn apply_update(&self, request: NativeUpdateRequest) -> Result<NativeUpdateStatus> {
        let release_signature = read_bounded_signature(&request.release_signature_path)?;
        let selection_signature = read_bounded_signature(&request.selection_signature_path)?;
        let verified = self.update_verifier.verify(UpdateCandidate {
            package_path: request.package_path,
            package_digest: request.package_digest,
            predecessor_digest: request.predecessor_digest,
            evidence_digest: request.evidence_digest,
            producer_id: request.producer_id,
            selector_id: request.selector_id,
            channel: PRODUCT_UPDATE_CHANNEL.to_string(),
            platform: NativePlatform::current(),
            architecture: std::env::consts::ARCH.to_string(),
            backend_protocol_version: NATIVE_PROTOCOL_VERSION,
            release_signature,
            selection_signature,
        })?;
        Ok(map_update_status(self.updater.apply(&verified)?))
    }

    pub fn recover_or_confirm_update(&self, running_digest: &str) -> Result<NativeUpdateStatus> {
        Ok(map_update_status(
            self.updater.recover_or_confirm(running_digest)?,
        ))
    }

    pub fn close(&mut self) -> Result<()> {
        self.shell.close()?;
        if self.persist_session_reference {
            let _ = self.session_store.delete()?;
        }
        Ok(())
    }
}

fn map_update_status(value: UpdateDisposition) -> NativeUpdateStatus {
    match value {
        UpdateDisposition::RestartRequired => NativeUpdateStatus::RestartRequired,
        UpdateDisposition::Confirmed => NativeUpdateStatus::Confirmed,
        UpdateDisposition::RolledBack => NativeUpdateStatus::RolledBack,
        UpdateDisposition::Quarantined => NativeUpdateStatus::Quarantined,
    }
}

fn read_bounded_signature(path: &Path) -> Result<Vec<u8>> {
    if !path.is_absolute() {
        bail!("native update signature path must be absolute");
    }
    let metadata = path.metadata().context("inspect native update signature")?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > 16 * 1024 {
        bail!("native update signature must be a non-empty bounded file");
    }
    std::fs::read(path).context("read native update signature")
}

fn platform_name(platform: NativePlatform) -> &'static str {
    match platform {
        NativePlatform::Windows => "windows",
        NativePlatform::Macos => "macos",
        NativePlatform::Linux => "linux",
        NativePlatform::Unsupported => "unsupported",
    }
}

fn validate_digest(value: &str, name: &str) -> Result<()> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        bail!("native {name} must be a non-zero lowercase SHA-256 digest");
    }
    Ok(())
}
