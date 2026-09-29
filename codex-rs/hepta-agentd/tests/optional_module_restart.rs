//! A real optional service on the SAME RuntimeTasks used by Agentd, backed by
//! AutomationStore, exercised in separate OS processes. Forty required echo
//! services represent sibling liveness; these are not forty real Codex sessions.
//! No provider, physical effect, independent evaluator, cross-schema migration
//! or deployed-host performance claim is made by this fixture.
use std::fs::File;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::RuntimeTasks;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationOperationReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::TimerPhase;
use codex_hepta_automation::automation_task_operation_intent;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_operations::DestinationApplyDisposition;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
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
        Generation::new(1)
            .unwrap_or_else(|error| panic!("stable original operation generation: {error:?}")),
    )
    .unwrap_or_else(|error| panic!("exact task intent: {error:?}"));
    let result = store
        .create_task_from_operation(&intent, &request.draft)
        .await;
    match request.fault {
        Fault::None => {
            let _ = request.reply.send(result);
        }
        Fault::PanicAfterCommit => {
            result.unwrap_or_else(|error| {
                panic!("effect must commit before injected task panic: {error:?}")
            });
            panic!("optional module panic after durable commit, before acknowledgement");
        }
        Fault::ProcessLossAfterCommit => {
            result.unwrap_or_else(|error| {
                panic!("effect must commit before injected process loss: {error:?}")
            });
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
    .unwrap_or_else(|error| panic!("same public host extension point: {error:?}"));
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
    .unwrap_or_else(|error| panic!("admission: {error:?}"));
    timeout(Duration::from_secs(10), result)
        .await
        .unwrap_or_else(|error| panic!("bounded reply: {error:?}"))
}

async fn prove_siblings(clients: &[mpsc::Sender<CoreRequest>]) {
    for (index, client) in clients.iter().enumerate() {
        let (reply, response) = oneshot::channel();
        client
            .send((index as u64, reply))
            .await
            .unwrap_or_else(|error| panic!("core admission: {error:?}"));
        let value = timeout(Duration::from_secs(2), response)
            .await
            .unwrap_or_else(|error| panic!("core live: {error:?}"))
            .unwrap_or_else(|error| panic!("core reply: {error:?}"));
        assert_eq!(value, index as u64 + 1);
    }
}

fn load_draft(root: &Path, file: &str) -> AutomationTaskDraft {
    let bytes =
        std::fs::read(root.join(file)).unwrap_or_else(|error| panic!("draft file: {error:?}"));
    serde_json::from_slice(&bytes).unwrap_or_else(|error| panic!("draft JSON: {error:?}"))
}

async fn worker(root: &Path, stage: &str) {
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))
        .unwrap_or_else(|error| panic!("fleet: {error:?}"));
    let layout = fleet
        .layout()
        .agent(&AgentId::parse(AGENT).unwrap_or_else(|error| panic!("agent: {error:?}")));
    let store = AutomationStore::open(&layout)
        .await
        .unwrap_or_else(|error| panic!("real SQLite reopen: {error:?}"));
    let first = load_draft(root, "first.json");
    let second = load_draft(root, "second.json");
    let initial = store
        .timer_status()
        .await
        .unwrap_or_else(|error| panic!("durable epoch: {error:?}"));
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_secs(2))
        .unwrap_or_else(|error| panic!("host: {error:?}"));
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
        .unwrap_or_else(|error| panic!("required service: {error:?}"));
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
                .unwrap_or_else(|error| panic!("observe panic: {error:?}"))
                .unwrap_or_else(|error| panic!("isolated: {error:?}"));
            assert_eq!(quarantines.load(Ordering::SeqCst), 1);
            assert_eq!(host.active_count(), 40);
            assert!(!stop.is_cancelled());
            let tasks = store
                .list_tasks(10)
                .await
                .unwrap_or_else(|error| panic!("committed despite ACK loss: {error:?}"));
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
                    .unwrap_or_else(|error| panic!("reply: {error:?}"))
                    .unwrap_or_else(|error| panic!("reconcile committed task: {error:?}"));
                assert_eq!(
                    receipt.disposition,
                    DestinationApplyDisposition::AlreadyApplied
                );
            }
            assert!(
                store
                    .quiesce_timer()
                    .await
                    .unwrap_or_else(|error| panic!("quiesce: {error:?}"))
                    .can_handoff()
            );
            host.retire_optional(&name)
                .await
                .unwrap_or_else(|error| panic!("drain optional task: {error:?}"));
            assert!(client.is_closed());
            let next = store
                .handoff_timer()
                .await
                .unwrap_or_else(|error| panic!("durable writer handoff: {error:?}"));
            assert_eq!(
                next.timer_status()
                    .await
                    .unwrap_or_else(|error| panic!("next status: {error:?}"))
                    .writer_epoch,
                initial.writer_epoch + 1
            );
            next.resume_timer()
                .await
                .unwrap_or_else(|error| panic!("publish compatible successor: {error:?}"));
            let fresh = new_draft("stale writer cannot create a new effect");
            let intent = automation_task_operation_intent(
                store.owner_agent_id(),
                &fresh,
                Generation::new(1).unwrap_or_else(|error| panic!("original generation: {error:?}")),
            )
            .unwrap_or_else(|error| panic!("intent: {error:?}"));
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
                .unwrap_or_else(|error| panic!("successor response: {error:?}"))
                .unwrap_or_else(|error| panic!("replay: {error:?}"));
            assert_eq!(
                replay.disposition,
                DestinationApplyDisposition::AlreadyApplied
            );
            assert_eq!(
                next.list_tasks(10)
                    .await
                    .unwrap_or_else(|error| panic!("no duplicate effects: {error:?}"))
                    .len(),
                2
            );
            host.retire_optional(&next_name)
                .await
                .unwrap_or_else(|error| panic!("close local route: {error:?}"));
            next.close().await;
        }
        "crash-quiesced" => {
            assert_eq!(initial.phase, TimerPhase::Active);
            let draining = store
                .quiesce_timer()
                .await
                .unwrap_or_else(|error| panic!("durable quiesce: {error:?}"));
            assert!(draining.can_handoff());
            assert_eq!(draining.writer_epoch, initial.writer_epoch);
            // No handoff, resume or normal host cleanup occurs after this cut.
            std::process::exit(CRASH_EXIT);
        }
        "crash-cutover" => {
            assert_eq!(initial.phase, TimerPhase::Active);
            assert!(
                store
                    .quiesce_timer()
                    .await
                    .unwrap_or_else(|error| panic!("quiesce: {error:?}"))
                    .can_handoff()
            );
            host.retire_optional(&name)
                .await
                .unwrap_or_else(|error| panic!("old route drained: {error:?}"));
            let next = store
                .handoff_timer()
                .await
                .unwrap_or_else(|error| panic!("committed successor epoch: {error:?}"));
            let cutover = next
                .timer_status()
                .await
                .unwrap_or_else(|error| panic!("successor state: {error:?}"));
            assert_eq!(cutover.phase, TimerPhase::Draining);
            assert_eq!(cutover.writer_epoch, initial.writer_epoch + 1);
            let fresh = new_draft("fenced even before successor publication");
            let intent = automation_task_operation_intent(
                store.owner_agent_id(),
                &fresh,
                Generation::new(1).unwrap_or_else(|error| panic!("original generation: {error:?}")),
            )
            .unwrap_or_else(|error| panic!("intent: {error:?}"));
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
                .unwrap_or_else(|error| panic!("draining service responded: {error:?}"))
                .is_err()
            );
            assert!(
                store
                    .claim_due(40_000, initial.writer_epoch, 1_000)
                    .await
                    .unwrap_or_else(|error| panic!(
                        "bounded scheduler read while draining: {error:?}"
                    ))
                    .is_none()
            );
            for draft in [first.clone(), second.clone()] {
                let receipt = ask(&client, draft, Fault::None)
                    .await
                    .unwrap_or_else(|error| panic!("recovery reply: {error:?}"))
                    .unwrap_or_else(|error| {
                        panic!("historical committed receipt remains readable: {error:?}")
                    });
                assert_eq!(
                    receipt.disposition,
                    DestinationApplyDisposition::AlreadyApplied
                );
            }
            assert_eq!(
                store
                    .list_tasks(10)
                    .await
                    .unwrap_or_else(|error| panic!("exact retained tasks: {error:?}"))
                    .len(),
                2
            );
            // Explicit trusted-host resume is distinct from merely reopening.
            // It preserves the committed writer epoch and operation identities.
            let resumed = store
                .resume_timer()
                .await
                .unwrap_or_else(|error| panic!("explicit compatible resume: {error:?}"));
            assert_eq!(resumed.phase, TimerPhase::Active);
            assert_eq!(resumed.writer_epoch, initial.writer_epoch);
            host.retire_optional(&name)
                .await
                .unwrap_or_else(|error| panic!("close recovered local route: {error:?}"));
        }
        "retire" => {
            assert!(
                store
                    .quiesce_timer()
                    .await
                    .unwrap_or_else(|error| panic!("quiesce: {error:?}"))
                    .can_handoff()
            );
            host.retire_optional(&name)
                .await
                .unwrap_or_else(|error| panic!("drain route: {error:?}"));
            assert_eq!(
                store
                    .retire_timer()
                    .await
                    .unwrap_or_else(|error| panic!("durable retirement: {error:?}"))
                    .phase,
                TimerPhase::Retired
            );
        }
        "reopen-retired" => {
            assert_eq!(initial.phase, TimerPhase::Retired);
            assert_eq!(
                ask(&client, new_draft("must not resurrect"), Fault::None)
                    .await
                    .unwrap_or_else(|error| panic!("reply: {error:?}")),
                Err(AutomationError::TimerFenced)
            );
            assert_eq!(
                store.resume_timer().await,
                Err(AutomationError::TimerFenced)
            );
            let replay = ask(&client, first.clone(), Fault::None)
                .await
                .unwrap_or_else(|error| panic!("historical reply: {error:?}"))
                .unwrap_or_else(|error| panic!("read-only receipt: {error:?}"));
            assert_eq!(
                replay.disposition,
                DestinationApplyDisposition::AlreadyApplied
            );
            host.retire_optional(&name)
                .await
                .unwrap_or_else(|error| panic!("unpublish fixture route: {error:?}"));
        }
        _ => panic!("unknown subprocess stage"),
    }
    prove_siblings(&core).await;
    assert!(
        !stop.is_cancelled(),
        "optional lifecycle must not kill the required host"
    );
    let final_status = store
        .timer_status()
        .await
        .unwrap_or_else(|error| panic!("current durable state: {error:?}"));
    let count = store
        .list_tasks(10)
        .await
        .unwrap_or_else(|error| panic!("task count: {error:?}"))
        .len();
    host.shutdown().await;
    store.close().await;
    let report = serde_json::json!({
        "stage": stage,
        "writer_epoch": final_status.writer_epoch,
        "task_count": count,
        "retired": final_status.phase == TimerPhase::Retired,
        "required_services_responded": 40
    });
    std::fs::write(
        root.join("report.json"),
        serde_json::to_vec(&report).unwrap_or_else(|error| panic!("report JSON: {error:?}")),
    )
    .unwrap_or_else(|error| panic!("report file: {error:?}"));
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
    let root = std::env::var_os(ROOT_ENV).unwrap_or_else(|| panic!("missing parent isolated root"));
    let stage =
        std::env::var(STAGE_ENV).unwrap_or_else(|error| panic!("parent's stage: {error:?}"));
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .unwrap_or_else(|error| panic!("runtime: {error:?}"))
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

