//! Four real ordinary Agentd incarnations around three real matched rounds.
//! This controlled test owns no production qualification or install credential.

use super::agentd_tests::ordinary_session;
use super::agentd_tests::seed_actions;
use super::*;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

// All current Python phase children inherit this new group. Keep the original
// child unreaped until signaling so an unrelated reused PID cannot be targeted.
struct OwnedRound {
    child: Child,
    reaped: bool,
}

impl OwnedRound {
    fn terminate_and_reap(&mut self) -> TestResult<()> {
        if self.reaped {
            return Ok(());
        }
        let pid = rustix::process::Pid::from_child(&self.child);
        let signaled = rustix::process::kill_process_group(pid, rustix::process::Signal::KILL);
        let waited = self.child.wait();
        self.reaped = waited.is_ok();
        waited?;
        match signaled {
            Ok(()) | Err(rustix::io::Errno::SRCH) => Ok(()),
            Err(error) => Err(error.into()),
        }
    }

    async fn wait(&mut self) -> TestResult<ExitStatus> {
        // This additional CI campaign guard does not promise completion of all
        // original 1,800s/600s phase worst cases. It never shortens a training
        // schedule: hitting it fails the whole round and retains its evidence.
        let deadline = Instant::now() + Duration::from_secs(2_700);
        loop {
            if let Some(status) = self.child.try_wait()? {
                self.reaped = true;
                return Ok(status);
            }
            if Instant::now() >= deadline {
                self.terminate_and_reap()?;
                return Err(
                    "controlled training round exceeded its 2,700s overall campaign guard".into(),
                );
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
}

impl Drop for OwnedRound {
    fn drop(&mut self) {
        let _ = self.terminate_and_reap();
    }
}

async fn train_round(
    input: &NativeInput,
    output: &Path,
    round: usize,
    readback: &Path,
) -> TestResult<serde_json::Value> {
    let script = PathBuf::from(
        std::env::var_os("HEPTA_PUBLIC_INITIAL_ROUND_RUNNER")
            .ok_or("explicit exact-source real-round runner required")?,
    )
    .canonicalize()?;
    let stem = output.parent().ok_or("round output parent")?;
    let stdout = File::create(stem.join(format!("round-{round}.stdout.log")))?;
    let stderr = File::create(stem.join(format!("round-{round}.stderr.log")))?;
    let launch = serde_json::json!({
        "schema":"hepta-controlled-real-round-launch-v2", "round":round,
        "python":input.python,"script":script,"script_sha256":Digest32::of_bytes(&fs::read(&script)?).to_string(),
        "chain":input.chain,"materials":input.materials,"parent":input.parent,
        "parent_sha256":input.parent_sha256,"ordinary_readback":readback,"output":output,
        "overall_round_guard_seconds":2_700,"all_phase_worst_cases_covered":false,
        "original_phase_budgets_unchanged":true,"isolated_python":true,"fresh_owned_process_group":true,
        "product_qualification_issued":false
    });
    fs::write(
        stem.join(format!("round-{round}.launch.json")),
        serde_json::to_vec_pretty(&launch)?,
    )?;
    let child = Command::new(&input.python)
        .args(["-I", "-B"])
        .arg(&script)
        .arg("--chain")
        .arg(&input.chain)
        .arg("--materials")
        .arg(&input.materials)
        .arg("--parent")
        .arg(&input.parent)
        .arg("--parent-sha256")
        .arg(&input.parent_sha256)
        .arg("--output")
        .arg(output)
        .arg("--round")
        .arg(round.to_string())
        .arg("--ordinary-readback")
        .arg(readback)
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONUSERBASE")
        .env("PYTHONNOUSERSITE", "1")
        .stdin(Stdio::null())
        .stdout(stdout)
        .stderr(stderr)
        .process_group(/*pgroup*/ 0)
        .spawn()?;
    let mut owner = OwnedRound {
        child,
        reaped: false,
    };
    let status = match owner.wait().await {
        Ok(status) => status,
        Err(error) => {
            let cleanup = owner.terminate_and_reap();
            fs::write(
                stem.join(format!("round-{round}.exit.json")),
                serde_json::to_vec_pretty(&serde_json::json!({
                    "round":round,"success":false,"failure":error.to_string(),
                    "cleanup_failure":cleanup.as_ref().err().map(ToString::to_string),
                    "direct_child_reaped":owner.reaped,"overall_round_guard_seconds":2_700
                }))?,
            )?;
            return Err(error);
        }
    };
    fs::write(
        stem.join(format!("round-{round}.exit.json")),
        serde_json::to_vec_pretty(&serde_json::json!({
            "round":round,"status":status.to_string(),"success":status.success(),"direct_child_reaped":true
        }))?,
    )?;
    if !status.success() {
        return Err(format!("real training round {round} failed ({status}); original logs and abort/assessment retained").into());
    }
    let path = output.join("assessment.json");
    if fs::metadata(&path)?.len() > 1024 * 1024 {
        return Err("controlled assessment exceeds its bounded test envelope".into());
    }
    let assessment: serde_json::Value = serde_json::from_slice(&fs::read(path)?)?;
    if assessment["schema"] != "hepta-controlled-real-round-assessment-v2"
        || assessment["round"] != round
        || assessment["decision"] != "hold-no-positive-gain"
        || assessment["all_required_controls_executed"] != true
        || assessment["training_budget_matched_by_steps_and_token_schedule"] != true
        || assessment["installed_child"] != false
        || assessment["product_qualification"] != false
    {
        return Err("round did not retain the original unqualified hold decision".into());
    }
    Ok(assessment)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual public V2 weights and three five-arm training/evaluation rounds"]
async fn real_public_initial_three_rounds_hold_and_read_original_current() -> TestResult<()> {
    let (input, mut worker, bytes) = input_and_worker("public-loop-session-0")?;
    let root = input.output.join("r");
    fs::create_dir(&root)?;
    let fixture = Fixture::with_profile(
        root.join("o"),
        &bytes,
        Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2),
    )?;
    let config = fixture.config("b")?;
    // Keep the three-round owner at its original artifact root, with a
    // portable Unix-domain socket path for real Agentd incarnations.
    #[cfg(unix)]
    std::assert!(
        config.identity().control_socket.as_os_str().as_encoded_bytes().len() < 104,
        "three-round Agentd socket path must fit the shortest supported Unix sun_path"
    );
    let identity = config.identity().clone();
    let actions = seed_actions(&config, i64::try_from(fixture.now)?).await?;
    worker.action_completions = actions.clone();
    let baseline = fixture
        .service
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    let mut effects = root.join("ordinary-0");
    let initial = ordinary_session(config, worker, &fixture, &effects, /*reads*/ 1).await?;
    let original_parent = initial["parent"].clone();
    let mut report = serde_json::json!({
        "schema":"hepta-controlled-public-initial-three-round-loop-v2",
        "controlled_test_issuer":true,"same_original_artifact_owner":true,
        "same_home_root":identity.home_root,"same_fleet_root":identity.fleet_root,
        "original_current":{"head_digest":baseline.head_digest.to_string(),"record_count":baseline.records,
            "file_digest":baseline.file_digest.to_string()},
        "ordinary_sessions":[initial],"rounds":[],"completed_rounds":0,
        "beneficial_releases":0,"installed_children":0,"product_qualification_issued":false,
        "public_network_ready":false,"independent_future_quality":false
    });
    let report_path = root.join("loop-observations.json");
    fs::write(&report_path, serde_json::to_vec_pretty(&report)?)?;
    for round in 1..=3 {
        let assessment = train_round(
            &input,
            &root.join(format!("round-{round}")),
            round,
            &effects.join("ordinary-session-result.json"),
        )
        .await?;
        if fixture
            .service
            .current_registry_view(initial_now_seconds()?)?
            .receipt()
            != baseline
        {
            return Err(
                "training changed the original CURRENT without a product credential".into(),
            );
        }
        let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(&identity.fleet_root)?)?;
        let stopped = registry.load_agent(&identity.agent_id)?.lifecycle;
        if stopped.lifecycle != AgentLifecycle::Stopped {
            return Err("previous ordinary incarnation did not stop before restart".into());
        }
        let starting = registry.compare_and_transition(
            &identity.agent_id,
            stopped.generation,
            AgentLifecycle::Starting,
        )?;
        let config = AgentdConfig::load(
            identity.fleet_root.clone(),
            identity.agent_id.clone(),
            starting.generation,
            identity.home_root.clone(),
            identity.run_root.clone(),
            identity.home_root.clone(),
            identity.workspace.clone(),
        )?;
        let (next_input, mut worker, next_bytes) =
            input_and_worker(&format!("public-loop-session-{round}"))?;
        if next_input.parent_sha256 != input.parent_sha256 || next_bytes != bytes {
            return Err("same selected generation-one parent changed between held rounds".into());
        }
        worker.action_completions = actions.clone();
        effects = root.join(format!("ordinary-{round}"));
        let observed = ordinary_session(config, worker, &fixture, &effects, /*reads*/ 1).await?;
        if observed["parent"] != original_parent
            || observed["spawn_generation"] != starting.generation
            || observed["current"]["head_digest"] != baseline.head_digest.to_string()
        {
            return Err(
                "fresh ordinary read did not consume the original held parent and CURRENT".into(),
            );
        }
        report["ordinary_sessions"]
            .as_array_mut()
            .ok_or("session report array")?
            .push(observed);
        report["rounds"]
            .as_array_mut()
            .ok_or("round report array")?
            .push(assessment);
        report["completed_rounds"] = serde_json::json!(round);
        fs::write(&report_path, serde_json::to_vec_pretty(&report)?)?;
    }
    std::assert_eq!(report["completed_rounds"], 3);
    std::assert_eq!(
        report["ordinary_sessions"]
            .as_array()
            .ok_or("session report array")?
            .len(),
        4
    );
    std::assert_eq!(
        fixture
            .service
            .current_registry_view(initial_now_seconds()?)?
            .receipt(),
        baseline
    );
    Ok(())
}
