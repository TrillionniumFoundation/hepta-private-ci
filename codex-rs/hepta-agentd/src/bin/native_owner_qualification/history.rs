//! Isolated VM-crash qualification only; no cross-boot writer or issuer handoff.
use super::common::*;
use codex_hepta_agentd::AgentdHos2Device;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::*;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Case {
    Complete,
    CrashAfterApplied,
    Historical,
}

pub fn requested_case() -> Result<Case> {
    let path = Path::new("/.hepta-native-case.json");
    if !path.exists() {
        return Ok(Case::Complete);
    }
    let mode = read_json(path, 0)?;
    anyhow::ensure!(
        mode != Case::Historical,
        "historical mode needs the retained original disk"
    );
    Ok(mode)
}

pub fn publish_case(mode: Case) -> Result<()> {
    let path = Path::new(RUN).join("case.json");
    let pending = Path::new(RUN).join(".case-pending");
    write_json(&pending, &mode, 0o440)?;
    chown(&pending, 0, 60002)?;
    std::fs::rename(pending, path)?;
    std::fs::File::open(RUN)?.sync_all()?;
    Ok(())
}

pub fn read_case() -> Result<Case> {
    let path = Path::new(RUN).join("case.json");
    wait_file(&path)?;
    read_json(&path, 0)
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CrashCandidate {
    pub current: CognitiveRecoveryAnchor,
    pub payload: String,
    pub dispatch_count: usize,
    pub original_daemon_joined: bool,
    pub agent_independent_history: Hos2DeliveryObservation,
}

/// Root can observe the controlled resource but cannot borrow role 3's
/// process-bound delivery-history slot. This is not a delivery receipt.
#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RootResourceObservation {
    boot_id: [u8; 16],
    revision: u64,
    active_cap_ns: u64,
    active_period_ns: u64,
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RetainedCrash {
    head: CognitiveCheckpointHead,
    candidate: CrashCandidate,
    root_resource_observation: RootResourceObservation,
    root_queried_delivery_history: bool,
    stopped_thread_ids: Vec<u32>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct HistoricalAdmission {
    root_pid: u32,
    observer_pid: u32,
    new_boot_id: [u8; 16],
    retained: RetainedCrash,
}

fn boot_text(bytes: &[u8; 16]) -> String {
    let text: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &text[..8],
        &text[8..12],
        &text[12..16],
        &text[16..20],
        &text[20..]
    )
}

fn head() -> Result<CognitiveCheckpointHead> {
    let value = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
        RootAuthorityDirectory::open(&Path::new(STATE).join("checkpoint"))?,
        "root-cognitive-checkpoint-v1".into(),
    )?
    .load("root-cognitive-checkpoint-v1")?;
    anyhow::ensure!(
        value.schema_version == 1
            && value.owner_agent_id.as_str() == OWNER
            && value.last_current.owner_agent_id == value.owner_agent_id
            && value.phase == CognitiveCheckpointPhase::Current
            && value.proposal.is_none()
            && value.publisher_epoch != 0
            && value.counter > 1
            && value.counter != u64::MAX
            && value.last_mutation_sequence != u64::MAX,
        "retained checkpoint is not a complete Current"
    );
    Ok(value)
}

