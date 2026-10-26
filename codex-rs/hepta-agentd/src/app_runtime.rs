use std::collections::BTreeMap;
use std::num::NonZeroUsize;
use std::sync::Arc;

use codex_app_server::AppServerRuntimeOptions;
use codex_app_server::AppServerTransport;
use codex_app_server::AppServerWebsocketAuthSettings;
use codex_app_server::RemoteControlStartupMode;
use codex_app_server::ThreadStoreConfig;
use codex_arg0::Arg0DispatchPaths;
use codex_config::LoaderOverrides;
use codex_features::Feature;
use codex_hepta_memory::CognitiveRuntime;
use codex_protocol::protocol::SessionSource;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_cli::CliConfigOverrides;

use crate::AgentdIdentity;
use crate::AgentdState;
use crate::error::contextual_io_error;
use crate::qualification_writer::qualification_turn_writer_host;

#[cfg(feature = "production-cognitive-write")]
const COGNITIVE_WRITE_ENABLED: bool = true;
#[cfg(not(feature = "production-cognitive-write"))]
const COGNITIVE_WRITE_ENABLED: bool = false;

#[cfg(feature = "qualification-cognitive-write")]
const QUALIFICATION_TURN_WRITER_ENABLED: bool = true;
#[cfg(not(feature = "qualification-cognitive-write"))]
const QUALIFICATION_TURN_WRITER_ENABLED: bool = false;

pub(crate) enum AppServerSocket {
    Bind,
    #[cfg(target_os = "linux")]
    RootBound(std::os::fd::OwnedFd),
}

/// The original Notes adapter owns its three dynamic tools outside Core's
/// general cognitive tool extension. This selection removes model capability;
/// it does not remove the externally retained Root Notes writer.
#[derive(Clone, Copy)]
pub(crate) enum AppServerModelToolProfile {
    Standard,
    #[cfg(target_os = "linux")]
    OriginalNotes,
}

impl AppServerModelToolProfile {
    fn cognitive_tools_enabled(self) -> bool {
        match self {
            Self::Standard => true,
            #[cfg(target_os = "linux")]
            Self::OriginalNotes => false,
        }
    }
}

pub(crate) async fn run_app_server(
    identity: AgentdIdentity,
    arg0_paths: Arg0DispatchPaths,
    cognitive_runtime: CognitiveRuntime,
    state: Arc<AgentdState>,
    production_writer_host: Option<Arc<crate::AgentdProductionWriterHost>>,
    socket: AppServerSocket,
    model_tools: AppServerModelToolProfile,
) -> std::io::Result<()> {
    let socket_path = AbsolutePathBuf::from_absolute_path(&identity.app_server_socket)?;
    let production_mutation: Option<Arc<dyn codex_hepta_memory::ProductionCognitiveMutation>> =
        production_writer_host.and_then(|host| host.production_mutation());
    let cognitive_write_enabled = model_tools.cognitive_tools_enabled()
        && (COGNITIVE_WRITE_ENABLED || production_mutation.is_some());
    let config_overrides = app_server_config_overrides(cognitive_write_enabled, model_tools);
    let runtime_options = app_server_runtime_options_for_agent(
        &identity,
        state,
        cognitive_runtime,
        production_mutation,
        model_tools,
    )?;
    let result = match socket {
        AppServerSocket::Bind => {
            codex_app_server::run_main_with_transport_options(
                arg0_paths,
                config_overrides,
                LoaderOverrides::default(),
                /*strict_config*/ true,
                /*default_analytics_enabled*/ false,
                AppServerTransport::UnixSocket { socket_path },
                SessionSource::Custom("hepta-agentd".to_string()),
                AppServerWebsocketAuthSettings::default(),
                runtime_options,
            )
            .await
        }
        #[cfg(target_os = "linux")]
        AppServerSocket::RootBound(socket) => {
            let socket = crate::listen_root_bound_socket(socket, socket_path.as_path())
                .map_err(std::io::Error::other)?;
            let listener =
                codex_app_server::InheritedControlSocket::from_inherited(socket, socket_path)?;
            codex_app_server::run_main_with_inherited_unix_listener(
                arg0_paths,
                config_overrides,
                LoaderOverrides::default(),
                /*strict_config*/ true,
                /*default_analytics_enabled*/ false,
                listener,
                SessionSource::Custom("hepta-agentd".to_string()),
                AppServerWebsocketAuthSettings::default(),
                runtime_options,
            )
            .await
        }
    };
    result.map_err(|error| {
        contextual_io_error(
            /* operation */ "run Codex App Server unix socket transport",
            /* path */ &identity.app_server_socket,
            /* source */ error,
        )
    })
}

