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
use crate::desktop_root_composition::attach_root_desktop_operation_host_with_startup_before;

#[path = "production_q24_successor.rs"]
mod successor;

#[path = "production_run_start_retention.rs"]
pub(crate) mod run_start_retention;
#[path = "production_source_capture.rs"]
pub(crate) mod source_capture;

#[path = "production_launcher_inputs.rs"]
mod inputs;

#[path = "production_initial_q24.rs"]
mod initial_q24;
pub(crate) use initial_q24::ledger_data::LedgerDeploymentData;

#[path = "production_post_a_q24.rs"]
mod post_a_q24;

#[path = "production_launcher_late_writer.rs"]
mod late_writer;

use inputs::LaunchInputs;
use inputs::NotesUiInputs;
use inputs::PrimaryInputs;

#[path = "production_notes_deployment.rs"]
mod notes_deployment;

#[path = "production_desktop_deployment.rs"]
mod desktop_deployment;

enum Startup {
    Ordinary(Box<AgentdConfig>),
    Root(Box<RootStartup>),
}

struct RootStartup {
    config: PreparedRootAgentdConfig,
    bootstrap: File,
    root_pidfd: OwnedFd,
    learning: Option<crate::RootLearningHandoffV1>,
    q24_model: Option<crate::RootQ24ModelFactoryHandoffV1>,
    publication: Option<crate::RootGenerationPublicationHandoffV1>,
    initial_publication: Option<crate::RootGenerationInitialHandoffV1>,
    historical: Option<crate::RootHistoricalTaskReadHandoffV1>,
    post_a_handoffs: Option<post_a_q24::PendingHandoffs>,
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
    q24_model: Option<crate::AgentdRootQ24ModelFactoryV1>,
    publication: Option<crate::RootGenerationPublicationHandoffV1>,
    initial_publication: Option<crate::RootGenerationInitialHandoffV1>,
    historical_read:
        Option<Arc<crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1>>,
    original_source_capture: Option<source_capture::OriginalSourceCaptureRequestV1>,
    original_run_start_retention: Option<run_start_retention::OriginalInitialRunStartRetainerV1>,
    post_a_handoffs: Option<post_a_q24::PendingHandoffs>,
    session_end: Instant,
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
                    mut learning_handoff,
                    mut q24_model_handoff,
                    publication_handoff,
                    initial_handoff,
                    historical_handoff,
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
                let post_a_handoffs = post_a_q24::PendingHandoffs::defer_for_original_profile(
                    &primary,
                    &mut learning_handoff,
                    &mut q24_model_handoff,
                )?;
                let config = config.prepare_root_handoff(uid, gid)?.drop_to_owner()?;
                // Root grants the original home/data access before capturing
                // this late handoff. Wait before arg0 creates helper aliases
                // under the final owner; doing so in the later async callback
                // would race those aliases against the filesystem handoff.
                let (bootstrap, root_pidfd) = crate::receive_root_production_handoff(
                    handoff,
                    remaining(bootstrap_deadline)?,
                )?;
                let learning = learning_handoff
                    .map(|handoff| {
                        crate::receive_root_learning_handoff(
                            handoff,
                            remaining(bootstrap_deadline)?,
                        )
                    })
                    .transpose()?;
                let q24_model = q24_model_handoff
                    .map(|handoff| {
                        crate::receive_root_q24_model_factory_handoff(
                            handoff,
                            remaining(bootstrap_deadline)?,
                        )
                    })
                    .transpose()?;
                let publication = publication_handoff
                    .map(|handoff| {
                        crate::receive_root_generation_publication_handoff(
                            handoff,
                            remaining(bootstrap_deadline)?,
                        )
                    })
                    .transpose()?;
                let initial_publication = initial_handoff
                    .map(|handoff| {
                        crate::receive_root_generation_initial_handoff(
                            handoff,
                            remaining(bootstrap_deadline)?,
                        )
                    })
                    .transpose()?;
                let historical = historical_handoff
                    .map(|handoff| {
                        crate::receive_root_historical_task_read_handoff(
                            handoff,
                            remaining(bootstrap_deadline)?,
                        )
                    })
                    .transpose()?;
                let inputs = RuntimeInputs {
                    primary,
                    notes,
                    notes_ui,
                };
                Startup::Root(Box::new(RootStartup {
                    config,
                    bootstrap,
                    root_pidfd,
                    learning,
                    q24_model,
                    publication,
                    initial_publication,
                    historical,
                    post_a_handoffs,
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

    /// Product entry for an original embedded host that already holds the real
    /// task, Dataset, role and storage capabilities. Default CLI receive remains
    /// fail-closed when those capabilities have not been deployed.
    pub async fn receive_q24_learning(
        self,
        inputs: crate::OriginalCellQ24LearningInputsV1,
    ) -> Result<
        (
            AgentdConfig,
            AgentdProductionLaunch,
            crate::LearningIterationHandleV1,
            Arc<crate::OriginalCellQ24LearningStageOwnersV1>,
        ),
        AgentdError,
    > {
        let (config, launch) = self.receive().await?;
        let launch = launch.ok_or_else(|| {
            AgentdError::Invalid(
                "original Root production launch is required for Q24 learning".into(),
            )
        })?;
        let (launch, config, handle, owners) = launch.assemble_q24_learning(config, inputs).await?;
        Ok((config, launch, handle, owners))
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
                    learning,
                    q24_model,
                    publication,
                    initial_publication,
                    historical,
                    post_a_handoffs,
                    control,
                    app_server,
                    lifetime,
                    deadline,
                    inputs,
                } = *root;
                let session_end = Instant::now() + lifetime;
                let mut root = crate::receive_root_production_inputs(
                    bootstrap,
                    root_pidfd,
                    config.identity(),
                    remaining(deadline)?.min(Duration::from_millis(500)),
                    lifetime,
                )
                .await?;
                let mut config = config
                    .finish(&root)?
                    .with_root_bound_sockets(control, app_server)?;
                let historical_read = if let Some(historical) = historical {
                    let connection =
                        AgentdRootProductionInputs::take_historical_task_read_connection(
                            &mut root,
                        )?;
                    let client = crate::RootHistoricalTaskReadHandoffV1::connect_original(
                        historical,
                        connection,
                        remaining(deadline)?.min(Duration::from_millis(500)),
                        session_end,
                    )
                    .await?;
                    crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1::require_same_original_session(&client, &root.session)?;
                    Some(client)
                } else {
                    None
                };
                let mut model_factory = None;
                if let Some(learning) = learning {
                    let learning: crate::RootLearningHandoffV1 = learning;
                    let lifetime = session_end
                        .checked_duration_since(Instant::now())
                        .filter(|remaining| !remaining.is_zero())
                        .ok_or_else(|| {
                            AgentdError::Protocol("original Root learning lifetime expired".into())
                        })?;
                    let inputs = learning
                        .connect(
                            &root,
                            config.identity(),
                            remaining(deadline)?.min(Duration::from_millis(500)),
                            lifetime,
                        )
                        .await?;
                    if let Some(model) = q24_model {
                        let model: crate::RootQ24ModelFactoryHandoffV1 = model;
                        model_factory = Some(
                            model
                                .connect(
                                    &root,
                                    &inputs,
                                    config.identity(),
                                    remaining(deadline)?.min(Duration::from_millis(500)),
                                    session_end
                                        .checked_duration_since(Instant::now())
                                        .filter(|remaining| !remaining.is_zero())
                                        .ok_or_else(|| {
                                            AgentdError::Protocol(
                                                "original Root Model lifetime expired".into(),
                                            )
                                        })?,
                                )
                                .await?,
                        );
                    }
                    config = config.with_root_learning_inputs(inputs)?;
                }
                Ok((
                    config,
                    Some(AgentdProductionLaunch {
                        root,
                        inputs,
                        q24_model: model_factory,
                        publication,
                        initial_publication,
                        historical_read,
                        original_source_capture: None,
                        original_run_start_retention: None,
                        post_a_handoffs,
                        session_end,
                    }),
                ))
            }
        }
    }
}

