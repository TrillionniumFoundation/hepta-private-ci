#![cfg(feature = "server")]

//! A real optional service on the SAME RuntimeTasks used by Agentd, backed by
//! AutomationStore, exercised in separate OS processes. Forty required echo
//! services represent sibling liveness; these are not forty real Codex sessions.
//! No provider, physical effect, independent evaluator, cross-schema migration
//! or deployed-host performance claim is made by this fixture.
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_components::automation::AutomationError;
use codex_hepta_agent_components::automation::AutomationOperationReceipt;
use codex_hepta_agent_components::automation::AutomationSchedule;
use codex_hepta_agent_components::automation::AutomationStore;
use codex_hepta_agent_components::automation::AutomationTaskDraft;
use codex_hepta_agent_components::automation::TimerPhase;
use codex_hepta_agent_components::automation::automation_task_operation_intent;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::RuntimeTasks;
use codex_hepta_operations::DestinationApplyDisposition;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const ROOT_ENV: &str = "HEPTA_OPTIONAL_RESTART_TEST_ROOT";
const STAGE_ENV: &str = "HEPTA_OPTIONAL_RESTART_TEST_STAGE";
const CRASH_EXIT: i32 = 73;

#[derive(Clone, Copy)]
enum Fault {
    None,
    PanicAfterCommit,
    ProcessLossAfterCommit,
}

struct Request {
    draft: AutomationTaskDraft,
    fault: Fault,
    reply: oneshot::Sender<Result<AutomationOperationReceipt, AutomationError>>,
}

type CoreRequest = (u64, oneshot::Sender<u64>);

async fn apply(store: &AutomationStore, request: Request) {
    let intent = automation_task_operation_intent(
        store.owner_agent_id(),
        &request.draft,
        Generation::new(1).expect("stable original operation generation"),
    )
    .expect("exact task intent");
    let result = store
        .create_task_from_operation(&intent, &request.draft)
        .await;
    match request.fault {
        Fault::None => {
            let _ = request.reply.send(result);
        }
        Fault::PanicAfterCommit => {
            result.expect("effect must commit before injected task panic");
            panic!("optional module panic after durable commit, before acknowledgement");
        }
        Fault::ProcessLossAfterCommit => {
            result.expect("effect must commit before injected process loss");
            // Exit without running Rust destructors. The next process must use
            // owner reconciliation/dedupe, not replay the mutation as new work.
            std::process::exit(CRASH_EXIT);
        }
    }
}

