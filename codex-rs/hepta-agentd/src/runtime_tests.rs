use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
#[cfg(feature = "qualification-cognitive-write")]
use std::time::SystemTime;
#[cfg(feature = "qualification-cognitive-write")]
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTick;
use codex_hepta_contracts::AgentId;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveRuntime;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::CompactFence;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::H7TrajectoryAppend;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::H7TrajectoryEventKind;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::H7TrajectoryRecord;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::LocalAdmission;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::LocalTurnLifecycleBinding;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::LogicalTurnAttemptRequest;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::LogicalTurnRequest;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::append_h7_trajectory_event_bound;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::h7_trajectory_local_receipt_digest;
use codex_hepta_paths::HeptaFleetRoot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::AgentdIdentity;
use super::AgentdState;
use super::CompletedRuntimeTask;
use super::EVENT_CAPACITY;
use super::cleanup_runtime_tasks;
use super::monitor_runtime;
use super::open_automation_store_after_generation_fence;
use super::open_cognitive_runtime_after_generation_fence;
use super::require_cognitive_runtime_for_profile;
use crate::AgentdMethod;
use crate::AgentdPayload;
#[cfg(feature = "qualification-cognitive-write")]
use crate::app_runtime::app_server_runtime_options_for_agent;
use crate::automation::DispatchRetryBudget;
use crate::automation::handle_automation_tick;
use crate::automation::run_automation_scheduler;
#[cfg(feature = "qualification-cognitive-write")]
use crate::qualification_writer::prepare_qualification_turn_writer_input;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory::LocalLeaseHeadDisposition;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[tokio::test]
async fn cleanup_never_polls_the_join_handle_already_consumed_by_select() {
    let mut control_task = tokio::spawn(async {});
    (&mut control_task)
        .await
        .expect("selected control task should complete");
    let mut app_server_task = tokio::spawn(std::future::pending::<()>());
    let mut monitor_task = tokio::spawn(std::future::pending::<()>());
    let mut automation_task = tokio::spawn(std::future::pending::<()>());

    cleanup_runtime_tasks(
        Some(CompletedRuntimeTask::Control),
        &mut control_task,
        &mut app_server_task,
        &mut monitor_task,
        &mut automation_task,
    )
    .await;

    assert!(control_task.is_finished());
    assert!(app_server_task.is_finished());
    assert!(monitor_task.is_finished());
    assert!(automation_task.is_finished());
}

struct RuntimeFixture {
    _temp: tempfile::TempDir,
    state: Arc<AgentdState>,
    registry: FleetRegistry,
    identity: AgentdIdentity,
}