impl AgentdProductionLaunch {
    /// Consume the independently received historical purpose. The original
    /// Initial/learned publication slot remains available for its own stage.
    pub(crate) fn take_original_historical_read(
        &mut self,
    ) -> Result<
        Arc<crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1>,
        AgentdError,
    > {
        let client = self.historical_read.take().ok_or_else(|| {
            AgentdError::GenerationFenced("original historical read absent or already taken".into())
        })?;
        crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1::require_same_original_session(&client, &self.root.session)?;
        Ok(client)
    }

    /// Take the actual separately received purpose offer before `run` consumes
    /// this launch. Retain it beside the original connection capability until
    /// the actual B and independently signed selection are available. This
    /// method does not connect, enroll or mutate CURRENT.
    pub fn take_generation_publication_handoff(
        &mut self,
    ) -> Result<crate::RootGenerationPublicationHandoffV1, AgentdError> {
        self.publication.take().ok_or_else(|| {
            AgentdError::Invalid("original publication handoff was absent or already taken".into())
        })
    }

    /// Take the independently received initial purpose once. The caller must
    /// use the original live connection and original selected target before
    /// configuring the returned Config; taking an offer changes no CURRENT.
    pub fn take_generation_initial_handoff(
        &mut self,
    ) -> Result<crate::RootGenerationInitialHandoffV1, AgentdError> {
        self.initial_publication.take().ok_or_else(|| {
            AgentdError::Invalid("original initial handoff was absent or already taken".into())
        })
    }

