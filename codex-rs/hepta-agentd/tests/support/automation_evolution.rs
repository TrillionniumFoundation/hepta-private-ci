//! Actual Agentd/App Server process entry, legacy owner migration and retirement.
//! The provider is a local fixture. This measures bounded control/storage work,
//! not model quality, independent release acceptance or production capacity.

use super::AGENT_A;
use super::AgentFixture;
use super::AutomationSchedule;
use super::AutomationTaskDraft;
use super::Duration;
use super::FleetHarness;
use super::Instant;
use super::MockResponsesConfig;
use super::ProductClient;
use super::Result;
use super::SystemTime;
use super::UNIX_EPOCH;
use super::agent_generation;
use super::ensure;
use super::final_sse;
use super::json;
use super::responses;
use super::wait_inactive;
use codex_hepta_agent_components::automation::AUTOMATION_SCHEMA_VERSION;
use codex_hepta_agent_components::automation::AutomationError;
use codex_hepta_agent_components::automation::AutomationStore;
use codex_hepta_agent_components::automation::AutomationTaskState;
use codex_hepta_agent_components::automation::TimerPhase;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::migrate::Migrate;

static LEGACY_MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("../hepta-automation/migrations");

async fn seed_legacy_owner(agent: &AgentFixture) -> Result<Vec<Vec<u8>>> {
    let home = AbsolutePathBuf::from_absolute_path(agent.layout.automation_root())?;
    let database = agent.layout.automation_root().join("automation_1.sqlite3");
    let pool = SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(&database)
        .await?;
    let mut connection = pool.acquire().await?;
    connection
        .ensure_migrations_table("_sqlx_migrations")
        .await?;
    for migration in LEGACY_MIGRATOR
        .iter()
        .filter(|migration| migration.version <= 3)
    {
        connection.apply("_sqlx_migrations", migration).await?;
    }
    sqlx::query(
        "INSERT INTO automation_meta(singleton,schema_version,owner_agent_id) VALUES(1,3,?)",
    )
    .bind(agent.agent_id.as_str())
    .execute(&mut *connection)
    .await?;
    let checksums = sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
        .fetch_all(&mut *connection)
        .await?;
    drop(connection);
    pool.close().await;
    Ok(checksums)
}

async fn owner_observation(agent: &AgentFixture) -> Result<(i64, i64, Vec<Vec<u8>>)> {
    let database = agent.layout.automation_root().join("automation_1.sqlite3");
    let options = sqlx::sqlite::SqliteConnectOptions::new()
        .filename(database)
        .read_only(true);
    let pool = sqlx::sqlite::SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await?;
    let schema = sqlx::query_scalar("SELECT schema_version FROM automation_meta WHERE singleton=1")
        .fetch_one(&pool)
        .await?;
    let tasks = sqlx::query_scalar("SELECT COUNT(*) FROM automation_tasks")
        .fetch_one(&pool)
        .await?;
    let checksums = sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
        .fetch_all(&pool)
        .await?;
    pool.close().await;
    Ok((schema, tasks, checksums))
}

