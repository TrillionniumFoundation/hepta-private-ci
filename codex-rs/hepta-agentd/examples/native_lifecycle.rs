//! Bounded, zero-turn qualification of the original Agentd lifecycle and stores.
//!
//! Usage: native_lifecycle /absolute/codex-hepta-agentd /fresh/fixture/root
//! The caller supplies an isolated environment and a writable, disposable root.
//! This does not grant effect authority, replace the writer owner, or prove G2.

#[cfg(unix)]
mod unix {
    use std::fs::OpenOptions;
    use std::fs::TryLockError;
    use std::path::Path;
    use std::path::PathBuf;
    use std::time::Duration;
    use std::time::Instant;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use anyhow::Context;
    use anyhow::Result;
    use anyhow::bail;
    use anyhow::ensure;
    use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
    use codex_hepta_agentd::AgentdClient;
    use codex_hepta_agentd::AgentdPayload;
    use codex_hepta_agentd::AgentdRequest;
    use codex_hepta_agentd::AgentdResponse;
    use codex_hepta_agentd::HealthSnapshot;
    use codex_hepta_agentd::MAX_CONTROL_FRAME_BYTES;
    use codex_hepta_automation::AutomationSchedule;
    use codex_hepta_automation::AutomationTaskDraft;
    use codex_hepta_automation::AutomationTaskState;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentLifecycle;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaAgentLayout;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_hepta_supervisor::AgentCommand;
    use codex_hepta_supervisor::AgentSupervisorSnapshot;
    use codex_hepta_supervisor::Supervisor;
    use codex_hepta_supervisor::SupervisorConfig;
    use codex_hepta_supervisor::SupervisorEventKind;
    use codex_hepta_supervisor::UnixProcessDriver;
    use codex_uds::UnixStream;
    use serde::Serialize;
    use serde_json::Value;
    use serde_json::json;
    use sqlx::Connection;
    use sqlx::Row;
    use sqlx::SqliteConnection;
    use sqlx::sqlite::SqliteConnectOptions;
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::io::BufReader;
    use tokio::time::timeout;

    const AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";
    const READY_TIMEOUT: Duration = Duration::from_secs(120);
    const STOP_TIMEOUT: Duration = Duration::from_secs(45);
    const POLL_INTERVAL: Duration = Duration::from_millis(50);

    #[derive(Serialize)]
    struct StopWitness {
        spawn_generation: u64,
        draining_generation: u64,
        stopped_generation: u64,
        owner_drain: AgentdResponse,
        events: Vec<Value>,
        writer_lock_released: bool,
    }

    #[derive(Clone, Serialize)]
    struct BoundedHealthError {
        message: String,
        truncated: bool,
    }

    #[derive(Clone, Serialize)]
    struct ReadinessHealthObservation {
        started_after_ms: u128,
        completed_after_ms: u128,
        supervisor_healthy: bool,
        supervisor_stop_requested: bool,
        supervisor_kill_requested: bool,
        outcome: std::result::Result<HealthSnapshot, BoundedHealthError>,
    }

    #[derive(Default, Serialize)]
    struct ReadinessDiagnostics {
        health_successes: u64,
        health_errors: u64,
        pre_stop_successes: u64,
        pre_stop_errors: u64,
        first_valid: Option<ReadinessHealthObservation>,
        last_valid: Option<ReadinessHealthObservation>,
        last_pre_stop: Option<ReadinessHealthObservation>,
        first_stop_observed_after_ms: Option<u128>,
        first_kill_observed_after_ms: Option<u128>,
    }

