//! Doc-hidden in-process Agentd host for cross-crate product qualification.
//!
//! The helper is compiled under the same dependency/features as the Agentd
//! library so qualification cannot select a stronger product feature set. It
//! starts the real Agentd control socket and App Server over a real fleet layout
//! and the canonical SQLite cognitive owner. External test consumers receive
//! only the public control client and bounded mutation fixtures; no AgentdState
//! handle, runtime authority, deployment authority, or control-protocol bypass
//! is exported.

use std::error::Error as StdError;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory::SourceRevisionId;
use codex_hepta_memory::StableMemoryId;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use crate::AgentdClient;
use crate::AgentdControlServer;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::app_runtime::run_app_server;

pub type TestResult<T> = Result<T, Box<dyn StdError + Send + Sync>>;

const READY_TIMEOUT: Duration = Duration::from_secs(10);
const EVENT_CAPACITY: usize = 32;

#[derive(Clone, Debug)]
pub struct SeededMemory {
    memory_id: StableMemoryId,
    citation: SourceRevisionId,
    expected_revision: u64,
}

pub struct CognitiveTestHost {
    _root: PathBuf,
    agent_id: AgentId,
    layout: HeptaAgentLayout,
    store: Arc<CognitiveStore>,
    cancellation: CancellationToken,
    control_task: Option<JoinHandle<Result<(), crate::AgentdError>>>,
    app_server_task: Option<JoinHandle<std::io::Result<()>>>,
}