fn app_server_config_overrides(
    cognitive_write_enabled: bool,
    model_tools: AppServerModelToolProfile,
) -> CliConfigOverrides {
    CliConfigOverrides {
        raw_overrides: vec![
            "features.hepta_governance=true".to_string(),
            "features.hepta_turn_recovery=true".to_string(),
            format!(
                "features.hepta_memory={}",
                model_tools.cognitive_tools_enabled()
            ),
            "features.hepta_memory_read_only=true".to_string(),
            // Agentd exposes the product cognitive feature, while actual mutation
            // tools still require the externally verified production capability
            // or the explicitly compiled qualification witness profile.
            format!("features.hepta_cognitive_write={cognitive_write_enabled}"),
        ],
    }
}

#[cfg(test)]
pub(crate) fn app_server_runtime_options(
    identity: &AgentdIdentity,
    cognitive_runtime: CognitiveRuntime,
) -> std::io::Result<AppServerRuntimeOptions> {
    app_server_runtime_options_with_writer(
        identity,
        cognitive_runtime,
        /*production_cognitive_mutation*/ None,
        /*qualification_turn_writer*/ None,
        /*prompt_runtime_host*/ None,
        /*graceful_drain*/ None,
        AppServerModelToolProfile::Standard,
    )
}

pub(crate) fn app_server_runtime_options_for_agent(
    identity: &AgentdIdentity,
    state: Arc<AgentdState>,
    cognitive_runtime: CognitiveRuntime,
    production_cognitive_mutation: Option<Arc<dyn codex_hepta_memory::ProductionCognitiveMutation>>,
    model_tools: AppServerModelToolProfile,
) -> std::io::Result<AppServerRuntimeOptions> {
    let prompt_runtime_host = state
        .prompt_pipeline_owner()
        .runtime_owner()
        .host()
        .map_err(std::io::Error::other)?;
    let graceful_drain = state.app_server_drain_handle();
    let writer = qualification_turn_writer_host(identity, state, &cognitive_runtime);
    app_server_runtime_options_with_writer(
        identity,
        cognitive_runtime,
        production_cognitive_mutation,
        writer,
        Some(prompt_runtime_host),
        Some(graceful_drain),
        model_tools,
    )
}

fn app_server_runtime_options_with_writer(
    identity: &AgentdIdentity,
    cognitive_runtime: CognitiveRuntime,
    production_cognitive_mutation: Option<Arc<dyn codex_hepta_memory::ProductionCognitiveMutation>>,
    qualification_turn_writer: Option<codex_hepta_memory_extension::QualificationTurnWriterHost>,
    prompt_runtime_host: Option<codex_hepta_codex_adapter::PromptRuntimeHost>,
    graceful_drain: Option<codex_app_server::AppServerDrainHandle>,
    model_tools: AppServerModelToolProfile,
) -> std::io::Result<AppServerRuntimeOptions> {
    let cognitive_tools_enabled = model_tools.cognitive_tools_enabled();
    let cognitive_write_enabled = cognitive_tools_enabled
        && (COGNITIVE_WRITE_ENABLED || production_cognitive_mutation.is_some());
    let production_cognitive_mutation =
        production_cognitive_mutation.filter(|_| cognitive_tools_enabled);
    let mut required_feature_states =
        BTreeMap::from([(Feature::HeptaCognitiveWrite, cognitive_write_enabled)]);
    if !cognitive_tools_enabled {
        // Applied after every request override. A model-backed Notes session
        // cannot reopen general cognitive tools through a new Core config.
        required_feature_states.insert(Feature::HeptaMemory, false);
    }
    let turn_queue_capacity = usize::try_from(identity.resources.turn_queue_capacity)
        .map_err(|_| std::io::Error::other("turn queue capacity does not fit this platform"))?;
    let turn_queue_capacity = NonZeroUsize::new(turn_queue_capacity).ok_or_else(|| {
        std::io::Error::other("agent manifest contains a zero turn queue capacity")
    })?;
    Ok(AppServerRuntimeOptions {
        remote_control_startup_mode: RemoteControlStartupMode::DisabledEphemeral,
        install_shutdown_signal_handler: false,
        graceful_drain,
        turn_queue_capacity: Some(turn_queue_capacity),
        required_sqlite_home: Some(AbsolutePathBuf::from_absolute_path(&identity.home_root)?),
        required_thread_store_mode: Some(ThreadStoreConfig::Local),
        hepta_cognitive_runtime: cognitive_runtime,
        hepta_cognitive_production_mutation: production_cognitive_mutation,
        // The owning agent supplies the qualification-only policy to the
        // explicit host owner.  The legacy turn callback remains disabled:
        // policy-gated local witness writes must be host-invoked and must not
        // create an unbound lease implicitly during turn startup.
        hepta_local_turn_lifecycle_enabled: false,
        hepta_local_development_policy: QUALIFICATION_TURN_WRITER_ENABLED
            .then_some(codex_hepta_memory::LocalDevelopmentLifecyclePolicy::qualification_only()),
        hepta_qualification_turn_writer_enabled: QUALIFICATION_TURN_WRITER_ENABLED,
        hepta_qualification_turn_writer: qualification_turn_writer,
        hepta_prompt_runtime_host: prompt_runtime_host,
        // This embedding-owned product capability is applied after managed
        // config and per-request overrides. Agentd therefore selects the
        // scoped cognitive mutation profile; ordinary Codex does not.
        required_feature_states,
        ..Default::default()
    })
}