fn attach_timer(
    host: &mut RuntimeTasks,
    store: AutomationStore,
    name: &str,
    quarantines: Arc<AtomicUsize>,
) -> mpsc::Sender<Request> {
    let (send, mut receive) = mpsc::channel::<Request>(4);
    host.spawn_optional_service(
        name,
        move |stop| async move {
            loop {
                tokio::select! {
                    biased;
                    () = stop.cancelled() => {
                        receive.close();
                        while let Some(request) = receive.recv().await {
                            apply(&store, request).await;
                        }
                        return Ok(());
                    }
                    request = receive.recv() => {
                        let Some(request) = request else {
                            return Err(AgentdError::Protocol("optional input closed".to_string()));
                        };
                        apply(&store, request).await;
                    }
                }
            }
        },
        move || {
            quarantines.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
        || Ok(()), // Unpublish the local route, not writer or effect acceptance.
    )
    .expect("same public host extension point");
    send
}

async fn ask(
    send: &mpsc::Sender<Request>,
    draft: AutomationTaskDraft,
    fault: Fault,
) -> Result<Result<AutomationOperationReceipt, AutomationError>, oneshot::error::RecvError> {
    let (reply, result) = oneshot::channel();
    send.send(Request {
        draft,
        fault,
        reply,
    })
    .await
    .expect("admission");
    timeout(Duration::from_secs(10), result)
        .await
        .expect("bounded reply")
}

async fn prove_siblings(clients: &[mpsc::Sender<CoreRequest>]) {
    for (index, client) in clients.iter().enumerate() {
        let (reply, response) = oneshot::channel();
        client
            .send((index as u64, reply))
            .await
            .expect("core admission");
        let value = timeout(Duration::from_secs(2), response)
            .await
            .expect("core live")
            .expect("core reply");
        assert_eq!(value, index as u64 + 1);
    }
}

fn load_draft(root: &Path, file: &str) -> AutomationTaskDraft {
    let bytes = std::fs::read(root.join(file)).expect("draft file");
    serde_json::from_slice(&bytes).expect("draft JSON")
}

async fn worker(root: &Path, stage: &str) {
    let recovery_started = Instant::now();
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet");
    let layout = fleet.layout().agent(&AgentId::parse(AGENT).expect("agent"));
    let store = AutomationStore::open(&layout)
        .await
        .expect("real SQLite reopen");
    let reopen_duration_us = recovery_started.elapsed().as_micros();
    let mut recovery_duration_us = None;
    let first = load_draft(root, "first.json");
    let second = load_draft(root, "second.json");
    let initial = store.timer_status().await.expect("durable epoch");
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).expect("host");
    let mut core = Vec::new();
    for index in 0..40 {
        let (send, mut receive) = mpsc::channel::<CoreRequest>(2);
        let cancellation = stop.child_token();
        host.spawn_required(&format!("core.{index}"), async move {
            loop {
                tokio::select! {
                    () = cancellation.cancelled() => return Ok(()),
                    request = receive.recv() => {
                        let Some((value, reply)) = request else { return Ok(()); };
                        let _ = reply.send(value + 1);
                    }
                }
            }
        })
        .expect("required service");
        core.push(send);
    }
    let quarantines = Arc::new(AtomicUsize::new(0));
    let name = format!("optional.timer.{}", initial.writer_epoch);
    let client = attach_timer(&mut host, store.clone(), &name, Arc::clone(&quarantines));
    assert_eq!(host.active_count(), 41);
    prove_siblings(&core).await;
    match stage {
        "isolate" => {
            assert!(
                ask(&client, first.clone(), Fault::PanicAfterCommit)
                    .await
                    .is_err()
            );
            timeout(Duration::from_secs(10), host.observe_next())
                .await
                .expect("observe panic")
                .expect("isolated");
            assert_eq!(quarantines.load(Ordering::SeqCst), 1);
            assert_eq!(host.active_count(), 40);
            assert!(!stop.is_cancelled());
            let tasks = store
                .list_tasks(10)
                .await
                .expect("committed despite ACK loss");
            assert_eq!(tasks.len(), 1);
        }
        "crash" => {
            let _ = ask(&client, second.clone(), Fault::ProcessLossAfterCommit).await;
            panic!("process-loss injection did not terminate the process");
        }
        "replace" => {
            for draft in [first.clone(), second.clone()] {
                let receipt = ask(&client, draft, Fault::None)
                    .await
                    .expect("reply")
                    .expect("reconcile committed task");
                assert_eq!(
                    receipt.disposition,
                    DestinationApplyDisposition::AlreadyApplied
                );
            }
            assert!(store.quiesce_timer().await.expect("quiesce").can_handoff());
            host.retire_optional(&name)
                .await
                .expect("drain optional task");
            assert!(client.is_closed());
            let next = store.handoff_timer().await.expect("durable writer handoff");
            assert_eq!(
                next.timer_status().await.expect("next status").writer_epoch,
                initial.writer_epoch + 1
            );
            next.resume_timer()
                .await
                .expect("publish compatible successor");
            let fresh = new_draft("stale writer cannot create a new effect");
            let intent = automation_task_operation_intent(
                store.owner_agent_id(),
                &fresh,
                Generation::new(1).expect("original generation"),
            )
            .expect("intent");
            assert_eq!(
                store.create_task_from_operation(&intent, &fresh).await,
                Err(AutomationError::TimerFenced)
            );
            let next_name = format!("optional.timer.{}", initial.writer_epoch + 1);
            let successor = attach_timer(
                &mut host,
                next.clone(),
                &next_name,
                Arc::clone(&quarantines),
            );
            let replay = ask(&successor, first.clone(), Fault::None)
                .await
                .expect("successor response")
                .expect("replay");
            assert_eq!(
                replay.disposition,
                DestinationApplyDisposition::AlreadyApplied
            );
            assert_eq!(
                next.list_tasks(10)
                    .await
                    .expect("no duplicate effects")
                    .len(),
                2
            );
            host.retire_optional(&next_name)
                .await
                .expect("close local route");
            next.close().await;
        }
        "crash-quiesced" => {
            assert_eq!(initial.phase, TimerPhase::Active);
            let draining = store.quiesce_timer().await.expect("durable quiesce");
            assert!(draining.can_handoff());
            assert_eq!(draining.writer_epoch, initial.writer_epoch);
            // No handoff, resume or normal host cleanup occurs after this cut.
            std::process::exit(CRASH_EXIT);
        }
        "crash-cutover" => {
            assert_eq!(initial.phase, TimerPhase::Active);
            assert!(store.quiesce_timer().await.expect("quiesce").can_handoff());
            host.retire_optional(&name)
                .await
                .expect("old route drained");
            let next = store
                .handoff_timer()
                .await
                .expect("committed successor epoch");
            let cutover = next.timer_status().await.expect("successor state");
            assert_eq!(cutover.phase, TimerPhase::Draining);
            assert_eq!(cutover.writer_epoch, initial.writer_epoch + 1);
            let fresh = new_draft("fenced even before successor publication");
            let intent = automation_task_operation_intent(
                store.owner_agent_id(),
                &fresh,
                Generation::new(1).expect("original generation"),
            )
            .expect("intent");
            assert_eq!(
                store.create_task_from_operation(&intent, &fresh).await,
                Err(AutomationError::TimerFenced)
            );
            // Deliberately lose the process after durable cutover but before
            // installing/resuming the successor. Recovery must not reset epoch.
            std::process::exit(CRASH_EXIT);
        }
        "recover-draining" => {
            assert_eq!(initial.phase, TimerPhase::Draining);
            assert!(initial.can_handoff());
            assert!(
                ask(
                    &client,
                    new_draft("must not bypass durable drain"),
                    Fault::None
                )
                .await
                .expect("draining service responded")
                .is_err()
            );
            assert!(
                store
                    .claim_due(40_000, initial.writer_epoch, 1_000)
                    .await
                    .expect("bounded scheduler read while draining")
                    .is_none()
            );
            for draft in [first.clone(), second.clone()] {
                let receipt = ask(&client, draft, Fault::None)
                    .await
                    .expect("recovery reply")
                    .expect("historical committed receipt remains readable");
                assert_eq!(
                    receipt.disposition,
                    DestinationApplyDisposition::AlreadyApplied
                );
            }
            assert_eq!(
                store
                    .list_tasks(10)
                    .await
                    .expect("exact retained tasks")
                    .len(),
                2
            );
            // Explicit trusted-host resume is distinct from merely reopening.
            // It preserves the committed writer epoch and operation identities.
            let resumed = store
                .resume_timer()
                .await
                .expect("explicit compatible resume");
            assert_eq!(resumed.phase, TimerPhase::Active);
            assert_eq!(resumed.writer_epoch, initial.writer_epoch);
            recovery_duration_us = Some(recovery_started.elapsed().as_micros());
            host.retire_optional(&name)
                .await
                .expect("close recovered local route");
        }
        "retire" => {
            assert!(store.quiesce_timer().await.expect("quiesce").can_handoff());
            host.retire_optional(&name).await.expect("drain route");
            assert_eq!(
                store
                    .retire_timer()
                    .await
                    .expect("durable retirement")
                    .phase,
                TimerPhase::Retired
            );
        }
        "reopen-retired" => {
            assert_eq!(initial.phase, TimerPhase::Retired);
            assert_eq!(
                ask(&client, new_draft("must not resurrect"), Fault::None)
                    .await
                    .expect("reply"),
                Err(AutomationError::TimerFenced)
            );
            assert_eq!(
                store.resume_timer().await,
                Err(AutomationError::TimerFenced)
            );
            let replay = ask(&client, first.clone(), Fault::None)
                .await
                .expect("historical reply")
                .expect("read-only receipt");
            assert_eq!(
                replay.disposition,
                DestinationApplyDisposition::AlreadyApplied
            );
            host.retire_optional(&name)
                .await
                .expect("unpublish fixture route");
        }
        _ => panic!("unknown subprocess stage"),
    }
    prove_siblings(&core).await;
    assert!(
        !stop.is_cancelled(),
        "optional lifecycle must not kill the required host"
    );
    let final_status = store.timer_status().await.expect("current durable state");
    let count = store.list_tasks(10).await.expect("task count").len();
    host.shutdown().await;
    store.close().await;
    let report = serde_json::json!({
        "stage": stage,
        "reopen_duration_us": reopen_duration_us,
        "recovery_duration_us": recovery_duration_us,
        "storage": owner_storage_sample(root),
        "leased_occurrences": final_status.leased_occurrences,
        "uncertain_dispatches": final_status.uncertain_dispatches,
        "writer_epoch": final_status.writer_epoch,
        "task_count": count,
        "retired": final_status.phase == TimerPhase::Retired,
        "required_services_responded": 40
    });
    std::fs::write(
        root.join("report.json"),
        serde_json::to_vec(&report).expect("report JSON"),
    )
    .expect("report file");
}