    fn stop_failure_evidence(
        snapshot: &AgentSupervisorSnapshot,
        spawn_generation: u64,
        draining_generation: u64,
        owner_drain: &AgentdResponse,
        stop_observed_from: Instant,
    ) -> Value {
        // Failure-only formatting of observations already made by the original
        // stop loop. No new health/drain RPC, tick, signal or filesystem probe.
        let stop_events = snapshot
            .events
            .iter()
            .filter(|event| event.generation >= draining_generation)
            .collect::<Vec<_>>();
        let events_skipped = stop_events.len().saturating_sub(16);
        let events = stop_events[events_skipped..]
            .iter()
            .map(|event| {
                let detail = format!("{:?}", event.kind);
                let mut chars = detail.chars();
                let detail: String = chars.by_ref().take(512).collect();
                json!({"generation": event.generation, "kind_debug": detail,
                    "detail_truncated": chars.next().is_some()})
            })
            .collect::<Vec<_>>();
        let logs_skipped = snapshot.logs.len().saturating_sub(32);
        let logs = snapshot.logs[logs_skipped..]
            .iter()
            .map(|log| {
                let captured = &log.bytes[..log.bytes.len().min(4096)];
                const HEX: &[u8; 16] = b"0123456789abcdef";
                let mut bytes_hex = String::with_capacity(captured.len() * 2);
                for &byte in captured {
                    bytes_hex.push(HEX[usize::from(byte >> 4)] as char);
                    bytes_hex.push(HEX[usize::from(byte & 15)] as char);
                }
                json!({"stream": format!("{:?}", log.stream),
                    "original_bytes": log.bytes.len(), "captured_bytes": captured.len(),
                    "truncated": captured.len() != log.bytes.len(),
                    "bytes_hex": bytes_hex, "text": String::from_utf8_lossy(captured)})
            })
            .collect::<Vec<_>>();
        json!({"schema_version": 1, "phase": "after_acknowledged_owner_drain",
            "spawn_generation": spawn_generation, "draining_generation": draining_generation,
            "owner_drain": owner_drain,
            "elapsed_after_stop_return_ms": stop_observed_from.elapsed().as_millis(),
            "snapshot": {"active": snapshot.active, "healthy": snapshot.healthy,
                "runtime_generation": snapshot.runtime_generation,
                "spawn_generation": snapshot.spawn_generation,
                "process_system_id": snapshot.process_system_id},
            "event_count": stop_events.len(), "events_skipped": events_skipped,
            "events": events, "log_count": snapshot.logs.len(),
            "logs_skipped": logs_skipped, "logs": logs})
    }

    struct Fixture {
        registry: FleetRegistry,
        agent_id: AgentId,
        layout: HeptaAgentLayout,
        workspace: PathBuf,
        supervisor: Supervisor<UnixProcessDriver>,
    }

    impl Fixture {
        fn recover(registry: FleetRegistry, agent_id: AgentId) -> Result<Self> {
            let record = registry.load_agent(&agent_id)?;
            let mut config = SupervisorConfig::local_default();
            config.health_timeout = READY_TIMEOUT;
            let (supervisor, report) = Supervisor::recover(
                registry.clone(),
                UnixProcessDriver::new(256)?,
                config,
                Instant::now(),
            )?;
            ensure!(
                report.faults.is_empty(),
                "recovery faults: {:?}",
                report.faults
            );
            Ok(Self {
                registry,
                agent_id,
                layout: record.layout,
                workspace: record.manifest.workspace.as_path().to_path_buf(),
                supervisor,
            })
        }

        fn snapshot(&self) -> Result<AgentSupervisorSnapshot> {
            self.supervisor
                .snapshot(&self.agent_id)
                .context("missing original supervisor slot")
        }

        fn tick(&mut self) -> Result<()> {
            let report = self.supervisor.tick(Instant::now());
            ensure!(
                report.faults.is_empty(),
                "supervisor faults: {:?}; snapshot: {:?}",
                report.faults,
                self.snapshot()?
            );
            Ok(())
        }

