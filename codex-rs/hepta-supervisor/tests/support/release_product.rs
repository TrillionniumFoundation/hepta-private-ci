use super::*;

pub(super) fn child_arguments(test_threads: u8) -> Vec<String> {
    vec![
        "--exact".to_string(),
        "support::production_release_agent_child".to_string(),
        "--ignored".to_string(),
        "--nocapture".to_string(),
        format!("--test-threads={test_threads}"),
    ]
}

pub(super) fn signed_h7_envelope(
    signer: &H7ArtifactSigner,
    transition: H7SignedArtifactTransition,
    expected_runtime_generation: u64,
    issued_at: u64,
    expires_at: u64,
) -> Result<codex_hepta_memory::H7SignedArtifactEnvelope> {
    let mut runtime = H7QualificationRuntime::new();
    let event = H7TrajectoryEvent::new(
        "release-controller-product-trajectory",
        1,
        transition.as_str(),
        100,
        /*accepted*/ true,
        1,
        1,
        1,
        Sha256Digest::for_bytes(b"release-controller-product-fence"),
    )?;
    runtime.append_trajectory_event(event)?;
    runtime.evaluate_trajectory("release-controller-product-trajectory")?;
    let artifact = runtime.propose_artifact(
        "release-controller-product-artifact",
        "release-controller-product-trajectory",
        1,
    )?;
    Ok(signer.sign(
        &artifact,
        /*ope*/ None,
        transition,
        expected_runtime_generation,
        /*predecessor_artifact_sha256*/
        (transition == H7SignedArtifactTransition::Rollback).then(|| artifact.body_sha256.clone()),
        issued_at,
        expires_at,
    )?)
}