pub fn monitor_crash(boot_bytes: Vec<u8>, agent_pid: u32) -> Result<()> {
    let candidate_path = Path::new(DATA).join("crash-candidate.json");
    wait_file(&candidate_path)?;
    let candidate: CrashCandidate = read_json(&candidate_path, 60002)?;
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut previous_stopped = Vec::new();
    let stopped_thread_ids = loop {
        let mut threads = Vec::new();
        for entry in std::fs::read_dir(format!("/proc/{agent_pid}/task"))? {
            let entry = entry?;
            let tid: u32 = entry
                .file_name()
                .to_str()
                .ok_or_else(|| anyhow::anyhow!("invalid task ID"))?
                .parse()?;
            anyhow::ensure!(
                tid != 0 && threads.len() < 128,
                "unexpected task enumeration"
            );
            threads.push(tid);
        }
        threads.sort_unstable();
        anyhow::ensure!(
            threads.binary_search(&agent_pid).is_ok(),
            "owner leader is absent"
        );
        let mut all_stopped = true;
        let mut observed_states = Vec::new();
        for tid in &threads {
            let status = std::fs::read_to_string(format!("/proc/{agent_pid}/task/{tid}/status"))?;
            let state = status
                .lines()
                .find_map(|line| line.strip_prefix("State:"))
                .and_then(|value| value.split_whitespace().next())
                .unwrap_or("missing");
            all_stopped &= state == "T";
            observed_states.push((*tid, state.to_owned()));
        }
        if all_stopped && threads == previous_stopped {
            break threads;
        }
        previous_stopped = if all_stopped { threads } else { Vec::new() };
        anyhow::ensure!(
            Instant::now() < deadline,
            "original owner did not stop all threads: {observed_states:?}"
        );
        std::thread::sleep(Duration::from_millis(20));
    };
    let current = head()?;
    anyhow::ensure!(
        candidate.dispatch_count == 1
            && candidate.original_daemon_joined
            && current.last_current == candidate.current
            && current.peer_lifetime.pid == agent_pid
            && current.peer_lifetime.process_start_ticks == ticks(agent_pid)?,
        "candidate differs from original Root Current"
    );
    let request = Hos2InstallBudgetV1::from_json(&candidate.payload).map_err(anyhow::Error::msg)?;
    anyhow::ensure!(
        request.delivery.boot_id == boot_bytes[96..112]
            && current.peer_lifetime.boot_id == boot_text(&request.delivery.boot_id),
        "original native and Root boot identities differ"
    );
    let control = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open("/dev/hepta-control")?;
    let native =
        AgentdHos2Device::from_bootstrap(control, &boot_bytes).map_err(anyhow::Error::msg)?;
    let usage = native.read_usage(1).map_err(anyhow::Error::msg)?;
    anyhow::ensure!(
        usage.boot_id == request.delivery.boot_id
            && usage.revision == 2
            && usage.active_cap_ns == 25_000_000
            && usage.active_period_ns == HOS2_CPU_PERIOD_NS
            && matches!(
                candidate.agent_independent_history,
                Hos2DeliveryObservation::Applied {
                    previous_revision: 1,
                    revision: 2,
                    ..
                }
            ),
        "independent Root resource and Agentd delivery observations differ"
    );
    let retained = RetainedCrash {
        head: current,
        candidate,
        root_resource_observation: RootResourceObservation {
            boot_id: usage.boot_id,
            revision: usage.revision,
            active_cap_ns: usage.active_cap_ns,
            active_period_ns: usage.active_period_ns,
        },
        root_queried_delivery_history: false,
        stopped_thread_ids,
    };
    write_json(
        &Path::new(ROOT).join("g2-admin/crash-receipt.json"),
        &retained,
        0o600,
    )?;
    println!(
        "HEPTA_NATIVE_VM_CRASH_READY {}",
        serde_json::to_string(&retained)?
    );
    // Only the host runner may kill its own isolated QEMU after recording this
    // marker. Root does not regrant, stop a host process, or mutate old history.
    Ok(())
}

pub async fn stop_at_crash_boundary(
    writer: &ProductionDurableWriter,
    request: &Hos2InstallBudgetV1,
    agent_independent_history: Hos2DeliveryObservation,
) -> Result<()> {
    let current = writer.checkpoint_current().await?;
    anyhow::ensure!(
        !writer.checkpoint_fenced(),
        "Current acknowledgement was uncertain"
    );
    let candidate = CrashCandidate {
        current,
        payload: request.to_json().map_err(anyhow::Error::msg)?,
        dispatch_count: 1,
        original_daemon_joined: true,
        agent_independent_history,
    };
    let pending = Path::new(DATA).join(".crash-candidate-pending");
    write_json(&pending, &candidate, 0o600)?;
    std::fs::rename(pending, Path::new(DATA).join("crash-candidate.json"))?;
    std::fs::File::open(DATA)?.sync_all()?;
    anyhow::ensure!(
        unsafe { libc::kill(std::process::id() as i32, libc::SIGSTOP) } == 0,
        "stop original owner"
    );
    // Resuming instead of crashing never authorizes re-entry or completion.
    Err(anyhow::anyhow!(
        "crash-qualified original owner was unexpectedly resumed"
    ))
}

