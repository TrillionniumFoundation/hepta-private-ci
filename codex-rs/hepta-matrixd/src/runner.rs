use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::future::Future;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_app_server_client::AppServerEvent;
use codex_app_server_protocol::CommandAction;
use codex_app_server_protocol::CommandExecutionApprovalDecision;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ServerRequest;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_sdk::MatrixIngress;
use codex_hepta_matrix_sdk::MatrixSdkClient;
use codex_hepta_matrix_sdk::MatrixSidecarConfig;
use codex_hepta_matrix_sdk::MatrixSyncExit;
use codex_hepta_matrix_sdk::OutboxDispatchConfig;
use codex_hepta_matrix_sdk::run_outbox_sender;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixSnapshot;
use codex_hepta_matrix_store::PendingApprovalDraft;
use codex_hepta_matrix_store::PendingApprovalKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::task::JoinSet;
use tokio::time::MissedTickBehavior;
use tokio_util::sync::CancellationToken;

use crate::MatrixAgentdConnectArgs;
use crate::MatrixAppServerBridge;
use crate::MatrixBridgeConfig;
use crate::MatrixRuntime;
use crate::MatrixdConfig;
use crate::control::MatrixdConnectionState;
use crate::control::MatrixdControlIdentity;
use crate::control::MatrixdControlServer;
use crate::control::MatrixdControlState;

const MATRIXD_CLIENT_VERSION: &str = env!("CARGO_PKG_VERSION");
const INBOX_RECOVERY_LIMIT: usize = 1_024;
const INBOX_POLL: Duration = Duration::from_millis(100);
const AGENTD_HEALTH_POLL: Duration = Duration::from_secs(1);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);
/// Stable generation of the per-Agent Matrix authority plane.
///
/// `agentd` spawn generations are replaceable execution leases. Matrix
/// cursors, inbox admissions, and stable transaction ids survive those
/// upgrades under the per-Agent process lock and exact binding revision.
const MATRIX_PLANE_GENERATION: u64 = 1;

fn matrix_plane_generation(_agentd_spawn_generation: u64) -> u64 {
    MATRIX_PLANE_GENERATION
}

