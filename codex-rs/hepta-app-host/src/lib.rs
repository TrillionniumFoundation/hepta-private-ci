//! Stable host façade for embedding Codex App Server in Hepta Agentd.
//!
//! Agentd supplies already-admitted owner capabilities and process geometry;
//! this crate alone knows App Server implementation types and startup details.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::num::NonZeroUsize;
use std::path::PathBuf;
use std::sync::Arc;

use codex_app_server::AppServerRuntimeOptions;
use codex_app_server::AppServerTransport;
use codex_app_server::AppServerWebsocketAuthSettings;
use codex_app_server::RemoteControlStartupMode;
use codex_app_server::ThreadStoreConfig;
use codex_arg0::Arg0DispatchPaths;
use codex_config::LoaderOverrides;
use codex_features::Feature;
use codex_hepta_app_bridge::memory::CognitiveRuntime;
use codex_hepta_app_bridge::memory::ProductionCognitiveMutation;
use codex_protocol::protocol::SessionSource;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_cli::CliConfigOverrides;

pub use codex_app_server::AppServerDrainHandle;
pub use codex_app_server::QueueHistoricalObservation;
pub use codex_app_server::QueueHistoricalOutcome;
pub use codex_app_server::QueueHistoricalTerminal;
pub struct HeptaAppServerHostOptions {
    pub socket_path: PathBuf,
    pub home_root: PathBuf,
    /// Credential storage selected by trusted daemon startup, never an RPC.
    pub credential_profile_home: Option<PathBuf>,
    pub turn_queue_capacity: u64,
    pub cognitive_runtime: CognitiveRuntime,
    pub production_cognitive_mutation: Option<Arc<dyn ProductionCognitiveMutation>>,
    pub qualification_turn_writer:
        Option<codex_hepta_app_bridge::memory_extension::QualificationTurnWriterHost>,
    pub prompt_runtime_host: Option<codex_hepta_app_bridge::prompt_extension::PromptRuntimeHost>,
    pub graceful_drain: Option<AppServerDrainHandle>,
    pub cognitive_write_profile: bool,
    pub qualification_turn_writer_profile: bool,
}

impl HeptaAppServerHostOptions {
    pub fn effective_cognitive_write(&self) -> bool {
        self.cognitive_write_profile || self.production_cognitive_mutation.is_some()
    }
}

pub fn config_overrides(cognitive_write_enabled: bool) -> CliConfigOverrides {
    CliConfigOverrides {
        raw_overrides: vec![
            "features.hepta_governance=true".to_string(),
            "features.hepta_turn_recovery=true".to_string(),
            "features.hepta_memory=true".to_string(),
            "features.hepta_memory_read_only=true".to_string(),
            format!("features.hepta_cognitive_write={cognitive_write_enabled}"),
        ],
    }
}

