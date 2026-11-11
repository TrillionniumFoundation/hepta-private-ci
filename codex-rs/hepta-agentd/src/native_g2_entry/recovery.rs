//! Finite actual Manager-exit handoff through original Root/material/owner APIs.
use super::activation;
use super::boot::Boot;
use super::cycle;
use super::evidence::Evidence;
use super::ipc;
use super::native_observer;
use super::owner::Command;
use super::provision;
use super::recovery_process;
use super::recovery_registration;
use super::root;
use super::supervisor;
use super::workload::Heartbeat;
use codex_hepta_agentd::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::ProductionRetainedHos2Terminal;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::sync::Arc;

#[allow(clippy::too_many_arguments)]
pub(super) fn run(
    boot: &Boot,
    evidence: &mut Evidence,
    mut manager: HostAuthorityPeerChannel,
    prepared: Arc<PreparedHostAuthoritySession>,
    service: std::thread::JoinHandle<std::io::Result<()>>,
    registry: &FleetRegistry,
    agent: &AgentId,
    supervisor: &mut supervisor::NativeSupervisor,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    proof: &HostSignedWriterAuthorizationV1,
    handoff: UnixDatagram,
    requests: &UnixListener,
    observer: &mut HostAuthorityPeerChannel,
    consumers: &Path,
    heartbeat: &Heartbeat,
) -> Result<(), Box<dyn std::error::Error>> {
    let name = "pending-retirement";
    let (queued, dispatch, current) = cycle::operate(
        evidence,
        &mut manager,
        cycle::OwnerCycle {
            root: &prepared,
            heartbeat,
            pid: boot.pids[0],
        },
        cycle::OperationSpec {
            name,
            cap: 25_000_000,
            retire: false,
        },
    )?;
    let old: CognitiveCheckpointReceipt = serde_json::from_value(current)?;
    let physical = prepared.observe_physical_current()?;
    if physical.current() != &old {
        return Err("Root Current changed before actual Manager exit".into());
    }
    let pin = supervisor::pin(boot.pids[0])?;
    let manager_birth = provision::start_ticks(boot.pids[0])?;
    supervisor.kill(agent)?;
    let revents = recovery_process::wait_signal_nine(&pin, boot.pids[0])?;
    drop(manager);
    evidence.emit(
        "manager_retired",
        serde_json::json!({"pid":boot.pids[0],"start_ticks":manager_birth,
        "root_pid":std::process::id(),"root_start_ticks":provision::start_ticks(1)?,
        "signal":9,"wait_kind":"signaled","wait_value":9,"pidfd_revents":revents,
        "old_current_token":old.token,"old_material_sha256":physical.material_sha256()}),
    )?;
    // The old same-object service ends through its actual pinned peer lifetime.
    // A panic or an unexpectedly still live child cannot admit a new service.
    let _closed = service
        .join()
        .map_err(|_| "old original Root lane panicked")?;
    drop(prepared);
    let (first, second) = recovery_process::watchdog(boot.pids[1])?;
    let observed = native_observer::read(observer, heartbeat.read())?;
    evidence.emit(
        "watchdog",
        serde_json::json!({"first_cpu_stat":first,"second_cpu_stat":second,"usage":observed}),
    )?;
    let predecessor = config
        .writer
        .as_ref()
        .ok_or("original writer registration absent")?;
    let expires = old.head.writer_binding.expires_at_unix_seconds;
    let actual = recovery_process::wait_expired(
        predecessor
            .authority_lease
            .expires_at_unix_ms
            .max(expires.checked_mul(1000).ok_or("local expiry overflow")?),
    )?;
    evidence.emit(
        "local_lease_retired",
        serde_json::json!({"lease_id":old.head.writer_binding.lease_id,
        "generation":old.head.writer_binding.generation,"mode":"expired",
        "observed_unix_seconds":actual/1000,"expires_at_unix_seconds":expires}),
    )?;
    recovery_process::start_successor(supervisor, agent)?;
    let (config, proof) =
        recovery_registration::rotate(boot, registry, agent, config, registration, proof, &old)?;
    // No Current/digest/image-path/grant is supplied to this factory. It reads
    // the actual protected predecessor, independently verifies and installs
    // retained Root material, then performs the original Current adoption.
    let prepared = Arc::new(
        PreparedHostAuthoritySession::recover_with_physical_material(
            Path::new(recovery_registration::CONFIG),
            Path::new(recovery_registration::REGISTRATION),
            supervisor::pin(boot.pids[2])?,
        )?,
    );
    let adopted = prepared.observe_physical_current()?;
    if adopted.material_sha256() != physical.material_sha256() {
        return Err("adoption replaced independent original material".into());
    }
    evidence.emit(
        "material_adopted",
        serde_json::json!({"previous":old,"successor":adopted.current(),
        "material_sha256":adopted.material_sha256()}),
    )?;
    let serving = Arc::clone(&prepared);
    let _service = std::thread::spawn(move || serving.serve_retained());
    activation::wait_lanes(&config)?;
    activation::send_original(&prepared, consumers, handoff)?;
    let mut recovery = ipc::channel(requests, boot.pids[2], 60001)?;
    root::owner_ready(
        evidence,
        &mut recovery,
        &prepared,
        root::OwnerReadiness {
            role: "recovery",
            pid: boot.pids[2],
            registry,
            agent,
            config: &config,
            proof: &proof,
        },
    )?;
    let response = cycle::request(
        &mut recovery,
        Command::Reconcile {
            occurrence_key: queued.occurrence_key.clone(),
        },
    )?;
    let retained: ProductionRetainedHos2Terminal =
        serde_json::from_value(response["retained"].clone())?;
    if retained.occurrence_key != queued.occurrence_key
        || retained.request_json != queued.payload_json
        || Some(&retained.terminal_json) != dispatch.target_receipt.as_ref()
        || retained.local_event_id != dispatch.local_event_id
        || retained.state != dispatch.state
    {
        return Err("actual recovered source differs from original terminal".into());
    }
    let usage = cycle::usage(&mut recovery, heartbeat)?;
    evidence.emit(
        "reconciled",
        serde_json::json!({"operation":name,"pid":boot.pids[2],
        "occurrence_key":retained.occurrence_key,"request_json":retained.request_json,
        "terminal_json":retained.terminal_json,"usage":usage}),
    )?;
    let (owner, current) = cycle::current(&mut recovery, &prepared)?;
    evidence.emit("source_terminal",serde_json::json!({"operation":name,"pid":boot.pids[2],
        "occurrence_key":retained.occurrence_key,"state":retained.state,"terminal_json":retained.terminal_json,
        "local_event_id":retained.local_event_id,"current":current.current(),"material_sha256":current.material_sha256(),
        "device_frontier":owner["device_frontier"],"notes_frontier":owner["notes_frontier"]}))?;
    let native = Hos2InstallBudgetV1::from_json(&retained.request_json)?;
    cycle::acknowledge(
        evidence,
        &mut recovery,
        boot.pids[2],
        name,
        &queued,
        &serde_json::to_value(current.current())?,
        &native,
    )?;
    let (_, _, current) = cycle::operate(
        evidence,
        &mut recovery,
        cycle::OwnerCycle {
            root: &prepared,
            heartbeat,
            pid: boot.pids[2],
        },
        cycle::OperationSpec {
            name: "used-recovery-allowance",
            cap: 50_000_000,
            retire: true,
        },
    )?;
    evidence.emit(
        "complete",
        serde_json::json!({"root_pid":std::process::id(),"operation_count":2,
        "final_owner_pid":boot.pids[2],"final_current_token":current["token"]}),
    )?;
    Ok(())
}