/// Run one exact-generation Matrix sidecar for one workspace Agent.
///
/// This is deliberately process-local composition: Matrix sync, durable
/// ingress/egress, and the App Server event projector all terminate together.
/// The supervisor remains lifecycle-only and there is no fleet-wide execution
/// gateway or shared writable state.
pub async fn run(config: MatrixdConfig) -> Result<(), MatrixdRunError> {
    prepare_matrix_root(&config)?;
    let _process_lock = acquire_process_lock(&config)?;
    let store = MatrixDurableStore::open(&config.layout, MatrixDurableConfig::default()).await?;
    store
        .fence_stale_pending_approvals(
            config.spawn_generation,
            &config.process_identity.process_incarnation,
            system_time_ms()?,
        )
        .await?;
    bind_rooms(&config, &store).await?;

    let workspace_root = AbsolutePathBuf::from_absolute_path(&config.workspace_root)
        .map_err(|error| MatrixdRunError::Invalid(error.to_string()))?;
    let connected = connect_via_agentd(&config).await?;
    let connections = Arc::new(MatrixdConnectionState::default());
    connections.set_agentd_connected(true);
    let transport = connected.transport;
    let events = connected.events;
    let bridge = MatrixAppServerBridge::new(
        MatrixBridgeConfig::new(config.agent_id.clone(), workspace_root),
        transport.clone(),
    )?;
    let runtime = Arc::new(MatrixRuntime::new(store.clone(), bridge));
    let sidecar_config = MatrixSidecarConfig {
        binding: config.binding.clone(),
        matrix_generation: matrix_plane_generation(config.spawn_generation),
        sync_timeline_limit: config.sync_timeline_limit,
        sync_timeout: config.sync_timeout,
    };
    sidecar_config.validate(&config.layout)?;
    let (sidecar, _session) = MatrixSdkClient::login_or_restore(
        &config.layout,
        sidecar_config.clone(),
        config.credentials().password(),
        config.credentials().store_passphrase(),
        Some(&config.device_display_name),
    )
    .await?;
    let sidecar = Arc::new(sidecar);
    let ingress = MatrixIngress::new(sidecar_config, store.clone());

    recover_startup_after_sync(
        runtime.as_ref(),
        sidecar.config(),
        async {
            sidecar.sync_durable_once(&store, &ingress).await?;
            Ok(())
        },
        |thread_id| {
            let transport = &transport;
            async move { Ok(transport.resume_thread(&thread_id).await?.thread.id) }
        },
    )
    .await?;
    connections.set_matrix_sync_connected(true);

    let cancel = CancellationToken::new();
    let control_state = Arc::new(MatrixdControlState::new(
        MatrixdControlIdentity {
            agent_id: config.agent_id.clone(),
            release_id: config.process_identity.release_id.clone(),
            fence: codex_hepta_matrix_protocol::MatrixdFence {
                binding_revision: config.binding.revision,
                binding_digest: config.process_identity.binding_digest.clone(),
                attached_agent_generation: config.spawn_generation,
                process_incarnation: config.process_identity.process_incarnation.clone(),
                plane_epoch: config.process_identity.plane_epoch,
            },
            expected_mxid: config.binding.expected_mxid.clone(),
            active_rooms: config.binding.allowed_rooms.clone(),
        },
        store.clone(),
        Arc::new(transport.clone()),
        Arc::clone(&connections),
    )?);
    let control_server = MatrixdControlServer::bind(
        config.layout.matrixd_control_socket().to_path_buf(),
        control_state,
        cancel.clone(),
    )
    .await?;
    let mut tasks = JoinSet::new();

    tasks.spawn(async move { control_server.run().await.map_err(MatrixdRunError::Control) });

    {
        let sidecar = Arc::clone(&sidecar);
        let store = store.clone();
        let ingress = ingress.clone();
        let cancel = cancel.clone();
        let connections = Arc::clone(&connections);
        tasks.spawn(async move {
            let result = sidecar
                .sync_durable_until_cancelled(&store, &ingress, &cancel)
                .await;
            connections.set_matrix_sync_connected(false);
            match result? {
                MatrixSyncExit::Cancelled if cancel.is_cancelled() => Ok(()),
                MatrixSyncExit::Cancelled => Err(MatrixdRunError::TaskExited("matrix sync")),
                MatrixSyncExit::IngressFenced => Err(MatrixdRunError::IngressFenced),
            }
        });
    }
    {
        let runtime = Arc::clone(&runtime);
        let cancel = cancel.clone();
        tasks.spawn(async move { run_inbox_dispatcher(runtime, cancel).await });
    }
    {
        let runtime = Arc::clone(&runtime);
        let store = store.clone();
        let transport = transport.clone();
        let cancel = cancel.clone();
        let connections = Arc::clone(&connections);
        let attached_agent_generation = config.spawn_generation;
        let process_incarnation = config.process_identity.process_incarnation.clone();
        tasks.spawn(async move {
            run_event_projector(
                EventProjectorContext {
                    runtime,
                    store,
                    transport,
                    attached_agent_generation,
                    process_incarnation,
                    connections,
                },
                events,
                cancel,
            )
            .await
        });
    }
    {
        let sidecar = Arc::clone(&sidecar);
        let store = store.clone();
        let cancel = cancel.clone();
        tasks.spawn(async move {
            run_outbox_sender(
                &store,
                sidecar.as_ref(),
                &OutboxDispatchConfig::default(),
                &cancel,
            )
            .await?;
            if cancel.is_cancelled() {
                Ok(())
            } else {
                Err(MatrixdRunError::TaskExited("outbox sender"))
            }
        });
    }
    {
        let cancel = cancel.clone();
        let socket = config.layout.agentd_control_socket().to_path_buf();
        let agent_id = config.agent_id.clone();
        let spawn_generation = config.spawn_generation;
        let connections = Arc::clone(&connections);
        tasks.spawn(async move {
            run_agentd_health_monitor(socket, agent_id, spawn_generation, connections, cancel).await
        });
    }

    let first_result = tokio::select! {
        signal = shutdown_signal() => signal,
        joined = tasks.join_next() => match joined {
            Some(Ok(Ok(()))) => Err(MatrixdRunError::TaskExited("runtime task")),
            Some(Ok(Err(error))) => Err(error),
            Some(Err(error)) => Err(MatrixdRunError::TaskJoin(error.to_string())),
            None => Err(MatrixdRunError::TaskExited("runtime task set")),
        },
    };

    connections.set_draining();
    cancel.cancel();
    let _ = tokio::time::timeout(SHUTDOWN_GRACE, async {
        while tasks.join_next().await.is_some() {}
    })
    .await;
    tasks.abort_all();
    store.close().await;
    first_result
}