#[cfg(test)]
mod tests {
    use codex_features::Feature;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_paths::HeptaFleetRoot;

    use super::COGNITIVE_WRITE_ENABLED;
    use super::QUALIFICATION_TURN_WRITER_ENABLED;
    use super::app_server_config_overrides;
    use super::app_server_runtime_options;
    use crate::AgentdIdentity;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

    #[test]
    fn agentd_forces_hepta_turn_recovery_on() {
        let overrides = app_server_config_overrides(
            COGNITIVE_WRITE_ENABLED,
            super::AppServerModelToolProfile::Standard,
        );
        assert!(
            overrides
                .raw_overrides
                .iter()
                .any(|value| value == "features.hepta_turn_recovery=true")
        );
    }

    #[test]
    fn agentd_forces_explicit_cognitive_write_profile_state() {
        let overrides = app_server_config_overrides(
            COGNITIVE_WRITE_ENABLED,
            super::AppServerModelToolProfile::Standard,
        );
        assert!(overrides.raw_overrides.iter().any(|value| {
            value == &format!("features.hepta_cognitive_write={COGNITIVE_WRITE_ENABLED}")
        }));
    }

    #[test]
    fn manifest_queue_capacity_reaches_app_server_runtime_options_exactly() {
        let agent_id = AgentId::parse(AGENT_ID).expect("valid agent id");
        let fleet_root_path = std::env::temp_dir().join("hepta-agentd-capacity-test");
        let fleet_root = HeptaFleetRoot::parse(fleet_root_path).expect("valid fleet root");
        let layout = fleet_root.layout().agent(&agent_id);
        let mut resources = ResourceBudget::local_default();
        resources.turn_queue_capacity = 37;
        let identity = AgentdIdentity {
            agent_id,
            workspace: std::env::temp_dir().join("hepta-agentd-capacity-workspace"),
            home_root: layout.home_root().to_path_buf(),
            run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(),
            app_server_socket: layout.app_server_socket().to_path_buf(),
            layout,
            spawn_generation: 1,
            fleet_root: fleet_root.as_path().to_path_buf(),
            resources,
        };

        let options =
            app_server_runtime_options(&identity, codex_hepta_memory::CognitiveRuntime::Absent)
                .expect("valid runtime options");
        assert_eq!(
            Some(37),
            options.turn_queue_capacity.map(std::num::NonZeroUsize::get)
        );
        assert_eq!(
            Some(identity.home_root.as_path()),
            options
                .required_sqlite_home
                .as_ref()
                .map(codex_utils_absolute_path::AbsolutePathBuf::as_path)
        );
        assert_eq!(
            Some(&codex_app_server::ThreadStoreConfig::Local),
            options.required_thread_store_mode.as_ref()
        );
        assert!(!options.hepta_local_turn_lifecycle_enabled);
        assert_eq!(
            QUALIFICATION_TURN_WRITER_ENABLED.then_some(
                codex_hepta_memory::LocalDevelopmentLifecyclePolicy::qualification_only()
            ),
            options.hepta_local_development_policy
        );
        assert_eq!(
            QUALIFICATION_TURN_WRITER_ENABLED,
            options.hepta_qualification_turn_writer_enabled
        );
        assert_eq!(
            Some(&COGNITIVE_WRITE_ENABLED),
            options
                .required_feature_states
                .get(&Feature::HeptaCognitiveWrite)
        );
    }

