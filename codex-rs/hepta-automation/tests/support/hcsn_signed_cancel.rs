//! Signed cancellation of an observed real worker, followed by cold reconciliation.
//! Only the authority key and discarded replies are synthetic. No process signal
//! is issued by this fixture; the authorized supervisor owns termination.

use super::*;

#[path = "hcsn_signed_cancel_recovery.rs"]
mod recovery;
use codex_hepta_automation::HcsnJobEvidenceV1;
use codex_hepta_automation::HcsnJobObservationV1;
use codex_hepta_automation::HcsnProcessIdentityV1;
use codex_hepta_automation::TaskFlowStepReceipt;
use pretty_assertions::assert_eq;

const NAME: &str = "signed_authority_real_worker_cancel_cold_recovery";
const COMMAND: &str = "signed-cancellation-dispatch";
const BOOT: &str = "/proc/sys/kernel/random/boot_id";

fn dispatch_command(record: &DispatchRecord) -> String {
    format!("{COMMAND}-{}", record.intent.run_id)
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Dispatches {
    start: DispatchRecord,
    cancel: DispatchRecord,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Running {
    observation: HcsnJobObservationV1,
    runner_sha256: Sha256Digest,
    worker_sha256: Sha256Digest,
    boot_id: String,
    proc_stat: String,
}

fn driver(config: &HcsnProcessSupervisorConfig, action: HcsnTaskFlowActionV1) -> LostReply {
    LostReply {
        real: HcsnTaskFlowDriver::new(
            SCOPE.to_string(),
            action,
            HcsnProcessSupervisor::new(config.clone()).expect("pinned supervisor"),
        )
        .expect("action driver"),
        contacts: 0,
    }
}

async fn execute(
    store: &AutomationStore,
    fixture: &Fixture,
    driver: &mut LostReply,
    record: &DispatchRecord,
    payload: &[u8],
    signed: &SignedFinalUseGrant,
) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
    store
        .execute_authorized_taskflow_effect(
            &fixture.authority,
            driver,
            &record.intent,
            payload,
            &fixture.owner,
            signed,
            &record.intent.final_use_binding().expect("binding"),
            &dispatch_command(record),
            now_ms(),
        )
        .await
}

// An independent /proc observation: reusing the PID cannot impersonate the
// original worker because its boot identity and kernel start ticks are bound.
fn live_incarnation(stat: &str, boot: &str, process: &HcsnProcessIdentityV1) -> bool {
    let fields: Vec<_> = stat
        .rsplit_once(')')
        .expect("kernel stat comm")
        .1
        .split_whitespace()
        .collect();
    let birth = [boot.as_bytes(), b"\0", fields[19].as_bytes()].concat();
    stat.split_whitespace()
        .next()
        .expect("kernel PID")
        .parse::<u64>()
        .expect("numeric kernel PID")
        == process.process_id
        && Sha256Digest::for_bytes(&birth) == process.incarnation
        && !matches!(fields[0], "Z" | "X")
}

pub(super) async fn run(
    root: &Path,
    config: &HcsnProcessSupervisorConfig,
    config_bytes: &[u8],
    payload: &[u8],
) {
    match std::env::var(PHASE_ENV).as_deref() {
        Ok("cancel-recover") => recovery::recover(root, config, config_bytes, payload).await,
        Err(std::env::VarError::NotPresent) => dispatch(root, config, config_bytes, payload).await,
        other => panic!("unexpected cancellation phase: {other:?}"),
    }
}

async fn dispatch(
    root: &Path,
    config: &HcsnProcessSupervisorConfig,
    config_bytes: &[u8],
    payload: &[u8],
) {
    for name in ["jobs", "cancellations"] {
        assert_eq!(
            fs::read_dir(config.durable_root.join(name))
                .expect("fresh namespace")
                .count(),
            0
        );
    }
    let state = root.join("signed-cancel-state");
    let fixture = Fixture::initialize(&state);
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let intent = fixture.prepare(&store, payload).await;
    let start = DispatchRecord {
        signed: fixture.sign(&intent),
        intent,
        payload_sha256: Sha256Digest::for_bytes(payload),
        config_sha256: Sha256Digest::for_bytes(config_bytes),
        parent_pid: std::process::id(),
    };
    let target = HcsnJobIdentityV1::for_taskflow(
        SCOPE,
        &start.intent.run_id,
        &start.intent.step_id,
        start.intent.payload_digest.clone(),
    )
    .expect("original worker identity");
    let cancel_payload = serde_json::to_vec(&target).expect("exact cancellation payload");
    write_new(&root.join("cancel-request.json"), &target);
    let intent = fixture
        .prepare_action(
            &store,
            &cancel_payload,
            "hcsn-signed-cancel-run",
            HcsnTaskFlowActionV1::Cancel,
        )
        .await;
    let cancel = DispatchRecord {
        signed: fixture.sign_named(&intent, "synthetic-real-worker-cancel-grant"),
        intent,
        payload_sha256: Sha256Digest::for_bytes(&cancel_payload),
        config_sha256: Sha256Digest::for_bytes(config_bytes),
        parent_pid: std::process::id(),
    };
    let records = Dispatches { start, cancel };
    write_new(&state.join("dispatches.json"), &records);
    let mut cancellation = driver(config, HcsnTaskFlowActionV1::Cancel);
    let mut invalid = records.cancel.signed.clone();
    invalid.signature[0] ^= 1;
    assert!(matches!(
        execute(
            &store,
            &fixture,
            &mut cancellation,
            &records.cancel,
            &cancel_payload,
            &invalid
        )
        .await,
        Err(AuthorizedEffectError::FinalUse(
            FinalUseError::InvalidSignature
        ))
    ));
    assert!(matches!(
        execute(
            &store,
            &fixture,
            &mut cancellation,
            &records.cancel,
            b"substituted target",
            &records.cancel.signed
        )
        .await,
        Err(AuthorizedEffectError::BindingMismatch)
    ));
    assert!(matches!(
        execute(
            &store,
            &fixture,
            &mut cancellation,
            &records.cancel,
            &cancel_payload,
            &records.start.signed
        )
        .await,
        Err(AuthorizedEffectError::FinalUse(
            FinalUseError::BindingMismatch
        ))
    ));
    assert_eq!(cancellation.contacts, 0);
    assert_eq!(
        fixture
            .authority
            .capacity()
            .expect("unspent grants")
            .used_nonces,
        0
    );
    assert_eq!(
        fs::read_dir(config.durable_root.join("cancellations"))
            .expect("no cancellation")
            .count(),
        0
    );
    let mut training = driver(config, HcsnTaskFlowActionV1::Start);
    let started = execute(
        &store,
        &fixture,
        &mut training,
        &records.start,
        payload,
        &records.start.signed,
    )
    .await
    .expect("signed start");
    assert_eq!(
        started.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(training.contacts, 1);
    let command = HcsnSupervisorCommandV1::start(
        target.clone(),
        String::from_utf8(payload.to_vec()).expect("UTF-8"),
    )
    .expect("start command");
    let mut supervisor = HcsnProcessSupervisor::new(config.clone()).expect("observing supervisor");
    let deadline = Instant::now() + Duration::from_secs(60);
    let observation = loop {
        let observation = supervisor.exchange(&command.status()).expect("status");
        match observation.state {
            HcsnJobStateV1::Running => break observation,
            HcsnJobStateV1::Reserved | HcsnJobStateV1::Unknown => {
                assert!(
                    Instant::now() < deadline,
                    "worker not observed running; keep this attempt"
                );
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
            state => panic!("worker reached {state:?} before cancellation; no termination credit"),
        }
    };
    let process = observation.process.as_ref().expect("running worker");
    let job = config
        .durable_root
        .join("jobs")
        .join(Sha256Digest::for_bytes(target.key.as_str().as_bytes()).as_str());
    let worker = fs::read(job.join("worker.json")).expect("worker identity");
    assert_eq!(
        serde_json::from_slice::<HcsnProcessIdentityV1>(&worker).expect("worker record"),
        *process
    );
    let boot_id = fs::read_to_string(BOOT).expect("boot identity");
    let proc_stat = fs::read_to_string(format!("/proc/{}/stat", process.process_id))
        .expect("live kernel process");
    assert!(live_incarnation(&proc_stat, &boot_id, process));
    write_new(
        &state.join("running.json"),
        &Running {
            runner_sha256: Sha256Digest::for_bytes(
                &fs::read(job.join("runner.json")).expect("runner"),
            ),
            worker_sha256: Sha256Digest::for_bytes(&worker),
            observation,
            boot_id,
            proc_stat,
        },
    );
    let cancelled = execute(
        &store,
        &fixture,
        &mut cancellation,
        &records.cancel,
        &cancel_payload,
        &records.cancel.signed,
    )
    .await
    .expect("signed cancellation");
    assert_eq!(
        cancelled.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(cancellation.contacts, 1);
    assert_eq!(
        fixture
            .authority
            .capacity()
            .expect("distinct spent nonces")
            .used_nonces,
        2
    );
    store.close().await;
    drop(store);
    drop(fixture);
    let child = Command::new(std::env::current_exe().expect("native test executable"))
        .args(["--ignored", "--exact", NAME, "--nocapture"])
        .env(PHASE_ENV, "cancel-recover")
        .output()
        .expect("fresh cancellation recovery process");
    write_new(
        &root.join("signed-cancel-child.json"),
        &serde_json::json!({
            "success": child.status.success(), "stdout": String::from_utf8_lossy(&child.stdout),
            "stderr": String::from_utf8_lossy(&child.stderr),
        }),
    );
    assert!(
        child.status.success(),
        "cold cancel recovery failed: {}",
        String::from_utf8_lossy(&child.stderr)
    );
    let result: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("signed-cancel.json")).expect("evidence"))
            .expect("JSON");
    assert_eq!(result["status"], "passed");
}