// Keep the startup sequence together: a complete durable Matrix batch must
// precede both the recovery snapshot and every App Server admission. Otherwise
// a message deleted while matrixd was offline could be recovered before its
// deletion reaches the local store. No runtime tasks or readiness are exposed
// until this sequence succeeds.
async fn recover_startup_after_sync<B, S, R, F>(
    runtime: &MatrixRuntime<B>,
    config: &MatrixSidecarConfig,
    initial_sync: S,
    mut resume_thread: R,
) -> Result<(), MatrixdRunError>
where
    B: crate::MatrixRuntimeBridge,
    S: Future<Output = Result<(), MatrixdRunError>>,
    R: FnMut(String) -> F,
    F: Future<Output = Result<String, MatrixdRunError>>,
{
    initial_sync.await?;
    // Subscriptions belong to this transport connection. Resume every exact
    // current thread before recovery can admit a turn and emit notifications.
    let snapshot = runtime
        .store()
        .snapshot(system_time_ms()?, INBOX_RECOVERY_LIMIT)
        .await?;
    for thread_id in current_room_thread_ids(
        &snapshot,
        &config.binding.allowed_rooms,
        config.binding.revision,
        config.matrix_generation,
    ) {
        let resumed_id = resume_thread(thread_id.clone()).await?;
        if resumed_id != thread_id {
            return Err(MatrixdRunError::Invalid(format!(
                "App Server resumed Matrix thread {resumed_id} instead of {thread_id}"
            )));
        }
    }
    runtime
        .recover_pending(INBOX_RECOVERY_LIMIT, system_time_ms()?)
        .await?;
    Ok(())
}

fn current_room_thread_ids(
    snapshot: &MatrixSnapshot,
    allowed_rooms: &[MatrixRoomId],
    binding_revision: u64,
    generation: u64,
) -> Vec<String> {
    let mut thread_ids = BTreeSet::new();
    for room_thread in &snapshot.room_threads {
        let is_current_binding = snapshot.bindings.iter().any(|binding| {
            binding.owner_agent_id == snapshot.owner_agent_id
                && binding.revision == binding_revision
                && binding.generation == generation
                && allowed_rooms
                    .iter()
                    .any(|allowed_room| allowed_room == &binding.room_id)
                && binding.room_id == room_thread.room_id
                && room_thread.binding_revision == binding_revision
                && room_thread.generation == generation
        });
        if is_current_binding && let Some(thread_id) = room_thread.thread_id.as_deref() {
            thread_ids.insert(thread_id.to_string());
        }
    }
    thread_ids.into_iter().collect()
}