    /// Retain this single original connection capability before `run` consumes
    /// the launch. Exactly one initial or learned publication purpose can use
    /// it while the original runtime still owns the live Root session.
    pub fn take_generation_publication_connection(
        &mut self,
    ) -> Result<crate::RootGenerationPublicationConnectionV1, AgentdError> {
        let inputs: &mut AgentdRootProductionInputs = &mut self.root;
        inputs.take_generation_publication_connection()
    }

    /// Assemble the real learning owners after receiving their original Root
    /// capabilities and before starting ordinary Agentd. Returned owners accept
    /// only the later concrete B/C handoffs for this same operation.
    pub async fn assemble_q24_learning(
        mut self,
        config: AgentdConfig,
        inputs: crate::OriginalCellQ24LearningInputsV1,
    ) -> Result<
        (
            Self,
            AgentdConfig,
            crate::LearningIterationHandleV1,
            Arc<crate::OriginalCellQ24LearningStageOwnersV1>,
        ),
        AgentdError,
    > {
        let factory = self.q24_model.take().ok_or_else(|| {
            AgentdError::Invalid("original Root Model factory handoff is required".into())
        })?;
        let (config, handle, owners) = config
            .with_root_q24_learning_owners(factory, inputs)
            .await?;
        Ok((self, config, handle, owners))
    }