fn new_draft(prompt: &str) -> AutomationTaskDraft {
    AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        prompt,
        AutomationSchedule::Once,
        /*first_run_at_ms*/ 20_000,
        /*created_at_ms*/ 10_000,
    )
}

#[test]
#[ignore = "subprocess entrypoint; invoked by the parent regression with exact arguments"]
fn optional_module_process_entrypoint() {
    let root = std::env::var_os(ROOT_ENV).expect("parent's isolated root");
    let stage = std::env::var(STAGE_ENV).expect("parent's stage");
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("runtime")
        .block_on(worker(Path::new(&root), &stage));
}

struct ChildGuard(Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        // A test assertion or wait error must not leave an orphaned owner
        // process holding the SQLite pool beyond the isolated test lifetime.
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

fn owner_storage_sample(root: &Path) -> serde_json::Value {
    let mut pending = vec![root.join("fleet")];
    let mut inspected = 0_usize;
    let mut file_bytes = 0_u64;
    let mut sqlite_main_bytes = 0_u64;
    let mut sqlite_sidecar_bytes = 0_u64;
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(directory).expect("owner directory") {
            let entry = entry.expect("owner entry");
            inspected += 1;
            assert!(inspected <= 4096, "bounded fixture storage walk");
            let metadata = entry.metadata().expect("owner metadata");
            if metadata.is_dir() {
                pending.push(entry.path());
                continue;
            }
            assert!(
                metadata.is_file(),
                "fixture contains only directories and files"
            );
            file_bytes += metadata.len();
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.ends_with("-wal") || name.ends_with("-shm") || name.ends_with("-journal") {
                sqlite_sidecar_bytes += metadata.len();
                continue;
            }
            let mut header = [0; 16];
            let mut file = File::open(entry.path()).expect("owner file");
            match file.read_exact(&mut header) {
                Ok(()) if &header == b"SQLite format 3\0" => {
                    sqlite_main_bytes += metadata.len();
                }
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::UnexpectedEof => {}
                Err(error) => panic!("owner header read: {error}"),
            }
        }
    }
    serde_json::json!({
        "owner_file_bytes": file_bytes,
        "sqlite_main_bytes": sqlite_main_bytes,
        "sqlite_sidecar_bytes": sqlite_sidecar_bytes
    })
}