fn prepare_matrix_root(config: &MatrixdConfig) -> Result<(), MatrixdRunError> {
    let matrix_root = config.layout.matrix_root();
    fs::create_dir_all(matrix_root)?;
    if matrix_root.canonicalize()? != matrix_root {
        return Err(MatrixdRunError::Invalid(
            "Matrix root must remain the canonical per-Agent path".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        fs::set_permissions(matrix_root, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

async fn connect_via_agentd(
    config: &MatrixdConfig,
) -> Result<crate::ConnectedMatrixAppServer, MatrixdRunError> {
    Ok(crate::connect_via_agentd(MatrixAgentdConnectArgs::new(
        config.layout.agentd_control_socket().to_path_buf(),
        config.agent_id.clone(),
        config.spawn_generation,
        MATRIXD_CLIENT_VERSION,
    ))
    .await?)
}

fn acquire_process_lock(config: &MatrixdConfig) -> Result<File, MatrixdRunError> {
    let lock_path = config.layout.matrix_root().join("matrixd.lock");
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(lock_path)?;
    lock.try_lock()
        .map_err(|_| MatrixdRunError::AlreadyRunning)?;
    Ok(lock)
}

async fn bind_rooms(
    config: &MatrixdConfig,
    store: &MatrixDurableStore,
) -> Result<(), MatrixdRunError> {
    let matrix_generation = matrix_plane_generation(config.spawn_generation);
    for room_id in &config.binding.allowed_rooms {
        let existing = store.room_binding(room_id).await?;
        let expected_revision = match existing.as_ref() {
            None => {
                if config.binding.revision != 1 {
                    return Err(MatrixdRunError::Invalid(
                        "a new Matrix room binding must begin at revision 1".to_string(),
                    ));
                }
                None
            }
            Some(binding)
                if binding.agent_user_id == config.binding.expected_mxid
                    && binding.generation == matrix_generation
                    && binding.revision == config.binding.revision =>
            {
                Some(binding.revision)
            }
            Some(_) => {
                return Err(MatrixdRunError::Invalid(
                    "Matrix room binding disagrees with the stable Matrix-plane generation or revision"
                        .to_string(),
                ));
            }
        };
        let bound = store
            .bind_room(&RoomBindingDraft {
                room_id: room_id.clone(),
                agent_user_id: config.binding.expected_mxid.clone(),
                expected_revision,
                generation: matrix_generation,
                changed_at_ms: system_time_ms()?,
            })
            .await?;
        if bound.revision != config.binding.revision
            || bound.generation != matrix_generation
            || bound.agent_user_id != config.binding.expected_mxid
        {
            return Err(MatrixdRunError::Invalid(
                "Matrix durable room binding did not converge to the configured identity"
                    .to_string(),
            ));
        }
    }
    Ok(())
}

async fn run_inbox_dispatcher<B>(
    runtime: Arc<MatrixRuntime<B>>,
    cancel: CancellationToken,
) -> Result<(), MatrixdRunError>
where
    B: crate::MatrixRuntimeBridge + 'static,
{
    let mut interval = tokio::time::interval(INBOX_POLL);
    interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            biased;
            _ = cancel.cancelled() => return Ok(()),
            _ = interval.tick() => {
                runtime
                    .recover_pending(INBOX_RECOVERY_LIMIT, system_time_ms()?)
                    .await?;
            }
        }
    }
}

struct EventProjectorContext<B> {
    runtime: Arc<MatrixRuntime<B>>,
    store: MatrixDurableStore,
    transport: crate::RemoteMatrixAppServerTransport,
    attached_agent_generation: u64,
    process_incarnation: String,
    connections: Arc<MatrixdConnectionState>,
}

async fn run_event_projector<B>(
    context: EventProjectorContext<B>,
    mut events: crate::RemoteMatrixAppServerEvents,
    cancel: CancellationToken,
) -> Result<(), MatrixdRunError>
where
    B: crate::MatrixRuntimeBridge + 'static,
{
    let EventProjectorContext {
        runtime,
        store,
        transport,
        attached_agent_generation,
        process_incarnation,
        connections,
    } = context;
    loop {
        let event = tokio::select! {
            biased;
            _ = cancel.cancelled() => return Ok(()),
            event = events.next_event() => event.ok_or(MatrixdRunError::AppServerDisconnected)?,
        };
        match &event {
            AppServerEvent::ServerRequest(request) => {
                project_server_request(
                    &store,
                    &transport,
                    request,
                    attached_agent_generation,
                    &process_incarnation,
                    system_time_ms()?,
                )
                .await?;
                continue;
            }
            AppServerEvent::ServerNotification(notification) => match notification.as_ref() {
                ServerNotification::TurnStarted(params) => {
                    store
                        .record_turn_started(&params.thread_id, &params.turn.id, system_time_ms()?)
                        .await?;
                }
                ServerNotification::TurnCompleted(params) => {
                    store
                        .record_turn_completed(
                            &params.thread_id,
                            &params.turn.id,
                            system_time_ms()?,
                        )
                        .await?;
                }
                ServerNotification::ServerRequestResolved(params) => {
                    let request_id_json = serde_json::to_string(&params.request_id)?;
                    store
                        .reconcile_server_request_resolved(
                            &request_id_json,
                            &params.thread_id,
                            attached_agent_generation,
                            &process_incarnation,
                            system_time_ms()?,
                        )
                        .await?;
                }
                _ => {}
            },
            AppServerEvent::Disconnected { .. } => {
                connections.set_agentd_connected(false);
                return Err(MatrixdRunError::AppServerDisconnected);
            }
            AppServerEvent::Lagged { .. } => {}
        }
        runtime
            .project_app_server_event(&event, system_time_ms()?)
            .await?;
    }
}

async fn project_server_request(
    store: &MatrixDurableStore,
    transport: &crate::RemoteMatrixAppServerTransport,
    request: &ServerRequest,
    attached_agent_generation: u64,
    process_incarnation: &str,
    created_at_ms: u64,
) -> Result<(), MatrixdRunError> {
    let (draft, supported) = match request {
        ServerRequest::CommandExecutionRequestApproval { request_id, params } => {
            let (summary, actionable) = command_approval_summary(params);
            let decisions = if actionable {
                supported_command_decisions(params.available_decisions.as_deref())
            } else {
                decline_only_decisions()
            };
            if decisions.is_empty() {
                (None, false)
            } else {
                let request_id_json = serde_json::to_string(request_id)?;
                let approval_key = stable_approval_key(
                    "command_execution",
                    request_id,
                    &params.thread_id,
                    &params.turn_id,
                    &params.item_id,
                    params.approval_id.as_deref(),
                )?;
                (
                    Some(PendingApprovalDraft {
                        approval: codex_hepta_matrix_protocol::PendingApproval {
                            approval_key,
                            kind: "command_execution".to_string(),
                            thread_id: params.thread_id.clone(),
                            turn_id: params.turn_id.clone(),
                            summary,
                            created_at_ms,
                            allowed_decisions: decisions,
                        },
                        request_id_json,
                        request_kind: PendingApprovalKind::CommandExecution,
                        attached_agent_generation,
                        process_incarnation: process_incarnation.to_string(),
                    }),
                    true,
                )
            }
        }
        ServerRequest::FileChangeRequestApproval { request_id, params } => {
            let (summary, actionable) = file_change_approval_summary(params);
            let request_id_json = serde_json::to_string(request_id)?;
            let approval_key = stable_approval_key(
                "file_change",
                request_id,
                &params.thread_id,
                &params.turn_id,
                &params.item_id,
                None,
            )?;
            (
                Some(PendingApprovalDraft {
                    approval: codex_hepta_matrix_protocol::PendingApproval {
                        approval_key,
                        kind: "file_change".to_string(),
                        thread_id: params.thread_id.clone(),
                        turn_id: params.turn_id.clone(),
                        summary,
                        created_at_ms,
                        allowed_decisions: if actionable {
                            all_local_approval_decisions()
                        } else {
                            decline_only_decisions()
                        },
                    },
                    request_id_json,
                    request_kind: PendingApprovalKind::FileChange,
                    attached_agent_generation,
                    process_incarnation: process_incarnation.to_string(),
                }),
                true,
            )
        }
        _ => (None, false),
    };

    if let Some(draft) = draft {
        store.store_pending_approval(&draft).await?;
        return Ok(());
    }
    if !supported {
        transport
            .reject_server_request(
                request.id().clone(),
                -32_601,
                "server request is unsupported by owner-local Matrix control".to_string(),
            )
            .await?;
    }
    Ok(())
}

fn all_local_approval_decisions() -> Vec<codex_hepta_matrix_protocol::LocalApprovalDecision> {
    use codex_hepta_matrix_protocol::LocalApprovalDecision;

    vec![
        LocalApprovalDecision::Accept,
        LocalApprovalDecision::AcceptForSession,
        LocalApprovalDecision::Decline,
        LocalApprovalDecision::Cancel,
    ]
}

fn decline_only_decisions() -> Vec<codex_hepta_matrix_protocol::LocalApprovalDecision> {
    use codex_hepta_matrix_protocol::LocalApprovalDecision;

    vec![
        LocalApprovalDecision::Decline,
        LocalApprovalDecision::Cancel,
    ]
}

fn command_approval_summary(
    params: &codex_app_server_protocol::CommandExecutionRequestApprovalParams,
) -> (String, bool) {
    let action = params
        .command_actions
        .as_deref()
        .and_then(typed_action_preview)
        .or_else(|| {
            params
                .command
                .as_deref()
                .map(|command| sanitize_summary_component(command, 480))
                .filter(|command| !command.is_empty())
        });
    let mut components = Vec::new();
    if let Some(action) = action.as_deref() {
        components.push(format!("action: {action}"));
    } else {
        components.push("action: unavailable".to_string());
    }
    if let Some(cwd) = params.cwd.as_ref() {
        let cwd = sanitize_summary_component(cwd.as_str(), 256);
        if !cwd.is_empty() {
            components.push(format!("cwd: {cwd}"));
        }
    }
    if let Some(reason) = params.reason.as_deref() {
        let reason = sanitize_summary_component(reason, 256);
        if !reason.is_empty() {
            components.push(format!("reason: {reason}"));
        }
    }
    let mut permissions = Vec::new();
    if params.network_approval_context.is_some()
        || params.proposed_network_policy_amendments.is_some()
    {
        permissions.push("network");
    }
    if let Some(additional) = params.additional_permissions.as_ref() {
        if additional.network.is_some() {
            permissions.push("additional-network");
        }
        if additional.file_system.is_some() {
            permissions.push("additional-filesystem");
        }
    }
    if params.proposed_execpolicy_amendment.is_some() {
        permissions.push("exec-policy-amendment");
    }
    if !permissions.is_empty() {
        permissions.sort_unstable();
        permissions.dedup();
        components.push(format!("permissions: {}", permissions.join(",")));
    }
    let summary = sanitize_summary_component(
        &format!("Command approval requested; {}", components.join("; ")),
        codex_hepta_matrix_protocol::MAX_PENDING_APPROVAL_SUMMARY_BYTES,
    );
    (summary, action.is_some())
}

fn file_change_approval_summary(
    params: &codex_app_server_protocol::FileChangeRequestApprovalParams,
) -> (String, bool) {
    let grant_root = params
        .grant_root
        .as_ref()
        .map(|path| sanitize_summary_component(&path.to_string_lossy(), 512))
        .filter(|path| !path.is_empty());
    let reason = params
        .reason
        .as_deref()
        .map(|reason| sanitize_summary_component(reason, 320))
        .filter(|reason| !reason.is_empty());
    let mut components = Vec::new();
    if let Some(root) = grant_root.as_deref() {
        components.push(format!("root: {root}"));
    }
    if let Some(reason) = reason.as_deref() {
        components.push(format!("reason: {reason}"));
    }
    if components.is_empty() {
        components.push("scope: unavailable".to_string());
    }
    let summary = sanitize_summary_component(
        &format!("File change approval requested; {}", components.join("; ")),
        codex_hepta_matrix_protocol::MAX_PENDING_APPROVAL_SUMMARY_BYTES,
    );
    (summary, grant_root.is_some())
}

fn typed_action_preview(actions: &[CommandAction]) -> Option<String> {
    let previews = actions
        .iter()
        .take(3)
        .filter_map(|action| match action {
            CommandAction::Read { name, path, .. } => Some(format!(
                "read {} at {}",
                sanitize_summary_component(name, 96),
                sanitize_summary_component(path.as_str(), 256)
            )),
            CommandAction::ListFiles { path, .. } => Some(format!(
                "list files{}",
                path.as_deref()
                    .map(|path| format!(" at {}", sanitize_summary_component(path, 256)))
                    .unwrap_or_default()
            )),
            CommandAction::Search { query, path, .. } => Some(format!(
                "search{}{}",
                query
                    .as_deref()
                    .map(|query| format!(" for {}", sanitize_summary_component(query, 160)))
                    .unwrap_or_default(),
                path.as_deref()
                    .map(|path| format!(" at {}", sanitize_summary_component(path, 256)))
                    .unwrap_or_default()
            )),
            CommandAction::Unknown { command } => {
                let command = sanitize_summary_component(command, 360);
                (!command.is_empty()).then_some(command)
            }
        })
        .filter(|preview| !preview.trim().is_empty())
        .collect::<Vec<_>>();
    (!previews.is_empty()).then(|| previews.join(" | "))
}

fn sanitize_summary_component(value: &str, max_bytes: usize) -> String {
    let mut output = String::new();
    let mut pending_space = false;
    for character in value.chars() {
        let forbidden = character.is_control()
            || matches!(
                character,
                '\u{061c}'
                    | '\u{200e}'..='\u{200f}'
                    | '\u{202a}'..='\u{202e}'
                    | '\u{2066}'..='\u{2069}'
            );
        if forbidden || character.is_whitespace() {
            pending_space = !output.is_empty();
            continue;
        }
        let extra = usize::from(pending_space) + character.len_utf8();
        if output.len().saturating_add(extra) > max_bytes {
            break;
        }
        if pending_space {
            output.push(' ');
            pending_space = false;
        }
        output.push(character);
    }
    output
}

fn supported_command_decisions(
    available: Option<&[CommandExecutionApprovalDecision]>,
) -> Vec<codex_hepta_matrix_protocol::LocalApprovalDecision> {
    use codex_hepta_matrix_protocol::LocalApprovalDecision;

    let Some(available) = available else {
        return all_local_approval_decisions();
    };
    let supports = |decision: LocalApprovalDecision| {
        available.iter().any(|candidate| {
            matches!(
                (candidate, decision),
                (
                    CommandExecutionApprovalDecision::Accept,
                    LocalApprovalDecision::Accept
                ) | (
                    CommandExecutionApprovalDecision::AcceptForSession,
                    LocalApprovalDecision::AcceptForSession
                ) | (
                    CommandExecutionApprovalDecision::Decline,
                    LocalApprovalDecision::Decline
                ) | (
                    CommandExecutionApprovalDecision::Cancel,
                    LocalApprovalDecision::Cancel
                )
            )
        })
    };
    all_local_approval_decisions()
        .into_iter()
        .filter(|decision| supports(*decision))
        .collect()
}

fn stable_approval_key(
    kind: &str,
    request_id: &RequestId,
    thread_id: &str,
    turn_id: &str,
    item_id: &str,
    approval_id: Option<&str>,
) -> Result<String, MatrixdRunError> {
    let framed = serde_json::to_vec(&(
        "hepta.matrix.pending-approval.v1",
        kind,
        request_id,
        thread_id,
        turn_id,
        item_id,
        approval_id,
    ))?;
    Ok(format!(
        "approval-{}",
        Sha256Digest::for_bytes(&framed).as_str()
    ))
}

async fn run_agentd_health_monitor(
    socket: std::path::PathBuf,
    agent_id: codex_hepta_contracts::AgentId,
    spawn_generation: u64,
    connections: Arc<MatrixdConnectionState>,
    cancel: CancellationToken,
) -> Result<(), MatrixdRunError> {
    let client = AgentdClient::new(socket, agent_id, spawn_generation)?;
    let mut interval = tokio::time::interval(AGENTD_HEALTH_POLL);
    interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            biased;
            _ = cancel.cancelled() => return Ok(()),
            _ = interval.tick() => {
                let health = match client.health().await {
                    Ok(health) => health,
                    Err(error) => {
                        connections.set_agentd_connected(false);
                        return Err(error.into());
                    }
                };
                if !health.ready || health.fenced {
                    connections.set_agentd_connected(false);
                    if health.fenced {
                        connections.set_fenced();
                    }
                    return Err(MatrixdRunError::AgentdFenced);
                }
                connections.set_agentd_connected(true);
            }
        }
    }
}

async fn shutdown_signal() -> Result<(), MatrixdRunError> {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
        tokio::select! {
            result = tokio::signal::ctrl_c() => result?,
            _ = terminate.recv() => {},
        }
        Ok(())
    }
    #[cfg(not(unix))]
    {
        tokio::signal::ctrl_c().await?;
        Ok(())
    }
}

