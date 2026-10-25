#![cfg(all(target_os = "linux", not(feature = "qualification-cognitive-write")))]
#![recursion_limit = "256"]

#[path = "support/native_memory_process_fixture.rs"]
mod native_memory_process_fixture;
#[path = "support/native_memory_process_ndu.rs"]
mod native_memory_process_ndu;
#[path = "support/native_memory_process_objective.rs"]
mod native_memory_process_objective;

use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_agentd::NativeMemoryModelConfigV1;
use codex_hepta_agentd::ObjectiveStartOutcome;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::MemoryCellQueryV1;
use codex_hepta_memory::MemoryCellRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixStream;

use native_memory_process_fixture::Fixture;
use native_memory_process_fixture::feed;
use native_memory_process_fixture::file_sha;
use native_memory_process_fixture::now_ms;
use native_memory_process_fixture::prepare;
use native_memory_process_fixture::retain;
use native_memory_process_fixture::sign;

fn root(label: &str) -> Result<PathBuf> {
    if let Some(root) = std::env::var_os("HEPTA_NATIVE_MEMORY_PROCESS_ROOT") {
        return Ok(PathBuf::from(root).join(label));
    }
    let parent = tempfile::Builder::new().prefix("hm-cp-").tempdir()?.keep();
    Ok(parent.join(label))
}

fn command(f: &Fixture, digest: Digest32, tag: &str) -> Result<Command> {
    let mut command = Command::new(env!("CARGO_BIN_EXE_codex-hepta-agentd"));
    command
        .current_dir(&f.identity.workspace)
        .env(
            codex_hepta_paths::HEPTA_FLEET_ROOT_ENV,
            &f.identity.fleet_root,
        )
        .env("HEPTA_AGENT_ID", f.identity.agent_id.as_str())
        .env(
            "HEPTA_AGENT_GENERATION",
            f.identity.spawn_generation.to_string(),
        )
        .env("HEPTA_AGENT_HOME", &f.identity.home_root)
        .env("HEPTA_AGENT_RUN_ROOT", &f.identity.run_root)
        .env("CODEX_HOME", &f.identity.home_root)
        .args(["--authbus-trust-file"])
        .arg(f.identity.home_root.join("objective-trust.json"))
        .args(["--authbus-checkpoint-file"])
        .arg(f.root.join("objective-checkpoint.json"))
        .args(["--objective-profile-file"])
        .arg(f.identity.home_root.join("objective-profile.json"))
        .args(["--native-memory-bootstrap"])
        .arg(&f.bootstrap)
        .args(["--native-memory-bootstrap-digest", &digest.to_string()])
        .stdin(Stdio::null())
        .stdout(
            std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(f.root.join(format!("{tag}.stdout")))?,
        )
        .stderr(
            std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(f.root.join(format!("{tag}.stderr")))?,
        );
    retain(
        &f.root.join(format!("{tag}.command.json")),
        &json!({"program":env!("CARGO_BIN_EXE_codex-hepta-agentd"),
        "arguments":command.get_args().map(|a|a.to_string_lossy().into_owned()).collect::<Vec<_>>(),
        "binary_sha256":file_sha(std::path::Path::new(env!("CARGO_BIN_EXE_codex-hepta-agentd")))?,
        "cwd":f.identity.workspace,"spawn_generation":f.identity.spawn_generation,"default_build":true,"production_qualified":false}),
    )?;
    Ok(command)
}