    #[cfg(target_os = "linux")]
    #[tokio::test]
    async fn notes_embedding_keeps_the_store_but_removes_general_cognitive_tool_state() {
        use codex_hepta_fleet::AgentManifest;
        use codex_hepta_fleet::FleetRegistry;
        use codex_hepta_fleet::WorkspaceBinding;
        use codex_hepta_memory::CognitiveRuntime;
        use codex_hepta_memory::CognitiveStore;
        use codex_hepta_memory_extension::HeptaMemoryFeatureFlags;
        use codex_hepta_memory_extension::HeptaMemoryThreadConfig;
        use std::sync::Arc;

        let temp = tempfile::tempdir().expect("private fixture");
        let root = temp.path().canonicalize().expect("canonical fixture");
        let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet path");
        let registry = FleetRegistry::initialize(fleet.clone()).expect("original registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let record = registry
            .register(
                AgentManifest::new(
                    AgentId::parse(AGENT_ID).expect("agent"),
                    WorkspaceBinding::new(workspace.clone(), &fleet).expect("workspace binding"),
                    ResourceBudget::local_default(),
                )
                .expect("manifest"),
            )
            .expect("register original agent");
        let identity = crate::AgentdIdentity {
            agent_id: record.manifest.agent_id,
            home_root: record.layout.home_root().into(),
            run_root: record.layout.run_root().into(),
            control_socket: record.layout.agentd_control_socket().into(),
            app_server_socket: record.layout.app_server_socket().into(),
            layout: record.layout,
            spawn_generation: 1,
            fleet_root: fleet.as_path().into(),
            workspace,
            resources: record.manifest.resources,
        };
        let store = Arc::new(
            CognitiveStore::open(&identity.layout)
                .await
                .expect("actual store"),
        );
        let options = super::app_server_runtime_options_with_writer(
            &identity,
            CognitiveRuntime::Available(store.clone()),
            /*production_cognitive_mutation*/ None,
            /*qualification_turn_writer*/ None,
            /*prompt_runtime_host*/ None,
            /*graceful_drain*/ None,
            super::AppServerModelToolProfile::OriginalNotes,
        )
        .expect("Notes runtime options");
        assert!(Arc::ptr_eq(
            options
                .hepta_cognitive_runtime
                .available_store()
                .expect("retained store"),
            &store
        ));

        // Simulate a later config/request trying to reopen both features. The
        // actual embedding constraints must still prevent the original
        // extension from creating the state that contributes cognitive tools.
        let mut features = codex_features::Features::with_defaults();
        features
            .enable(Feature::HeptaGovernance)
            .enable(Feature::HeptaMemory)
            .enable(Feature::HeptaCognitiveWrite);
        let mut standard_features = features.clone();
        let standard =
            super::app_server_runtime_options(&identity, CognitiveRuntime::Available(store))
                .expect("ordinary product runtime options");
        for (feature, enabled) in standard.required_feature_states {
            standard_features.set_enabled(feature, enabled);
        }
        assert!(
            HeptaMemoryThreadConfig::for_features(HeptaMemoryFeatureFlags {
                governance_enabled: standard_features.enabled(Feature::HeptaGovernance),
                memory_enabled: standard_features.enabled(Feature::HeptaMemory),
                read_only_enabled: true,
                write_enabled: standard_features.enabled(Feature::HeptaCognitiveWrite),
            })
            .is_some()
        );
        for (feature, enabled) in options.required_feature_states {
            features.set_enabled(feature, enabled);
        }
        assert!(
            HeptaMemoryThreadConfig::for_features(HeptaMemoryFeatureFlags {
                governance_enabled: features.enabled(Feature::HeptaGovernance),
                memory_enabled: features.enabled(Feature::HeptaMemory),
                read_only_enabled: true,
                write_enabled: features.enabled(Feature::HeptaCognitiveWrite),
            })
            .is_none()
        );
        assert!(features.enabled(Feature::HeptaGovernance));
        assert!(!features.enabled(Feature::HeptaCognitiveWrite));
    }
}