fn system_time_ms() -> Result<u64, MatrixdRunError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| MatrixdRunError::Clock)?
        .as_millis();
    u64::try_from(millis).map_err(|_| MatrixdRunError::Clock)
}

#[derive(Debug, thiserror::Error)]
pub enum MatrixdRunError {
    #[error("invalid matrixd runtime configuration: {0}")]
    Invalid(String),
    #[error("another matrixd already owns this Agent root")]
    AlreadyRunning,
    #[error("the Matrix ingress durable write path was fenced")]
    IngressFenced,
    #[error("the exact-generation agentd is no longer ready")]
    AgentdFenced,
    #[error("the Agent App Server event stream disconnected")]
    AppServerDisconnected,
    #[error("matrixd runtime task exited unexpectedly: {0}")]
    TaskExited(&'static str),
    #[error("matrixd runtime task failed to join: {0}")]
    TaskJoin(String),
    #[error("system clock is outside the supported range")]
    Clock,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Control(#[from] crate::control::MatrixdControlError),
    #[error(transparent)]
    Agentd(#[from] codex_hepta_agentd::AgentdError),
    #[error(transparent)]
    Bridge(#[from] crate::MatrixBridgeError),
    #[error(transparent)]
    Runtime(#[from] crate::MatrixRuntimeError),
    #[error(transparent)]
    Store(#[from] codex_hepta_matrix_store::MatrixDurableError),
    #[error(transparent)]
    Sdk(#[from] codex_hepta_matrix_sdk::MatrixSdkError),
    #[error(transparent)]
    SdkConfig(#[from] codex_hepta_matrix_sdk::MatrixSidecarConfigError),
    #[error(transparent)]
    Outbox(#[from] codex_hepta_matrix_sdk::OutboxDispatchError),
}

#[cfg(test)]
#[path = "runner_startup_tests.rs"]
mod startup_tests;

#[cfg(test)]
mod tests {
    use super::MATRIX_PLANE_GENERATION;
    use super::command_approval_summary;
    use super::file_change_approval_summary;
    use super::matrix_plane_generation;
    use codex_app_server_protocol::CommandExecutionRequestApprovalParams;
    use codex_app_server_protocol::FileChangeRequestApprovalParams;
    use codex_hepta_matrix_protocol::MAX_PENDING_APPROVAL_SUMMARY_BYTES;

    fn assert_safe_bounded_summary(summary: &str) {
        assert!(!summary.is_empty());
        assert!(summary.len() <= MAX_PENDING_APPROVAL_SUMMARY_BYTES);
        assert!(!summary.chars().any(|character| {
            character.is_control()
                || matches!(
                    character,
                    '\u{061c}'
                        | '\u{200e}'..='\u{200f}'
                        | '\u{202a}'..='\u{202e}'
                        | '\u{2066}'..='\u{2069}'
                )
        }));
    }

    #[test]
    fn product_runner_has_one_durable_sync_authority() {
        let source = include_str!("runner.rs");
        let handler_api = ["install_ingress", "_handler"].concat();
        let unsafe_sync_api = ["sync_until", "_cancelled"].concat();
        assert!(source.contains("sync_durable_until_cancelled"));
        assert!(!source.contains(&handler_api));
        assert!(!source.contains(&unsafe_sync_api));
        assert!(
            source.find("acquire_process_lock(&config)")
                < source.find("MatrixDurableStore::open(&config.layout"),
            "the per-Agent matrixd lock must precede SQLite open/migration",
        );
        assert_eq!(MATRIX_PLANE_GENERATION, 1);
        assert_eq!(matrix_plane_generation(1), matrix_plane_generation(2));
        assert_eq!(matrix_plane_generation(u64::MAX), MATRIX_PLANE_GENERATION);
    }

    #[test]
    fn command_approval_summary_is_typed_safe_bounded_and_does_not_echo_hidden_fields() {
        let long_reason = format!("why\u{202e}\n{}", "🧠".repeat(600));
        let params: CommandExecutionRequestApprovalParams =
            serde_json::from_value(serde_json::json!({
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "startedAtMs": 1,
                "reason": long_reason,
                "networkApprovalContext": {
                    "host": "AUTH_TOKEN_SENTINEL.example",
                    "protocol": "https"
                },
                "command": "RAW_AUTH_TOKEN_SENTINEL",
                "cwd": "/tmp/work\u{2066}space",
                "commandActions": [{
                    "type": "read",
                    "command": "TYPED_ACTION_RAW_TOKEN_SENTINEL",
                    "name": "config\u{202e}\nfile",
                    "path": "/tmp/input"
                }]
            }))
            .expect("valid command approval fixture");

        let (summary, actionable) = command_approval_summary(&params);
        assert!(actionable);
        assert_safe_bounded_summary(&summary);
        assert!(summary.contains("read config file at /tmp/input"));
        assert!(summary.contains("cwd: /tmp/work space"));
        assert!(summary.contains("permissions: network"));
        assert!(!summary.contains("AUTH_TOKEN_SENTINEL.example"));
        assert!(!summary.contains("RAW_AUTH_TOKEN_SENTINEL"));
        assert!(!summary.contains("TYPED_ACTION_RAW_TOKEN_SENTINEL"));
    }

    #[test]
    fn file_approval_summary_bounds_multibyte_and_strips_control_and_bidi() {
        let params: FileChangeRequestApprovalParams = serde_json::from_value(serde_json::json!({
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "item-1",
            "startedAtMs": 1,
            "reason": format!("need\nwrite\u{202d}{}", "界".repeat(700)),
            "grantRoot": "/tmp/project\u{2069}\nroot"
        }))
        .expect("valid file approval fixture");

        let (summary, actionable) = file_change_approval_summary(&params);
        assert!(actionable);
        assert_safe_bounded_summary(&summary);
        assert!(summary.contains("root: /tmp/project root"));
        assert!(summary.contains("reason: need write"));
    }

    #[test]
    fn file_approval_reason_without_a_concrete_scope_is_not_actionable() {
        let params: FileChangeRequestApprovalParams = serde_json::from_value(serde_json::json!({
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "item-1",
            "startedAtMs": 1,
            "reason": "please allow this change",
            "grantRoot": null
        }))
        .expect("valid file approval fixture");

        let (summary, actionable) = file_change_approval_summary(&params);
        assert!(!actionable);
        assert_safe_bounded_summary(&summary);
        assert!(summary.contains("reason: please allow this change"));
    }
}
