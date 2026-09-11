use std::future::Future;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_arg0::Arg0DispatchPaths;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationStore;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::FederatedRecallSet;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::app_runtime::run_app_server;
use crate::automation::run_automation_scheduler;

const EVENT_CAPACITY: usize = 128;
const GENERATION_POLL_INTERVAL: Duration = Duration::from_millis(50);
const APP_SERVER_PROBE_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CompletedRuntimeTask {
    Control,
    AppServer,
    Monitor,
    Automation,
}

pub async fn run(config: AgentdConfig, arg0_paths: Arg0DispatchPaths) -> Result<(), AgentdError> {
    let trust_file = config
        .authbus_trust_file()
        .map(std::path::Path::to_path_buf);
    let (identity, registry, writer_lock) = config.into_parts();
    let _writer_lock = writer_lock;
    let federation_owner_layouts = registry
        .load()?
        .agents
        .into_values()
        .filter(|record| record.manifest.agent_id != identity.agent_id)
        .map(|record| record.layout)
        .collect::<Vec<_>>();
    let state = Arc::new(AgentdState::new(
        identity.clone(),
        registry,
        EVENT_CAPACITY,
    )?);
    if let Some(path) = trust_file {
        state.refresh_generation()?;
        let host = crate::authbus_ingress::TextIngress::open(&identity, path).await?;
        state.refresh_generation()?;
        state
            .authbus
            .set(Arc::new(host))
            .map_err(|_| AgentdError::Protocol("AuthBus host already attached".to_string()))?;
    }
    let cognitive_layout = identity.layout.clone();
    let cognitive_runtime = open_cognitive_runtime_after_generation_fence(&state, || async move {
        CognitiveStore::open(&cognitive_layout).await
    })
    .await?;
    // The writer-enabled qualification binary must never start in a
    // degraded CognitiveRuntime state.  The default/production binary keeps
    // the existing availability-tolerant behavior; only the explicit
    // compile-time qualification profile takes this fail-closed startup gate.
    let cognitive_runtime = require_cognitive_runtime_for_profile(cognitive_runtime)?;
    if let Some(store) = cognitive_runtime.available_store() {
        state.attach_cognitive_store(Arc::clone(store))?;
    }
    let cognitive_runtime = attach_federation_after_generation_fence(
        &state,
        cognitive_runtime,
        federation_owner_layouts,
    )
    .await?;
    let automation_layout = identity.layout.clone();
    let automation_store = open_automation_store_after_generation_fence(&state, || async move {
        AutomationStore::open(&automation_layout).await
    })
    .await?;
    if let Some(store) = automation_store.as_ref() {
        state.attach_automation_store(store.clone())?;
    }
    let cancellation = CancellationToken::new();
    let control = AgentdControlServer::bind(
        identity.control_socket.clone(),
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await?;
    let mut control_task = tokio::spawn(control.run());
    let mut app_server_task = tokio::spawn(run_app_server(
        identity.clone(),
        arg0_paths,
        cognitive_runtime,
        Arc::clone(&state),
    ));
    let mut monitor_task = tokio::spawn(monitor_runtime(Arc::clone(&state)));
    let automation_cancellation = cancellation.clone();
    let automation_state = Arc::clone(&state);
    let mut automation_task = tokio::spawn(async move {
        match automation_store {
            Some(store) => {
                run_automation_scheduler(store, automation_state, identity, automation_cancellation)
                    .await
            }
            None => {
                // Automation is an optional per-Agent product plane. A corrupt or
                // unavailable private store must not create a second failure domain
                // for Codex sessions, tools, or the App Server.
                automation_cancellation.cancelled().await;
                Ok(())
            }
        }
    });

    let (outcome, completed_task) = tokio::select! {
        result = &mut control_task => (
            joined("control server", result),
            Some(CompletedRuntimeTask::Control),
        ),
        result = &mut app_server_task => (
            joined_io("Codex App Server", result),
            Some(CompletedRuntimeTask::AppServer),
        ),
        result = &mut monitor_task => (
            joined("generation monitor", result),
            Some(CompletedRuntimeTask::Monitor),
        ),
        result = &mut automation_task => (
            joined("automation scheduler", result),
            Some(CompletedRuntimeTask::Automation),
        ),
        signal = shutdown_signal() => {
            signal?;
            state.mark_draining()?;
            (Ok(()), None)
        }
    };
    cancellation.cancel();
    cleanup_runtime_tasks(
        completed_task,
        &mut control_task,
        &mut app_server_task,
        &mut monitor_task,
        &mut automation_task,
    )
    .await;
    outcome
}

#[cfg(feature = "qualification-cognitive-write")]
fn require_cognitive_runtime_for_profile(
    runtime: CognitiveRuntime,
) -> Result<CognitiveRuntime, AgentdError> {
    if runtime.available_store().is_some() {
        Ok(runtime)
    } else {
        Err(AgentdError::QualificationCognitiveRuntimeUnavailable)
    }
}

#[cfg(not(feature = "qualification-cognitive-write"))]
fn require_cognitive_runtime_for_profile(
    runtime: CognitiveRuntime,
) -> Result<CognitiveRuntime, AgentdError> {
    Ok(runtime)
}

async fn open_automation_store_after_generation_fence<Open, OpenFuture>(
    state: &AgentdState,
    open: Open,
) -> Result<Option<AutomationStore>, AgentdError>
where
    Open: FnOnce() -> OpenFuture,
    OpenFuture: Future<Output = Result<AutomationStore, codex_hepta_automation::AutomationError>>,
{
    state.refresh_generation()?;
    let opened = open().await;
    state.refresh_generation()?;
    match opened {
        Ok(store) => Ok(Some(store)),
        Err(AutomationError::Unavailable | AutomationError::Corrupt) => Ok(None),
        Err(error) => Err(error.into()),
    }
}

async fn attach_federation_after_generation_fence(
    state: &AgentdState,
    runtime: CognitiveRuntime,
    owner_layouts: Vec<codex_hepta_paths::HeptaAgentLayout>,
) -> Result<CognitiveRuntime, AgentdError> {
    if runtime.available_store().is_none() || owner_layouts.is_empty() {
        return Ok(runtime);
    }
    state.refresh_generation()?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| AgentdError::Protocol(error.to_string()))?
        .as_secs();
    let now = i64::try_from(now)
        .map_err(|_| AgentdError::Protocol("system clock overflow".to_string()))?;
    let federation =
        FederatedRecallSet::discover(state.identity().agent_id.clone(), owner_layouts, now).await;
    // Discovery reads other owner stores and can outlive a lifecycle update.
    // Fence once more before the read-only set reaches App Server.
    state.refresh_generation()?;
    Ok(runtime.with_federation(federation))
}

