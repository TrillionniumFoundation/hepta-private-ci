use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_authbus::IssuerRegistration;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;

use crate::backend::AgentdBackendConnector;
use crate::backend::BackendConnectError;
use crate::platform::PlatformAdapter;
use crate::platform::SystemPlatformAdapter;
use crate::session_store::OpaqueSessionReference;
use crate::session_store::SessionReferenceStore;
use crate::session_store::SessionStoreError;
use crate::shell::BackendSessionObservation;
use crate::shell::EndpointManifest;
use crate::shell::NativePresentationState;
use crate::shell::NativeSession;
use crate::shell::NativeShellRuntime;
use crate::shell::PlatformCapabilityRequest;
use crate::shell::PlatformDecision;
use crate::shell::RuntimeView;
use crate::shell::ShellError;
use crate::shell::TrustedGrantVerifier;
use crate::ui_state::NativeLocale;
use crate::ui_state::NativeUiState;
use crate::ui_state::ScaleFactorMilli;
use crate::updater::NativeUpdateController;
use crate::updater::SignedUpdateManifestV1;
use crate::updater::SignedUpdateVerifier;
use crate::updater::UpdateDisposition;
use crate::updater::UpdateDriver;
use crate::updater::UpdateError;

#[derive(Debug)]
pub enum NativeHostError {
    Backend(BackendConnectError),
    Shell(ShellError),
    SessionStore(SessionStoreError),
    Update(UpdateError),
}

impl fmt::Display for NativeHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NativeHostError {}

impl From<BackendConnectError> for NativeHostError {
    fn from(value: BackendConnectError) -> Self {
        Self::Backend(value)
    }
}

impl From<ShellError> for NativeHostError {
    fn from(value: ShellError) -> Self {
        Self::Shell(value)
    }
}

impl From<SessionStoreError> for NativeHostError {
    fn from(value: SessionStoreError) -> Self {
        Self::SessionStore(value)
    }
}

impl From<UpdateError> for NativeHostError {
    fn from(value: UpdateError) -> Self {
        Self::Update(value)
    }
}

/// Composition root for native shell state, OS adapters, secure session
/// references, signed updates and renderer-independent UI state.
///
/// Backend session authentication remains owned by Agentd. The host can obtain
/// a generation-fenced observation through `AgentdBackendConnector`, but it
/// never fabricates a backend session or effect grant.
pub struct NativeApplicationHost<P, K, D>
where
    P: PlatformAdapter,
    K: KeyringStore,
    D: UpdateDriver,
{
    shell: NativeShellRuntime<P>,
    sessions: SessionReferenceStore<K>,
    updates: NativeUpdateController<D>,
    ui: NativeUiState,
}

impl<P, K, D> NativeApplicationHost<P, K, D>
where
    P: PlatformAdapter,
    K: KeyringStore,
    D: UpdateDriver,
{
    pub fn new(
        shell: NativeShellRuntime<P>,
        sessions: SessionReferenceStore<K>,
        updates: NativeUpdateController<D>,
        ui: NativeUiState,
    ) -> Self {
        Self {
            shell,
            sessions,
            updates,
            ui,
        }
    }

    pub fn connect(
        &mut self,
        manifest: EndpointManifest,
        observed: BackendSessionObservation,
        opaque_reference: String,
    ) -> Result<NativeSession, NativeHostError> {
        let session = self.shell.connect_runtime(manifest, observed)?;
        self.sessions.save(&OpaqueSessionReference {
            endpoint_id: session.endpoint_id.clone(),
            session_id: session.session_id.clone(),
            generation: session.generation,
            opaque_reference,
        })?;
        Ok(session)
    }

    pub async fn connect_agentd(
        &mut self,
        connector: &AgentdBackendConnector,
        manifest: EndpointManifest,
        opaque_reference: String,
    ) -> Result<NativeSession, NativeHostError> {
        let observed = connector.authenticate(&manifest).await?;
        self.connect(manifest, observed, opaque_reference)
    }

    pub fn recover_session_reference(
        &self,
    ) -> Result<Option<OpaqueSessionReference>, NativeHostError> {
        self.sessions.load().map_err(Into::into)
    }

    pub fn present_runtime_view(
        &mut self,
        view: RuntimeView,
    ) -> Result<NativePresentationState, NativeHostError> {
        let state = self.shell.render_runtime_view(view)?;
        self.ui.present_runtime_view(state.clone());
        Ok(state)
    }

    pub fn request_platform_capability(
        &mut self,
        request: PlatformCapabilityRequest,
    ) -> Result<PlatformDecision, NativeHostError> {
        let decision = self.shell.request_platform_capability(request)?;
        self.ui.present_operation(decision.clone());
        Ok(decision)
    }

    pub fn reconcile_indeterminate(
        &mut self,
    ) -> Result<Vec<PlatformDecision>, NativeHostError> {
        let decisions = self.shell.reconcile_indeterminate()?;
        for decision in &decisions {
            self.ui.present_operation(decision.clone());
        }
        Ok(decisions)
    }

    pub fn apply_shell_update(
        &mut self,
        manifest: &SignedUpdateManifestV1,
        package_bytes: &[u8],
        platform: &str,
        architecture: &str,
        backend_protocol_version: u32,
    ) -> Result<UpdateDisposition, NativeHostError> {
        match self.updates.apply_shell_update(
            manifest,
            package_bytes,
            platform,
            architecture,
            backend_protocol_version,
        ) {
            Ok(disposition) => {
                let succeeded = matches!(
                    disposition.status,
                    crate::updater::UpdateStatus::Succeeded
                );
                let quarantined = matches!(
                    disposition.status,
                    crate::updater::UpdateStatus::Quarantined
                );
                self.ui.present_update_status(succeeded, quarantined);
                Ok(disposition)
            }
            Err(error) => {
                self.ui.present_update_status(false, false);
                Err(error.into())
            }
        }
    }

    pub fn close(&mut self) {
        self.shell.close();
    }

    pub fn sign_out(&mut self) -> Result<(), NativeHostError> {
        self.shell.close();
        self.sessions.clear()?;
        Ok(())
    }

    pub fn ui(&self) -> &NativeUiState {
        &self.ui
    }

    pub fn ui_mut(&mut self) -> &mut NativeUiState {
        &mut self.ui
    }

    pub fn shell(&self) -> &NativeShellRuntime<P> {
        &self.shell
    }
}

pub type SystemNativeApplicationHost<D> =
    NativeApplicationHost<SystemPlatformAdapter, DefaultKeyringStore, D>;

pub fn bootstrap_system_host<D: UpdateDriver>(
    grant_issuer: IssuerRegistration,
    operation_journal: PathBuf,
    keyring_account: impl Into<String>,
    update_verifier: SignedUpdateVerifier,
    update_driver: D,
    locale: NativeLocale,
    scale: ScaleFactorMilli,
) -> Result<SystemNativeApplicationHost<D>, NativeHostError> {
    let shell = NativeShellRuntime::open_with_journal(
        SystemPlatformAdapter::new(),
        TrustedGrantVerifier::new(grant_issuer),
        operation_journal,
    )?;
    let sessions = SessionReferenceStore::new(DefaultKeyringStore, keyring_account)?;
    let updates = NativeUpdateController::new(update_verifier, update_driver);
    Ok(NativeApplicationHost::new(
        shell,
        sessions,
        updates,
        NativeUiState::new(locale, scale),
    ))
}
