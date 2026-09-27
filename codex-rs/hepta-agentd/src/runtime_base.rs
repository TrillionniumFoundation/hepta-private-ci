use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_arg0::Arg0DispatchPaths;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationStore;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_memory::CognitiveRuntime;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::time::Instant;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::CognitiveRetrievalMode;
use crate::RuntimeTasks;
use crate::app_runtime::run_app_server;
use crate::automation::spawn_automation_service;

const EVENT_CAPACITY: usize = 128;
const GENERATION_POLL_INTERVAL: Duration = Duration::from_millis(50);
const APP_SERVER_PROBE_TIMEOUT: Duration = Duration::from_secs(2);
const RUN_DRAIN_POLL_INTERVAL: Duration = Duration::from_millis(50);
const RUN_DRAIN_GRACE: Duration = Duration::from_secs(5);
const RUN_RECONCILE_GRACE: Duration = Duration::from_secs(2);

const TASK_SHUTDOWN_GRACE: Duration = Duration::from_secs(3);

pub async fn run(
    mut config: AgentdConfig,
    arg0_paths: Arg0DispatchPaths,
) -> Result<(), AgentdError> {
    config.require_intelligence_composition()?;
    let production_operations = config.take_production_operations();
    let plasticity_bootstrap = config.take_plasticity_runtime_bootstrap();
    let self_iteration_bootstrap = config.take_self_iteration_coordinator_bootstrap();
    if self_iteration_bootstrap.is_some() && plasticity_bootstrap.is_none() {
        return Err(AgentdError::Invalid(
            "self-iteration coordinator requires the existing plasticity owner".to_string(),
        ));
    }
    let trust_file = config
        .authbus_trust_file()
        .map(std::path::Path::to_path_buf);
    let evidence_trust_file = config
        .evidence_trust_file()
        .map(std::path::Path::to_path_buf);
    let evidence_recovery_frontier = config
        .evidence_recovery_frontier_files()
        .map(|(frontier, trust)| (frontier.to_path_buf(), trust.to_path_buf()));
    let automation_effect_host_file = config
        .automation_effect_host_file()
        .map(std::path::Path::to_path_buf);
    let objective_profile_file = config
        .objective_profile_file()
        .map(std::path::Path::to_path_buf);
    if objective_profile_file.is_some() && trust_file.is_none() {
        return Err(AgentdError::Invalid(
            "objective profile requires explicit AuthBus trust configuration".to_string(),
        ));
    }
    let checkpoint_file = config
        .authbus_checkpoint_file()
        .map(std::path::Path::to_path_buf);
    let prompt_registry_recovery_checkpoint = config
        .prompt_registry_recovery_checkpoint_file()
        .map(std::path::Path::to_path_buf);
    let ranker = config.cognitive_ranker();
    let mut production_writer_host = config.production_writer_host();
    if production_operations.is_some() && production_writer_host.is_none() {
        return Err(AgentdError::Invalid(
            "production operations require an independently recovered production writer host"
                .to_string(),
        ));
    }
    let retrieval_mode = config.cognitive_retrieval_mode();
    let retrieval_context = config.cognitive_retrieval_context();
    let retrieval_learning = config.cognitive_retrieval_learning();
    require_cognitive_retrieval_context_for_mode(retrieval_mode, retrieval_context.is_some())?;
    let intuition_policy_host = config.intuition_policy_host();
    let intelligence_product = config.intelligence_product_runner();
    let intelligence_invocation = config.intelligence_invocation_provider();
    require_intelligence_composition(
        intelligence_product.is_some(),
        intelligence_invocation.is_some(),
    )?;
    let (identity, registry, writer_lock) = config.into_parts();
    let _writer_lock = writer_lock;
    let federation_owner_layouts = registry
        .load()?
        .agents
        .into_values()
        .filter(|record| record.manifest.agent_id != identity.agent_id)
        .map(|record| record.layout)
        .collect::<Vec<_>>();
    let state = Arc::new(AgentdState::new_with_prompt_registry_recovery(
        identity.clone(),
        registry,
        EVENT_CAPACITY,
        prompt_registry_recovery_checkpoint.as_deref(),
    )?);
    let plasticity_runtime =
        crate::plasticity_runtime::compose_plasticity_runtime_v1(&state, plasticity_bootstrap)?;
    let self_iteration_runtime =
        crate::self_iteration_coordinator::compose_self_iteration_coordinator_v1(
            self_iteration_bootstrap,
        );
    if let Some(host) = intuition_policy_host {
        state.intuition_policy.set(host).map_err(|_| {
            AgentdError::Invalid("intuition policy host already attached".to_string())
        })?;
    }
    if let Some(ranker) = ranker {
        state
            .cognitive_ranker
            .set(ranker)
            .map_err(|_| AgentdError::Invalid("cognitive ranker already attached".to_string()))?;
    }
    if let Some(runner) = intelligence_product {
        state.intelligence_product.set(runner).map_err(|_| {
            AgentdError::Invalid("intelligence product runner already attached".to_string())
        })?;
    }
    if let Some(provider) = intelligence_invocation {
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
    }
    if let Some(current) = retrieval_context {
        state
            .cognitive_retrieval_context
            .set(current)
            .map_err(|_| {
                AgentdError::Invalid("cognitive retrieval context already attached".to_string())
            })?;
    }
    if let Some(sink) = retrieval_learning {
        state.cognitive_retrieval_learning.set(sink).map_err(|_| {
            AgentdError::Invalid("cognitive retrieval learning sink already attached".to_string())
        })?;
    }
    match (trust_file, checkpoint_file) {
        (Some(trust), Some(checkpoint)) => {
            state.refresh_generation()?;
            let host =
                crate::authbus_ingress::TextIngress::open(&identity, trust, checkpoint).await?;
            state.refresh_generation()?;
            state
                .authbus
                .set(Arc::new(host))
                .map_err(|_| AgentdError::Protocol("AuthBus host already attached".to_string()))?;
        }
        (None, None) => {}
        _ => {
            return Err(AgentdError::Invalid(
                "AuthBus trust and external replay checkpoint must be configured together"
                    .to_string(),
            ));
        }
    }
    if let Some(path) = evidence_trust_file {
        state.refresh_generation()?;
        let host =
            crate::evidence_host::EvidenceHost::open(&identity, path, evidence_recovery_frontier)
                .await?;
        state.refresh_generation()?;
        state.evidence.set(Arc::new(host)).map_err(|_| {
            AgentdError::Protocol("kernel evidence host already attached".to_string())
        })?;
    } else if evidence_recovery_frontier.is_some() {
        return Err(AgentdError::Invalid(
            "kernel evidence recovery frontier requires --evidence-trust-file".to_string(),
        ));
    }
    if let Some(path) = objective_profile_file {
        state.refresh_generation()?;
        let host = Arc::new(crate::objective_runtime::ObjectiveRuntimeHost::open(
            &identity, &path,
        )?);
        let current_generation = state.current_generation()?;
        host.reconcile(
            &state,
            current_generation,
            crate::authbus_ingress::now_ms()?,
        )?;
        state
            .objective_runtime
            .set(host)
            .map_err(|_| AgentdError::Protocol("objective runtime already attached".to_string()))?;
        state.refresh_generation()?;
    }
    let cognitive_runtime = match production_writer_host.as_ref() {
        Some(host) => {
            state.refresh_generation()?;
            let runtime = host.cognitive_runtime();
            state.refresh_generation()?;
            runtime
        }
        None => {
            let cognitive_layout = identity.layout.clone();
            open_cognitive_runtime_after_generation_fence(&state, || async move {
                CognitiveStore::open(&cognitive_layout).await
            })
            .await?
        }
    };
    // The writer-enabled qualification binary must never start in a
    // degraded CognitiveRuntime state.  The default/production binary keeps
    // the existing availability-tolerant behavior; only the explicit
    // compile-time qualification profile takes this fail-closed startup gate.
    let cognitive_runtime = require_cognitive_runtime_for_profile(cognitive_runtime)?;
    if let Some(store) = cognitive_runtime.available_store() {
        state.attach_cognitive_store(Arc::clone(store))?;
    }
    let production_operations = match production_operations {
        Some(operations) => {
            let recovered_host = production_writer_host.as_ref().ok_or_else(|| {
                AgentdError::Protocol(
                    "production operations require the recovered writer owner".to_string(),
                )
            })?;
            let (host, interval) = operations.attach(Arc::clone(recovered_host)).await?;
            state.attach_production_operations(Arc::clone(&host))?;
            production_writer_host = Some(Arc::clone(&host));
            Some((host, interval))
        }
        None => None,
    };
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
    if let Some(path) = automation_effect_host_file {
        state.refresh_generation()?;
        let host =
            crate::automation_effect_host::AgentdAutomationEffectHost::open(&identity, &path)?;
        state.refresh_generation()?;
        state.attach_automation_effect_host(Arc::new(host))?;
    }
    state.mark_runtime_prerequisites_ready()?;
    let cancellation = CancellationToken::new();
    let control = AgentdControlServer::bind(
        identity.control_socket.clone(),
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await?;
    // The single task host owns cancellation and joining on every exit path.
    // All fallible owner opens and control binding above precede task startup.
    let mut tasks = RuntimeTasks::new(cancellation.clone(), TASK_SHUTDOWN_GRACE)?;
    let startup: Result<(), AgentdError> = async {
        if let Some((host, interval)) = production_operations {
            tasks.spawn_required(
                "production-operation-reconciler",
                run_production_operation_reconciler(host, interval, cancellation.clone()),
            )?;
        }
        tasks.spawn_required("control-server", control.run())?;
        let app_identity = identity.clone();
        let app_state = Arc::clone(&state);
        let app_drain = state.app_server_drain_handle();
        let app_lifetime = cancellation.clone();
        tasks.spawn_required("codex-app-server", async move {
            run_app_server(
                app_identity,
                arg0_paths,
                cognitive_runtime,
                app_state,
                production_writer_host,
            )
            .await
            .map_err(AgentdError::from)?;
            if app_drain.drained() && app_drain.running_turns() == 0 {
                // A completed drain is not an unexpected required-service exit.
                // Keep control and durable reconcilers alive so Supervisor can
                // observe the acknowledgement before its explicit stop signal.
                app_lifetime.cancelled().await;
            }
            Ok(())
        })?;
        tasks.spawn_required(
            "generation-monitor",
            monitor_runtime(Arc::clone(&state), cancellation.clone()),
        )?;
        tasks.spawn_required(
            "authbus-relay",
            crate::authbus_dispatch::run(Arc::clone(&state), cancellation.clone()),
        )?;
        if let Some(owner) = plasticity_runtime {
            tasks.spawn_required(
                "plasticity-owner",
                owner.run(Arc::clone(&state), cancellation.clone()),
            )?;
        }
        if let Some(owner) = self_iteration_runtime {
            tasks.spawn_required(
                "self-iteration-coordinator",
                owner.run(Arc::clone(&state), cancellation.clone()),
            )?;
        }
        spawn_automation_service(
            &mut tasks,
            automation_store,
            Arc::clone(&state),
            identity,
            cancellation.clone(),
        )
        .await?;
        Ok(())
    }
    .await;
    if let Err(error) = startup {
        tasks.shutdown().await;
        return Err(error);
    }
    tasks
        .run_until(async move {
            shutdown_signal().await?;
            // Keep control and owner reconciliation alive throughout drain.
            drain_runtime(state).await
        })
        .await
}

fn require_intelligence_composition(runner: bool, provider: bool) -> Result<(), AgentdError> {
    if runner != provider {
        return Err(AgentdError::Invalid(
            "canonical intelligence requires both a runner and an authoritative invocation provider"
                .to_string(),
        ));
    }
    Ok(())
}

fn require_cognitive_retrieval_context_for_mode(
    mode: CognitiveRetrievalMode,
    configured: bool,
) -> Result<(), AgentdError> {
    match (mode, configured) {
        (CognitiveRetrievalMode::Compatibility, false)
        | (CognitiveRetrievalMode::HnmfRequired, true) => Ok(()),
        (CognitiveRetrievalMode::Compatibility, true) => Err(AgentdError::Invalid(
            "compatibility retrieval profile forbids an HNMF current context; select HnmfRequired explicitly"
                .to_string(),
        )),
        (CognitiveRetrievalMode::HnmfRequired, false) => Err(AgentdError::Invalid(
            "HNMF-required retrieval profile requires a current authenticated retrieval context"
                .to_string(),
        )),
    }
}

#[cfg(feature = "production-cognitive-write")]
fn require_cognitive_runtime_for_profile(
    runtime: CognitiveRuntime,
) -> Result<CognitiveRuntime, AgentdError> {
    if runtime.available_store().is_some() {
        Ok(runtime)
    } else {
        Err(AgentdError::CognitiveWriteRuntimeUnavailable)
    }
}

#[cfg(not(feature = "production-cognitive-write"))]
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
    let runtime = runtime.with_federation_sources(state.identity().agent_id.clone(), owner_layouts);
    // Physical federation reads rediscover current grants. Fence the fleet
    // generation on both sides of composition without freezing a reader set.
    state.refresh_generation()?;
    Ok(runtime)
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

async fn run_production_operation_reconciler(
    host: Arc<crate::AgentdProductionWriterHost>,
    interval: Duration,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    loop {
        // Reconcile immediately after startup/restart, then at a bounded
        // cadence. Agentd never dispatches from this recovery loop.
        host.reconcile(256).await?;
        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(interval) => {}
        }
    }
}