async fn open_cognitive_runtime_after_generation_fence<Open, OpenFuture>(
    state: &AgentdState,
    open: Open,
) -> Result<CognitiveRuntime, AgentdError>
where
    Open: FnOnce() -> OpenFuture,
    OpenFuture: Future<Output = Result<CognitiveStore, codex_hepta_memory::CognitiveStoreError>>,
{
    state.refresh_generation()?;
    let cognitive_runtime = CognitiveRuntime::from_open_result(open().await);
    // Opening and migrating the store is bounded durable work. Fence again
    // before binding control or starting App Server so a generation change
    // concurrent with that work cannot reach a serving runtime.
    state.refresh_generation()?;
    Ok(cognitive_runtime)
}

async fn monitor_runtime(state: Arc<AgentdState>) -> Result<(), AgentdError> {
    let mut app_server_ready = false;
    loop {
        if state.is_fenced()? {
            return Err(AgentdError::GenerationFenced(
                "agentd runtime was fenced by an owner or generation violation".to_string(),
            ));
        }
        if let Err(error) = state.refresh_generation() {
            state.mark_fenced();
            return Err(error);
        }
        if !app_server_ready {
            match probe_app_server(state.identity()).await {
                Ok(()) => {
                    state.mark_app_server_ready()?;
                    app_server_ready = true;
                }
                Err(error @ AgentdError::GenerationFenced(_)) => {
                    state.mark_fenced();
                    return Err(error);
                }
                Err(_not_ready) => {}
            }
        }
        tokio::time::sleep(GENERATION_POLL_INTERVAL).await;
    }
}