    /// Start the original configured MCP manager and retain its exact selected
    /// peer beside the same Root session and recovered writer until Agentd exits.
    /// This is a newly initialized original startup session, not a connector or
    /// an already running App Server thread's peer.
    pub async fn run(
        self,
        mut config: AgentdConfig,
        arg0_paths: Arg0DispatchPaths,
    ) -> Result<(), AgentdError> {
        config.require_root_learning_assembled()?;
        if self.post_a_handoffs.is_some() {
            return Err(AgentdError::GenerationFenced(
                "post-A learning handoffs must be installed before run".into(),
            ));
        }
        if self.initial_publication.is_some() {
            return Err(AgentdError::Invalid(
                "original initial handoff must be taken for actual initial publication before run"
                    .into(),
            ));
        }
        if self.publication.is_some() {
            return Err(AgentdError::Invalid(
                "original publication handoff must be taken for the later actual selection before run".into(),
            ));
        }
        if self.q24_model.is_some() {
            return Err(AgentdError::Invalid("original Root Model factory received, but concrete learning owners are not assembled".into()));
        }
        if let Some(capture) = self.original_source_capture {
            config.install_original_source_capture(capture)?;
        }
        if let Some(retained) = self.original_run_start_retention {
            config.install_original_run_start_retention(retained)?;
        }
        let RuntimeInputs {
            primary,
            notes,
            notes_ui,
        } = self.inputs;
        let mut mcp: Option<codex_app_server::ConfiguredMcpRuntime> = None;
        let mut android_device: Option<Arc<crate::AgentdAndroidTextDevice>> = None;
        let result = async {
            if matches!(&primary, PrimaryInputs::Desktop { .. })
                && (notes.is_some() || notes_ui.is_some())
            {
                return Err(AgentdError::Invalid(
                    "joint Desktop launch cannot consume legacy Notes inputs".into(),
                ));
            }
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
            let mut desktop_attachment = None;
            let mut initial_attachment = None;
            let (attachment, android_deadline) = match primary {
                PrimaryInputs::InitialQ24 { deployment }
                | PrimaryInputs::PostAQ24 { deployment } => {
                    if deployment.is_some() || notes.is_some() || notes_ui.is_some() {
                        return Err(AgentdError::GenerationFenced(
                            "Q24 must consume its deployment before run".into(),
                        ));
                    }
                    let (configured, retained) =
                        initial_q24::writer::attach(config, self.root, self.session_end).await?;
                    config = configured;
                    initial_attachment = Some(retained);
                    (None, None)
                }
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
                    (Some(attachment), Some(deadline))
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
                    (Some(attachment), None)
                }
                PrimaryInputs::Desktop {
                    handoff,
                    deployment,
                    session_pidfd,
                    deadline,
                } => {
                    // The real Root handoff above, including all original lanes,
                    // precedes this read of the late sealed joint deployment.
                    deadline.remaining()?;
                    let desktop_deployment::DesktopDeployment {
                        bindings,
                        peer,
                        startup_release,
                        route,
                        seed,
                        previous_recovery,
                    } = desktop_deployment::read(deployment, config.identity())?;
                    let session =
                        crate::AgentdNotesSessionLifetime::from_inherited(session_pidfd, &peer)?;
                    deadline.remaining()?;
                    session.check_alive()?;
                    let joint = attach_root_desktop_operation_host_with_startup_before(
                        &mut config,
                        self.root,
                        handoff,
                        Duration::from_millis(100),
                        startup_release,
                        deadline,
                    )
                    .await?;
                    deadline.remaining()?;
                    session.check_alive()?;
                    config = config.with_root_desktop_thread_tools(
                        &joint,
                        bindings,
                        route,
                        seed,
                        session,
                        Duration::from_secs(10),
                    )?;
                    deadline.remaining()?;
                    if let Some((notes, calculator)) = previous_recovery {
                        config = config
                            .with_original_desktop_previous_recovery_requests(
                                notes, calculator, deadline,
                            )
                            .await?;
                        deadline.remaining()?;
                    }
                    // Retain the whole joint attachment, including Calculator's
                    // read-only observer, until the original runtime stops.
                    desktop_attachment = Some(joint);
                    (None, None)
                }
            };
            if let Some((deployment, listener, session_pidfd)) = notes_ui {
                let original = attachment.as_ref().ok_or_else(|| {
                    AgentdError::Invalid("legacy Notes UI has no original Root attachment".into())
                })?;
                let notes_deployment::NotesDeployment {
                    bindings,
                    peer,
                    previous_recovery,
                    startup_release: _,
                    interaction,
                } = deployment;
                let peer = crate::AgentdNotesUiPeer {
                    uid: peer.uid,
                    pid: peer.pid,
                    boot_id: peer.boot_id,
                    process_start_ticks: peer.process_start_ticks,
                };
                match interaction {
                    crate::notes_launch_mode::NotesLaunchMode::LiteralUiV1 => {
                        let (configured, adapter) = config.with_root_notes_literal_adapter(
                            original,
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
                                original,
                                bindings,
                                route,
                                Duration::from_secs(10),
                            )?
                            .with_original_notes_thread_seed(*seed)?
                            .with_original_notes_thread_session(lifetime)?;
                        // The explicit model profile admits no literal UI
                        // endpoint. Root retains pathname cleanup custody.
                        drop(listener);
                    }
                }
                if let Some(previous) = previous_recovery {
                    config = config
                        .with_original_notes_previous_recovery_request(previous)
                        .await?;
                }
            }
            if let Some(deadline) = android_deadline {
                remaining(deadline)?;
            }
            let result = crate::run(config, arg0_paths).await;
            // Keep the authenticated Root feed and original checkpoint/grant
            // handles alive until all original runtime workers have stopped.
            drop((attachment, desktop_attachment, initial_attachment));
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