async fn monitor_runtime(
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
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
        state.expire_run_deadlines()?;
        if !app_server_ready {
            let observation = tokio::select! {
                () = cancellation.cancelled() => return Ok(()),
                observation = probe_app_server(state.identity()) => observation,
            };
            match observation {
                Ok(()) => {
                    state.mark_app_server_ready()?;
                    if let Some(host) = state.objective_runtime.get() {
                        host.reconcile(
                            &state,
                            state.current_generation()?,
                            crate::authbus_ingress::now_ms()?,
                        )?;
                    }
                    app_server_ready = true;
                }
                Err(error @ AgentdError::GenerationFenced(_)) => {
                    state.mark_fenced();
                    return Err(error);
                }
                Err(_not_ready) => {}
            }
        }
        tokio::select! {
            () = cancellation.cancelled() => return Ok(()),
            () = tokio::time::sleep(GENERATION_POLL_INTERVAL) => {}
        }
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

async fn drain_runtime(state: Arc<AgentdState>) -> Result<(), AgentdError> {
    state.mark_draining()?;
    let drain_deadline = Instant::now() + RUN_DRAIN_GRACE;
    loop {
        state.expire_run_deadlines()?;
        if state.active_run_count()? == 0 {
            return Ok(());
        }
        if Instant::now() >= drain_deadline {
            break;
        }
        sleep(RUN_DRAIN_POLL_INTERVAL).await;
    }

    state.mark_unresolved_runs_indeterminate("shutdown_drain_timeout")?;
    let reconcile_deadline = Instant::now() + RUN_RECONCILE_GRACE;
    loop {
        if state.unresolved_run_count()? == 0 {
            return Ok(());
        }
        if Instant::now() >= reconcile_deadline {
            break;
        }
        sleep(RUN_DRAIN_POLL_INTERVAL).await;
    }

    let unresolved = state.unresolved_run_count()?;
    if unresolved == 0 {
        Ok(())
    } else {
        Err(AgentdError::Protocol(format!(
            "agentd shutdown left {unresolved} indeterminate run(s); owner recovery is required"
        )))
    }
}

#[cfg(unix)]
async fn shutdown_signal() -> Result<(), AgentdError> {
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    let mut interrupt = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())?;
    tokio::select! {
        signal = terminate.recv() => signal.ok_or_else(|| {
            AgentdError::Protocol("SIGTERM listener closed before receiving a signal".to_string())
        })?,
        signal = interrupt.recv() => signal.ok_or_else(|| {
            AgentdError::Protocol("SIGINT listener closed before receiving a signal".to_string())
        })?,
    }
    Ok(())
}

#[cfg(not(unix))]
async fn shutdown_signal() -> Result<(), AgentdError> {
    tokio::signal::ctrl_c().await.map_err(Into::into)
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
