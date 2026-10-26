//! Explicit production entry for the original Root, writer and native Runtime.
//! The ordinary Agentd startup path does not acquire any of these capabilities.

use std::ffi::OsString;
use std::fs::File;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::OriginalAndroidTextDevice;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::AgentdAndroidRuntimeInputs;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdRootProductionInputs;
use crate::PreparedRootAgentdConfig;

#[path = "production_launcher_inputs.rs"]
mod inputs;

use inputs::LaunchInputs;
use inputs::NotesUiInputs;
use inputs::PrimaryInputs;

#[path = "production_notes_deployment.rs"]
mod notes_deployment;

enum Startup {
    Ordinary(Box<AgentdConfig>),
    Root(Box<RootStartup>),
}

struct RootStartup {
    config: PreparedRootAgentdConfig,
    bootstrap: File,
    root_pidfd: OwnedFd,
    control: OwnedFd,
    app_server: OwnedFd,
    lifetime: Duration,
    deadline: Instant,
    inputs: RuntimeInputs,
}

/// Construct only in the original arg0 single-thread preflight. This retains
/// the original Config and lock FD across Root publication and credential drop.
pub struct AgentdProductionStartup(Startup);

/// The authenticated original Root inputs and selected original Runtime input
/// remain owned by the same process until their single production composition.
pub struct AgentdProductionLaunch {
    root: AgentdRootProductionInputs,
    inputs: RuntimeInputs,
}

struct RuntimeInputs {
    primary: PrimaryInputs,
    notes: Option<UnixDatagram>,
    notes_ui: Option<NotesUiInputs>,
}

impl AgentdProductionStartup {
    /// Parse inherited rights before opening the original Config, so a bad CLI
    /// descriptor cannot accidentally name Config's newly opened writer lock.
    /// This still uses the original environment/Registry Starting admission.
    pub fn from_process_environment(
        arguments: Vec<OsString>,
    ) -> Result<(Self, Vec<OsString>), AgentdError> {
        let (inputs, ordinary) = inputs::parse(arguments)?;
        let config = AgentdConfig::from_process_environment()?;
        let startup = match inputs {
            None => Startup::Ordinary(Box::new(config)),
            Some(inputs) => {
                let LaunchInputs {
                    handoff,
                    uid,
                    gid,
                    control,
                    app_server,
                    primary,
                    bootstrap_deadline,
                    notes,
                    notes_ui,
                    lifetime,
                } = inputs;
                let config = config.prepare_root_handoff(uid, gid)?.drop_to_owner()?;
                // Root grants the original home/data access before capturing
                // this late handoff. Wait before arg0 creates helper aliases
                // under the final owner; doing so in the later async callback
                // would race those aliases against the filesystem handoff.
                let (bootstrap, root_pidfd) = crate::receive_root_production_handoff(
                    handoff,
                    remaining(bootstrap_deadline)?,
                )?;
                let inputs = RuntimeInputs {
                    primary,
                    notes,
                    notes_ui,
                };
                Startup::Root(Box::new(RootStartup {
                    config,
                    bootstrap,
                    root_pidfd,
                    control,
                    app_server,
                    lifetime,
                    deadline: bootstrap_deadline,
                    inputs,
                }))
            }
        };
        Ok((Self(startup), ordinary))
    }

    pub fn identity(&self) -> &AgentdIdentity {
        match &self.0 {
            Startup::Ordinary(config) => config.identity(),
            Startup::Root(root) => root.config.identity(),
        }
    }

    /// Connect all original Root lanes before MCP initialization. Root's fixed
    /// accept barrier cannot serve an observation while other lanes are absent.
    pub async fn receive(
        self,
    ) -> Result<(AgentdConfig, Option<AgentdProductionLaunch>), AgentdError> {
        match self.0 {
            Startup::Ordinary(config) => Ok((*config, None)),
            Startup::Root(root) => {
                let RootStartup {
                    config,
                    bootstrap,
                    root_pidfd,
                    control,
                    app_server,
                    lifetime,
                    deadline,
                    inputs,
                } = *root;
                let root = crate::receive_root_production_inputs(
                    bootstrap,
                    root_pidfd,
                    config.identity(),
                    remaining(deadline)?.min(Duration::from_millis(500)),
                    lifetime,
                )
                .await?;
                let config = config
                    .finish(&root)?
                    .with_root_bound_sockets(control, app_server)?;
                Ok((config, Some(AgentdProductionLaunch { root, inputs })))
            }
        }
    }
}