        async fn start(&mut self, program: &Path) -> Result<(AgentdClient, HealthSnapshot, u64)> {
            self.supervisor.start(
                &self.agent_id,
                AgentCommand::new(program, Vec::new())?,
                Instant::now(),
            )?;
            let generation = self
                .snapshot()?
                .spawn_generation
                .context("missing original spawn generation")?;
            let client = AgentdClient::new(
                self.layout.agentd_control_socket().to_path_buf(),
                self.agent_id.clone(),
                generation,
            )?;
            stage(
                "spawned",
                json!({"spawn_generation": generation, "process_id": self.snapshot()?.process_system_id}),
            );
            let deadline = Instant::now() + READY_TIMEOUT;
            let observed_from = deadline - READY_TIMEOUT;
            let mut diagnostics = ReadinessDiagnostics::default();
            loop {
                self.tick()?;
                let snapshot = self.snapshot()?;
                let started_after_ms = observed_from.elapsed().as_millis();
                let health = client.health().await;
                let completed_after_ms = observed_from.elapsed().as_millis();
                // Classify this same RPC with the snapshot taken before it.
                // A health call after tick sent SIGTERM cannot describe the
                // last health response before the original stop request.
                let stop_requested = snapshot.events.iter().any(|event| {
                    event.generation >= generation
                        && matches!(&event.kind, SupervisorEventKind::StopRequested)
                });
                let kill_requested = snapshot.events.iter().any(|event| {
                    event.generation >= generation
                        && matches!(&event.kind, SupervisorEventKind::KillRequested)
                });
                if stop_requested {
                    diagnostics
                        .first_stop_observed_after_ms
                        .get_or_insert(started_after_ms);
                }
                if kill_requested {
                    diagnostics
                        .first_kill_observed_after_ms
                        .get_or_insert(started_after_ms);
                }
                let before_stop = diagnostics.first_stop_observed_after_ms.is_none()
                    && diagnostics.first_kill_observed_after_ms.is_none();
                let outcome = match &health {
                    Ok(health) => {
                        diagnostics.health_successes =
                            diagnostics.health_successes.saturating_add(1);
                        if before_stop {
                            diagnostics.pre_stop_successes =
                                diagnostics.pre_stop_successes.saturating_add(1);
                        }
                        Ok(health.clone())
                    }
                    Err(error) => {
                        diagnostics.health_errors = diagnostics.health_errors.saturating_add(1);
                        if before_stop {
                            diagnostics.pre_stop_errors =
                                diagnostics.pre_stop_errors.saturating_add(1);
                        }
                        let message = format!("{error:?}");
                        let mut chars = message.chars();
                        let message = chars.by_ref().take(512).collect();
                        Err(BoundedHealthError {
                            message,
                            truncated: chars.next().is_some(),
                        })
                    }
                };
                let observation = ReadinessHealthObservation {
                    started_after_ms,
                    completed_after_ms,
                    supervisor_healthy: snapshot.healthy,
                    supervisor_stop_requested: stop_requested,
                    supervisor_kill_requested: kill_requested,
                    outcome,
                };
                // Only these three fixed slots are retained, never a poll log.
                // HealthSnapshot was already validated by the original client
                // under its bounded frame and identity checks.
                if observation.outcome.is_ok() {
                    diagnostics
                        .first_valid
                        .get_or_insert_with(|| observation.clone());
                    diagnostics.last_valid = Some(observation.clone());
                }
                if before_stop {
                    diagnostics.last_pre_stop = Some(observation);
                }
                if let Ok(health) = health.as_ref()
                    && health.ready
                    && snapshot.healthy
                {
                    ensure!(snapshot.active && !health.fenced && health.promotion_ready);
                    ensure!(health.lifecycle == AgentLifecycle::Running);
                    ensure!(snapshot.process_system_id == Some(u64::from(health.process_id)));
                    ensure!(health.workspace == self.workspace);
                    ensure!(health.home_root == self.layout.home_root());
                    ensure!(health.run_root == self.layout.run_root());
                    ensure!(
                        self.registry
                            .load_agent(&self.agent_id)?
                            .lifecycle
                            .lifecycle
                            == AgentLifecycle::Running
                    );
                    let lifecycle = client.lifecycle().await?;
                    ensure!(lifecycle.app_server_ready && !lifecycle.fenced);
                    ensure!(
                        client.session_ingress().await?.socket_path
                            == self.layout.app_server_socket()
                    );
                    require_writer_lock_held(self.layout.writer_lock())?;
                    return Ok((client, health.clone(), generation));
                }
                ensure!(
                    snapshot.active,
                    "Agentd exited before readiness: {snapshot:?}; health: {health:?}; readiness_observations: {}",
                    serde_json::to_string(&diagnostics)?
                );
                ensure!(
                    Instant::now() < deadline,
                    "readiness timeout: {snapshot:?}; health: {health:?}; readiness_observations: {}",
                    serde_json::to_string(&diagnostics)?
                );
                tokio::time::sleep(POLL_INTERVAL).await;
            }
        }