async fn wait_exit(child: &mut Child) -> Result<std::process::ExitStatus> {
    let until = tokio::time::Instant::now() + Duration::from_secs(30);
    loop {
        if let Some(exit) = child.try_wait()? {
            return Ok(exit);
        }
        ensure!(
            tokio::time::Instant::now() < until,
            "owned daemon did not exit; no SIGKILL fallback"
        );
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

async fn control(f: &Fixture, sequence: u64, request: Value) -> Result<Value> {
    let mut stream = UnixStream::connect(f.identity.home_root.join("memory-current.sock")).await?;
    let wire = json!({"schema_version":1,"sequence":sequence,"command":request});
    retain(
        &f.root.join(format!("control-{sequence:03}.request.json")),
        &wire,
    )?;
    stream.write_all(&serde_json::to_vec(&wire)?).await?;
    stream.shutdown().await?;
    let mut bytes = Vec::new();
    tokio::time::timeout(
        Duration::from_secs(130),
        stream.take(1_048_577).read_to_end(&mut bytes),
    )
    .await??;
    ensure!(bytes.len() <= 1_048_576, "unbounded response");
    let response: Value = serde_json::from_slice(&bytes)?;
    retain(
        &f.root.join(format!("control-{sequence:03}.response.json")),
        &response,
    )?;
    ensure!(
        response["sequence"] == sequence,
        "response correlation differs"
    );
    Ok(response)
}

async fn ready(f: &Fixture, child: &mut Child, client: &AgentdClient) -> Result<()> {
    let until = tokio::time::Instant::now() + Duration::from_secs(60);
    loop {
        ensure!(
            child.try_wait()?.is_none(),
            "default daemon exited before readiness"
        );
        if client.health().await.is_ok_and(|h| h.promotion_ready) {
            break;
        }
        ensure!(
            tokio::time::Instant::now() < until,
            "promotion readiness timed out"
        );
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    f.registry.compare_and_transition(
        &f.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    loop {
        if client.health().await.is_ok_and(|h| h.ready) {
            break;
        }
        ensure!(
            tokio::time::Instant::now() < until,
            "serving readiness timed out"
        );
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    retain(&f.root.join("daemon-health.json"), &client.health().await?)?;
    let admitted = client.objective_start(f.objective.ingress.clone()).await?;
    retain(&f.root.join("objective-admission.json"), &admitted)?;
    let ObjectiveStartOutcome::Admitted { receipt } = admitted else {
        anyhow::bail!("actual ObjectiveStart was not admitted")
    };
    ensure!(
        receipt.objective_digest == f.objective.digest.to_string(),
        "actual objective differs from host preparation"
    );
    Ok(())
}

async fn cleanup(f: &Fixture, child: &mut Child, client: &AgentdClient) -> Result<Value> {
    if let Some(status) = child.try_wait()? {
        return Ok(json!({"already_exited":true,"exit_code":status.code()}));
    }
    let drained = async {
        let mut run_released = false;
        if let Ok(Some(run)) = client.run_status("process.current.run".into()).await {
            let cancelled = client
                .run_cancel(
                    "process.current.run".into(),
                    run.revision,
                    "controlled process qualification complete".into(),
                )
                .await?;
            client
                .run_release_closed("process.current.run".into(), cancelled.receipt.revision)
                .await?;
            run_released = true;
        }
        f.registry.compare_and_transition(
            &f.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )?;
        let until = tokio::time::Instant::now() + Duration::from_secs(10);
        let mut responses = Vec::new();
        loop {
            let mut stream = UnixStream::connect(&f.identity.control_socket).await?;
            let mut request = serde_json::to_vec(&AgentdRequest::drain(
                /*request_id*/ 900, /*spawn_generation*/ 1,
            ))?;
            request.push(b'\n');
            stream.write_all(&request).await?;
            let mut drain = Vec::new();
            tokio::time::timeout(
                Duration::from_secs(3),
                stream.take(65_537).read_to_end(&mut drain),
            )
            .await??;
            let drain: Value = serde_json::from_slice(&drain)?;
            let done = drain["payload"]["type"] == "drain"
                && drain["payload"]["admission_closed"] == true
                && drain["payload"]["drained"] == true
                && drain["payload"]["running_turns"] == 0
                && drain["payload"]["fenced"] == false;
            responses.push(drain);
            if done {
                retain(&f.root.join("drain.json"), &responses)?;
                break;
            }
            if tokio::time::Instant::now() >= until {
                retain(&f.root.join("drain.json"), &responses)?;
                anyhow::bail!("actual drain acknowledgement timed out");
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        Ok::<_, anyhow::Error>(run_released)
    }
    .await;
    let pid = child.id();
    ensure!(
        Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status()?
            .success(),
        "owned daemon SIGTERM failed"
    );
    let status = wait_exit(child).await?;
    ensure!(
        status.success(),
        "graceful daemon shutdown was unsuccessful: {status}"
    );
    let run_released = drained?;
    f.registry.compare_and_transition(
        &f.identity.agent_id,
        /*expected_generation*/ 3,
        AgentLifecycle::Stopped,
    )?;
    Ok(
        json!({"run_released":run_released,"drain_acknowledged":true,"signal":"SIGTERM","pid":pid,"exit_code":status.code(),"sigkill_used":false}),
    )
}

async fn reject_old_cut_after_restart(f: &mut Fixture) -> Result<()> {
    let starting = f.registry.compare_and_transition(
        &f.identity.agent_id,
        /*expected_generation*/ 4,
        AgentLifecycle::Starting,
    )?;
    let mut descriptor: Value = serde_json::from_slice(&std::fs::read(&f.bootstrap)?)?;
    descriptor["spawn_generation"] = json!(starting.generation);
    f.identity.spawn_generation = starting.generation;
    f.bootstrap = f.identity.home_root.join("restart-bootstrap.json");
    retain(&f.bootstrap, &descriptor)?;
    f.bootstrap_sha256 = Digest32::of_bytes(&std::fs::read(&f.bootstrap)?);
    let mut replay = command(f, f.bootstrap_sha256, "restart-old-cut")?.spawn()?;
    let exit = wait_exit(&mut replay).await?;
    let stderr = std::fs::read_to_string(f.root.join("restart-old-cut.stderr"))?;
    retain(
        &f.root.join("restart-old-cut.report.json"),
        &json!({"exit_code":exit.code(),"new_spawn_generation":starting.generation,
        "old_authority_cut_rebound_to_current_generation":true,"error":stderr,"production_qualified":false}),
    )?;
    ensure!(
        !exit.success() && stderr.contains("pinned file drift"),
        "restart did not reject the actual old authority pin: {stderr}"
    );
    Ok(())
}

async fn exercise(f: &Fixture, child: &mut Child, positive: bool) -> Result<Value> {
    let client = AgentdClient::new(
        f.identity.control_socket.clone(),
        f.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
    )?;
    let attempted=async {
        ready(f,child,&client).await?;
        let status=control(f,/*sequence*/ 1,json!({"method":"status"})).await?;
        ensure!(status["ok"]==true && status["payload"]["daemon_pid"]==child.id(),"not the actual owned default daemon");
        let query=MemoryCellQueryV1 {request_id:StableId::new("process.current.query")?,key:f.document.key.clone(),deadline_unix_ms:now_ms()+180_000};
        let mut wrong=query.clone();wrong.key.role=MemoryCellRoleV1::Semantic;
        ensure!(control(f,/*sequence*/ 2,json!({"method":"prepare","run_id":"process.current.run","query":wrong})).await?["ok"]==false,"typed key substitution admitted");
        ensure!(control(f,/*sequence*/ 3,json!({"method":"prepare","run_id":"missing.run","query":query})).await?["ok"]==false,"unknown objective admitted");
        let prepared=control(f,/*sequence*/ 4,json!({"method":"prepare","run_id":"process.current.run","query":query})).await?;
        ensure!(prepared["ok"]==true,"actual current prepare rejected: {prepared}");
        let binding:FinalUseBinding=serde_json::from_value(prepared["payload"]["binding"].clone())?;
        ensure!(binding.subject_id==f.identity.agent_id.as_str() && binding.destination_id=="process.ndu","binding identity differs");
        let grant=sign(binding,"process.current.read",now_ms())?;
        let prepared_id=prepared["payload"]["prepared_id"].clone();
        ensure!(control(f,/*sequence*/ 5,json!({"method":"execute","prepared_id":"not-the-prepared-read","grant":grant})).await?["ok"]==false,"prepared identity substitution admitted");
        let revoked=feed(/*revision*/ 3,std::slice::from_ref(&grant.grant.grant_id),now_ms())?;
        if !positive {ensure!(control(f,/*sequence*/ 6,json!({"method":"revoke","update":revoked})).await?["ok"]==true,"revocation failed");}
        let executed=control(f,/*sequence*/ 7,json!({"method":"execute","prepared_id":prepared_id,"grant":grant})).await?;
        if positive {
            ensure!(executed["ok"]==true,"actual decoder rejected: {executed}");
            ensure!(executed["payload"].get("text").is_none() && executed["payload"].get("execution").is_none(),"answer escaped before delivery fence");
            let delivered=control(f,/*sequence*/ 8,json!({"method":"deliver"})).await?;
            ensure!(delivered["ok"]==true,"current result did not deliver");
            let execution=&delivered["payload"]["execution"];
            ensure!(execution["text"].as_str().is_some_and(|v|v.trim()==f.document.value),"raw decoder exact answer differs");
            ensure!(execution["decoder_queries"]==1 && execution["feature_forward_calls"]==1,"unexpected model counts");
            ensure!(delivered["payload"]["abstain"]==true && delivered["payload"]["authority_grants_any"]==false,"shadow gained action authority");
            ensure!(control(f,/*sequence*/ 9,json!({"method":"revoke","update":revoked})).await?["ok"]==true,"revocation failed");
            let denied=control(f,/*sequence*/ 10,json!({"method":"deliver"})).await?;
            ensure!(denied["ok"]==false && denied["error"].as_str().is_some_and(|e|e.contains("Revoked")),"revoked result delivered: {denied}");
            ensure!(control(f,/*sequence*/ 11,json!({"method":"execute","prepared_id":prepared_id,"grant":grant})).await?["ok"]==false,"replayed execution admitted");
        } else {
            ensure!(executed["ok"]==false && executed["error"].as_str().is_some_and(|e|e.contains("prepared NDU binding no longer current")),"revoked prepared grant escaped: {executed}");
            let state=control(f,/*sequence*/ 8,json!({"method":"status"})).await?;
            ensure!(state["ok"]==true && state["payload"]["attempted"]==true && state["payload"]["completed"]==false,
                "failed execution did not retain its consumed session: {state}");
            let replay=control(f,/*sequence*/ 9,json!({"method":"execute","prepared_id":prepared_id,"grant":grant})).await?;
            ensure!(replay["ok"]==false && replay["error"]=="unknown or consumed prepared read",
                "failed execution enrollment could replay: {replay}");
        }
        let count=std::fs::read_dir(&f.model.receipt_directory)?.filter_map(Result::ok).filter(|e|e.path().is_dir()).count();
        ensure!(count==usize::from(positive),"refused requests entered a model child");
        Ok::<_,anyhow::Error>(json!({"actual_default_daemon_process":true,"actual_objective_start":true,"separate_issuer_process":true,
            "daemon_pid":child.id(),"issuer_pid":std::process::id(),"new_training_updates":0,"decoder_queries":count,
            "source_authority_epoch":23,"source_owner_epoch":31,"ndu_authority_epoch":11,"objective_authority_epoch":7,
            "positive_delivery":positive,"revocation_refused":true,"denominator":usize::from(positive),"previously_exposed_case":true,"production_qualified":false}))
    }.await;
    let shutdown = cleanup(f, child, &client).await;
    let report = json!({"engineering_pass":attempted.is_ok() && shutdown.is_ok(),"result":attempted.as_ref().ok(),
        "error":attempted.as_ref().err().map(|e|format!("{e:#}")),"shutdown":shutdown.as_ref().ok(),"shutdown_error":shutdown.as_ref().err().map(|e|format!("{e:#}"))});
    retain(&f.root.join("process-report.json"), &report)?;
    attempted?;
    shutdown?;
    Ok(report)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn default_daemon_current_process_refuses_pin_drift_and_revoked_read_without_model()
-> Result<()> {
    let mut f = prepare(root("negative")?, /*trained*/ None).await?;
    let mut rejected = command(&f, Digest32::of_bytes(b"wrong bootstrap"), "wrong-pin")?.spawn()?;
    ensure!(
        !wait_exit(&mut rejected).await?.success(),
        "default daemon accepted wrong bootstrap pin"
    );
    ensure!(
        std::fs::read_to_string(f.root.join("wrong-pin.stderr"))?.contains("pinned file drift"),
        "unexpected startup failure"
    );
    let mut daemon = command(&f, f.bootstrap_sha256, "daemon")?.spawn()?;
    exercise(&f, &mut daemon, /*positive*/ false).await?;
    reject_old_cut_after_restart(&mut f).await?;
    println!("actual default process evidence: {}", f.root.display());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires explicitly pinned existing model/source; one decoder query, no training"]
async fn pretrained_default_daemon_current_process_delivers_once_then_refuses_revocation()
-> Result<()> {
    let model: NativeMemoryModelConfigV1 = serde_json::from_slice(&std::fs::read(
        std::env::var_os("HEPTA_NATIVE_MEMORY_PROCESS_MODEL_CONFIG")
            .ok_or_else(|| anyhow::anyhow!("explicit model config required"))?,
    )?)?;
    let document = std::fs::read(
        std::env::var_os("HEPTA_NATIVE_MEMORY_PROCESS_SOURCE_DOCUMENT")
            .ok_or_else(|| anyhow::anyhow!("explicit source document required"))?,
    )?;
    let mut f = prepare(root("positive")?, Some((model, document))).await?;
    let mut daemon = command(&f, f.bootstrap_sha256, "daemon")?.spawn()?;
    exercise(&f, &mut daemon, /*positive*/ true).await?;
    reject_old_cut_after_restart(&mut f).await?;
    println!(
        "actual default pretrained process evidence: {}",
        f.root.display()
    );
    Ok(())
}