impl CognitiveTestHost {
    pub async fn start(
        root: PathBuf,
        agent_id: AgentId,
        model: &str,
        provider_base_url: &str,
        codex_executable: PathBuf,
    ) -> TestResult<Self> {
        // Require a real, explicitly built dispatch-capable executable. A test
        // harness current_exe() or an absent path cannot stand in for Codex.
        let codex_executable = codex_executable.canonicalize()?;
        if !codex_executable.is_file() {
            return Err("Agentd test Codex executable must be a regular file".into());
        }
        validate_config_scalar(model, "model")?;
        validate_config_scalar(provider_base_url, "provider base URL")?;
        std::fs::create_dir_all(&root)?;
        let root = root.canonicalize()?;
        let fleet_path = root.join("fleet");
        let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace)?;
        let workspace = workspace.canonicalize()?;
        let binding = WorkspaceBinding::new(&workspace, &fleet_root)?;
        let manifest =
            AgentManifest::new(agent_id.clone(), binding, ResourceBudget::local_default())?;
        let record = registry.register(manifest)?;
        registry.compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)?;
        std::fs::create_dir_all(record.layout.home_root())?;
        std::fs::create_dir_all(record.layout.run_root())?;
        write_model_config(record.layout.home_root(), model, provider_base_url)?;

        let identity = AgentdIdentity {
            agent_id: agent_id.clone(),
            layout: record.layout.clone(),
            spawn_generation: 1,
            fleet_root: fleet_path,
            workspace,
            resources: record.manifest.resources,
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: record.layout.app_server_socket().to_path_buf(),
        };
        let state = Arc::new(AgentdState::new(
            identity.clone(),
            registry.clone(),
            EVENT_CAPACITY,
        )?);
        let store = Arc::new(CognitiveStore::open(&identity.layout).await?);
        state.attach_cognitive_store(Arc::clone(&store))?;
        // Use the same owner-readiness boundary as the normal daemon. A bound
        // socket alone must not open admission before its stores are ready.
        state.mark_runtime_prerequisites_ready()?;
        registry.compare_and_transition(&agent_id, 1, AgentLifecycle::Running)?;
        state.refresh_generation()?;

        codex_utils_home_dir::set_process_codex_home_override(
            AbsolutePathBuf::from_absolute_path(identity.home_root.clone())?,
        )?;

        let cancellation = CancellationToken::new();
        let control = AgentdControlServer::bind(
            identity.control_socket.clone(),
            Arc::clone(&state),
            cancellation.clone(),
        )
        .await?;
        let control_task = tokio::spawn(control.run());
        let app_server_task = tokio::spawn(run_app_server(
            identity.clone(),
            Arg0DispatchPaths {
                codex_self_exe: Some(codex_executable),
                ..Default::default()
            },
            CognitiveRuntime::Available(Arc::clone(&store)),
            Arc::clone(&state),
            /*production_writer_host*/ None,
        ));

        let deadline = Instant::now() + READY_TIMEOUT;
        while !identity.app_server_socket.exists() {
            if app_server_task.is_finished() {
                let outcome = app_server_task.await?;
                return Err(
                    format!("Agentd test App Server exited before readiness: {outcome:?}").into(),
                );
            }
            if Instant::now() >= deadline {
                return Err("timed out waiting for Agentd test App Server socket".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        state.mark_app_server_ready()?;

        let client = AgentdClient::new(identity.control_socket.clone(), agent_id.clone(), 1)?;
        let deadline = Instant::now() + READY_TIMEOUT;
        loop {
            match client.health().await {
                Ok(health) if health.ready => break,
                _ if Instant::now() >= deadline => {
                    return Err("timed out waiting for Agentd test control readiness".into());
                }
                _ => tokio::time::sleep(Duration::from_millis(10)).await,
            }
        }

        Ok(Self {
            _root: root,
            agent_id,
            layout: identity.layout,
            store,
            cancellation,
            control_task: Some(control_task),
            app_server_task: Some(app_server_task),
        })
    }

    pub fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    pub fn control_socket(&self) -> &Path {
        self.layout.agentd_control_socket()
    }

    pub async fn seed_verified_memory(
        &self,
        stable_key: &str,
        content: &str,
    ) -> TestResult<SeededMemory> {
        let access = CognitiveAccess::agent_private(self.agent_id.clone());
        let scope = CognitiveScope::AgentPrivate;
        let now = now_seconds()?;
        let citation = self
            .store
            .append_source(
                &access,
                &SourceDraft {
                    scope: scope.clone(),
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: format!("cognitive-worker-race:{stable_key}:{now}"),
                    content: content.as_bytes().to_vec(),
                    observed_at_unix_seconds: now,
                },
            )
            .await?;
        let memory = self
            .store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: stable_key.to_string(),
                    revision: MemoryRevisionDraft {
                        scope,
                        content: content.to_string(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: now,
                        valid_to_unix_seconds: None,
                        citations: vec![citation.clone()],
                    },
                },
            )
            .await?;
        Ok(SeededMemory {
            memory_id: memory.id.memory_id,
            citation,
            expected_revision: memory.id.revision,
        })
    }

    pub async fn tombstone(&self, memory: &SeededMemory, reason: &str) -> TestResult<()> {
        let access = CognitiveAccess::agent_private(self.agent_id.clone());
        self.store
            .forget_memory(
                &access,
                &memory.memory_id,
                memory.expected_revision,
                &ForgetMemoryDraft {
                    scope: CognitiveScope::AgentPrivate,
                    reason: reason.to_string(),
                    valid_from_unix_seconds: now_seconds()?,
                    citations: vec![memory.citation.clone()],
                },
            )
            .await?;
        Ok(())
    }

    pub async fn correct(&self, memory: &SeededMemory, content: &str) -> TestResult<()> {
        let access = CognitiveAccess::agent_private(self.agent_id.clone());
        self.store
            .correct_memory(
                &access,
                &memory.memory_id,
                memory.expected_revision,
                &MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: content.to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: now_seconds()?,
                    valid_to_unix_seconds: None,
                    citations: vec![memory.citation.clone()],
                },
            )
            .await?;
        Ok(())
    }

    pub async fn shutdown(mut self) {
        self.cancellation.cancel();
        if let Some(task) = self.control_task.take() {
            task.abort();
            let _ = task.await;
        }
        if let Some(task) = self.app_server_task.take() {
            task.abort();
            let _ = task.await;
        }
    }
}

impl Drop for CognitiveTestHost {
    fn drop(&mut self) {
        self.cancellation.cancel();
        if let Some(task) = self.control_task.as_ref() {
            task.abort();
        }
        if let Some(task) = self.app_server_task.as_ref() {
            task.abort();
        }
    }
}

fn validate_config_scalar(value: &str, label: &str) -> TestResult<()> {
    if value.is_empty()
        || value
            .chars()
            .any(|character| matches!(character, '"' | '\n' | '\r'))
    {
        return Err(format!("invalid {label}").into());
    }
    Ok(())
}

fn write_model_config(home: &Path, model: &str, provider_base_url: &str) -> std::io::Result<()> {
    std::fs::write(
        home.join("config.toml"),
        format!(
            r#"
model = "{model}"
approval_policy = "never"
sandbox_mode = "read-only"
model_provider = "cognitive_worker_race"

[model_providers.cognitive_worker_race]
name = "Cognitive worker race qualification"
base_url = "{provider_base_url}"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
"#
        ),
    )
}

fn now_seconds() -> TestResult<i64> {
    let seconds = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    Ok(i64::try_from(seconds)?)
}