        async fn drain_reply(
            &self,
            request_id: u64,
            spawn_generation: u64,
            current_generation: u64,
        ) -> Result<AgentdResponse> {
            // The public original drain protocol is queried directly because
            // AgentdClient exposes no drain convenience method. This creates
            // no lifecycle transition: only Supervisor::drain does that.
            timeout(Duration::from_secs(2), async {
                let stream = UnixStream::connect(self.layout.agentd_control_socket()).await?;
                let (reader, mut writer) = tokio::io::split(stream);
                let mut request =
                    serde_json::to_vec(&AgentdRequest::drain(request_id, spawn_generation))?;
                request.push(b'\n');
                ensure!((request.len() as u64) <= MAX_CONTROL_FRAME_BYTES);
                writer.write_all(&request).await?;
                writer.shutdown().await?;
                let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
                let mut bytes = Vec::new();
                let count = reader.read_until(b'\n', &mut bytes).await?;
                ensure!(
                    count > 0
                        && (count as u64) <= MAX_CONTROL_FRAME_BYTES
                        && bytes.ends_with(b"\n"),
                    "invalid original drain frame"
                );
                let reply: AgentdResponse = serde_json::from_slice(&bytes)?;
                ensure!(
                    reply.schema_version == AGENTD_CONTROL_SCHEMA_VERSION
                        && reply.request_id == request_id
                        && reply.agent_id == self.agent_id
                        && reply.spawn_generation == spawn_generation
                        && reply.current_generation == current_generation,
                    "original drain identity/generation mismatch"
                );
                Ok::<AgentdResponse, anyhow::Error>(reply)
            })
            .await
            .context("original drain response timed out")?
        }

