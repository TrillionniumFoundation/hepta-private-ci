//! Continued original Supervisor/Root/Host lifecycle over finite kernel roles.
//! Runtime release, physical Current, real exit/reap and fresh authority are
//! separate observations. None is substituted for another or inferred from a
//! plan flag, a clock delay, a new PID, or current CPU cap alone.

use super::*;

#[path = "native_cpu_continuity_history.rs"]
mod history;
#[path = "native_cpu_continuity_renewal.rs"]
mod renewal;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::Hos2DeliveryObservation;
use codex_hepta_memory::ProductionLeaseReceipt;
use codex_hepta_supervisor::ProcessDriverError;
use codex_hepta_supervisor::ProcessExit;
use codex_hepta_supervisor::SupervisorEventKind;
pub(super) use history::history_only;
pub(super) use renewal::renewal;
use std::os::fd::BorrowedFd;

pub(super) fn stop_owner<F>(
    evidence: &mut evidence::Evidence,
    owner: &mut Active,
    supervisor: &mut Supervisor<KernelInitialProcessDriver<F>>,
    agent: &AgentId,
    deadline: u64,
    publish_evidence: bool,
) -> io::Result<recovery::PreparedRecovery>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    let inspected = owner.rpc.call(commands::Command::Inspect)?;
    let frontiers = [
        serde_json::from_value::<FinalUseFrontier>(inspected["device_frontier"].clone())
            .map_err(error)?,
        serde_json::from_value::<FinalUseFrontier>(inspected["notes_frontier"].clone())
            .map_err(error)?,
    ];
    let lifetime = owner.retained.lifetime().clone();
    let snapshot = supervisor
        .snapshot(agent)
        .ok_or_else(|| invalid("original live Supervisor snapshot absent"))?;
    if !snapshot.active
        || !snapshot.healthy
        || snapshot.process_system_id != Some(u64::from(lifetime.pid))
        || snapshot.spawn_generation != Some(owner.bundle.writer.spawn_generation)
    {
        return Err(invalid(
            "original Supervisor does not own this healthy release publisher",
        ));
    }
    supervisor.stop(agent, Instant::now()).map_err(error)?;
    loop {
        remaining(deadline)?;
        let report = supervisor.tick(Instant::now());
        if !report.faults.is_empty() {
            return Err(invalid(
                "original Supervisor stop failed before release observation",
            ));
        }
        if owner.release.readable()? {
            break;
        }
        if !supervisor
            .snapshot(agent)
            .is_some_and(|snapshot| snapshot.active)
        {
            return Err(invalid(
                "native publisher exited before authenticating its original release",
            ));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    let released: ProductionLeaseReceipt = owner.release.read()?;
    // The original writer produced this value only after its terminal row and
    // bound Current ACK. The source Process stays alive for independent Root
    // observation; Root does not reinterpret exit as a successful release.
    let current = owner.service.native_cpu_current()?;
    let binding = &current.head.writer_binding;
    if released.schema_version != 1
        || released.namespace != "production_durable_writer"
        || released.state != "released"
        || released.external_effect
        || released.owner_agent_id != current.head.owner_agent_id
        || released.lease_id != binding.lease_id
        || released.generation != binding.generation
        || released.authority_epoch != binding.authority_epoch
        || released.owner_epoch != binding.owner_epoch
        || released.authority_grant_digest != binding.authority_grant_digest
        || current.head.phase != CognitiveCheckpointPhase::Current
        || current.head.peer_lifetime != lifetime
        || binding.generation != owner.bundle.writer.local_lease_generation
    {
        return Err(invalid(
            "actual release receipt does not bind this original Current and publisher",
        ));
    }
    let material = evidence::retained_material(owner, &current)?;
    material.verify_unchanged().map_err(error)?;
    let material_sha256 = evidence::material(owner, &current)?.1;
    if publish_evidence {
        evidence.emit(
            "owner_released",
            serde_json::json!({"pid":lifetime.pid,"peer_lifetime":lifetime,
            "receipt":released,"current":current,"material_sha256":material_sha256,
            "device_frontier":frontiers[0],"notes_frontier":frontiers[1]}),
        )?;
    }
    owner.release.send(&commands::ReleaseAck {
        schema_version: 1,
        operation: "runtime.native-cpu.release-observed.v1".into(),
        receipt_sha256: codex_hepta_contracts::Sha256Digest::for_bytes(
            &serde_json::to_vec(&released).map_err(error)?,
        ),
        current: current.clone(),
    })?;
    while supervisor
        .snapshot(agent)
        .is_some_and(|snapshot| snapshot.active)
    {
        remaining(deadline)?;
        let report = supervisor.tick(Instant::now());
        if !report.faults.is_empty() {
            return Err(invalid(
                "original Supervisor failed to reap the released publisher",
            ));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    let stopped = supervisor
        .snapshot(agent)
        .ok_or_else(|| invalid("original stopped Supervisor snapshot absent"))?;
    let actual_exit = stopped
        .events
        .iter()
        .rev()
        .find_map(|event| match &event.kind {
            SupervisorEventKind::Exited(exit) => Some((event.generation, *exit)),
            _ => None,
        });
    if !matches!(actual_exit, Some((generation,ProcessExit {success:true,code:Some(0)}))
        if generation >= owner.bundle.writer.spawn_generation)
    {
        return Err(invalid(
            "released original owner did not actually exit zero",
        ));
    }
    let retired = crate::RetiredCheckpointPublisher::observe(lifetime.clone()).map_err(error)?;
    material.verify_unchanged().map_err(error)?;
    owner.join_retired_lanes()?;
    if publish_evidence {
        evidence.emit("owner_stopped", serde_json::json!({"pid":lifetime.pid,"peer_lifetime":lifetime,
            "release_generation":released.generation,"supervisor":snapshot_json(supervisor,agent,owner.bundle.writer.spawn_generation)?}))?;
    }
    Ok(recovery::PreparedRecovery {
        authorization: recovery::RecoveryAuthorization::Installed,
        previous: current,
        writer: owner.bundle.writer.clone(),
        proof: owner.bundle.writer_proof.clone(),
        retired,
        material,
        frontiers,
    })
}

fn snapshot_json<F>(
    supervisor: &Supervisor<KernelInitialProcessDriver<F>>,
    agent: &AgentId,
    from: u64,
) -> io::Result<serde_json::Value>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    let snapshot = supervisor
        .snapshot(agent)
        .ok_or_else(|| invalid("original Supervisor snapshot missing"))?;
    let events = snapshot
        .events
        .iter()
        .filter(|event| event.generation >= from)
        .map(|event| {
            let (kind, details) = match &event.kind {
                SupervisorEventKind::Spawned => ("spawned", serde_json::Value::Null),
                SupervisorEventKind::Healthy => ("healthy", serde_json::Value::Null),
                SupervisorEventKind::Lifecycle(state) => {
                    ("lifecycle", serde_json::json!({"state":state}))
                }
                SupervisorEventKind::DrainRequested => ("drain_requested", serde_json::Value::Null),
                SupervisorEventKind::StopRequested => ("stop_requested", serde_json::Value::Null),
                SupervisorEventKind::KillRequested => ("kill_requested", serde_json::Value::Null),
                SupervisorEventKind::Exited(exit) => (
                    "exited",
                    serde_json::json!({"success":exit.success,"code":exit.code}),
                ),
                other => ("other", serde_json::json!({"detail":format!("{other:?}")})),
            };
            serde_json::json!({"generation":event.generation,"kind":kind,"details":details})
        })
        .collect::<Vec<_>>();
    Ok(
        serde_json::json!({"active":snapshot.active,"healthy":snapshot.healthy,
        "runtime_generation":snapshot.runtime_generation,"spawn_generation":snapshot.spawn_generation,
        "process_system_id":snapshot.process_system_id,"events":events}),
    )
}

fn start_ready<F>(
    evidence: &mut evidence::Evidence,
    installation: &Arc<Mutex<Installation>>,
    active: &Arc<Mutex<Option<Active>>>,
    supervisor: &mut Supervisor<KernelInitialProcessDriver<F>>,
    agent: &AgentId,
    deadline: u64,
) -> io::Result<Active>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    if installation.lock().map_err(error)?.recovery.is_none()
        || active.lock().map_err(error)?.is_some()
    {
        return Err(invalid(
            "original successor material is not exclusively pending",
        ));
    }
    reentry::start(evidence, installation, active, supervisor, agent, deadline)?;
    loop {
        remaining(deadline)?;
        let report = supervisor.tick(Instant::now());
        if !report.faults.is_empty() {
            return Err(invalid("original successor Supervisor reported a fault"));
        }
        if supervisor
            .snapshot(agent)
            .is_some_and(|snapshot| snapshot.healthy)
        {
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let next = active
        .lock()
        .map_err(error)?
        .take()
        .ok_or_else(|| invalid("original successor activation missing"))?;
    let snapshot = supervisor
        .snapshot(agent)
        .ok_or_else(|| invalid("original successor snapshot missing"))?;
    if snapshot.process_system_id != Some(u64::from(next.registration.peer_pid))
        || snapshot.spawn_generation != Some(next.bundle.writer.spawn_generation)
    {
        return Err(invalid(
            "Supervisor and activated original Host identity differ",
        ));
    }
    Ok(next)
}

fn emit_owner<F>(
    evidence: &mut evidence::Evidence,
    owner: &mut Active,
    supervisor: &Supervisor<KernelInitialProcessDriver<F>>,
    agent: &AgentId,
) -> io::Result<()>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    let inspected = owner.rpc.call(commands::Command::Inspect)?;
    let current = owner.service.native_cpu_current()?;
    let material_sha256 = evidence::material(owner, &current)?.1;
    let bootstrap: Vec<u8> =
        serde_json::from_value(inspected["kernel_bootstrap"].clone()).map_err(error)?;
    let expected_bytes = if owner.image.kernel.is_some() {
        240
    } else {
        200
    };
    if bootstrap.len() != expected_bytes
        || u64::from_le_bytes(bootstrap[16..24].try_into().unwrap()) != owner.image.role
    {
        return Err(invalid(
            "actual Host bootstrap differs from original image activation",
        ));
    }
    if let Some(image) = &owner.image.kernel {
        let launch = image.launch();
        let retirement = image.retirement();
        let saved = image.durable_observation();
        saved.verify_durable().map_err(error)?;
        if u64::from_le_bytes(bootstrap[200..208].try_into().unwrap()) != u64::from(image.pid())
            || u64::from_le_bytes(bootstrap[224..232].try_into().unwrap()) != launch.generation()
            || bootstrap[96..112] != launch.boot_id()
        {
            return Err(invalid(
                "current Process bootstrap differs from authenticated kernel launch",
            ));
        }
        let payload = std::str::from_utf8(saved.payload()).map_err(error)?;
        evidence.emit("kernel_launch_saved",serde_json::json!({"boot_id":launch.boot_id(),
            "launch_generation":launch.generation(),"launch_receipt":launch.bytes().as_slice(),
            "retirement_receipt":retirement.bytes().as_slice(),"observation_id":saved.observation_id(),
            "durable_payload_json":payload,"durable_payload_sha256":codex_hepta_contracts::Sha256Digest::for_bytes(saved.payload())}))?;
    }
    evidence.emit("continuity_owner",serde_json::json!({"role":owner.image.label(),"pid":owner.registration.peer_pid,
        "kernel_bootstrap":bootstrap,"supervisor":snapshot_json(supervisor,agent,owner.bundle.writer.spawn_generation)?,
        "root_lease":owner.root_lease,"writer":owner.bundle.writer,"writer_proof":owner.bundle.writer_proof,
        "current":current,"material_sha256":material_sha256,"device_frontier":inspected["device_frontier"],
        "notes_frontier":inspected["notes_frontier"],"usage":inspected["usage"]}))
}

fn next_owner<F>(
    evidence: &mut evidence::Evidence,
    previous: recovery::PreparedRecovery,
    installation: &Arc<Mutex<Installation>>,
    active: &Arc<Mutex<Option<Active>>>,
    supervisor: &mut Supervisor<KernelInitialProcessDriver<F>>,
    agent: &AgentId,
    deadline: u64,
) -> io::Result<Active>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    let current = previous.previous.clone();
    let frontiers = previous.frontiers;
    let local_generation = previous.writer.local_lease_generation;
    let owner_epoch = previous.writer.owner_epoch;
    let original_spawn = previous.writer.spawn_generation;
    let material_sha256 = material_digest(&previous.material)?;
    {
        let mut owner = installation.lock().map_err(error)?;
        if owner.recovery.is_some() {
            return Err(invalid("another original handoff is pending"));
        }
        owner.recovery = Some(previous);
    }
    let mut next = start_ready(evidence, installation, active, supervisor, agent, deadline)?;
    let adopted = next
        .adopted
        .as_ref()
        .ok_or_else(|| invalid("original material adoption missing"))?;
    if next.bundle.writer.local_lease_generation
        != local_generation
            .checked_add(1)
            .ok_or_else(|| invalid("local generation overflow"))?
        || next.bundle.writer.owner_epoch <= owner_epoch
        || next.bundle.writer.spawn_generation <= original_spawn
        || adopted.head.last_current != current.head.last_current
        || [
            next.bundle.consumers.device.frontier,
            next.bundle.consumers.notes.frontier,
        ] != frontiers
    {
        return Err(invalid(
            "original generation/material/consumer continuation differs",
        ));
    }
    evidence.emit(
        "material_adopted",
        serde_json::json!({"previous":current,"successor":adopted,
        "material_sha256":material_sha256}),
    )?;
    emit_owner(evidence, &mut next, supervisor, agent)?;
    Ok(next)
}

fn material_digest(material: &codex_hepta_memory::VerifiedCognitiveMaterial) -> io::Result<String> {
    material.verify_unchanged().map_err(error)?;
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(material.path())?;
    let mut hash = Sha256::new();
    let mut bytes = [0; 64 * 1024];
    loop {
        let read = file.read(&mut bytes)?;
        if read == 0 {
            break;
        }
        hash.update(&bytes[..read]);
    }
    material.verify_unchanged().map_err(error)?;
    Ok(format!("{:x}", hash.finalize()))
}

/// Each fixed case interrupts a different real successor activation. The old
/// owner first finishes its normal original drain/release/reap ceremony.
pub(super) fn activation_failure<F>(
    evidence: &mut evidence::Evidence,
    mut old: Active,
    installation: &Arc<Mutex<Installation>>,
    active: &Arc<Mutex<Option<Active>>>,
    supervisor: &mut Supervisor<KernelInitialProcessDriver<F>>,
    agent: &AgentId,
    deadline: u64,
) -> io::Result<Active>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    let (point, advances) = match evidence.scenario() {
        "activation-after-proof-v1" => (reentry::FailurePoint::AfterProof, 1_u64),
        "activation-after-material-v1" => (reentry::FailurePoint::AfterMaterial, 2_u64),
        _ => return Err(invalid("unsupported fixed partial-activation case")),
    };
    emit_owner(evidence, &mut old, supervisor, agent)?;
    let terminal = evidence.operation("before-partial-activation", 25_000_000, &mut old)?;
    evidence.acknowledge(&terminal, &mut old)?;
    evidence.window("before-partial-activation", &mut old)?;
    let previous = stop_owner(evidence, &mut old, supervisor, agent, deadline, true)?;
    let current = previous.previous.clone();
    let frontiers = previous.frontiers;
    let local_generation = previous.writer.local_lease_generation;
    let material_sha256 = material_digest(&previous.material)?;
    drop(old);
    {
        let mut owner = installation.lock().map_err(error)?;
        if owner.recovery.is_some()
            || owner.activation.is_some()
            || owner.activation_fault.is_some()
        {
            return Err(invalid("another original activation or failure is pending"));
        }
        owner.recovery = Some(previous);
        owner.activation_fault = Some(point);
        owner.last_activation_reconciliation = None;
    }
    let mut next = start_ready(evidence, installation, active, supervisor, agent, deadline)?;
    let adopted = next
        .adopted
        .as_ref()
        .ok_or_else(|| invalid("reentered original physical adoption absent"))?;
    let actual_fault = installation
        .lock()
        .map_err(error)?
        .last_activation_reconciliation
        .clone()
        .ok_or_else(|| invalid("actual failed activation reconciliation was not observed"))?;
    let expected_point = match point {
        reentry::FailurePoint::AfterProof => "after_proof",
        reentry::FailurePoint::AfterMaterial => "after_material",
    };
    if actual_fault["fault"]["point"].as_str() != Some(expected_point)
        || actual_fault["fault"]["wait_value"].as_i64() != Some(i64::from(libc::SIGKILL))
        || installation
            .lock()
            .map_err(error)?
            .activation_fault
            .is_some()
        || next.bundle.writer.local_lease_generation
            != local_generation
                .checked_add(advances)
                .ok_or_else(|| invalid("original reentry local generation overflow"))?
        || adopted.head.last_current != current.head.last_current
        || [
            next.bundle.consumers.device.frontier,
            next.bundle.consumers.notes.frontier,
        ] != frontiers
        || next.image.kernel.is_none()
        || next.image.role != 1
    {
        return Err(invalid(
            "actual reentry did not preserve the exact original cut and unused generation",
        ));
    }
    evidence.emit(
        "material_adopted",
        serde_json::json!({
            "previous":current,"successor":adopted,"material_sha256":material_sha256,
        }),
    )?;
    emit_owner(evidence, &mut next, supervisor, agent)?;
    let terminal = evidence.operation("after-partial-activation", 35_000_000, &mut next)?;
    evidence.acknowledge(&terminal, &mut next)?;
    evidence.window("after-partial-activation", &mut next)?;
    Ok(next)
}