pub(super) async fn run_release_controller(
    command: &str,
    fleet_root: &HeptaFleetRoot,
    request_path: &Path,
    journal_path: &Path,
    wait_seconds: u64,
) -> Result<ProductionReleaseJournalV1> {
    let output =
        tokio::process::Command::new(env!("CARGO_BIN_EXE_hepta-supervisor-release-controller"))
            .arg(command)
            .arg("--fleet-root")
            .arg(fleet_root.as_path())
            .arg("--request")
            .arg(request_path)
            .arg("--journal")
            .arg(journal_path)
            .arg("--wait-seconds")
            .arg(wait_seconds.to_string())
            .output()
            .await?;
    let journal: ProductionReleaseJournalV1 =
        serde_json::from_slice(&output.stdout).with_context(|| {
            format!(
                "controller output: {}",
                String::from_utf8_lossy(&output.stderr)
            )
        })?;
    ensure!(
        output.status.success()
            || matches!(
                journal.status,
                ProductionReleaseCallerStatusV1::Indeterminate
                    | ProductionReleaseCallerStatusV1::RecoveryRequired
            ),
        "controller failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(journal)
}

pub(super) async fn wait_for_daemon(registry: &FleetRegistry) -> Result<SupervisordClient> {
    let deadline = Instant::now() + Duration::from_secs(10);
    let client = SupervisordClient::new(registry.layout().supervisor_socket().to_path_buf())?;
    loop {
        match client.health().await {
            Ok(_) => return Ok(client),
            Err(error) => {
                ensure!(
                    Instant::now() < deadline,
                    "supervisord did not become ready: {error:#}"
                );
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        }
    }
}

pub(super) async fn wait_for_release(
    client: &SupervisordClient,
    agent_id: &AgentId,
    release_id: &ReleaseId,
    timeout: Duration,
) -> Result<codex_hepta_supervisor::SupervisordAgentStatus> {
    let deadline = Instant::now() + timeout;
    loop {
        let status = match client.snapshot(agent_id.clone()).await {
            Ok(status) => status,
            Err(error) => {
                ensure!(Instant::now() < deadline, "query release progress: {error}");
                tokio::time::sleep(Duration::from_millis(25)).await;
                continue;
            }
        };
        if status.healthy
            && !status.release_change_pending
            && status.current_release.as_ref() == Some(release_id)
        {
            return Ok(status);
        }
        ensure!(
            Instant::now() < deadline,
            "release {release_id} did not become healthy: {status:?}"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

pub(super) async fn wait_for_inactive(
    client: &SupervisordClient,
    agent_id: &AgentId,
    timeout: Duration,
) -> Result<()> {
    let deadline = Instant::now() + timeout;
    loop {
        let status = match client.snapshot(agent_id.clone()).await {
            Ok(status) => status,
            Err(error) => {
                ensure!(Instant::now() < deadline, "query release progress: {error}");
                tokio::time::sleep(Duration::from_millis(25)).await;
                continue;
            }
        };
        if !status.active {
            return Ok(());
        }
        ensure!(Instant::now() < deadline, "Agent did not stop: {status:?}");
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

pub(super) fn unix_seconds() -> Result<u64> {
    Ok(SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)?
        .as_secs())
}

pub(super) fn read_drain_count(path: &Path) -> Result<u64> {
    if !path.exists() {
        return Ok(0);
    }
    Ok(std::fs::read_to_string(path)?.trim().parse()?)
}

pub(super) struct DaemonGroup {
    child: Child,
    process_group: i32,
}

impl DaemonGroup {
    pub(super) fn spawn(
        fleet_root: &Path,
        grant_key_path: &Path,
        h7_key_path: &Path,
    ) -> Result<Self> {
        let mut command = Command::new(env!("CARGO_BIN_EXE_hepta-supervisord"));
        command
            .arg("--fleet-root")
            .arg(fleet_root)
            .arg("--grant-verifier-key")
            .arg(grant_key_path)
            .arg("--grant-signer-id")
            .arg(GRANT_SIGNER_ID)
            .arg("--grant-signer-epoch")
            .arg(GRANT_SIGNER_EPOCH.to_string())
            .arg("--h7-verifier-key")
            .arg(h7_key_path)
            .arg("--h7-signer-id")
            .arg(H7_SIGNER_ID)
            .arg("--h7-signer-epoch")
            .arg(H7_SIGNER_EPOCH.to_string())
            .env_remove("OPENAI_API_KEY")
            .env_remove("CODEX_API_KEY")
            .env_remove("OPENAI_BASE_URL")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .process_group(0);
        let child = command.spawn()?;
        let process_group = i32::try_from(child.id()).context("daemon PID fits process group")?;
        Ok(Self {
            child,
            process_group,
        })
    }

    pub(super) fn crash(&mut self) -> Result<()> {
        self.child.kill()?;
        self.child.wait()?;
        Ok(())
    }

    pub(super) fn terminate(&mut self) -> Result<()> {
        send_group_signal(self.process_group, libc::SIGTERM)?;
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if self.child.try_wait()?.is_some() {
                return Ok(());
            }
            ensure!(Instant::now() < deadline, "supervisord ignored SIGTERM");
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

impl Drop for DaemonGroup {
    fn drop(&mut self) {
        // Children adopted by a new daemon retain their original test group.
        // Keep cleanup ownership even after SIGKILL of the original leader.
        let _ = send_group_signal(self.process_group, libc::SIGKILL);
        let _ = self.child.wait();
    }
}

pub(super) fn send_group_signal(process_group: i32, signal: i32) -> Result<()> {
    // SAFETY: the test created this dedicated process group and owns its children.
    if unsafe { libc::kill(-process_group, signal) } == -1 {
        let error = std::io::Error::last_os_error();
        if error.kind() != std::io::ErrorKind::NotFound {
            return Err(error.into());
        }
    }
    Ok(())
}

#[test]
#[ignore = "child entry for native Agentd-protocol qualification; not the Agentd product binary"]
pub(super) fn production_release_agent_child() {
    if let Err(error) = run_agent_child() {
        panic!("production release Agentd fixture failed: {error:#}");
    }
}

pub(super) fn run_agent_child() -> Result<()> {
    let fleet_root = HeptaFleetRoot::from_env()?;
    let agent_id = AgentId::parse(std::env::var("HEPTA_AGENT_ID")?)?;
    let spawn_generation = std::env::var("HEPTA_AGENT_GENERATION")?.parse::<u64>()?;
    let layout = fleet_root.layout().agent(&agent_id);
    let socket = layout.agentd_control_socket().to_path_buf();
    prepare_fixture_socket(&socket)?;
    let listener = UnixListener::bind(&socket)?;
    let mut drain_seen = false;
    for stream in listener.incoming() {
        let mut reader = BufReader::new(stream?);
        let mut bytes = Vec::new();
        reader.read_until(b'\n', &mut bytes)?;
        let request: AgentdRequest = serde_json::from_slice(&bytes)?;
        let run_root = PathBuf::from(
            std::env::var_os("HEPTA_AGENT_RUN_ROOT").context("HEPTA_AGENT_RUN_ROOT")?,
        );
        let home_root =
            PathBuf::from(std::env::var_os("HEPTA_AGENT_HOME").context("HEPTA_AGENT_HOME")?);
        let workspace = std::env::current_dir()?;
        let lifecycle = latest_lifecycle(&run_root)?;
        let payload = match request.method {
            AgentdMethod::Health => AgentdPayload::Health(HealthSnapshot {
                promotion_ready: true,
                ready: lifecycle.lifecycle == AgentLifecycle::Running,
                fenced: false,
                lifecycle: lifecycle.lifecycle,
                process_id: std::process::id(),
                workspace,
                home_root,
                run_root: run_root.clone(),
            }),
            AgentdMethod::Drain => {
                if !drain_seen {
                    increment_drain_count(&run_root.join(DRAIN_COUNT_FILE))?;
                    drain_seen = true;
                }
                AgentdPayload::Drain(DrainSnapshot {
                    admission_closed: true,
                    running_turns: 0,
                    drained: true,
                    lifecycle: lifecycle.lifecycle,
                    fenced: false,
                })
            }
            _ => AgentdPayload::Error {
                code: "unsupported_fixture_method".to_string(),
                message: "fixture supports only health and drain".to_string(),
            },
        };
        let response = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            agent_id: agent_id.clone(),
            spawn_generation,
            current_generation: lifecycle.generation,
            payload,
        };
        let mut stream = reader.into_inner();
        serde_json::to_writer(&mut stream, &response)?;
        stream.write_all(b"\n")?;
    }
    Ok(())
}

pub(super) fn latest_lifecycle(run_root: &Path) -> Result<AgentLifecycleState> {
    let mut latest: Option<(u64, PathBuf)> = None;
    for entry in std::fs::read_dir(run_root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        let Some(value) = name
            .strip_prefix("lifecycle-")
            .and_then(|value| value.strip_suffix(".json"))
        else {
            continue;
        };
        let Ok(generation) = value.parse::<u64>() else {
            continue;
        };
        if latest
            .as_ref()
            .is_none_or(|(current, _)| generation > *current)
        {
            latest = Some((generation, entry.path()));
        }
    }
    let (_, path) = latest.context("fixture lifecycle state")?;
    Ok(serde_json::from_slice(&std::fs::read(path)?)?)
}

pub(super) fn increment_drain_count(path: &Path) -> Result<()> {
    let next = read_drain_count(path)?
        .checked_add(1)
        .context("drain count overflow")?;
    let mut file = File::create(path)?;
    writeln!(file, "{next}")?;
    file.sync_all()?;
    Ok(())
}

pub(super) fn prepare_fixture_socket(path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if let Err(error) = std::fs::remove_file(path)
        && error.kind() != std::io::ErrorKind::NotFound
    {
        return Err(error.into());
    }
    Ok(())
}

pub(super) fn external_grant(
    request: &codex_hepta_supervisor::SignRequest,
    key: &Path,
    request_path: &Path,
) -> Result<codex_hepta_supervisor::H7H89ProductionGrant> {
    std::fs::write(request_path, serde_json::to_vec(request)?)?;
    let output = Command::new(env!("CARGO_BIN_EXE_hepta-authority-signer"))
        .args(["--sign", "--key-file"])
        .arg(key)
        .arg("--request")
        .arg(request_path)
        .output()?;
    ensure!(
        output.status.success(),
        "independent signer failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    match serde_json::from_slice(&output.stdout)? {
        codex_hepta_supervisor::SignResponse::ProductionGrant { grant } => Ok(grant),
        _ => anyhow::bail!("unexpected independent signer response"),
    }
}