        async fn stop(&mut self) -> Result<StopWitness> {
            let spawn_generation = self
                .snapshot()?
                .spawn_generation
                .context("missing running spawn generation")?;
            self.supervisor.drain(&self.agent_id, Instant::now())?;
            let draining = self.registry.load_agent(&self.agent_id)?.lifecycle;
            ensure!(draining.lifecycle == AgentLifecycle::Draining);
            let drain_deadline = Instant::now() + Duration::from_secs(30);
            let mut request_id = 1_u64;
            let owner_drain = loop {
                let reply = self
                    .drain_reply(request_id, spawn_generation, draining.generation)
                    .await?;
                let AgentdPayload::Drain(drain) = &reply.payload else {
                    bail!("original owner rejected drain: {:?}", reply.payload);
                };
                ensure!(drain.lifecycle == AgentLifecycle::Draining && !drain.fenced);
                if drain.admission_closed && drain.running_turns == 0 && drain.drained {
                    break reply;
                }
                ensure!(
                    Instant::now() < drain_deadline,
                    "original owner/App Server did not acknowledge drain: {drain:?}"
                );
                request_id = request_id
                    .checked_add(1)
                    .context("drain request sequence overflow")?;
                tokio::time::sleep(POLL_INTERVAL).await;
            };
            // Only after the actual owner/App Server acknowledges drain does
            // the original Supervisor send its ordinary stop request.
            self.supervisor.stop(&self.agent_id, Instant::now())?;
            let deadline = Instant::now() + STOP_TIMEOUT;
            let stop_observed_from = deadline - STOP_TIMEOUT;
            loop {
                self.tick()?;
                let snapshot = self.snapshot()?;
                if !snapshot.active {
                    let lifecycle = self.registry.load_agent(&self.agent_id)?.lifecycle;
                    ensure!(
                        lifecycle.lifecycle == AgentLifecycle::Stopped,
                        "unexpected terminal lifecycle: {lifecycle:?}; stop_diagnostics={}",
                        stop_failure_evidence(
                            &snapshot,
                            spawn_generation,
                            draining.generation,
                            &owner_drain,
                            stop_observed_from,
                        )
                    );
                    let observed = snapshot
                        .events
                        .iter()
                        .filter(|event| event.generation >= draining.generation)
                        .collect::<Vec<_>>();
                    ensure!(
                        observed.len() <= 16,
                        "original stop event witness exceeds bound; stop_diagnostics={}",
                        stop_failure_evidence(
                            &snapshot,
                            spawn_generation,
                            draining.generation,
                            &owner_drain,
                            stop_observed_from,
                        )
                    );
                    let mut events = Vec::new();
                    for event in observed {
                        let detail = match &event.kind {
                            SupervisorEventKind::Lifecycle(value) => {
                                json!({"generation": event.generation, "kind": "lifecycle", "lifecycle": value})
                            }
                            SupervisorEventKind::DrainRequested => {
                                json!({"generation": event.generation, "kind": "drain_requested"})
                            }
                            SupervisorEventKind::StopRequested => {
                                json!({"generation": event.generation, "kind": "stop_requested"})
                            }
                            SupervisorEventKind::Exited(exit) => {
                                json!({"generation": event.generation, "kind": "exited", "success": exit.success, "code": exit.code})
                            }
                            other => bail!(
                                "unexpected original stop event: {other:?}; stop_diagnostics={}",
                                stop_failure_evidence(
                                    &snapshot,
                                    spawn_generation,
                                    draining.generation,
                                    &owner_drain,
                                    stop_observed_from,
                                )
                            ),
                        };
                        events.push(detail);
                    }
                    let expected = vec![
                        json!({"generation": draining.generation, "kind": "lifecycle", "lifecycle": "draining"}),
                        json!({"generation": draining.generation, "kind": "drain_requested"}),
                        json!({"generation": draining.generation, "kind": "stop_requested"}),
                        json!({"generation": lifecycle.generation, "kind": "lifecycle", "lifecycle": "stopped"}),
                        json!({"generation": lifecycle.generation, "kind": "exited", "success": true, "code": 0}),
                    ];
                    ensure!(
                        events == expected,
                        "original stop was not an acknowledged graceful exit: {events:?}; stop_diagnostics={}",
                        stop_failure_evidence(
                            &snapshot,
                            spawn_generation,
                            draining.generation,
                            &owner_drain,
                            stop_observed_from,
                        )
                    );
                    let lock = OpenOptions::new()
                        .read(true)
                        .write(true)
                        .open(self.layout.writer_lock())?;
                    lock.try_lock().with_context(|| {
                        format!(
                            "writer lock remained held after original stop; stop_diagnostics={}",
                            stop_failure_evidence(
                                &snapshot,
                                spawn_generation,
                                draining.generation,
                                &owner_drain,
                                stop_observed_from,
                            )
                        )
                    })?;
                    drop(lock);
                    return Ok(StopWitness {
                        spawn_generation,
                        draining_generation: draining.generation,
                        stopped_generation: lifecycle.generation,
                        owner_drain,
                        events,
                        writer_lock_released: true,
                    });
                }
                ensure!(
                    Instant::now() < deadline,
                    "original stop timeout; stop_diagnostics={}",
                    stop_failure_evidence(
                        &snapshot,
                        spawn_generation,
                        draining.generation,
                        &owner_drain,
                        stop_observed_from,
                    )
                );
                tokio::time::sleep(POLL_INTERVAL).await;
            }
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            if self
                .supervisor
                .snapshot(&self.agent_id)
                .is_some_and(|snapshot| snapshot.active)
            {
                // The original driver owns this exact fixture process. Never
                // signal a PID obtained from outside the fixture's registry.
                let _ = self.supervisor.kill(&self.agent_id);
                let deadline = Instant::now() + Duration::from_secs(3);
                while Instant::now() < deadline {
                    let _ = self.supervisor.tick(Instant::now());
                    if self
                        .supervisor
                        .snapshot(&self.agent_id)
                        .is_some_and(|snapshot| !snapshot.active)
                    {
                        break;
                    }
                    std::thread::sleep(POLL_INTERVAL);
                }
            }
        }
    }

    fn require_writer_lock_held(path: &Path) -> Result<()> {
        let lock = OpenOptions::new().read(true).write(true).open(path)?;
        match lock.try_lock() {
            Err(TryLockError::WouldBlock) => Ok(()),
            Err(TryLockError::Error(error)) => {
                Err(error).context("cannot inspect original writer lock")
            }
            Ok(()) => bail!("original ready Agentd does not hold its writer lock"),
        }
    }