fn run_process(root: &Path, stage: &str, exit: i32) -> Option<serde_json::Value> {
    let report = root.join("report.json");
    if report.exists() {
        std::fs::remove_file(&report)
            .unwrap_or_else(|error| panic!("remove stale report: {error:?}"));
    }
    let log = root.join(format!("{stage}.log"));
    let output = File::create(&log).unwrap_or_else(|error| panic!("log: {error:?}"));
    let mut child = ChildGuard(
        Command::new(
            std::env::current_exe().unwrap_or_else(|error| panic!("test executable: {error:?}")),
        )
        .args([
            "--ignored",
            "--exact",
            "optional_module_process_entrypoint",
            "--nocapture",
        ])
        .env(ROOT_ENV, root)
        .env(STAGE_ENV, stage)
        .stdin(Stdio::null())
        .stdout(Stdio::from(
            output
                .try_clone()
                .unwrap_or_else(|error| panic!("stdout: {error:?}")),
        ))
        .stderr(Stdio::from(output))
        .spawn()
        .unwrap_or_else(|error| panic!("real subprocess: {error:?}")),
    );
    let deadline = Instant::now() + Duration::from_secs(60);
    let status = loop {
        if let Some(status) = child
            .0
            .try_wait()
            .unwrap_or_else(|error| panic!("wait: {error:?}"))
        {
            break status;
        }
        if Instant::now() >= deadline {
            panic!("optional module subprocess timed out: {stage}");
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    if status.code() != Some(exit) {
        let bytes = std::fs::read(&log).unwrap_or_else(|error| panic!("failure log: {error:?}"));
        panic!(
            "{stage}: {status}; {}",
            String::from_utf8_lossy(&bytes[..bytes.len().min(64 * 1024)])
        );
    }
    if exit == 0 {
        let bytes =
            std::fs::read(&report).unwrap_or_else(|error| panic!("new stage report: {error:?}"));
        let value: serde_json::Value =
            serde_json::from_slice(&bytes).unwrap_or_else(|error| panic!("report: {error:?}"));
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
    let directory = tempfile::tempdir().unwrap_or_else(|error| panic!("isolated owner: {error:?}"));
    let root = directory
        .path()
        .canonicalize()
        .unwrap_or_else(|error| panic!("canonical root: {error:?}"));
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))
        .unwrap_or_else(|error| panic!("fleet: {error:?}"));
    let registry = FleetRegistry::initialize(fleet.clone())
        .unwrap_or_else(|error| panic!("registry: {error:?}"));
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap_or_else(|error| panic!("workspace: {error:?}"));
    let manifest = AgentManifest::new(
        AgentId::parse(AGENT).unwrap_or_else(|error| panic!("agent: {error:?}")),
        WorkspaceBinding::new(workspace, &fleet)
            .unwrap_or_else(|error| panic!("binding: {error:?}")),
        ResourceBudget::local_default(),
    )
    .unwrap_or_else(|error| panic!("manifest: {error:?}"));
    registry
        .register(manifest)
        .unwrap_or_else(|error| panic!("registered owner: {error:?}"));
    for (file, prompt) in [
        ("first.json", "before optional failure"),
        ("second.json", "before process loss"),
    ] {
        std::fs::write(
            root.join(file),
            serde_json::to_vec(&new_draft(prompt))
                .unwrap_or_else(|error| panic!("draft JSON: {error:?}")),
        )
        .unwrap_or_else(|error| panic!("draft file: {error:?}"));
    }
    let isolated =
        run_process(&root, "isolate", 0).unwrap_or_else(|| panic!("missing isolated report"));
    assert_eq!(isolated["task_count"], 1);
    assert!(run_process(&root, "crash", CRASH_EXIT).is_none());
    for epoch in 2..=5 {
        let result =
            run_process(&root, "replace", 0).unwrap_or_else(|| panic!("missing replaced report"));
        assert_eq!(result["writer_epoch"], epoch);
        assert_eq!(result["task_count"], 2);
    }
    assert!(run_process(&root, "crash-quiesced", CRASH_EXIT).is_none());
    let recovered = run_process(&root, "recover-draining", 0)
        .unwrap_or_else(|| panic!("missing recover quiesce report"));
    assert_eq!(recovered["writer_epoch"], 5);
    assert_eq!(recovered["task_count"], 2);
    for epoch in 6..=9 {
        assert!(run_process(&root, "crash-cutover", CRASH_EXIT).is_none());
        let recovered = run_process(&root, "recover-draining", 0)
            .unwrap_or_else(|| panic!("missing recover cutover report"));
        assert_eq!(recovered["writer_epoch"], epoch);
        assert_eq!(recovered["task_count"], 2);
    }
    let retired =
        run_process(&root, "retire", 0).unwrap_or_else(|| panic!("missing retired report"));
    assert_eq!(retired["writer_epoch"], 10);
    let recovered = run_process(&root, "reopen-retired", 0)
        .unwrap_or_else(|| panic!("missing recovered retirement report"));
    assert_eq!(recovered["writer_epoch"], 10);
    assert_eq!(recovered["task_count"], 2);
    assert_eq!(recovered["retired"], true);
}