async fn stop_process(fleet: &mut FleetHarness, agent: &AgentFixture) -> Result<()> {
    fleet.supervisor.stop(&agent.agent_id, Instant::now())?;
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        let report = fleet.supervisor.tick(Instant::now());
        ensure!(report.faults.is_empty(), "stop faults: {:?}", report.faults);
        if fleet
            .supervisor
            .snapshot(&agent.agent_id)
            .is_none_or(|snapshot| !snapshot.active)
        {
            return Ok(());
        }
        ensure!(
            Instant::now() < deadline,
            "process did not acknowledge stop"
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

fn resource_sample(agent: &AgentFixture, process_id: u32) -> Result<serde_json::Value> {
    let mut database_bytes = 0_u64;
    let mut wal_bytes = 0_u64;
    for entry in std::fs::read_dir(agent.layout.automation_root())? {
        let entry = entry?;
        let name = entry.file_name();
        if name == "automation_1.sqlite3" {
            database_bytes = entry.metadata()?.len();
        } else if name == "automation_1.sqlite3-wal" {
            wal_bytes = entry.metadata()?.len();
        }
    }
    #[cfg(target_os = "linux")]
    let resident_kib = {
        let status = std::fs::read_to_string(format!("/proc/{process_id}/status"))?;
        status.lines().find_map(|line| {
            line.strip_prefix("VmRSS:")?
                .split_whitespace()
                .next()?
                .parse::<u64>()
                .ok()
        })
    };
    #[cfg(not(target_os = "linux"))]
    let resident_kib: Option<u64> = None;
    Ok(
        json!({"database_bytes": database_bytes, "wal_bytes": wal_bytes,
        "process_id": process_id, "resident_kib": resident_kib}),
    )
}

fn latency_summary(samples: &[u128]) -> serde_json::Value {
    assert!(!samples.is_empty());
    let mut ordered = samples.to_vec();
    ordered.sort_unstable();
    let percentile = |percent: usize| ordered[(ordered.len() * percent).div_ceil(100) - 1];
    json!({"sample_count": ordered.len(), "p50_us": percentile(50),
        "p95_us": percentile(95), "p99_us": percentile(99), "samples_us": samples})
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn normal_product_migrates_restarts_hands_off_and_keeps_retired_automation_absent()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "automation-evolution-product")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let old_checksums = seed_legacy_owner(&agent).await?;
    ensure!(
        old_checksums.len() == 3,
        "fixture must be an actual v3 schema"
    );
    let started = Instant::now();
    fleet.start(&agent)?;
    let (mut control, mut health) = fleet.wait_ready(&agent, 1).await?;
    let startup_us = started.elapsed().as_micros();
    let (schema, task_count, migrated_checksums) = owner_observation(&agent).await?;
    ensure!(schema == i64::from(AUTOMATION_SCHEMA_VERSION) && task_count == 0);
    ensure!(
        old_checksums
            .iter()
            .all(|checksum| migrated_checksums.contains(checksum)),
        "normal startup changed historical migration identity"
    );
    let baseline = resource_sample(&agent, health.process_id)?;
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product
        .start_thread_with_ephemeral(&agent.workspace, false)
        .await?;
    product.shutdown().await?;
    let mut create_samples = Vec::new();
    let mut cancel_samples = Vec::new();
    let mut restart_samples = Vec::new();
    let mut task_ids = Vec::new();
    for cycle in 0..32 {
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let draft = AutomationTaskDraft::new(
            thread.clone(),
            format!("bounded lifecycle work {cycle}"),
            AutomationSchedule::Once,
            now + 3_600_000,
            now,
        );
        let started = Instant::now();
        let task = control.automation_create(draft).await?;
        create_samples.push(started.elapsed().as_micros());
        ensure!(
            task.owner_agent_id == agent.agent_id && task.state == AutomationTaskState::Enabled
        );
        task_ids.push(task.task_id);
        let started = Instant::now();
        let cancelled = control.automation_cancel(task.task_id).await?;
        cancel_samples.push(started.elapsed().as_micros());
        ensure!(
            cancelled.task_id == task.task_id && cancelled.state == AutomationTaskState::Cancelled
        );
        if cycle == 7 || cycle == 15 || cycle == 23 {
            let old_generation = agent_generation(&fleet, &agent.agent_id)?;
            let old_process = health.process_id;
            let started = Instant::now();
            fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
            let (fresh_control, fresh_health) =
                fleet.wait_new_spawn(&agent, old_generation).await?;
            restart_samples.push(started.elapsed().as_micros());
            ensure!(
                fresh_health.process_id != old_process,
                "restart must replace the process"
            );
            ensure!(
                control.health().await.is_err(),
                "old generation client was not fenced"
            );
            control = fresh_control;
            health = fresh_health;
        }
        let tasks = control.automation_list(64).await?;
        ensure!(
            tasks.len() == task_ids.len(),
            "committed tasks lost or duplicated"
        );
        ensure!(
            tasks
                .iter()
                .all(|task| task.state == AutomationTaskState::Cancelled)
        );
    }
    let loaded = resource_sample(&agent, health.process_id)?;
    let previous_generation = agent_generation(&fleet, &agent.agent_id)?;
    stop_process(&mut fleet, &agent).await?;
    let predecessor = AutomationStore::open(&agent.layout).await?;
    let before = predecessor.quiesce_timer().await?;
    ensure!(
        before.can_handoff(),
        "unfinished owner work must block handoff"
    );
    let successor = predecessor.handoff_timer().await?;
    let probe = AutomationTaskDraft::new(
        thread.clone(),
        "stale writer",
        AutomationSchedule::Once,
        4_000_000_000_000,
        1,
    );
    ensure!(predecessor.create_task(&probe).await == Err(AutomationError::TimerFenced));
    let resumed = successor.resume_timer().await?;
    ensure!(resumed.writer_epoch == before.writer_epoch + 1);
    predecessor.close().await;
    successor.close().await;
    fleet.start(&agent)?;
    let (current, current_health) = fleet.wait_new_spawn(&agent, previous_generation).await?;
    ensure!(current.automation_list(64).await?.len() == task_ids.len());
    let generation = agent_generation(&fleet, &agent.agent_id)?;
    stop_process(&mut fleet, &agent).await?;
    let owner = AutomationStore::open(&agent.layout).await?;
    ensure!(owner.quiesce_timer().await?.can_handoff());
    let retired = owner.retire_timer().await?;
    ensure!(retired.phase == TimerPhase::Retired);
    owner.close().await;
    fleet.start(&agent)?;
    let (retired_control, retired_health) = fleet.wait_new_spawn(&agent, generation).await?;
    ensure!(retired_health.ready && retired_health.process_id != current_health.process_id);
    let error = retired_control
        .automation_create(probe)
        .await
        .expect_err("retired capability must not accept new work");
    ensure!(error.to_string().contains("automation_unavailable"));
    let retained = AutomationStore::open(&agent.layout).await?;
    ensure!(
        retained.timer_status().await? == retired,
        "startup resurrected a retired owner"
    );
    ensure!(retained.list_tasks(64).await?.len() == task_ids.len());
    retained.close().await;
    let mut product = ProductClient::connect(&agent, &retired_control).await?;
    let normal_thread = product.start_thread(&agent.workspace).await?;
    let normal =
        responses::mount_sse_sequence(&model, vec![final_sse("retired-capability-normal-turn")])
            .await;
    product
        .run_turn(
            &normal_thread,
            "Normal product work after optional automation retirement.",
        )
        .await?;
    ensure!(
        normal.requests().len() == 1,
        "retiring automation broke normal product execution"
    );
    product.shutdown().await?;
    let (schema, retained_count, checksums) = owner_observation(&agent).await?;
    ensure!(schema == i64::from(AUTOMATION_SCHEMA_VERSION) && retained_count == 32);
    ensure!(checksums == migrated_checksums);
    println!(
        "{}",
        json!({"fixture": "normal_agentd_control_and_app_server_local_provider",
        "schema_from": 3, "schema_to": schema, "startup_and_migration_us": startup_us,
        "successful_create_cancel_cycles": task_ids.len(), "create": latency_summary(&create_samples),
        "cancel": latency_summary(&cancel_samples), "restart_samples_us": restart_samples,
        "baseline_resources": baseline, "loaded_resources": loaded,
        "retired_resources": resource_sample(&agent, retired_health.process_id)?,
        "retained_business_tasks": retained_count,
        "history_policy": "cancelled tasks are retained business history, not leaked runtime generations",
        "provider": "local_fixture", "long_run_or_production_capacity_claim": false})
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn normal_due_automation_reaches_app_server_terminal_and_does_not_replay_after_restart()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "automation-due-product")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    eprintln!("due automation stage: startup");
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    eprintln!("due automation stage: ready");
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product
        .start_thread_with_ephemeral(&agent.workspace, false)
        .await?;
    let model_call =
        responses::mount_sse_sequence(&model, vec![final_sse("normal-due-automation-terminal")])
            .await;
    let marker = "Execute the ordinary due automation capability exactly once.";
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let started = Instant::now();
    let task = control
        .automation_create(AutomationTaskDraft::new(
            thread.clone(),
            marker,
            AutomationSchedule::Once,
            now,
            now,
        ))
        .await?;
    eprintln!("due automation stage: task committed");
    let deadline = Instant::now() + Duration::from_secs(20);
    let terminal = loop {
        let tasks = control.automation_list(4).await?;
        let snapshot = match product.read_thread(&thread).await {
            Ok(snapshot) => snapshot,
            // Thread creation is lazy: before the first admitted user message
            // App Server explicitly refuses includeTurns. This is not a
            // terminal result and must not be confused with missing history
            // after a completed operation or any other transport/read failure.
            Err(error) if error.to_string().contains(
                "is not materialized yet; includeTurns is unavailable before first user message",
            ) => {
                ensure!(Instant::now() < deadline,
                    "due task never materialized the owning thread: {error:#}; tasks={tasks:?}");
                tokio::time::sleep(Duration::from_millis(25)).await;
                continue;
            }
            Err(error) => return Err(error),
        };
        // The task's Completed state records queue admission. Require an
        // independently observed App Server terminal, not an ACK-as-success.
        if tasks.iter().any(|value| {
            value.task_id == task.task_id && value.state == AutomationTaskState::Completed
        }) && snapshot.thread.turns.len() == 1
            && snapshot.thread.turns[0].status == codex_app_server_protocol::TurnStatus::Completed
        {
            break snapshot;
        }
        ensure!(
            Instant::now() < deadline,
            "due task never reached actual App Server completion"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    };
    eprintln!("due automation stage: terminal observed");
    let terminal_us = started.elapsed().as_micros();
    ensure!(
        model_call.requests().len() == 1,
        "normal queue did not dispatch exactly once"
    );
    ensure!(
        serde_json::to_string(&terminal.thread)?.contains(marker),
        "wrong input reached the owning thread"
    );
    let turn_id = terminal.thread.turns[0].id.clone();
    product.shutdown().await?;
    eprintln!("due automation stage: first client closed");
    let generation = agent_generation(&fleet, &agent.agent_id)?;
    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let (recovered_control, _) = fleet.wait_new_spawn(&agent, generation).await?;
    eprintln!("due automation stage: replacement ready");
    let mut recovered_product = ProductClient::connect(&agent, &recovered_control).await?;
    let recovered = recovered_product.read_thread(&thread).await?;
    ensure!(recovered.thread.turns.len() == 1 && recovered.thread.turns[0].id == turn_id);
    ensure!(recovered.thread.turns[0].status == codex_app_server_protocol::TurnStatus::Completed);
    let tasks = recovered_control.automation_list(4).await?;
    ensure!(
        tasks.len() == 1
            && tasks[0].task_id == task.task_id
            && tasks[0].state == AutomationTaskState::Completed
            && tasks[0].next_run_at_ms.is_none()
    );
    ensure!(
        model_call.requests().len() == 1,
        "restart replayed a completed occurrence"
    );
    eprintln!("due automation stage: recovered terminal checked");
    recovered_product.shutdown().await?;
    println!(
        "{}",
        json!({
            "fixture": "normal_due_automation_to_app_server_terminal",
            "terminal_us": terminal_us, "provider_request_count": 1,
            "retained_task_count": 1, "retained_turn_count": 1,
            "same_terminal_after_process_restart": true,
            "provider": "local_fixture", "external_effect_completion_claim": false,
        })
    );
    Ok(())
}

#[path = "automation_evolution_soak.rs"]
mod soak;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn normal_pending_task_survives_kill_without_old_client_or_provider_replay() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "pending-automation-process-loss")?;
    let model = wiremock::MockServer::builder()
        .body_print_limit(wiremock::BodyPrintLimit::Limited(512))
        .start()
        .await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let model_calls = responses::mount_sse_sequence(
        &model,
        vec![final_sse("normal-product-after-pending-task-recovery")],
    )
    .await;
    fleet.start(&agent)?;
    let (original, old_health) = fleet.wait_ready(&agent, 1).await?;
    let mut product = ProductClient::connect(&agent, &original).await?;
    let thread = product
        .start_thread_with_ephemeral(&agent.workspace, false)
        .await?;
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let pending = original
        .automation_create(AutomationTaskDraft::new(
            thread,
            "persisted but not due across process loss",
            AutomationSchedule::Once,
            now + 3_600_000,
            now,
        ))
        .await?;
    ensure!(pending.state == AutomationTaskState::Enabled);
    product.shutdown().await?;
    let old_generation = agent_generation(&fleet, &agent.agent_id)?;
    let started = Instant::now();
    // Use the real supervisor's immediate kill, not graceful drain or a
    // synthetic owner reopen. The durable task has not been cancelled/settled.
    fleet.supervisor.kill(&agent.agent_id)?;
    wait_inactive(&mut fleet, &agent.agent_id).await?;
    fleet.start(&agent)?;
    let (current, health) = fleet.wait_new_spawn(&agent, old_generation).await?;
    let recovery_us = started.elapsed().as_micros();
    ensure!(health.process_id != old_health.process_id);
    let recovered = current.automation_list(8).await?;
    ensure!(
        recovered == vec![pending.clone()],
        "pending task changed across kill/reopen"
    );
    ensure!(
        original.automation_cancel(pending.task_id).await.is_err(),
        "old generation client mutated the successor"
    );
    ensure!(current.automation_list(8).await? == vec![pending.clone()]);
    ensure!(
        model_calls.requests().is_empty(),
        "not-due work reached the provider"
    );
    ensure!(
        current.automation_cancel(pending.task_id).await?.state == AutomationTaskState::Cancelled
    );
    let mut normal = ProductClient::connect(&agent, &current).await?;
    let thread = normal.start_thread(&agent.workspace).await?;
    normal
        .run_turn(&thread, "normal product after pending task recovery")
        .await?;
    normal.shutdown().await?;
    ensure!(
        model_calls.requests().len() == 1,
        "recovery duplicated provider dispatch"
    );
    let (_, count, _) = owner_observation(&agent).await?;
    ensure!(count == 1);
    println!(
        "{}",
        json!({
            "fixture": "normal_pending_task_kill_recovery",
            "retained_pending_tasks": count,
            "unchanged_task_after_reopen": true,
            "old_generation_cancel_rejected": true,
            "recovery_us": recovery_us,
            "provider_requests_from_pending_task": 0,
            "post_recovery_normal_turns": 1,
            "provider": "local_fixture",
            "provider_inflight_crash_claim": false
        })
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ordinary_product_lists_256_retained_tasks_without_oversized_frames() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "bounded-task-listing-product")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    // Seed through the same durable owner before handing it to the daemon.
    // Future tasks do not dispatch; the listing is exercised over the actual
    // control socket, not by substituting an in-memory response builder.
    let store = AutomationStore::open(&agent.layout).await?;
    for index in 0..256 {
        store
            .create_task(&AutomationTaskDraft::new(
                "019153a4-3088-7e03-a56a-9b1964f75ddd",
                format!("retained task {index}: {}", "x".repeat(300)),
                AutomationSchedule::Once,
                4_000_000_000_000,
                index / 8 + 1,
            ))
            .await?;
    }
    let expected = store.list_tasks(256).await?;
    ensure!(serde_json::to_vec(&expected)?.len() > 65_536);
    store.close().await;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let started = Instant::now();
    let actual = control.automation_list(256).await?;
    let listing_us = started.elapsed().as_micros();
    ensure!(
        actual == expected,
        "paged control listing lost or reordered owner rows"
    );
    let page = control.automation_list_page_v1(256, None).await?;
    ensure!(page.tasks.len() <= 32 && page.next_cursor.is_some());
    ensure!(serde_json::to_vec(&page)?.len() <= 60 * 1024);
    let (_, retained, _) = owner_observation(&agent).await?;
    ensure!(retained == 256);
    println!(
        "{}",
        json!({"fixture": "ordinary_control_paged_task_history",
        "retained_tasks": actual.len(), "listing_us": listing_us,
        "legacy_result_bytes": serde_json::to_vec(&expected)?.len(),
        "first_page_bytes": serde_json::to_vec(&page)?.len(),
        "control_frame_limit_bytes": 65_536, "provider": "local_unused_fixture"})
    );
    Ok(())
}