async fn probe_app_server(identity: &AgentdIdentity) -> Result<(), AgentdError> {
    let socket_path = AbsolutePathBuf::from_absolute_path(&identity.app_server_socket)?;
    let client = timeout(
        APP_SERVER_PROBE_TIMEOUT,
        RemoteAppServerClient::connect(RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
            client_name: "hepta-agentd-readiness".to_string(),
            client_version: env!("CARGO_PKG_VERSION").to_string(),
            experimental_api: false,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: 8,
        }),
    )
    .await
    .map_err(|_| AgentdError::Protocol("App Server readiness probe timed out".to_string()))??;
    let expected_home = identity.home_root.to_string_lossy();
    if client.codex_home() != Some(expected_home.as_ref()) {
        let actual = client.codex_home().unwrap_or("<missing>").to_string();
        let _ = client.shutdown().await;
        return Err(AgentdError::GenerationFenced(format!(
            "App Server home {actual} does not match agent home {expected_home}"
        )));
    }
    client.shutdown().await?;
    Ok(())
}

fn joined(
    label: &str,
    result: Result<Result<(), AgentdError>, tokio::task::JoinError>,
) -> Result<(), AgentdError> {
    match result {
        Ok(Ok(())) => Err(AgentdError::Protocol(format!(
            "{label} exited before agentd shutdown"
        ))),
        Ok(Err(error)) => Err(error),
        Err(error) => Err(AgentdError::Protocol(format!(
            "{label} task failed: {error}"
        ))),
    }
}

fn joined_io(
    label: &str,
    result: Result<std::io::Result<()>, tokio::task::JoinError>,
) -> Result<(), AgentdError> {
    match result {
        Ok(Ok(())) => Err(AgentdError::Protocol(format!(
            "{label} exited before agentd shutdown"
        ))),
        Ok(Err(error)) => Err(error.into()),
        Err(error) => Err(AgentdError::Protocol(format!(
            "{label} task failed: {error}"
        ))),
    }
}

async fn abort_and_join<T>(task: &mut JoinHandle<T>) {
    if !task.is_finished() {
        task.abort();
    }
    let _ = task.await;
}

async fn cleanup_runtime_tasks<ControlOutput, AppServerOutput, MonitorOutput, AutomationOutput>(
    completed_task: Option<CompletedRuntimeTask>,
    control_task: &mut JoinHandle<ControlOutput>,
    app_server_task: &mut JoinHandle<AppServerOutput>,
    monitor_task: &mut JoinHandle<MonitorOutput>,
    automation_task: &mut JoinHandle<AutomationOutput>,
) {
    if completed_task != Some(CompletedRuntimeTask::Control) {
        abort_and_join(control_task).await;
    }
    if completed_task != Some(CompletedRuntimeTask::AppServer) {
        abort_and_join(app_server_task).await;
    }
    if completed_task != Some(CompletedRuntimeTask::Monitor) {
        abort_and_join(monitor_task).await;
    }
    if completed_task != Some(CompletedRuntimeTask::Automation) {
        abort_and_join(automation_task).await;
    }
}

#[cfg(unix)]
async fn shutdown_signal() -> Result<(), AgentdError> {
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    terminate.recv().await.ok_or_else(|| {
        AgentdError::Protocol("SIGTERM listener closed before receiving a signal".to_string())
    })
}

#[cfg(not(unix))]
async fn shutdown_signal() -> Result<(), AgentdError> {
    tokio::signal::ctrl_c().await.map_err(Into::into)
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
