//! Renderer-independent composition of the existing desktop runtime owner.
use std::net::SocketAddr;
use std::sync::Arc;

use crate::backend::LoopbackGatewayBackend;
use crate::error::ShellError;
use crate::journal::OperationJournal;
use crate::launch_options::NativeLaunchOptions;
use crate::model::EndpointManifest;
use crate::platform::PlatformPolicy;
use crate::platform::SystemPlatformAdapter;
use crate::private_state::PrivateStateRoot;
use crate::runtime::NativeShellRuntime;
use crate::security::KernelFinalUseGate;
use crate::security::SignedEndpointManifestV1;
use crate::security::TrustedKeySet;
use crate::session_store::GatewayCredentialStore;
use crate::updater::UpdateManager;

#[derive(Clone, Debug)]
pub struct NativeHostObservation {
    pub ready: bool,
    pub revision: u64,
    pub agents: Vec<NativeAgentObservation>,
    pub lifecycle_available: bool,
    pub previous_action_pending: bool,
    pub observed_faults: u64,
    pub chat_available: bool,
}

#[derive(Clone, Debug)]
pub struct NativeAgentObservation {
    pub id: String,
    pub state: String,
    pub healthy: bool,
    pub active: bool,
    pub running: bool,
    pub release: Option<String>,
    pub lifecycle_generation: u64,
}

/// Private-state validation and the existing journal live with the sole runtime.
pub struct NativeHost {
    pub runtime: NativeShellRuntime,
    pub manifest: EndpointManifest,
    pub updater: UpdateManager,
    pub options: NativeLaunchOptions,
    pub chat: Option<crate::chat_presentation::DesktopChat>,
    _private_state: PrivateStateRoot,
}

impl NativeHost {
    /// Only a successful original runtime observation is actionable. The
    /// returned revision still belongs to the owner's displayed-view fence.
    pub fn refresh(&mut self) -> Result<NativeHostObservation, ShellError> {
        if self.runtime.session().is_none() {
            self.runtime.connect_runtime(&self.manifest)?;
        }
        let (_, value) = self.runtime.refresh_runtime_view()?;
        let fleet =
            crate::fleet_observation::FleetObservation::parse(&value)?.ok_or_else(|| {
                ShellError::Backend("this renderer requires the installed Fleet source".into())
            })?;
        let view = self
            .runtime
            .view()
            .ok_or_else(|| ShellError::State("current observation unavailable".into()))?;
        use crate::fleet_observation::AgentLifecycle;
        Ok(NativeHostObservation {
            ready: fleet.health.ready,
            revision: view.revision,
            agents: fleet
                .agents
                .into_iter()
                .map(|agent| NativeAgentObservation {
                    id: agent.agent_id,
                    state: match agent.lifecycle {
                        AgentLifecycle::Stopped => "Stopped",
                        AgentLifecycle::Starting => "Starting",
                        AgentLifecycle::Running => "Running",
                        AgentLifecycle::Draining => "Stopping",
                        AgentLifecycle::Failed => "Needs attention",
                    }
                    .into(),
                    healthy: agent.healthy,
                    active: agent.active,
                    running: agent.lifecycle == AgentLifecycle::Running,
                    release: agent.current_release,
                    lifecycle_generation: agent.lifecycle_generation,
                })
                .collect(),
            lifecycle_available: self.runtime.fleet_lifecycle_available(),
            previous_action_pending: self.runtime.fleet_lifecycle_pending(),
            observed_faults: fleet.health.observed_faults,
            chat_available: self.runtime.chat_available(),
        })
    }

    pub fn open(raw_arguments: &[String]) -> Result<Self, Box<dyn std::error::Error>> {
        let arguments = crate::launch_config::expand_launch_arguments(raw_arguments)?;
        let options = NativeLaunchOptions::parse(&arguments)?;
        if options.update_handoff.is_some() {
            return Err(
                "finish the admitted update through Hepta Native before switching renderers".into(),
            );
        }
        let private_state = PrivateStateRoot::open(options.state_dir.clone())?;
        let trusted_keys = TrustedKeySet::from_path(&options.trusted_keys)?;
        let signed_manifest: SignedEndpointManifestV1 =
            crate::file_input::read_json_file(&options.endpoint_manifest, 64 * 1024)?;
        let verified = signed_manifest.verify(&trusted_keys)?;
        let manifest = verified.manifest;
        let address: SocketAddr = manifest.address.parse()?;
        let credentials = GatewayCredentialStore::default();
        let mut backend = LoopbackGatewayBackend::new(
            address,
            credentials.load(&verified.gateway_credential_account)?,
        )?;
        if let Some(account) = &options.lifecycle_keyring_account {
            backend =
                backend.with_fleet_lifecycle_capability(credentials.load_lifecycle(account)?)?;
        }
        if let Some(account) = &options.chat_keyring_account {
            backend = backend.with_chat_capability(credentials.load_chat(account)?)?;
        }
        let platform = SystemPlatformAdapter::new(PlatformPolicy::new(
            options.allowed_roots.clone(),
            options.allow_clipboard,
            options.allow_notifications,
        )?);
        let journal = OperationJournal::open(options.state_dir.join("operation-journal.json"))?;
        let final_use = options
            .final_use_authority
            .clone()
            .map(KernelFinalUseGate::open)
            .transpose()?
            .map(Arc::new);
        let mut runtime =
            NativeShellRuntime::new(Box::new(backend), Box::new(platform), final_use, journal);
        if options.lifecycle_keyring_account.is_some() {
            runtime = runtime.enable_fleet_lifecycle(private_state.clone())?;
        }
        let updater = UpdateManager::new(trusted_keys, options.state_dir.join("updates"))?;
        if !options.check_connection {
            let _recovery_owner = updater.lock_runner()?;
            if updater.recover_interrupted_activation()? {
                return Err(ShellError::State(
                    "interrupted update rolled back; restart the admitted predecessor".into(),
                )
                .into());
            }
        }
        let chat = options
            .chat_keyring_account
            .as_ref()
            .map(|_| crate::chat_presentation::DesktopChat::open(private_state.clone()))
            .transpose()?;
        Ok(Self {
            runtime,
            manifest,
            updater,
            options,
            chat,
            _private_state: private_state,
        })
    }
}