    async fn read_store(path: &Path, table: &str, expected_owner: &AgentId) -> Result<Value> {
        ensure!(
            std::fs::symlink_metadata(path)?.is_file(),
            "store is not a physical file: {}",
            path.display()
        );
        let options = SqliteConnectOptions::new()
            .filename(path)
            .read_only(true)
            .pragma("query_only", "ON")
            .busy_timeout(Duration::from_secs(5));
        let mut connection = SqliteConnection::connect_with(&options).await?;
        let integrity: Vec<String> = sqlx::query_scalar("PRAGMA quick_check")
            .fetch_all(&mut connection)
            .await?;
        ensure!(integrity == ["ok"], "store integrity failed: {integrity:?}");
        // SQLx receives only static SQL literals for the two original metadata tables.
        let query = match table {
            "cognitive_meta" => sqlx::query(
                "SELECT schema_version, owner_agent_id FROM cognitive_meta WHERE singleton = 1",
            ),
            "automation_meta" => sqlx::query(
                "SELECT schema_version, owner_agent_id FROM automation_meta WHERE singleton = 1",
            ),
            _ => bail!("unsupported original metadata table: {table}"),
        };
        let row = query.fetch_one(&mut connection).await?;
        let schema_version: i64 = row.try_get("schema_version")?;
        let owner: String = row.try_get("owner_agent_id")?;
        ensure!(schema_version > 0 && owner == expected_owner.as_str());
        let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&mut connection)
            .await?;
        ensure!(
            journal_mode == "wal",
            "original store lost WAL mode: {journal_mode}"
        );
        let migrations: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations WHERE success = 1")
                .fetch_one(&mut connection)
                .await?;
        ensure!(migrations > 0);
        let automation_runs = if table == "automation_meta" {
            let runs: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM automation_runs")
                .fetch_one(&mut connection)
                .await?;
            ensure!(
                runs == 0,
                "zero-turn fixture unexpectedly dispatched an automation"
            );
            Some(runs)
        } else {
            None
        };
        connection.close().await?;
        Ok(
            json!({"path": path, "schema_version": schema_version, "owner_agent_id": owner,
            "quick_check": integrity, "journal_mode": journal_mode, "migrations": migrations,
            "automation_runs": automation_runs}),
        )
    }

    async fn stores(layout: &HeptaAgentLayout) -> Result<Value> {
        let cognitive = read_store(
            &layout.cognitive_root().join("cognitive_1.sqlite3"),
            "cognitive_meta",
            layout.agent_id(),
        )
        .await?;
        let automation = read_store(
            &layout.automation_root().join("automation_1.sqlite3"),
            "automation_meta",
            layout.agent_id(),
        )
        .await?;
        Ok(json!({"cognitive": cognitive, "automation": automation}))
    }

    fn stage(name: &str, detail: Value) {
        println!(
            "HEPTA_F1_STAGE {}",
            json!({"stage": name, "detail": detail})
        );
    }

    pub async fn run(program: PathBuf, root: PathBuf) -> Result<()> {
        ensure!(
            program.is_absolute() && root.is_absolute(),
            "both paths must be absolute"
        );
        let program = program
            .canonicalize()
            .context("resolve original Agentd executable")?;
        ensure!(program.is_file());
        std::fs::create_dir(&root).context("fixture root must not already exist")?;
        let root = root.canonicalize()?;
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace)?;
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        let agent_id = AgentId::parse(AGENT_ID).map_err(anyhow::Error::msg)?;
        let registered = registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(&workspace, &fleet_root)?,
            ResourceBudget::local_default(),
        )?)?;
        ensure!(registered.lifecycle.lifecycle == AgentLifecycle::Stopped);
        stage(
            "registered",
            json!({"agent_id": agent_id, "lifecycle": registered.lifecycle, "program": program}),
        );
        let mut fixture = Fixture::recover(registry.clone(), agent_id.clone())?;
        let (client, first_health, first_generation) = fixture.start(&program).await?;
        stage(
            "first_ready",
            json!({"health": first_health, "spawn_generation": first_generation}),
        );
        ensure!(
            client.automation_list(16).await?.is_empty(),
            "fresh original store is not empty"
        );
        let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        // This is a store-only fixture row. It names no real thread or turn,
        // is scheduled 30 days ahead, and is disabled before any restart.
        let future_ms = now_ms
            .checked_add(30 * 86_400_000)
            .context("future schedule overflow")?;
        let created = client
            .automation_create(AutomationTaskDraft::new(
                "019153a4-3088-7e03-a56a-9b1964f75ddd",
                "F1 persistent store witness; disabled and never dispatched",
                AutomationSchedule::Once,
                future_ms,
                now_ms,
            ))
            .await?;
        let witness = client
            .automation_set_enabled(
                created.task_id,
                /*enabled*/ false,
                /*resume_at_ms*/ None,
            )
            .await?;
        ensure!(
            witness.owner_agent_id == agent_id && witness.state == AutomationTaskState::Disabled
        );
        ensure!(client.automation_list(16).await? == [witness.clone()]);
        let first_stores = stores(&fixture.layout).await?;
        stage(
            "original_store_witness",
            json!({"task": witness, "stores": first_stores}),
        );
        let first_stop = fixture.stop().await?;
        let first_stopped_generation = first_stop.stopped_generation;
        drop(client);
        let stopped_stores = stores(&fixture.layout).await?;
        ensure!(
            stopped_stores == first_stores,
            "owner/schema changed during stop"
        );
        drop(fixture);
        stage(
            "first_stopped",
            json!({"registry_generation": first_stopped_generation, "stop": first_stop}),
        );

        // Reopen through the original registry and Supervisor APIs. Neither
        // the helper nor a shell script edits lifecycle/generation files.
        let reopened_registry = FleetRegistry::open_existing(fleet_root)?;
        let mut fixture = Fixture::recover(reopened_registry, agent_id.clone())?;
        let recovered = fixture.registry.load_agent(&agent_id)?.lifecycle;
        ensure!(
            recovered.lifecycle == AgentLifecycle::Stopped
                && recovered.generation == first_stopped_generation
        );
        ensure!(!fixture.snapshot()?.active);
        stage("stopped_state_recovered", json!({"lifecycle": recovered}));
        let (client, second_health, second_generation) = fixture.start(&program).await?;
        ensure!(
            second_generation > first_generation && second_generation > first_stopped_generation
        );
        ensure!(second_health.process_id != first_health.process_id);
        let reopened_tasks = client.automation_list(16).await?;
        ensure!(
            reopened_tasks == [witness.clone()],
            "original persisted row changed or vanished"
        );
        let reopened_stores = stores(&fixture.layout).await?;
        ensure!(
            reopened_stores == first_stores,
            "reopened original stores changed owner/schema"
        );
        stage(
            "second_ready_witness_recovered",
            json!({"health": second_health, "spawn_generation": second_generation, "task": witness}),
        );
        let final_stop = fixture.stop().await?;
        let final_generation = final_stop.stopped_generation;
        drop(client);
        let final_stores = stores(&fixture.layout).await?;
        ensure!(final_stores == first_stores);
        stage(
            "final_stopped",
            json!({"registry_generation": final_generation, "stop": final_stop}),
        );
        let report = json!({
            "schema_version": 1, "status": "passed",
            "scope": "original-registry-supervisor-agentd-store-lifecycle",
            "agent_id": agent_id, "agentd_program": program, "fixture_root": root,
            "first_health": first_health, "second_health": second_health,
            "first_spawn_generation": first_generation, "second_spawn_generation": second_generation,
            "first_stopped_generation": first_stopped_generation, "final_stopped_generation": final_generation,
            "first_stop": first_stop, "final_stop": final_stop,
            "original_persisted_task": witness, "stores": final_stores,
            "model_turns_requested": 0, "automation_runs": 0,
            "production_authority_configured": false, "hos2_control_qualified": false,
            "power_loss_recovery_qualified": false
        });
        let report_path = root.join("native-lifecycle-result.json");
        let mut report_file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&report_path)?;
        serde_json::to_writer_pretty(&mut report_file, &report)?;
        report_file.sync_all()?;
        std::fs::File::open(&root)?.sync_all()?;
        println!("HEPTA_F1_RESULT {report}");
        Ok(())
    }
}

#[cfg(unix)]
fn main() -> anyhow::Result<()> {
    let mut args = std::env::args_os().skip(1);
    let program = args
        .next()
        .ok_or_else(|| anyhow::anyhow!("usage: native_lifecycle AGENTD_ELF FRESH_FIXTURE_ROOT"))?;
    let root = args
        .next()
        .ok_or_else(|| anyhow::anyhow!("missing fresh fixture root"))?;
    anyhow::ensure!(args.next().is_none(), "unexpected extra argument");
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?
        .block_on(unix::run(program.into(), root.into()))
}

#[cfg(not(unix))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("native_lifecycle requires the original UnixProcessDriver")
}