fn runtime_fixture() -> RuntimeFixture {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp
        .path()
        .canonicalize()
        .expect("canonical temporary root");
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("valid fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("initialize registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("create workspace");
    let workspace = workspace.canonicalize().expect("canonical workspace");
    let agent_id = AgentId::parse(AGENT_ID).expect("valid agent id");
    let binding = WorkspaceBinding::new(&workspace, &fleet_root).expect("workspace binding");
    let manifest = AgentManifest::new(agent_id.clone(), binding, ResourceBudget::local_default())
        .expect("agent manifest");
    let record = registry.register(manifest).expect("register agent");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("start generation");
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources.clone(),
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = Arc::new(
        AgentdState::new(identity.clone(), registry.clone(), EVENT_CAPACITY).expect("agent state"),
    );
    RuntimeFixture {
        _temp: temp,
        state,
        registry,
        identity,
    }
}

#[tokio::test]
async fn duplicate_automation_attachment_does_not_replace_the_live_store() {
    let fixture = runtime_fixture();
    fixture
        .registry
        .compare_and_transition(&fixture.identity.agent_id, 1, AgentLifecycle::Running)
        .expect("running generation");
    fixture.state.refresh_generation().expect("refresh running");
    fixture
        .state
        .mark_app_server_ready()
        .expect("mark App Server ready");

    let first = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("first automation store");
    let replacement = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("replacement automation store");
    fixture
        .state
        .attach_automation_store(first.clone())
        .expect("attach first automation store");
    assert!(matches!(
        fixture.state.attach_automation_store(replacement),
        Err(crate::AgentdError::Protocol(_))
    ));

    first.close().await;
    let response = fixture
        .state
        .response(1, 1, AgentdMethod::AutomationList { limit: 1 })
        .await
        .expect("closed original store degrades to typed unavailable");
    assert!(matches!(
        response.payload,
        AgentdPayload::Error { ref code, .. } if code == "automation_unavailable"
    ));
}

#[tokio::test]
async fn unavailable_cognitive_store_degrades_without_leaking_open_error() {
    let fixture = runtime_fixture();
    let runtime = open_cognitive_runtime_after_generation_fence(&fixture.state, || async {
        Err(CognitiveStoreError::Unavailable(
            "/private/raw/cognitive.sqlite: secret detail".to_string(),
        ))
    })
    .await
    .expect("store outage must not block agent execution");

    let CognitiveRuntime::Unavailable(reason) = runtime else {
        panic!("store outage must remain distinguishable from absence");
    };
    assert_eq!(reason.code(), "storage_unavailable");
    assert!(!format!("{reason:?}").contains("/private/raw"));
}

#[cfg(feature = "qualification-cognitive-write")]
#[test]
fn qualification_profile_fails_closed_when_cognitive_store_is_unavailable() {
    let result = require_cognitive_runtime_for_profile(CognitiveRuntime::Unavailable(
        codex_hepta_memory::CognitiveUnavailableReason::StorageUnavailable,
    ));
    assert!(matches!(
        result,
        Err(crate::AgentdError::QualificationCognitiveRuntimeUnavailable)
    ));
}

#[cfg(feature = "qualification-cognitive-write")]
#[tokio::test]
async fn qualification_host_binds_one_local_turn_and_replays_exactly_once() {
    let fixture = runtime_fixture();
    fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .expect("running generation");
    fixture.state.refresh_generation().expect("refresh running");
    fixture
        .state
        .mark_app_server_ready()
        .expect("mark App Server ready");

    let store = Arc::new(
        CognitiveStore::open(&fixture.identity.layout)
            .await
            .expect("open cognitive store"),
    );
    let runtime = CognitiveRuntime::Available(Arc::clone(&store));
    let options = app_server_runtime_options_for_agent(
        &fixture.identity,
        Arc::clone(&fixture.state),
        runtime,
    )
    .expect("runtime options");
    assert!(
        options.hepta_qualification_turn_writer.is_some(),
        "the explicit qualification profile must carry the Agentd-owned host"
    );

    let input = prepare_qualification_turn_writer_input(
        Arc::clone(&fixture.state),
        Arc::clone(&store),
        fixture.identity.agent_id.clone(),
        fixture.identity.spawn_generation,
        "turn:agentd-qualification-host".to_string(),
    )
    .await
    .expect("prepare host-bound input");
    let persisted_expiry = input
        .lease
        .binding()
        .expect("host-bound binding")
        .lease_expires_at_unix_seconds;

    // The second prepare computes a fresh wall-clock TTL.  Wait until its
    // newly computed expiry would differ from the persisted one, proving
    // that the exact replay uses the stored binding rather than a fresh TTL.
    let _second_start = loop {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs();
        if now.saturating_add(3_600) != persisted_expiry {
            break now;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    let replayed_input = prepare_qualification_turn_writer_input(
        Arc::clone(&fixture.state),
        Arc::clone(&store),
        fixture.identity.agent_id.clone(),
        fixture.identity.spawn_generation,
        "turn:agentd-qualification-host".to_string(),
    )
    .await
    .expect("same-spawn prepare reopens the exact active head");
    assert_eq!(
        replayed_input
            .lease
            .binding()
            .expect("replayed binding")
            .lease_expires_at_unix_seconds,
        persisted_expiry,
        "same-spawn replay must retain the persisted TTL binding"
    );
    assert_eq!(
        replayed_input.lease.fencing_token(),
        input.lease.fencing_token()
    );
    assert_eq!(
        replayed_input
            .lease
            .snapshot_counts()
            .await
            .expect("replayed counts")
            .lease_rows,
        1,
        "reprepare must not append a second lease row"
    );
    replayed_input
        .binding
        .verify_current(&replayed_input.lease, &replayed_input.executor)
        .await
        .expect("binding remains current");
    assert!(!replayed_input.binding.external_effects);
    assert!(!replayed_input.binding.kg_write_authority);
    assert!(!replayed_input.binding.production_caller);

    replayed_input
        .lease
        .admit(
            replayed_input.occurrence_key.clone(),
            "codex.turn.qualification.start.v1",
            replayed_input.payload_json.clone(),
        )
        .await
        .expect("first local admission");
    replayed_input
        .lease
        .admit(
            replayed_input.occurrence_key.clone(),
            "codex.turn.qualification.start.v1",
            replayed_input.payload_json.clone(),
        )
        .await
        .expect("duplicate local admission replays");
    let counts = replayed_input
        .lease
        .snapshot_counts()
        .await
        .expect("local counts");
    assert_eq!(counts.event_rows, 1);
    assert_eq!(counts.outbox_rows, 1);
    // This fixture exercises admission replay without executing the turn
    // lifecycle contributor. Withdraw its queued intent before closing the
    // lease; admission alone supplies no completed-turn observation.
    replayed_input
        .lease
        .rollback_occurrence(
            replayed_input.occurrence_key.clone(),
            "qualification fixture ended before turn execution",
        )
        .await
        .expect("withdraw unexecuted local intent");
    replayed_input
        .lease
        .release()
        .await
        .expect("release local lease");
}

#[cfg(feature = "qualification-cognitive-write")]
#[tokio::test]
async fn qualification_prepare_takes_over_expired_registry_head_without_evidence() {
    let fixture = runtime_fixture();
    fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .expect("running generation");
    fixture.state.refresh_generation().expect("refresh running");
    fixture
        .state
        .mark_app_server_ready()
        .expect("mark App Server ready");

    let store = Arc::new(
        CognitiveStore::open(&fixture.identity.layout)
            .await
            .expect("open cognitive store"),
    );
    let turn_id = "turn:agentd-expired-qualification";
    let spawn_generation = fixture.identity.spawn_generation;
    let fleet_generation = fixture
        .state
        .qualification_turn_authority()
        .expect("qualification authority");
    let logical = LogicalTurnRequest::new(
        format!("qualification:logical:{turn_id}"),
        "qualification:local",
        Sha256Digest::for_bytes(format!("qualification:logical-binding:v1:{turn_id}").as_bytes()),
    )
    .expect("logical request");
    let old = LogicalTurnAttemptRequest::new(
        "seed-expired-attempt",
        "seed-expired-lease",
        "seed-expired-journal",
        "seed-expired-trajectory",
        "seed-expired-occurrence",
        /*authority_epoch*/ 1,
        fleet_generation,
        /*generation*/ 1,
        "seed-expired-fence",
        /*lease_expires_at_unix_seconds*/ 1,
    )
    .expect("expired attempt request");
    store
        .reserve_or_replay_logical_turn(logical, old.clone())
        .await
        .expect("seed expired registry attempt");

    let input = prepare_qualification_turn_writer_input(
        Arc::clone(&fixture.state),
        Arc::clone(&store),
        fixture.identity.agent_id.clone(),
        spawn_generation,
        turn_id.to_string(),
    )
    .await
    .expect("expired zero-evidence attempt is taken over");
    assert_ne!(input.lease.lease_id(), old.lease_id);
    assert_ne!(input.trajectory_id, old.trajectory_id);
    let old_head = store
        .inspect_local_lease_head(old.lease_id)
        .await
        .expect("inspect superseded lease");
    assert_eq!(old_head.disposition, LocalLeaseHeadDisposition::RolledBack);
    input
        .lease
        .release()
        .await
        .expect("release takeover test lease");
}

#[cfg(feature = "qualification-cognitive-write")]
#[tokio::test]
async fn qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence() {
    let fixture = runtime_fixture();
    fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .expect("running generation");
    fixture.state.refresh_generation().expect("refresh running");
    fixture
        .state
        .mark_app_server_ready()
        .expect("mark App Server ready");

    let store = Arc::new(
        CognitiveStore::open(&fixture.identity.layout)
            .await
            .expect("open cognitive store"),
    );
    let fleet_generation = fixture
        .state
        .qualification_turn_authority()
        .expect("qualification authority");
    let turn_id = "turn:agentd-expired-terminal";
    let spawn_generation = fixture.identity.spawn_generation;
    let logical = LogicalTurnRequest::new(
        format!("qualification:logical:{turn_id}"),
        "qualification:local",
        Sha256Digest::for_bytes(format!("qualification:logical-binding:v1:{turn_id}").as_bytes()),
    )
    .expect("logical request");
    let expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + 1;
    let old = LogicalTurnAttemptRequest::new(
        "seed-terminal-attempt",
        "seed-terminal-lease",
        "seed-terminal-journal",
        "seed-terminal-trajectory",
        "seed-terminal-occurrence",
        /*authority_epoch*/ 1,
        fleet_generation,
        /*generation*/ 1,
        "seed-terminal-fence",
        expires_at,
    )
    .expect("terminal attempt request");
    let reservation = store
        .reserve_or_replay_logical_turn(logical, old)
        .await
        .expect("seed registry attempt");
    let codex_hepta_memory::LogicalTurnReservation::Acquired { attempt } = reservation else {
        panic!("seed must acquire registry attempt")
    };
    let head = store
        .inspect_local_lease_head(&attempt.lease_id)
        .await
        .expect("inspect seeded head")
        .head
        .expect("seeded head");
    let lease = store
        .reopen_host_bound_lease(
            head,
            attempt.authority_epoch,
            attempt.owner_epoch,
            attempt.lease_expires_at_unix_seconds,
        )
        .await
        .expect("reopen seeded lease");
    let fence = CompactFence::new(
        attempt.authority_epoch,
        attempt.owner_epoch,
        attempt.generation,
        attempt.fencing_token.clone(),
    )
    .expect("compact fence");
    let executor = store
        .open_local_compact_executor_bound(attempt.journal_id.clone(), fence, &lease)
        .await
        .expect("open compact executor");
    let binding =
        LocalTurnLifecycleBinding::from_handles(turn_id, &lease, &executor).expect("binding");
    let payload = r#"{"schema_version":1,"external_effect":false,"kg_write_authority":false,"production_caller":false}"#;
    let receipt = match lease
        .admit(
            attempt.occurrence_key.clone(),
            "codex.turn.qualification.start.v1",
            payload,
        )
        .await
        .expect("admit local intent")
    {
        LocalAdmission::Queued(receipt) | LocalAdmission::Replay(receipt) => receipt,
    };
    let trajectory_id = attempt.trajectory_id.clone();
    let start = H7TrajectoryRecord::new(
        trajectory_id.clone(),
        /*event_seq*/ 1,
        format!("{trajectory_id}:event:turn-start"),
        H7TrajectoryEventKind::TurnStart,
        turn_id,
        attempt.occurrence_key.clone(),
        /*causal_parent_seq*/ None,
        /*causal_parent_sha256*/ None,
        Sha256Digest::for_bytes(payload.as_bytes()),
        Sha256Digest::for_bytes(b"qualification:observation-only-policy:v1"),
        Sha256Digest::for_bytes(b"qualification:model-receipt:not-applicable:v1"),
        h7_trajectory_local_receipt_digest(&receipt),
        "turn_started",
        /*reward_bps*/ 0,
        /*safety_ok*/ true,
        r#"{"source":"qualification_turn_writer"}"#,
        "not_applicable",
    )
    .expect("start trajectory");
    let H7TrajectoryAppend::Inserted {
        event_sha256: parent,
        ..
    } = append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
        .await
        .expect("append H7 start")
    else {
        panic!("start must be inserted")
    };
    let terminal = H7TrajectoryRecord::terminal(
        trajectory_id.clone(),
        /*event_seq*/ 2,
        format!("{trajectory_id}:event:terminal:stop"),
        turn_id,
        format!("{}:terminal", attempt.occurrence_key),
        /*causal_parent_seq*/ 1,
        parent,
        Sha256Digest::for_bytes(b"terminal-state"),
        Sha256Digest::for_bytes(b"qualification:observation-only-policy:v1"),
        Sha256Digest::for_bytes(b"qualification:model-receipt:not-applicable:v1"),
        Sha256Digest::for_bytes(b"terminal-receipt"),
        "turn_stopped",
        "turn_stopped",
        r#"{"source":"qualification_turn_writer","terminal_action":"stop"}"#,
    )
    .expect("terminal trajectory");
    append_h7_trajectory_event_bound(&lease, &executor, &binding, &terminal)
        .await
        .expect("append H7 terminal");
    drop(binding);
    drop(executor);
    drop(lease);
    tokio::time::sleep(Duration::from_secs(2)).await;

    let result = prepare_qualification_turn_writer_input(
        Arc::clone(&fixture.state),
        Arc::clone(&store),
        fixture.identity.agent_id.clone(),
        spawn_generation,
        turn_id.to_string(),
    )
    .await;
    assert!(
        result.is_err(),
        "terminal recovery returns no writable input"
    );
    let inspected = store
        .inspect_local_lease_head(&attempt.lease_id)
        .await
        .expect("inspect recovered head");
    assert_eq!(
        inspected.disposition,
        LocalLeaseHeadDisposition::ExpiredActive,
        "registry-backed H7 quarantine must not mutate the active registry head"
    );
}

#[cfg(not(feature = "qualification-cognitive-write"))]
#[test]
fn default_profile_preserves_degraded_cognitive_runtime_behavior() {
    let result = require_cognitive_runtime_for_profile(CognitiveRuntime::Unavailable(
        codex_hepta_memory::CognitiveUnavailableReason::StorageUnavailable,
    ))
    .expect("default profile remains availability tolerant");
    assert!(matches!(
        result,
        CognitiveRuntime::Unavailable(
            codex_hepta_memory::CognitiveUnavailableReason::StorageUnavailable
        )
    ));
}

#[tokio::test]
async fn unavailable_automation_store_degrades_without_startup_failure() {
    let fixture = runtime_fixture();
    let store = open_automation_store_after_generation_fence(&fixture.state, || async {
        Err(AutomationError::Unavailable)
    })
    .await
    .expect("automation storage outage must not block agent execution");
    assert!(store.is_none());
}

#[tokio::test]
async fn automation_owner_mismatch_remains_fail_closed() {
    let fixture = runtime_fixture();
    let result = open_automation_store_after_generation_fence(&fixture.state, || async {
        Err(AutomationError::AccessDenied)
    })
    .await;
    assert!(matches!(
        result,
        Err(crate::AgentdError::Automation(
            AutomationError::AccessDenied
        ))
    ));
}

#[tokio::test]
async fn automation_generation_change_during_open_remains_fail_closed() {
    let fixture = runtime_fixture();
    let registry = fixture.registry.clone();
    let agent_id = fixture.identity.agent_id.clone();
    let result = open_automation_store_after_generation_fence(&fixture.state, move || async move {
        registry
            .compare_and_transition(&agent_id, 1, AgentLifecycle::Failed)
            .expect("concurrent generation change");
        Err(AutomationError::Unavailable)
    })
    .await;
    assert!(matches!(
        result,
        Err(crate::AgentdError::GenerationFenced(_))
    ));
}

#[tokio::test]
async fn runtime_automation_store_failure_stops_only_the_scheduler_plane() {
    let fixture = runtime_fixture();
    fixture
        .registry
        .compare_and_transition(&fixture.identity.agent_id, 1, AgentLifecycle::Running)
        .expect("running generation");
    fixture.state.refresh_generation().expect("refresh running");
    fixture
        .state
        .mark_app_server_ready()
        .expect("mark App Server ready");

    let store = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("open automation store");
    fixture
        .state
        .attach_automation_store(store.clone())
        .expect("attach automation store");
    let cancellation = CancellationToken::new();
    let scheduler_task = tokio::spawn(run_automation_scheduler(
        store.clone(),
        Arc::clone(&fixture.state),
        fixture.identity.clone(),
        cancellation.clone(),
    ));

    tokio::time::sleep(Duration::from_millis(500)).await;
    assert!(
        fixture
            .state
            .automation_is_available()
            .expect("automation state"),
        "scheduler did not enter its normal running loop"
    );
    store.close().await;
    timeout(Duration::from_secs(3), async {
        loop {
            if !fixture
                .state
                .automation_is_available()
                .expect("automation state")
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .expect("runtime store failure was not quarantined");

    assert!(
        !scheduler_task.is_finished(),
        "quarantined automation scheduler must wait for agentd cancellation"
    );
    let unavailable = fixture
        .state
        .response(1, 1, AgentdMethod::AutomationList { limit: 1 })
        .await
        .expect("typed unavailable response");
    assert!(matches!(
        unavailable.payload,
        AgentdPayload::Error { ref code, .. } if code == "automation_unavailable"
    ));
    let health = fixture
        .state
        .response(2, 1, AgentdMethod::Health)
        .await
        .expect("health response");
    assert!(matches!(
        health.payload,
        AgentdPayload::Health(ref snapshot) if snapshot.ready && !snapshot.fenced
    ));

    cancellation.cancel();
    timeout(Duration::from_secs(1), scheduler_task)
        .await
        .expect("scheduler did not observe cancellation")
        .expect("scheduler task panicked")
        .expect("quarantined scheduler returned an error");
}

#[tokio::test]
async fn dispatch_uncertain_tick_fail_stops_scheduler_until_cancelled() {
    let fixture = runtime_fixture();
    fixture
        .registry
        .compare_and_transition(&fixture.identity.agent_id, 1, AgentLifecycle::Running)
        .expect("running generation");
    fixture.state.refresh_generation().expect("refresh running");
    fixture
        .state
        .mark_app_server_ready()
        .expect("mark App Server ready");
    let store = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("open automation store");
    fixture
        .state
        .attach_automation_store(store.clone())
        .expect("attach automation store");

    let cancellation = CancellationToken::new();
    let state = Arc::clone(&fixture.state);
    let task = tokio::spawn({
        let cancellation = cancellation.clone();
        async move {
            let mut retry_budget = DispatchRetryBudget::default();
            handle_automation_tick(
                AutomationTick::DispatchUncertain {
                    task_id: codex_hepta_automation::AutomationTaskId::parse(
                        "019153a4-3088-7000-a56a-9b1964f75009",
                    )
                    .expect("task id"),
                    occurrence: 1,
                },
                &mut retry_budget,
                &state,
                &cancellation,
            )
            .await
        }
    });

    timeout(Duration::from_secs(2), async {
        loop {
            if !fixture
                .state
                .automation_is_available()
                .expect("automation state")
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("DispatchUncertain did not quarantine automation");
    assert!(!task.is_finished(), "fail-stop must wait for cancellation");
    cancellation.cancel();
    assert!(task.await.expect("handler task").expect("handler result"));
    let health = fixture
        .state
        .response(1, 1, AgentdMethod::Health)
        .await
        .expect("health response");
    assert!(matches!(
        health.payload,
        AgentdPayload::Health(ref snapshot) if snapshot.ready && !snapshot.fenced
    ));
}

#[tokio::test]
async fn automation_owner_fence_still_terminates_the_runtime_monitor() {
    let fixture = runtime_fixture();
    fixture.state.mark_fenced();
    let result = timeout(
        Duration::from_secs(1),
        monitor_runtime(Arc::clone(&fixture.state)),
    )
    .await
    .expect("fenced monitor did not terminate");
    assert!(matches!(
        result,
        Err(crate::AgentdError::GenerationFenced(_))
    ));
}

#[tokio::test]
async fn stale_generation_is_fenced_before_cognitive_store_open() {
    let fixture = runtime_fixture();
    let agent_id = &fixture.identity.agent_id;
    fixture
        .registry
        .compare_and_transition(agent_id, 1, AgentLifecycle::Running)
        .expect("running");
    fixture
        .registry
        .compare_and_transition(agent_id, 2, AgentLifecycle::Draining)
        .expect("draining");
    fixture
        .registry
        .compare_and_transition(agent_id, 3, AgentLifecycle::Stopped)
        .expect("stopped");
    fixture
        .registry
        .compare_and_transition(agent_id, 4, AgentLifecycle::Starting)
        .expect("new starting generation");
    let opened = Arc::new(AtomicBool::new(false));
    let opened_by_call = Arc::clone(&opened);
    let result =
        open_cognitive_runtime_after_generation_fence(&fixture.state, move || async move {
            opened_by_call.store(true, Ordering::SeqCst);
            Err(CognitiveStoreError::Unavailable("must not run".to_string()))
        })
        .await;

    assert!(matches!(
        result,
        Err(crate::AgentdError::GenerationFenced(_))
    ));
    assert!(!opened.load(Ordering::SeqCst));
    assert_eq!(
        std::fs::read_dir(fixture.identity.layout.cognitive_root())
            .expect("cognitive root")
            .count(),
        0,
        "a stale generation must not touch the cognitive database"
    );
}

#[tokio::test]
async fn generation_change_during_open_is_fenced_before_serving() {
    let fixture = runtime_fixture();
    let registry = fixture.registry.clone();
    let agent_id = fixture.identity.agent_id.clone();
    let opened = Arc::new(AtomicBool::new(false));
    let opened_by_call = Arc::clone(&opened);
    let result =
        open_cognitive_runtime_after_generation_fence(&fixture.state, move || async move {
            opened_by_call.store(true, Ordering::SeqCst);
            registry
                .compare_and_transition(&agent_id, 1, AgentLifecycle::Failed)
                .expect("concurrent generation change");
            Err(CognitiveStoreError::Unavailable(
                "simulated outage".to_string(),
            ))
        })
        .await;

    assert!(opened.load(Ordering::SeqCst));
    assert!(matches!(
        result,
        Err(crate::AgentdError::GenerationFenced(_))
    ));
}