pub fn historical_root(boot: Boot) -> Result<()> {
    let retained: RetainedCrash =
        read_json(&Path::new(ROOT).join("g2-admin/crash-receipt.json"), 0)?;
    anyhow::ensure!(
        head()? == retained.head,
        "protected Current changed since independent pre-crash receipt"
    );
    let old_request =
        Hos2InstallBudgetV1::from_json(&retained.candidate.payload).map_err(anyhow::Error::msg)?;
    let new_boot_id: [u8; 16] = boot.bytes[96..112].try_into()?;
    anyhow::ensure!(
        old_request.delivery.boot_id != new_boot_id
            && retained.candidate.current == retained.head.last_current
            && retained.head.peer_lifetime.boot_id == boot_text(&old_request.delivery.boot_id)
            && std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim()
                == boot_text(&new_boot_id)
            && retained.candidate.dispatch_count == 1
            && retained.candidate.original_daemon_joined
            && !retained.root_queried_delivery_history
            && !retained.stopped_thread_ids.is_empty()
            && retained.root_resource_observation
                == RootResourceObservation {
                    boot_id: old_request.delivery.boot_id,
                    revision: 2,
                    active_cap_ns: 25_000_000,
                    active_period_ns: HOS2_CPU_PERIOD_NS
                }
            && matches!(
                retained.candidate.agent_independent_history,
                Hos2DeliveryObservation::Applied {
                    previous_revision: 1,
                    revision: 2,
                    ..
                }
            ),
        "historical receipt does not describe the preceding qualified boot"
    );
    let output = Path::new(RUN).join("observer");
    std::fs::create_dir(&output)?;
    std::fs::set_permissions(&output, std::os::unix::fs::PermissionsExt::from_mode(0o700))?;
    chown(&output, 60002, 60002)?;
    let admission = HistoricalAdmission {
        root_pid: boot.root_pid,
        observer_pid: boot.agent_pid,
        new_boot_id,
        retained,
    };
    let path = Path::new(RUN).join("historical.json");
    write_json(&path, &admission, 0o440)?;
    chown(&path, 0, 60002)?;
    publish_case(Case::Historical)?;
    let mut status = 0;
    anyhow::ensure!(
        unsafe { libc::waitpid(boot.agent_pid as i32, &mut status, 0) } == boot.agent_pid as i32
            && libc::WIFEXITED(status)
            && libc::WEXITSTATUS(status) == 0,
        "historical observer failed"
    );
    let report: serde_json::Value = read_json(&output.join("report.json"), 60002)?;
    anyhow::ensure!(
        head()? == admission.retained.head
            && report["current_cut"]
                == serde_json::to_value(&admission.retained.head.last_current)?
            && report["exact_payload"] == admission.retained.candidate.payload
            && report["new_boot_id"] == serde_json::to_value(new_boot_id)?
            && report["state"] == "indeterminate"
            && report["observation"] == "unknown"
            && report["dispatch_count_this_boot"] == 0
            && report["issuer_connected"] == false,
        "independent Root historical result differs"
    );
    println!(
        "HEPTA_NATIVE_HISTORY_COMPLETE {}",
        serde_json::to_string(&serde_json::json!({
            "root_protected_head": head()?, "owner_report": report
        }))?
    );
    unsafe {
        libc::reboot(libc::RB_POWER_OFF);
    }
    Err(anyhow::anyhow!("poweroff returned"))
}

pub fn historical_agent(boot: &Boot, native: AgentdHos2Device) -> Result<()> {
    let admission: HistoricalAdmission = read_json(&Path::new(RUN).join("historical.json"), 0)?;
    anyhow::ensure!(
        admission.root_pid == boot.root_pid
            && admission.observer_pid == boot.agent_pid
            && admission.new_boot_id == boot.bytes[96..112],
        "historical observer lifetime differs"
    );
    let fleet = codex_hepta_paths::HeptaFleetRoot::parse(Path::new(DATA).join("fleet"))?;
    let layout = fleet.layout().agent(&AgentId::parse(OWNER)?);
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let history = CognitiveStore::open_active_wal_read_only_recovery(&layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&admission.retained.head.last_current)).await?;
        let retained = history.retained_operation("native-original-writer", "native:g2:original:1").await?
            .ok_or_else(|| anyhow::anyhow!("original historical operation is absent"))?;
        let request = Hos2InstallBudgetV1::from_json(&retained.payload_json).map_err(anyhow::Error::msg)?;
        anyhow::ensure!(retained.state == LocalOutcomeState::Indeterminate && retained.topic == HOS2_INSTALL_TOPIC_V1
            && retained.payload_json == admission.retained.candidate.payload
            && request.delivery.boot_id != admission.new_boot_id, "original K/D/payload or state changed");
        // The original adapter rejects old boot identity before ioctl. This is
        // Unavailable -> Unknown, not a fabricated kernel HistoryLost result.
        let unavailable = native.query(&request.delivery).err()
            .ok_or_else(|| anyhow::anyhow!("old boot unexpectedly produced live history"))?;
        anyhow::ensure!(unavailable == "native boot changed; the old D remains unknown",
            "old history failed for a different reason");
        let usage = native.read_usage(1).map_err(anyhow::Error::msg)?;
        anyhow::ensure!(usage.revision == 1 && usage.active_cap_ns == u64_at(&boot.bytes, 168)
            && usage.active_period_ns == HOS2_CPU_PERIOD_NS, "new boot resource changed");
        let report = serde_json::json!({"qualification":"original_retained_current_native_vm_crash_history",
            "production_ready":false,"current_cut":history.anchor(),"exact_payload":retained.payload_json,
            "old_delivery":request.delivery,"new_boot_id":admission.new_boot_id,"state":"indeterminate",
            "observation":"unknown","adapter_error":unavailable,"old_boot_ioctl_issued":false,
            "dispatch_count_previous_boot":1,"dispatch_count_this_boot":0,"issuer_connected":false,
            "writer_opened":false,"retirement_attempted":false,"physical_power_loss":false});
        history.close().await;
        write_json(&Path::new(RUN).join("observer/report.json"), &report, 0o600)?;
        println!("HEPTA_NATIVE_HISTORY_OWNER_REPORT {report}");
        Ok(())
    })
}
