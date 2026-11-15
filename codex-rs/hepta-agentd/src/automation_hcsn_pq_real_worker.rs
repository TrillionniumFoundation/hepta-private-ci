//! Explicit actual-worker acceptance through the schema 3 Agentd host.
//! Keys and external trust services are local fixtures. Responses are preserved;
//! this fixture does not manufacture ambiguous provider observations.

use std::process::Command;
use std::time::Instant;

use codex_hepta_automation::HcsnJobEvidenceV1;
use codex_hepta_automation::HcsnJobObservationV1;
use codex_hepta_automation::HcsnJobStateV1;
use codex_hepta_automation::HcsnProcessIdentityV1;
use codex_hepta_automation::HcsnProcessSupervisor;
use codex_hepta_automation::HcsnProcessSupervisorConfig;
use codex_hepta_automation::HcsnSupervisor;
use codex_hepta_automation::HcsnTaskFlowActionV1;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_contracts::FinalUseError;
use serde::Serialize;

use super::*;

#[path = "automation_hcsn_pq_real_recovery.rs"]
mod recovery;
#[path = "automation_hcsn_pq_real_support.rs"]
mod setup;

const ROOT_ENV: &str = "HEPTA_HCSN_PQ_WORKER_ROOT";
const PHASE_ENV: &str = "HEPTA_HCSN_PQ_WORKER_PHASE";
const TEST_NAME: &str =
    "automation_effect_host::hcsn_pq::tests::real_worker::pq_host_real_worker_cancel_cold_recovery";
const BOOT: &str = "/proc/sys/kernel/random/boot_id";

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct SupervisorInput {
    python_executable: PathBuf,
    python_sha256: Sha256Digest,
    repository_root: PathBuf,
    supervisor_sha256: Sha256Digest,
    durable_root: PathBuf,
}

