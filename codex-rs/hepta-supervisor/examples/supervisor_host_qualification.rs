//! Real-process, filesystem-backed qualification of the normal Supervisor
//! daemon. The lightweight child is explicitly NOT the Agentd product binary.
#[cfg(not(unix))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("Supervisor host qualification requires Unix")
}

#[cfg(unix)]
#[tokio::main(flavor = "multi_thread", worker_threads = 4)]
async fn main() -> anyhow::Result<()> {
    host::main().await
}

#[cfg(unix)]
mod host {
    use anyhow::Context;
    use anyhow::Result;
    use anyhow::ensure;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ReleaseId;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_hepta_supervisor::SupervisorConfig;
    use codex_hepta_supervisor::SupervisordAgentStatus;
    use codex_hepta_supervisor::SupervisordClient;
    use serde_json::Value;
    use serde_json::json;
    use std::fs::File;
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::process::CommandExt;
    use std::path::Path;
    use std::path::PathBuf;
    use std::process::Child;
    use std::process::Command;
    use std::process::Stdio;
    use std::time::Duration;
    use std::time::Instant;

    pub async fn main() -> Result<()> {
        let mut args = std::env::args_os().skip(1);
        let binary = PathBuf::from(args.next().context(
            "usage: supervisor_host_qualification ABS_SUPERVISORD ABS_RECEIPT [instances=256]",
        )?)
        .canonicalize()?;
        let receipt = PathBuf::from(args.next().context("receipt path required")?);
        ensure!(receipt.is_absolute(), "receipt path must be absolute");
        let count = args
            .next()
            .map(|arg| {
                arg.into_string()
                    .map_err(|_| anyhow::anyhow!("invalid instance count"))
            })
            .transpose()?
            .map(|arg| arg.parse::<usize>())
            .transpose()?
            .unwrap_or(256);
        ensure!(
            (8..=256).contains(&count) && args.next().is_none(),
            "instances must be in 8..=256"
        );
        let mut output = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&receipt)?;
        let directory = tempfile::Builder::new()
            .prefix("hsq-")
            .tempdir_in("/tmp")?
            .keep();
        let mut report = json!({
            "schema_version": 1, "backend": "native_agentd_protocol_fixture", "instances": count,
            "source_commit": command_output("git", &["rev-parse", "HEAD"]),
            "source_tree": command_output("git", &["rev-parse", "HEAD^{tree}"]),
            "source_dirty": !command_output("git", &["status", "--porcelain"]).is_empty(),
            "host": command_output("hostname", &[]), "platform": command_output("uname", &["-a"]),
            "load_before": std::fs::read_to_string("/proc/loadavg").ok(),
            "supervisord_sha256": Sha256Digest::for_bytes(&std::fs::read(&binary)?),
            "evidence_directory": directory, "deployment_qualified": false,
            "independent_acceptance": false, "checks": [], "unmeasured_faults": ["hardware power loss", "fsync EIO", "ENOSPC", "Matrix-enabled 256 fleet"]
        });
        let result = qualify(&binary, &directory, count, &mut report).await;
        report["status"] = json!(if result.is_ok() { "passed" } else { "failed" });
        report["error"] = json!(result.as_ref().err().map(|error| format!("{error:#}")));
        report["load_after"] = json!(std::fs::read_to_string("/proc/loadavg").ok());
        serde_json::to_writer_pretty(&mut output, &report)?;
        output.write_all(b"\n")?;
        output.sync_all()?;
        println!("{}", serde_json::to_string(&report)?);
        result
    }

    async fn qualify(
        binary: &Path,
        directory: &Path,
        count: usize,
        report: &mut Value,
    ) -> Result<()> {
        let setup = Instant::now();
        let root = HeptaFleetRoot::parse(directory.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let program = directory.join("qualification-agent.py");
        std::fs::write(&program, include_str!("../tests/support/host_agent.py"))?;
        std::fs::set_permissions(&program, std::fs::Permissions::from_mode(0o700))?;
        let release = ReleaseId::parse("host-qualification-v1")?;
        registry.install_release(release.clone(), &program, Vec::new())?;
        let mut ids = Vec::with_capacity(count);
        for index in 0..count {
            let id = AgentId::parse(format!("019153a4-3088-7e03-a56a-{index:012x}"))
                .map_err(anyhow::Error::msg)?;
            let workspace = directory.join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace)?;
            registry.register(AgentManifest::new(
                id.clone(),
                WorkspaceBinding::new(workspace, &root)?,
                ResourceBudget::local_default(),
            )?)?;
            registry.allow_release(&id, &release)?;
            let layout = root.layout().agent(&id);
            std::fs::write(
                layout.run_root().join("qualification-control-socket"),
                layout
                    .agentd_control_socket()
                    .as_os_str()
                    .as_encoded_bytes(),
            )?;
            ids.push(id);
        }
        report["setup_ms"] = json!(setup.elapsed().as_secs_f64() * 1000.0);
        let mut processes = vec![Daemon::spawn(binary, &root, directory, 0)?];
        let client = SupervisordClient::new(root.layout().supervisor_socket().to_path_buf())?;
        wait_daemon(&client).await?;
        let startup = Instant::now();
        for id in &ids {
            let state = client.snapshot(id.clone()).await?;
            // Never blindly replay a timed-out Start: the next step observes
            // the same registered release and requires an actual healthy PID.
            if let Err(error) = client.start(state.control_fence, release.clone()).await {
                report["checks"]
                    .as_array_mut()
                    .context("receipt check array is invalid")?
                    .push(json!({"start_ack_indeterminate": id, "error": error.to_string()}));
            }
        }
        let mut current = wait_healthy(&client, &ids, None, Duration::from_secs(90)).await?;
        report["startup_ms"] = json!(startup.elapsed().as_secs_f64() * 1000.0);
        report["peak_observed_live_instances"] = json!(current.len());
        report["warm_snapshot_latency_ms"] = latency_samples(&client, &ids, 128).await?;
        for percent in [10_usize, 50, 100] {
            let wave = (count * percent).div_ceil(100);
            let before: Vec<_> = current.iter().map(|state| state.process_id).collect();
            let start = Instant::now();
            for state in current.iter().take(wave) {
                signal_pid(state.process_id.context("live pid")?, libc::SIGKILL)?;
            }
            current = wait_healthy(
                &client,
                &ids,
                Some((&before, wave)),
                Duration::from_secs(90),
            )
            .await?;
            report["checks"]
                .as_array_mut()
                .context("receipt check array is invalid")?
                .push(json!({
                    "kind": "physical_crash_wave", "percent": percent, "count": wave,
                    "all_replaced": true, "unrelated_pids_unchanged": true,
                    "recovery_ms": start.elapsed().as_secs_f64() * 1000.0,
                    "snapshot_latency_ms": latency_samples(&client, &ids, 64).await?
                }));
        }
        // The first child has used three attempts across the three waves.
        signal_pid(current[0].process_id.context("canary pid")?, libc::SIGKILL)?;
        wait_inactive(&client, &ids[0], Duration::from_secs(10)).await?;
        let budget = read_budget(&root, &ids[0])?;
        ensure!(
            budget["main"]["attempts"] == 3 && budget["main"]["pending"] == false,
            "restart budget widened: {budget}"
        );
        report["checks"]
            .as_array_mut()
            .context("receipt check array is invalid")?
            .push(json!({"kind": "fourth_crash_exhausted", "budget": budget}));

        let last = ids.len() - 1;
        let state = client.snapshot(ids[last].clone()).await?;
        client.kill(state.control_fence).await?;
        wait_inactive(&client, &ids[last], Duration::from_secs(10)).await?;
        let before_restart: Vec<_> = current.iter().map(|state| state.process_id).collect();
        processes[0].crash()?;
        let start = Instant::now();
        processes.push(Daemon::spawn(binary, &root, directory, 1)?);
        wait_daemon(&client).await?;
        for (index, id) in ids.iter().enumerate() {
            let state = client.snapshot(id.clone()).await?;
            if index == 0 || index == last {
                ensure!(!state.active, "stopped/exhausted child resurrected");
            } else {
                ensure!(
                    state.process_id == before_restart[index],
                    "adoption changed unrelated pid"
                );
            }
        }
        report["checks"].as_array_mut().context("receipt check array is invalid")?.push(json!({"kind": "supervisord_sigkill_adoption", "elapsed_ms": start.elapsed().as_secs_f64() * 1000.0, "explicit_kill_not_resurrected": true}));

        // A real read-only run directory prevents durable restart publication.
        let victim = &ids[count - 3];
        let run = root.layout().agent(victim).run_root().to_path_buf();
        let state = client.snapshot(victim.clone()).await?;
        let mut permissions = PermissionGuard::readonly(&run)?;
        signal_pid(state.process_id.context("fault pid")?, libc::SIGKILL)?;
        tokio::time::sleep(Duration::from_secs(2)).await;
        let failed = client.snapshot(victim.clone()).await?;
        ensure!(
            !failed.healthy && (failed.process_id == state.process_id || !failed.active),
            "write failure caused untracked success"
        );
        report["checks"].as_array_mut().context("receipt check array is invalid")?.push(json!({"kind": "filesystem_permission_failure", "before": state, "after": failed, "no_unwitnessed_replacement": true}));
        permissions.restore()?;

        if std::env::var_os("HEPTA_SUPERVISOR_QUAL_PRELOAD").is_some() {
            qualify_io_faults(&client, &root, directory, &ids, report).await?;
            report["unmeasured_faults"] =
                json!(["hardware power loss", "Matrix-enabled 256 fleet"]);
        }

        for (victim_index, fault_file, kind) in [
            (
                count - 2,
                "qualification-malformed-drain",
                "malformed_drain_ignores_sigterm",
            ),
            (
                2,
                "qualification-trickle-drain",
                "trickled_drain_ignores_sigterm",
            ),
        ] {
            let victim = &ids[victim_index];
            let run = root.layout().agent(victim).run_root().to_path_buf();
            std::fs::write(run.join("qualification-ignore-stop"), b"1")?;
            std::fs::write(run.join(fault_file), b"1")?;
            let before = client.snapshot(victim.clone()).await?;
            let start = Instant::now();
            client.drain(before.control_fence).await?;
            // Sample a healthy, unrelated peer while the faulty drain is active,
            // not only after the problematic child has already been killed.
            let during = latency_samples(&client, &ids[1..2], 64).await?;
            let config = SupervisorConfig::local_default();
            let bound = config.drain_timeout + config.stop_grace + Duration::from_secs(5);
            wait_inactive(&client, victim, bound).await?;
            ensure!(
                start.elapsed() <= bound,
                "physical stop exceeded total deadline: {kind}"
            );
            report["checks"].as_array_mut().context("receipt check array is invalid")?.push(json!({
                "kind": kind, "terminated": true, "elapsed_ms": start.elapsed().as_secs_f64()*1000.0,
                "configured_drain_seconds": config.drain_timeout.as_secs(), "configured_stop_seconds": config.stop_grace.as_secs(),
                "peer_snapshot_latency_during_drain_ms": during,
            }));
        }
        report["final_budget"] = read_budget(&root, &ids[0])?;
        Ok(())
    }

    async fn qualify_io_faults(
        client: &SupervisordClient,
        root: &HeptaFleetRoot,
        directory: &Path,
        ids: &[AgentId],
        report: &mut Value,
    ) -> Result<()> {
        let control = directory.join("io-fault-control");
        let hit = directory.join("io-fault-control.hit");
        for (mode, offset) in [("fsync_eio", 4), ("write_enospc", 5)] {
            let victim = &ids[ids.len() - offset];
            let before = client.snapshot(victim.clone()).await?;
            let run = root.layout().agent(victim).run_root().to_path_buf();
            let old_budget = read_budget(root, victim)?;
            std::fs::write(&control, format!("{mode}\n{}\n", run.display()))?;
            signal_pid(
                before.process_id.context("I/O fault victim PID")?,
                libc::SIGKILL,
            )?;
            let deadline = Instant::now() + Duration::from_secs(5);
            while !hit.is_file() {
                ensure!(
                    Instant::now() < deadline,
                    "I/O fault interposer did not trigger: {mode}"
                );
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
            tokio::time::sleep(Duration::from_millis(300)).await;
            let after = client.snapshot(victim.clone()).await?;
            ensure!(
                !after.healthy && (!after.active || after.process_id == before.process_id),
                "I/O publication failure launched an unwitnessed replacement: {mode}"
            );
            let budget = read_budget(root, victim)?;
            let old_attempts = old_budget["main"]["attempts"]
                .as_u64()
                .context("old attempt count")?;
            let attempts = budget["main"]["attempts"]
                .as_u64()
                .context("new attempt count")?;
            ensure!(
                attempts >= old_attempts && attempts <= old_attempts + 1,
                "I/O fault reset or inflated budget"
            );
            std::fs::rename(&hit, directory.join(format!("io-fault-{mode}.hit")))?;
            report["checks"]
                .as_array_mut()
                .context("receipt check array")?
                .push(json!({
                    "kind": mode, "injection": "test-only LD_PRELOAD one-shot syscall errno",
                    "trigger_observed": true, "before": before, "after": after,
                    "budget_before": old_budget, "budget_after": budget,
                    "no_unwitnessed_replacement": true
                }));
        }
        Ok(())
    }

    fn read_budget(root: &HeptaFleetRoot, id: &AgentId) -> Result<Value> {
        Ok(serde_json::from_slice(&std::fs::read(
            root.layout()
                .agent(id)
                .run_root()
                .join("supervisor-restart-budget.json"),
        )?)?)
    }
    async fn wait_daemon(client: &SupervisordClient) -> Result<()> {
        let deadline = Instant::now() + Duration::from_secs(90);
        loop {
            match client.health().await {
                Ok(_) => return Ok(()),
                Err(error) => ensure!(Instant::now() < deadline, "daemon unavailable: {error}"),
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    }
    async fn wait_healthy(
        client: &SupervisordClient,
        ids: &[AgentId],
        old: Option<(&[Option<u64>], usize)>,
        timeout: Duration,
    ) -> Result<Vec<SupervisordAgentStatus>> {
        let deadline = Instant::now() + timeout;
        loop {
            let mut states = Vec::with_capacity(ids.len());
            let mut ready = true;
            for (index, id) in ids.iter().enumerate() {
                let state = client.snapshot(id.clone()).await?;
                ready &= state.active && state.healthy;
                if let Some((pids, affected)) = old {
                    if index < affected {
                        ready &= state.process_id != pids[index];
                    } else {
                        ensure!(state.process_id == pids[index], "healthy peer pid changed");
                    }
                }
                states.push(state);
            }
            if ready {
                return Ok(states);
            }
            ensure!(
                Instant::now() < deadline,
                "fleet failed bounded readiness: {states:?}"
            );
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
    async fn wait_inactive(
        client: &SupervisordClient,
        id: &AgentId,
        timeout: Duration,
    ) -> Result<()> {
        let deadline = Instant::now() + timeout;
        loop {
            let state = client.snapshot(id.clone()).await?;
            if !state.active {
                return Ok(());
            }
            ensure!(
                Instant::now() < deadline,
                "child still active beyond control deadline: {state:?}"
            );
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    }
    async fn latency_samples(
        client: &SupervisordClient,
        ids: &[AgentId],
        count: usize,
    ) -> Result<Value> {
        let mut samples = Vec::with_capacity(count);
        for index in 0..count {
            let start = Instant::now();
            client.snapshot(ids[index % ids.len()].clone()).await?;
            samples.push(start.elapsed().as_secs_f64() * 1000.0);
        }
        samples.sort_by(f64::total_cmp);
        Ok(
            json!({"samples": count, "p50": samples[(count-1)*50/100], "p95": samples[(count-1)*95/100], "p99": samples[(count-1)*99/100], "max": samples[count-1]}),
        )
    }
    fn signal_pid(pid: u64, signal: i32) -> Result<()> {
        let pid = i32::try_from(pid)?;
        // SAFETY: each positive PID came from this isolated test-owned fleet.
        ensure!(
            unsafe { libc::kill(pid, signal) } == 0,
            "signal: {}",
            std::io::Error::last_os_error()
        );
        Ok(())
    }
    fn command_output(program: &str, args: &[&str]) -> String {
        Command::new(program)
            .args(args)
            .output()
            .ok()
            .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_string())
            .unwrap_or_default()
    }
    struct Daemon {
        child: Child,
        group: i32,
    }
    impl Daemon {
        fn spawn(
            binary: &Path,
            root: &HeptaFleetRoot,
            directory: &Path,
            index: usize,
        ) -> Result<Self> {
            let log = File::create(directory.join(format!("supervisord-{index}.log")))?;
            let mut command = Command::new(binary);
            if let Some(preload) = std::env::var_os("HEPTA_SUPERVISOR_QUAL_PRELOAD") {
                let preload = PathBuf::from(preload);
                ensure!(
                    cfg!(target_os = "linux") && preload.is_absolute() && preload.is_file(),
                    "I/O qualification requires an absolute Linux interposer"
                );
                command.env("LD_PRELOAD", preload).env(
                    "HEPTA_QUAL_IO_FAULT_CONTROL",
                    directory.join("io-fault-control"),
                );
            }
            let child = command
                .arg("--fleet-root")
                .arg(root.as_path())
                .env_remove("OPENAI_API_KEY")
                .env_remove("CODEX_API_KEY")
                .stdin(Stdio::null())
                .stdout(log.try_clone()?)
                .stderr(log)
                .process_group(0)
                .spawn()?;
            Ok(Self {
                group: i32::try_from(child.id())?,
                child,
            })
        }
        fn crash(&mut self) -> Result<()> {
            self.child.kill()?;
            self.child.wait()?;
            Ok(())
        }
    }
    impl Drop for Daemon {
        fn drop(&mut self) {
            // SAFETY: the dedicated group was created and retained by this
            // guard; adopted children stay in that group after leader SIGKILL.
            unsafe {
                libc::kill(-self.group, libc::SIGKILL);
            }
            let _ = self.child.wait();
        }
    }
    struct PermissionGuard {
        path: PathBuf,
        mode: u32,
    }
    impl PermissionGuard {
        fn readonly(path: &Path) -> Result<Self> {
            let guard = Self {
                path: path.to_path_buf(),
                mode: std::fs::metadata(path)?.permissions().mode(),
            };
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o500))?;
            ensure!(
                std::fs::OpenOptions::new()
                    .create_new(true)
                    .write(true)
                    .open(path.join("qualification-write-probe"))
                    .is_err(),
                "host privilege bypassed permission fault"
            );
            Ok(guard)
        }
        fn restore(&mut self) -> Result<()> {
            std::fs::set_permissions(&self.path, std::fs::Permissions::from_mode(self.mode))?;
            Ok(())
        }
    }
    impl Drop for PermissionGuard {
        fn drop(&mut self) {
            let _ = self.restore();
        }
    }
}