fn run_process(root: &Path, stage: &str, exit: i32) -> Option<serde_json::Value> {
    let started = Instant::now();
    let report = root.join("report.json");
    if report.exists() {
        std::fs::remove_file(&report).expect("remove stale report");
    }
    let log = root.join(format!("{stage}.log"));
    let output = File::create(&log).expect("log");
    let mut child = ChildGuard(
        Command::new(std::env::current_exe().expect("test executable"))
            .args([
                "--ignored",
                "--exact",
                "optional_module_process_entrypoint",
                "--nocapture",
            ])
            .env(ROOT_ENV, root)
            .env(STAGE_ENV, stage)
            .stdin(Stdio::null())
            .stdout(Stdio::from(output.try_clone().expect("stdout")))
            .stderr(Stdio::from(output))
            .spawn()
            .expect("real subprocess"),
    );
    let deadline = Instant::now() + Duration::from_secs(60);
    let status = loop {
        if let Some(status) = child.0.try_wait().expect("wait") {
            break status;
        }
        if Instant::now() >= deadline {
            panic!("optional module subprocess timed out: {stage}");
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    if status.code() != Some(exit) {
        let bytes = std::fs::read(&log).expect("failure log");
        panic!(
            "{stage}: {status}; {}",
            String::from_utf8_lossy(&bytes[..bytes.len().min(64 * 1024)])
        );
    }
    if exit == 0 {
        let bytes = std::fs::read(&report).expect("new stage report");
        let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("report");
        value["subprocess_wall_us"] = serde_json::json!(started.elapsed().as_micros());
        assert_eq!(value["stage"], stage);
        assert_eq!(value["required_services_responded"], 40);
        Some(value)
    } else {
        assert!(
            !report.exists(),
            "abrupt process loss cannot publish completion"
        );
        None
    }
}

#[test]
fn forty_first_service_survives_faults_replacement_retirement_and_real_process_restart() {
    let directory = tempfile::tempdir().expect("isolated owner");
    let root = directory.path().canonicalize().expect("canonical root");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let manifest = AgentManifest::new(
        AgentId::parse(AGENT).expect("agent"),
        WorkspaceBinding::new(workspace, &fleet).expect("binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    registry.register(manifest).expect("registered owner");
    for (file, prompt) in [
        ("first.json", "before optional failure"),
        ("second.json", "before process loss"),
    ] {
        std::fs::write(
            root.join(file),
            serde_json::to_vec(&new_draft(prompt)).expect("draft JSON"),
        )
        .expect("draft file");
    }
    let isolated = run_process(&root, "isolate", 0).expect("isolated");
    assert_eq!(isolated["task_count"], 1);
    assert!(run_process(&root, "crash", CRASH_EXIT).is_none());
    let mut replacement_samples = Vec::new();
    let mut recovery_samples = Vec::new();
    for epoch in 2..=5 {
        let result = run_process(&root, "replace", 0).expect("replaced");
        assert_eq!(result["writer_epoch"], epoch);
        assert_eq!(result["task_count"], 2);
        replacement_samples.push(result);
    }
    let crash_started = Instant::now();
    assert!(run_process(&root, "crash-quiesced", CRASH_EXIT).is_none());
    let quiesce_crash_wall_us = crash_started.elapsed().as_micros();
    let recovered = run_process(&root, "recover-draining", 0).expect("recover quiesce");
    assert_eq!(recovered["writer_epoch"], 5);
    assert_eq!(recovered["task_count"], 2);
    recovery_samples.push(serde_json::json!({
        "cut": "quiesced",
        "crash_wall_us": quiesce_crash_wall_us,
        "observation": recovered
    }));
    for epoch in 6..=9 {
        let crash_started = Instant::now();
        assert!(run_process(&root, "crash-cutover", CRASH_EXIT).is_none());
        let cutover_crash_wall_us = crash_started.elapsed().as_micros();
        let recovered = run_process(&root, "recover-draining", 0).expect("recover cutover");
        assert_eq!(recovered["writer_epoch"], epoch);
        assert_eq!(recovered["task_count"], 2);
        recovery_samples.push(serde_json::json!({
            "cut": "cutover",
            "crash_wall_us": cutover_crash_wall_us,
            "observation": recovered
        }));
    }
    let retired = run_process(&root, "retire", 0).expect("retired");
    assert_eq!(retired["writer_epoch"], 10);
    let recovered = run_process(&root, "reopen-retired", 0).expect("recovered retirement");
    assert_eq!(recovered["writer_epoch"], 10);
    assert_eq!(recovered["task_count"], 2);
    assert_eq!(recovered["retired"], true);
    let baseline = &replacement_samples[0]["storage"];
    let final_storage = &recovered["storage"];
    let sqlite_growth_bytes =
        i128::from(final_storage["sqlite_main_bytes"].as_u64().expect("bytes"))
            - i128::from(baseline["sqlite_main_bytes"].as_u64().expect("bytes"));
    let owner_file_growth_bytes =
        i128::from(final_storage["owner_file_bytes"].as_u64().expect("bytes"))
            - i128::from(baseline["owner_file_bytes"].as_u64().expect("bytes"));
    let task_count_growth = recovered["task_count"].as_i64().expect("task count")
        - replacement_samples[0]["task_count"]
            .as_i64()
            .expect("task count");
    let report = serde_json::json!({
        "fixture": "sqlite_owner_with_runtime_tasks_and_40_echo_siblings",
        "replacement_success_count": replacement_samples.len(),
        "recovery_success_count": recovery_samples.len(),
        "replacement_samples": replacement_samples,
        "recovery_samples": recovery_samples,
        "retirement": retired,
        "retired_reopen": recovered,
        "sqlite_main_growth_bytes": sqlite_growth_bytes,
        "owner_file_growth_bytes": owner_file_growth_bytes,
        "task_count_growth": task_count_growth
    });
    println!("{report}");
}