impl SupervisorInput {
    fn config(&self) -> HcsnProcessSupervisorConfig {
        HcsnProcessSupervisorConfig {
            python_executable: self.python_executable.clone(),
            python_sha256: self.python_sha256.clone(),
            repository_root: self.repository_root.clone(),
            supervisor_sha256: self.supervisor_sha256.clone(),
            durable_root: self.durable_root.clone(),
            deadline: Duration::from_secs(10),
        }
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Effect {
    intent: AuthorizedEffectIntent,
    signed: SignedFinalUseGrant,
}

impl Effect {
    fn command(&self) -> String {
        format!("{}-dispatch", self.intent.run_id)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Dispatches {
    start: Effect,
    cancel: Effect,
    parent_pid: u32,
    host_config_sha256: Sha256Digest,
    supervisor_config_sha256: Sha256Digest,
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

fn file_sha(path: &Path) -> anyhow::Result<Sha256Digest> {
    Ok(Sha256Digest::for_bytes(&fs::read(path)?))
}

fn live_incarnation(
    stat: &str,
    boot: &str,
    process: &HcsnProcessIdentityV1,
) -> anyhow::Result<bool> {
    let (_, tail) = stat
        .rsplit_once(')')
        .ok_or_else(|| anyhow::anyhow!("malformed kernel process stat"))?;
    let fields: Vec<_> = tail.split_whitespace().collect();
    anyhow::ensure!(fields.len() > 19, "incomplete kernel process stat");
    let pid = stat
        .split_whitespace()
        .next()
        .ok_or_else(|| anyhow::anyhow!("missing kernel PID"))?
        .parse::<u64>()?;
    let birth = [boot.as_bytes(), b"\0", fields[19].as_bytes()].concat();
    Ok(pid == process.process_id
        && Sha256Digest::for_bytes(&birth) == process.incarnation
        && !matches!(fields[0], "Z" | "X"))
}

#[tokio::test]
#[ignore = "requires a fresh Linux CPU fixture from verify_pq_host; invokes and cancels an actual worker"]
async fn pq_host_real_worker_cancel_cold_recovery() -> anyhow::Result<()> {
    let root =
        PathBuf::from(std::env::var_os(ROOT_ENV).expect("explicit real PQ host fixture root"));
    anyhow::ensure!(
        root.is_absolute() && root.canonicalize()? == root,
        "canonical fixture root required"
    );
    let config_bytes = fs::read(root.join("supervisor-config.json"))?;
    let input: SupervisorInput = serde_json::from_slice(&config_bytes)?;
    anyhow::ensure!(
        input.durable_root == root.join("supervisor-store"),
        "fresh attempt store only"
    );
    let payload = fs::read(root.join("request.json"))?;
    match std::env::var(PHASE_ENV).as_deref() {
        Ok("recover") => recovery::recover(&root, &input, &config_bytes, &payload).await,
        Err(std::env::VarError::NotPresent) => {
            dispatch(&root, &input, &config_bytes, &payload).await
        }
        other => anyhow::bail!("unexpected PQ worker phase: {other:?}"),
    }
}

async fn dispatch(
    root: &Path,
    input: &SupervisorInput,
    config_bytes: &[u8],
    payload: &[u8],
) -> anyhow::Result<()> {
    for namespace in ["jobs", "cancellations"] {
        assert_eq!(fs::read_dir(input.durable_root.join(namespace))?.count(), 0);
    }
    let owner = root.join("agent-owner");
    fs::create_dir(&owner)?;
    let identity = setup::identity(&owner, /*initialize*/ true)?;
    let services = setup::install(root, input)?;
    let config_path = root.join("pq-host-config.json");
    let host = AgentdAutomationEffectHost::open(&identity, &config_path)?;
    assert_eq!(
        host.authority.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    let store = AutomationStore::open(&identity.layout).await?;
    let start = setup::prepare(
        &store,
        &identity,
        "pq-real-start",
        payload,
        HcsnTaskFlowActionV1::Start,
    )
    .await?;
    let target = HcsnJobIdentityV1::for_taskflow(
        SCOPE,
        &start.intent.run_id,
        &start.intent.step_id,
        start.intent.payload_digest.clone(),
    )?;
    let cancel_payload = serde_json::to_vec(&target)?;
    setup::write_new(&root.join("cancel-request.json"), &target)?;
    let cancel = setup::prepare(
        &store,
        &identity,
        "pq-real-cancel",
        &cancel_payload,
        HcsnTaskFlowActionV1::Cancel,
    )
    .await?;
    let records = Dispatches {
        start,
        cancel,
        parent_pid: std::process::id(),
        host_config_sha256: file_sha(&config_path)?,
        supervisor_config_sha256: Sha256Digest::for_bytes(config_bytes),
    };
    setup::write_new(&root.join("pq-dispatches.json"), &records)?;
    let mut invalid = records.start.signed.clone();
    invalid.signature[0] ^= 1;
    assert!(
        host.execute(
            &store,
            &records.start.intent,
            payload,
            &invalid,
            &records.start.command(),
            NOW
        )
        .await
        .is_err()
    );
    assert!(
        host.execute(
            &store,
            &records.cancel.intent,
            &cancel_payload,
            &records.start.signed,
            &records.cancel.command(),
            NOW
        )
        .await
        .is_err()
    );
    assert!(
        host.execute(
            &store,
            &records.cancel.intent,
            b"substituted target",
            &records.cancel.signed,
            &records.cancel.command(),
            NOW
        )
        .await
        .is_err()
    );
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert!(
        store
            .pending_authorized_taskflow_effects(8)
            .await?
            .is_empty()
    );
    for namespace in ["jobs", "cancellations"] {
        assert_eq!(fs::read_dir(input.durable_root.join(namespace))?.count(), 0);
    }
    let started = host
        .execute(
            &store,
            &records.start.intent,
            payload,
            &records.start.signed,
            &records.start.command(),
            NOW,
        )
        .await?;
    assert_eq!(
        started.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let command =
        HcsnSupervisorCommandV1::start(target.clone(), String::from_utf8(payload.to_vec())?)?;
    let mut supervisor = HcsnProcessSupervisor::new(input.config())?;
    let deadline = Instant::now() + Duration::from_secs(60);
    let observation = loop {
        let observed = supervisor.exchange(&command.status())?;
        match observed.state {
            HcsnJobStateV1::Running => break observed,
            HcsnJobStateV1::Reserved | HcsnJobStateV1::Unknown => {
                anyhow::ensure!(
                    Instant::now() < deadline,
                    "worker never observed live; preserve attempt"
                );
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
            state => {
                anyhow::bail!("worker reached {state:?} before cancellation; no termination credit")
            }
        }
    };
    let process = observation.process.as_ref().expect("running worker");
    let job = input
        .durable_root
        .join("jobs")
        .join(Sha256Digest::for_bytes(target.key.as_str().as_bytes()).as_str());
    assert_eq!(
        serde_json::from_slice::<HcsnProcessIdentityV1>(&fs::read(job.join("worker.json"))?)?,
        *process
    );
    assert_eq!(process.host_id, file_sha(Path::new("/etc/machine-id"))?);
    let boot_id = fs::read_to_string(BOOT)?;
    let proc_stat = fs::read_to_string(format!("/proc/{}/stat", process.process_id))?;
    assert!(live_incarnation(&proc_stat, &boot_id, process)?);
    setup::write_new(
        &root.join("pq-running.json"),
        &Running {
            runner_sha256: file_sha(&job.join("runner.json"))?,
            worker_sha256: file_sha(&job.join("worker.json"))?,
            observation,
            boot_id,
            proc_stat,
        },
    )?;
    let cancelled = host
        .execute(
            &store,
            &records.cancel.intent,
            &cancel_payload,
            &records.cancel.signed,
            &records.cancel.command(),
            NOW,
        )
        .await?;
    assert!(matches!(
        cancelled.observation,
        Some(TaskFlowStepObservation::Indeterminate | TaskFlowStepObservation::Succeeded)
    ));
    setup::write_new(
        &root.join("pq-initial-receipts.json"),
        &[started, cancelled],
    )?;
    assert_eq!(host.authority.capacity()?.used_nonces, 2);
    store.close().await;
    drop(store);
    drop(host);
    let child = Command::new(std::env::current_exe()?)
        .args(["--ignored", "--exact", TEST_NAME, "--nocapture"])
        .env(PHASE_ENV, "recover")
        .output()?;
    setup::write_new(
        &root.join("pq-host-child.json"),
        &serde_json::json!({ "success": child.status.success(),
        "stdout": String::from_utf8_lossy(&child.stdout), "stderr": String::from_utf8_lossy(&child.stderr) }),
    )?;
    anyhow::ensure!(
        child.status.success(),
        "cold PQ host failed: {}",
        String::from_utf8_lossy(&child.stderr)
    );
    let result: Value = serde_json::from_slice(&fs::read(root.join("pq-host.json"))?)?;
    assert_eq!(result["status"], "passed");
    setup::write_new(
        &root.join("pq-service-requests.json"),
        &serde_json::json!({
        "clock": services.clock.requests.load(Ordering::SeqCst), "frontier": services.frontier.requests.load(Ordering::SeqCst),
        "fixture_only": true, "independent_custody_proven": false }),
    )?;
    Ok(())
}
