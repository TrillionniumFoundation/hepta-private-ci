//! Bounded load on the ordinary control socket, scheduler and App Server.
//! HEPTA_EVOLUTION_ROUNDS expands an explicitly requested experiment, not a
//! production option. Samples distinguish retained business history from leaks.

use super::AGENT_A;
use super::AutomationError;
use super::AutomationSchedule;
use super::AutomationStore;
use super::AutomationTaskDraft;
use super::AutomationTaskState;
use super::Duration;
use super::FleetHarness;
use super::Instant;
use super::MockResponsesConfig;
use super::ProductClient;
use super::Result;
use super::SystemTime;
use super::TimerPhase;
use super::UNIX_EPOCH;
use super::agent_generation;
use super::ensure;
use super::final_sse;
use super::json;
use super::latency_summary;
use super::owner_observation;
use super::resource_sample;
use super::responses;
use super::stop_process;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn normal_product_bounded_evolution_under_concurrent_load() -> Result<()> {
    let rounds = match std::env::var("HEPTA_EVOLUTION_ROUNDS") {
        Ok(value) => value.parse::<usize>()?,
        Err(std::env::VarError::NotPresent) => 4,
        Err(error) => return Err(error.into()),
    };
    ensure!(
        (2..=32).contains(&rounds),
        "experiment rounds must be in 2..=32"
    );
    const WIDTH: usize = 4;
    // Deliberate process rotations consume the same durable budget as fault
    // recovery. Declare this bounded experiment's budget instead of changing
    // production defaults, resetting its journal or advancing a synthetic clock.
    let mut supervisor_config = codex_hepta_supervisor::SupervisorConfig::local_default();
    supervisor_config.restart_max_attempts = u32::try_from(rounds)?;
    // High-churn experiment: exercise real persisted backoff without spending
    // the workload on production anti-flapping delays. Report this policy with
    // measurements; these are not production-default restart latency claims.
    supervisor_config.restart_backoff_base = Duration::from_micros(10);
    let restart_backoff_base_us = supervisor_config.restart_backoff_base.as_micros();
    let restart_window_ms = supervisor_config.restart_window.as_millis();
    let mut fleet = FleetHarness::with_supervisor_config(supervisor_config)?;
    let agent = fleet.register(AGENT_A, "bounded-evolution-load")?;
    let model = wiremock::MockServer::builder()
        .body_print_limit(wiremock::BodyPrintLimit::Limited(512))
        .start()
        .await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let model_calls = responses::mount_sse_sequence(
        &model,
        (0..rounds * WIDTH + 1)
            .map(|index| final_sse(&format!("evolution-load-{index}")))
            .collect(),
    )
    .await;
    let mut stage = "startup".to_string();
    let experiment_started = Instant::now();
    let outcome: Result<()> = async {
    let started = Instant::now();
    fleet.start(&agent)?;
    let (mut control, mut health) = fleet.wait_ready(&agent, 1).await?;
    let baseline = resource_sample(&agent, health.process_id)?;
    let mut wave_latencies = Vec::new();
    let mut restart_latencies = Vec::new();
    let mut samples = Vec::new();
    let mut terminal_identities = Vec::new();
    let mut verified_history_reads = 0_usize;
    for round in 0..rounds {
        let round_started = Instant::now();
        stage = format!("round {round}: thread creation");
        eprintln!("product evolution stage: {stage}");
        let mut product = ProductClient::connect(&agent, &control).await?;
        let mut threads = Vec::new();
        let mut drafts = Vec::new();
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        for slot in 0..WIDTH {
            let thread = product.start_thread_with_ephemeral(&agent.workspace, false).await?;
            drafts.push(AutomationTaskDraft::new(
                thread.clone(), format!("evolution round {round} slot {slot}"),
                AutomationSchedule::Once, now, now,
            ));
            threads.push(thread);
        }
        let [a, b, c, d]: [AutomationTaskDraft; WIDTH] = drafts.try_into()
            .map_err(|_| anyhow::anyhow!("invalid experiment width"))?;
        stage = format!("round {round}: concurrent task creation");
        eprintln!("product evolution stage: {stage}");
        let wave_started = Instant::now();
        let (a, b, c, d) = tokio::try_join!(
            control.automation_create(a), control.automation_create(b),
            control.automation_create(c), control.automation_create(d),
        )?;
        let tasks = [a, b, c, d];
        stage = format!("round {round}: terminal observation");
        eprintln!("product evolution stage: {stage}");
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            let mut completed = Vec::new();
            for thread in &threads {
                let snapshot = match product.read_thread(thread).await {
                    Ok(value) => value,
                    Err(error) if error.to_string().contains(
                        "is not materialized yet; includeTurns is unavailable before first user message"
                    ) => continue,
                    Err(error) => return Err(error),
                };
                ensure!(snapshot.thread.turns.len() <= 1, "duplicate product turn");
                if let Some(turn) = snapshot.thread.turns.first()
                    && turn.status == codex_app_server_protocol::TurnStatus::Completed
                {
                    completed.push((thread.clone(), turn.id.clone()));
                }
            }
            if completed.len() == WIDTH {
                terminal_identities.extend(completed);
                break;
            }
            if Instant::now() >= deadline {
                let tasks = control.automation_list(u16::try_from(rounds * WIDTH * 2)?).await?;
                anyhow::bail!("wave {round} did not reach product terminals; completed={completed:?}; tasks={tasks:?}; health={:?}", control.health().await?);
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        wave_latencies.push(wave_started.elapsed().as_micros());
        stage = format!("round {round}: settled task listing");
        eprintln!("product evolution stage: {stage}");
        let visible = control.automation_list(u16::try_from(rounds * WIDTH * 2)?).await?;
        for task in &tasks {
            ensure!(visible.iter().any(|row| row.task_id == task.task_id
                && row.state == AutomationTaskState::Completed && row.next_run_at_ms.is_none()),
                "product terminal lacks its settled timer occurrence");
        }
        stage = format!("round {round}: future task cancellation");
        eprintln!("product evolution stage: {stage}");
        for thread in &threads {
            let future = control.automation_create(AutomationTaskDraft::new(
                thread.clone(), "cancel before effect", AutomationSchedule::Once,
                now + 3_600_000, now,
            )).await?;
            ensure!(control.automation_cancel(future.task_id).await?.state
                == AutomationTaskState::Cancelled);
        }
        ensure!(model_calls.requests().len() == (round + 1) * WIDTH,
            "cancelled work or duplicate occurrence reached the provider");
        product.shutdown().await?;
        let loaded = resource_sample(&agent, health.process_id)?;
        let generation = agent_generation(&fleet, &agent.agent_id)?;
        let old_process = health.process_id;
        stage = format!("round {round}: process restart");
        eprintln!("product evolution stage: {stage}");
        let restart_started = Instant::now();
        fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
        let (fresh_control, fresh_health) = fleet.wait_new_spawn(&agent, generation).await?;
        restart_latencies.push(restart_started.elapsed().as_micros());
        ensure!(fresh_health.process_id != old_process, "restart did not replace process");
        ensure!(control.health().await.is_err(), "old client lost its generation fence");
        control = fresh_control;
        health = fresh_health;
        stage = format!("round {round}: recovered terminal history");
        eprintln!("product evolution stage: {stage}");
        let history_started = Instant::now();
        let mut recovered = ProductClient::connect(&agent, &control).await?;
        // Check EVERY prior terminal after EVERY restart. Bound observation
        // concurrency to the existing four-request workload instead of making
        // the harness impose an unbounded fan-out or a serial RPC bottleneck.
        let history = terminal_identities.chunks_exact(WIDTH);
        ensure!(history.remainder().is_empty(), "partial terminal wave");
        for group in history {
            let requests: [ClientRequest; WIDTH] = std::array::from_fn(|slot| {
                ClientRequest::ThreadRead {
                    request_id: recovered.request_id(),
                    params: ThreadReadParams {
                        thread_id: group[slot].0.clone(),
                        include_turns: true,
                    },
                }
            });
            let [a, b, c, d] = requests;
            let reader = recovered.inner.request_handle();
            let (a, b, c, d) = tokio::try_join!(
                reader.request_typed::<ThreadReadResponse>(a),
                reader.request_typed::<ThreadReadResponse>(b),
                reader.request_typed::<ThreadReadResponse>(c),
                reader.request_typed::<ThreadReadResponse>(d),
            )?;
            for ((thread, terminal_id), snapshot) in group.iter().zip([a, b, c, d]) {
                ensure!(snapshot.thread.id == *thread
                    && snapshot.thread.turns.len() == 1
                    && snapshot.thread.turns[0].id == *terminal_id
                    && snapshot.thread.turns[0].status == codex_app_server_protocol::TurnStatus::Completed,
                    "restart changed committed terminal history");
                verified_history_reads += 1;
            }
        }
        recovered.shutdown().await?;
        let history_verify_us = history_started.elapsed().as_micros();
        let (_, count, _) = owner_observation(&agent).await?;
        ensure!(count == i64::try_from((round + 1) * WIDTH * 2)?,
            "lost or duplicated durable business tasks");
        ensure!(model_calls.requests().len() == (round + 1) * WIDTH,
            "restart replayed settled work");
        let sample = json!({"round": round, "before_restart": loaded,
            "after_restart": resource_sample(&agent, health.process_id)?,
            "business_tasks": count, "terminal_turns": terminal_identities.len(),
            "verified_history_reads": verified_history_reads,
            "history_verify_us": history_verify_us,
            "round_wall_us": round_started.elapsed().as_micros(),
            "elapsed_wall_us": started.elapsed().as_micros()});
        // Retain bounded progress even if the unchanged watchdog terminates us.
        eprintln!("product evolution sample: {sample}");
        samples.push(sample);
    }
    ensure!(verified_history_reads == WIDTH * rounds * (rounds + 1) / 2,
        "history verification omitted a terminal or a restart");
    stage = "retirement and old database restore".to_string();
        eprintln!("product evolution stage: {stage}");
    let generation = agent_generation(&fleet, &agent.agent_id)?;
    stop_process(&mut fleet, &agent).await?;
    let owner = AutomationStore::open(&agent.layout).await?;
    let database = owner.path().to_path_buf();
    owner.close().await;
    let backup = tempfile::NamedTempFile::new()?;
    std::fs::copy(&database, backup.path())?;
    let owner = AutomationStore::open(&agent.layout).await?;
    ensure!(owner.quiesce_timer().await?.can_handoff());
    let retired = owner.retire_timer().await?;
    ensure!(retired.phase == TimerPhase::Retired);
    ensure!(owner.resume_timer().await == Err(AutomationError::TimerFenced));
    owner.close().await;
    std::fs::copy(backup.path(), &database)?;
    ensure!(matches!(AutomationStore::open(&agent.layout).await,
        Err(AutomationError::Corrupt)), "old SQLite snapshot bypassed retirement");
    fleet.start(&agent)?;
    let (retired_control, retired_health) = fleet.wait_new_spawn(&agent, generation).await?;
    let (_, count, _) = owner_observation(&agent).await?;
    ensure!(count == i64::try_from(rounds * WIDTH * 2)?);
    let mut normal = ProductClient::connect(&agent, &retired_control).await?;
    let thread = normal.start_thread(&agent.workspace).await?;
    let probe = AutomationTaskDraft::new(thread.clone(), "retired rejection",
        AutomationSchedule::Once, 1, 1);
    let error = retired_control.automation_create(probe).await
        .expect_err("retired capability admitted new work");
    ensure!(error.to_string().contains("automation_unavailable"));
    normal.run_turn(&thread, "ordinary product remains available after retirement").await?;
    ensure!(model_calls.requests().len() == rounds * WIDTH + 1);
    normal.shutdown().await?;
    println!("{}", json!({"fixture": "ordinary_product_bounded_concurrent_evolution",
        "rounds": rounds, "concurrent_requests_per_wave": WIDTH,
        "restart_attempt_budget": rounds, "restart_window_ms": restart_window_ms,
        "restart_backoff_base_us": restart_backoff_base_us,
        "terminal_turns": terminal_identities.len(), "cancelled_tasks": rounds * WIDTH,
        "process_restarts": restart_latencies.len(), "wall_us": started.elapsed().as_micros(),
        "history_observation_concurrency": WIDTH, "verified_history_reads": verified_history_reads,
        "wave_terminal_observation_latency": latency_summary(&wave_latencies),
        "restart_ready_latency": latency_summary(&restart_latencies),
        "baseline_resources": baseline, "samples": samples,
        "retired_resources": resource_sample(&agent, retired_health.process_id)?,
        "retained_business_tasks": count, "post_retirement_normal_turns": 1,
        "pre_retirement_database_restore_quarantined": true,
        "provider": "local_fixture", "multi_day_or_production_capacity_claim": false}));
    Ok(())
    }.await;
    if let Err(error) = &outcome {
        fleet.supervisor.tick(Instant::now());
        if let Some(snapshot) = fleet.supervisor.snapshot(&agent.agent_id) {
            let tail = snapshot
                .logs
                .iter()
                .flat_map(|entry| entry.bytes.iter().copied())
                .collect::<Vec<_>>();
            for line in String::from_utf8_lossy(&tail)
                .lines()
                .filter(|line| line.contains("automation") || line.contains("quarantine"))
                .take(20)
            {
                eprintln!(
                    "product process diagnostic: {}",
                    line.chars().take(512).collect::<String>()
                );
            }
        }
        // Preserve the original diagnostic before mock drop also checks its
        // exact provider count. No timeout, completion or count is waived.
        eprintln!(
            "product evolution failed at {stage} after {:?}: {error:#}; provider_requests={}",
            experiment_started.elapsed(),
            model_calls.requests().len()
        );
    }
    outcome
}