impl AgentdProductionLaunch {
    /// Start the original configured MCP manager and retain its exact selected
    /// peer beside the same Root session and recovered writer until Agentd exits.
    /// This is a newly initialized original startup session, not a connector or
    /// an already running App Server thread's peer.
    pub async fn run(
        self,
        mut config: AgentdConfig,
        arg0_paths: Arg0DispatchPaths,
    ) -> Result<(), AgentdError> {
        let RuntimeInputs {
            primary,
            notes,
            notes_ui,
        } = self.inputs;
        let mut mcp: Option<codex_app_server::ConfiguredMcpRuntime> = None;
        let mut android_device: Option<Arc<crate::AgentdAndroidTextDevice>> = None;
        let result = async {
            // The Root late handoff is already complete. Read the original
            // sealed Notes deployment once, before receiving its application
            // offer, so the trusted Session's staged reservation can be
            // activated only after the actual original owners are ready.
            let mut notes_ui = notes_ui
                .map(|ui| {
                    Ok::<_, AgentdError>((
                        notes_deployment::read(ui.deployment, config.identity())?,
                        ui.listener,
                        ui.session_pidfd,
                    ))
                })
                .transpose()?;
            let release = notes_ui
                .as_mut()
                .and_then(|(deployment, _, _)| deployment.startup_release.take());
            let (attachment, android_deadline) = match primary {
                PrimaryInputs::Android {
                    server,
                    environment,
                    payload,
                    deadline,
                } => {
                    let payload_json = inputs::read_payload(payload)?;
                    let home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)
                        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
                    let workspace =
                        AbsolutePathBuf::from_absolute_path(&config.identity().workspace)
                            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
                    let original = codex_app_server::initialize_configured_mcp_server(
                        home,
                        workspace,
                        arg0_paths.clone(),
                        &server,
                        &environment,
                        remaining(deadline)?,
                    )
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!("original Runtime MCP startup: {error}"))
                    })?;
                    mcp = Some(original);
                    let original = mcp.as_ref().ok_or_else(|| {
                        AgentdError::Protocol("original MCP startup handle disappeared".into())
                    })?;
                    let android = AgentdAndroidRuntimeInputs::from_mcp_binding(
                        original.binding(),
                        &server,
                        &environment,
                        tokio::runtime::Handle::current(),
                        payload_json,
                        deadline,
                    )
                    .await?;
                    let (target, device) = crate::prepare_android_runtime_target(android)?;
                    android_device = Some(device);
                    let target: Arc<dyn FinalUseProductionOutboxTarget> = target;
                    let attachment = crate::attach_root_production_operation_host_with_startup(
                        &mut config,
                        self.root,
                        target,
                        notes,
                        Duration::from_millis(100),
                        release,
                    )
                    .await?;
                    (attachment, Some(deadline))
                }
                PrimaryInputs::Notes => {
                    let notes = notes.ok_or_else(|| {
                        AgentdError::Invalid(
                            "original Notes primary has no application handoff".into(),
                        )
                    })?;
                    let attachment = crate::attach_root_notes_operation_host_with_startup(
                        &mut config,
                        self.root,
                        notes,
                        Duration::from_millis(100),
                        release,
                    )
                    .await?;
                    (attachment, None)
                }
            };
            if let Some((deployment, listener, session_pidfd)) = notes_ui {
                let notes_deployment::NotesDeployment {
                    bindings,
                    peer,
                    previous_recovery,
                    startup_release: _,
                    interaction,
                } = deployment;
                if let Some(previous) = previous_recovery {
                    config = config.with_original_notes_previous_recovery(previous)?;
                }
                let peer = crate::AgentdNotesUiPeer {
                    uid: peer.uid,
                    pid: peer.pid,
                    boot_id: peer.boot_id,
                    process_start_ticks: peer.process_start_ticks,
                };
                match interaction {
                    crate::notes_launch_mode::NotesLaunchMode::LiteralUiV1 => {
                        let (configured, adapter) = config.with_root_notes_literal_adapter(
                            &attachment,
                            bindings,
                            Duration::from_secs(10),
                        )?;
                        config = configured;
                        let expected_path = config.identity().run_root.join("notes-objective.sock");
                        let listener = crate::listen_root_bound_socket(listener, &expected_path)?;
                        let runtime = crate::AgentdNotesUiRuntime::from_inherited(
                            listener,
                            session_pidfd,
                            peer,
                            adapter,
                        )?;
                        config = config.with_original_notes_ui(runtime)?;
                    }
                    crate::notes_launch_mode::NotesLaunchMode::OriginalThreadToolV1 {
                        route,
                        seed,
                    } => {
                        let lifetime = crate::AgentdNotesSessionLifetime::from_inherited(
                            session_pidfd,
                            &peer,
                        )?;
                        config = config
                            .with_root_notes_thread_tools(
                                &attachment,
                                bindings,
                                route,
                                Duration::from_secs(10),
                            )?
                            .with_original_notes_thread_seed(seed)?
                            .with_original_notes_thread_session(lifetime)?;
                        // The explicit model profile admits no literal UI
                        // endpoint. Root retains pathname cleanup custody.
                        drop(listener);
                    }
                }
            }
            if let Some(deadline) = android_deadline {
                remaining(deadline)?;
            }
            let result = crate::run(config, arg0_paths).await;
            // Keep the authenticated Root feed and original checkpoint/grant
            // handles alive until all original runtime workers have stopped.
            drop(attachment);
            result
        }
        .await;
        if let Some(device) = android_device {
            device.invalidate();
        }
        if let Some(mcp) = mcp {
            mcp.shutdown().await;
        }
        result
    }
}

fn remaining(deadline: Instant) -> Result<Duration, AgentdError> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero() && *value <= Duration::from_secs(30))
        .ok_or_else(|| AgentdError::Protocol("original production launch deadline expired".into()))
}