fn relay_config_overrides(
    cognitive_write_enabled: bool,
    relay_enabled: bool,
) -> CliConfigOverrides {
    let mut overrides = config_overrides(cognitive_write_enabled);
    if relay_enabled {
        overrides.raw_overrides.extend([
            "model_provider=\"hepta-relay\"".to_owned(),
            "model_providers.hepta-relay.name=\"Hepta model authority\"".to_owned(),
            "model_providers.hepta-relay.base_url=\"http://localhost/hepta/v1\"".to_owned(),
            "model_providers.hepta-relay.wire_api=\"responses\"".to_owned(),
            "model_providers.hepta-relay.requires_openai_auth=false".to_owned(),
            "model_providers.hepta-relay.supports_websockets=false".to_owned(),
            "model_providers.hepta-relay.request_max_retries=0".to_owned(),
            "model_providers.hepta-relay.stream_max_retries=0".to_owned(),
        ]);
    }
    overrides
}
pub fn runtime_options(
    options: HeptaAppServerHostOptions,
) -> std::io::Result<AppServerRuntimeOptions> {
    let cognitive_write_enabled = options.effective_cognitive_write();
    let turn_queue_capacity = usize::try_from(options.turn_queue_capacity)
        .map_err(|_| std::io::Error::other("turn queue capacity does not fit this platform"))?;
    let turn_queue_capacity = NonZeroUsize::new(turn_queue_capacity).ok_or_else(|| {
        std::io::Error::other("agent manifest contains a zero turn queue capacity")
    })?;
    Ok(AppServerRuntimeOptions {
        remote_control_startup_mode: RemoteControlStartupMode::DisabledEphemeral,
        install_shutdown_signal_handler: false,
        graceful_drain: options.graceful_drain,
        turn_queue_capacity: Some(turn_queue_capacity),
        required_sqlite_home: Some(AbsolutePathBuf::from_absolute_path(&options.home_root)?),
        credential_profile_home: options
            .credential_profile_home
            .map(AbsolutePathBuf::from_absolute_path)
            .transpose()?,
        required_thread_store_mode: Some(ThreadStoreConfig::Local),
        hepta_cognitive_runtime: options.cognitive_runtime,
        hepta_cognitive_production_mutation: options.production_cognitive_mutation,
        hepta_local_turn_lifecycle_enabled: false,
        hepta_local_development_policy: options.qualification_turn_writer_profile.then_some(
            codex_hepta_app_bridge::memory::LocalDevelopmentLifecyclePolicy::qualification_only(),
        ),
        hepta_qualification_turn_writer_enabled: options.qualification_turn_writer_profile,
        hepta_qualification_turn_writer: options.qualification_turn_writer,
        hepta_prompt_runtime_host: options.prompt_runtime_host,
        required_feature_states: BTreeMap::from([(
            Feature::HeptaCognitiveWrite,
            cognitive_write_enabled,
        )]),
        ..Default::default()
    })
}
pub async fn run(
    arg0_paths: Arg0DispatchPaths,
    options: HeptaAppServerHostOptions,
) -> std::io::Result<()> {
    let relay_enabled = std::env::var_os("HEPTA_MODEL_RELAY_SOCKET").is_some();
    if relay_enabled && options.credential_profile_home.is_some() {
        return Err(std::io::Error::other(
            "model relay cannot expose a credential profile to the workload",
        ));
    }
    let socket_path_raw = options.socket_path.clone();
    let socket_path = AbsolutePathBuf::from_absolute_path(&socket_path_raw)?;
    let cognitive_write_enabled = options.effective_cognitive_write();
    let runtime_options = runtime_options(options)?;
    codex_app_server::run_main_with_transport_options(
        arg0_paths,
        relay_config_overrides(cognitive_write_enabled, relay_enabled),
        LoaderOverrides::default(),
        true,
        false,
        AppServerTransport::UnixSocket { socket_path },
        SessionSource::Custom("hepta-agentd".to_string()),
        AppServerWebsocketAuthSettings::default(),
        runtime_options,
    )
    .await
    .map_err(|error| {
        std::io::Error::new(
            error.kind(),
            format!(
                "run Codex App Server unix socket transport at {}: {error}",
                socket_path_raw.display()
            ),
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options(turn_queue_capacity: u64) -> HeptaAppServerHostOptions {
        HeptaAppServerHostOptions {
            socket_path: std::env::temp_dir().join("hepta-app-host-test.sock"),
            home_root: std::env::temp_dir().join("hepta-app-host-home"),
            credential_profile_home: None,
            turn_queue_capacity,
            cognitive_runtime: CognitiveRuntime::Absent,
            production_cognitive_mutation: None,
            qualification_turn_writer: None,
            prompt_runtime_host: None,
            graceful_drain: None,
            cognitive_write_profile: false,
            qualification_turn_writer_profile: false,
        }
    }

    #[test]
    fn overrides_keep_recovery_and_cognitive_profile_explicit() {
        let overrides = config_overrides(true);
        assert!(
            overrides
                .raw_overrides
                .iter()
                .any(|value| value == "features.hepta_turn_recovery=true")
        );
        assert!(
            overrides
                .raw_overrides
                .iter()
                .any(|value| value == "features.hepta_cognitive_write=true")
        );
    }

    #[test]
    fn runtime_options_preserve_manifest_capacity_and_fail_closed_defaults() {
        let options = options(37);
        let home_root = options.home_root.clone();
        let runtime = runtime_options(options).expect("valid host options");
        assert_eq!(Some(37), runtime.turn_queue_capacity.map(NonZeroUsize::get));
        assert_eq!(
            Some(home_root.as_path()),
            runtime
                .required_sqlite_home
                .as_ref()
                .map(AbsolutePathBuf::as_path)
        );
        assert_eq!(
            Some(&ThreadStoreConfig::Local),
            runtime.required_thread_store_mode.as_ref()
        );
        assert!(!runtime.hepta_local_turn_lifecycle_enabled);
        assert!(runtime.hepta_local_development_policy.is_none());
        assert_eq!(
            Some(&false),
            runtime
                .required_feature_states
                .get(&Feature::HeptaCognitiveWrite)
        );
    }

    #[test]
    fn zero_turn_queue_capacity_is_rejected() {
        let error = runtime_options(options(0)).expect_err("zero queue must fail");
        assert_eq!(std::io::ErrorKind::Other, error.kind());
    }

    #[test]
    fn explicit_shared_credential_profile_preserves_two_private_state_roots() {
        let profile = std::env::temp_dir().join("shared-test-credential-profile");
        let homes = [
            std::env::temp_dir().join("agent-a-private-home"),
            std::env::temp_dir().join("agent-b-private-home"),
        ];
        for home in homes {
            let mut host = options(/*turn_queue_capacity*/ 37);
            host.home_root = home.clone();
            host.credential_profile_home = Some(profile.clone());
            let runtime = runtime_options(host).expect("explicit profile binding");
            assert_eq!(
                Some(home.as_path()),
                runtime
                    .required_sqlite_home
                    .as_ref()
                    .map(AbsolutePathBuf::as_path)
            );
            assert_eq!(
                Some(profile.as_path()),
                runtime
                    .credential_profile_home
                    .as_ref()
                    .map(AbsolutePathBuf::as_path)
            );
        }
        let runtime = runtime_options(options(/*turn_queue_capacity*/ 37))
            .expect("default private credentials");
        assert!(runtime.credential_profile_home.is_none());
    }
}
