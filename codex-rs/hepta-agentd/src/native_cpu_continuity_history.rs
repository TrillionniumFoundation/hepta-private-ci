//! Original history-only recovery after both initial privileged owners exit.
use super::*;
use std::os::fd::AsRawFd;

fn require_launch_busy(
    evidence: &mut evidence::Evidence,
    installation: &Arc<Mutex<Installation>>,
    stage: &str,
) -> io::Result<()> {
    let installed = installation.lock().map_err(error)?;
    let before = installed.launcher.query()?;
    let failure = match installed.launcher.advance(&before) {
        Err(failure) => failure,
        Ok(_) => {
            return Err(invalid(
                "kernel accepted a launch while original images are live or unreaped",
            ));
        }
    };
    if failure.raw_os_error() != Some(libc::EBUSY) || installed.launcher.query()? != before {
        return Err(invalid(
            "kernel factory did not retain its exact generation after busy refusal",
        ));
    }
    evidence.emit(
        "launch_refused",
        serde_json::json!({"stage":stage,"expected_generation":before.generation(),
        "errno":failure.raw_os_error(),"launch_receipt":before.bytes().as_slice()}),
    )
}

pub(in super::super) fn history_only<F>(
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
    if old.image.role != 1 || old.image.pid != 2 || old.image.generation() != 0 {
        return Err(invalid(
            "history qualification must begin with the real initial Manager",
        ));
    }
    let terminal = evidence.operation("history-pending-retirement", 25_000_000, &mut old)?;
    let material = evidence::retained_material(&old, &terminal.current)?;
    material.verify_unchanged().map_err(error)?;
    let manager = old.retained.lifetime().clone();
    let initial_spawn = old.bundle.writer.spawn_generation;
    if manager != terminal.current.head.peer_lifetime {
        return Err(invalid("retained Manager Current lifetime differs"));
    }
    let recovery_lifetime = peer(4, 60001)?;
    let _retained_recovery =
        crate::RetainedCheckpointPublisher::capture(recovery_lifetime.clone()).map_err(error)?;
    let manager_fd = pidfd(manager.pid)?;
    let recovery_fd = pidfd(recovery_lifetime.pid)?;
    require_launch_busy(evidence, installation, "live")?;
    for (role, lifetime, held) in [
        ("recovery", &recovery_lifetime, &recovery_fd),
        ("manager", &manager, &manager_fd),
    ] {
        if unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                held.as_raw_fd(),
                libc::SIGKILL,
                std::ptr::null::<libc::siginfo_t>(),
                0,
            )
        } < 0
        {
            return Err(io::Error::last_os_error());
        }
        let (revents, signal) = recovery::observe_child_exit(lifetime.pid, held, deadline)?;
        evidence.emit("initial_owner_retired",serde_json::json!({"role":role,"peer_lifetime":lifetime,
            "pidfd_revents":revents,"wait_kind":"signaled","wait_value":signal,"signal":libc::SIGKILL}))?;
    }
    require_launch_busy(evidence, installation, "unreaped")?;
    let retired = crate::RetiredCheckpointPublisher::observe(manager).map_err(error)?;
    old.join_retired_lanes()?;
    let previous = recovery::PreparedRecovery {
        authorization: recovery::RecoveryAuthorization::Installed,
        previous: terminal.current.clone(),
        writer: old.bundle.writer.clone(),
        proof: old.bundle.writer_proof.clone(),
        retired,
        material,
        frontiers: terminal.frontiers,
    };
    drop(old);
    let (first_stat, second_stat) = recovery::observe_watchdog(deadline)?;
    evidence.emit(
        "history_watchdog",
        serde_json::json!({"first_cpu_stat":first_stat,"second_cpu_stat":second_stat}),
    )?;
    let expiry = previous
        .previous
        .head
        .writer_binding
        .expires_at_unix_seconds;
    let observed = loop {
        remaining(deadline)?;
        let unix = installation
            .lock()
            .map_err(error)?
            .clock
            .now_unix_ms()
            .map_err(error)?
            / 1000;
        if unix >= expiry {
            break unix;
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    previous.material.verify_unchanged().map_err(error)?;
    evidence.emit(
        "local_lease_retired",
        serde_json::json!({"lease_id":previous.writer.local_lease_id,
        "generation":previous.writer.local_lease_generation,"mode":"expired",
        "observed_unix_seconds":observed,"expires_at_unix_seconds":expiry}),
    )?;
    {
        let mut owner = installation.lock().map_err(error)?;
        if owner.recovery.is_some() {
            return Err(invalid("another original recovery is pending"));
        }
        owner.recovery = Some(previous);
    }
    // The existing Supervisor first reaps Manager, then its ordinary restart
    // attempts the already-dead initial Recovery slot. That original driver's
    // guard reaps its own child. Only this independently observed failure is
    // accepted; no caller writes Starting or skips the failed generation.
    loop {
        remaining(deadline)?;
        let report = supervisor.tick(Instant::now());
        if !report.faults.is_empty() {
            let snapshot = supervisor
                .snapshot(agent)
                .ok_or_else(|| invalid("failed original slot snapshot missing"))?;
            let installed = installation.lock().map_err(error)?;
            let registered = installed.fleet.load_agent(agent).map_err(error)?;
            let recovery_reaped = match std::fs::symlink_metadata("/proc/4") {
                Err(failure) if failure.kind() == io::ErrorKind::NotFound => true,
                Ok(_) => false,
                Err(failure) => return Err(failure),
            };
            if report.faults.len() != 1
                || report.faults[0].agent_id != *agent
                || snapshot.active
                || !report.faults[0]
                    .message
                    .ends_with("kernel-initial child is no longer alive")
                || registered.lifecycle.lifecycle != codex_hepta_fleet::AgentLifecycle::Failed
                || installed.launcher.query()?.generation() != 0
                || installed.recovery.is_none()
                || active.lock().map_err(error)?.is_some()
                || !recovery_reaped
            {
                return Err(invalid(
                    "unexpected original Supervisor failure while consuming the dead initial slot",
                ));
            }
            evidence.emit(
                "initial_recovery_reaped",
                serde_json::json!({"peer_lifetime":recovery_lifetime,
                "registry":registered.lifecycle,"driver_fault":report.faults[0].message,
                "supervisor":snapshot_json(supervisor,agent,initial_spawn)?}),
            )?;
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let mut history = start_ready(evidence, installation, active, supervisor, agent, deadline)?;
    if history.image.role != 5
        || history.image.kernel.as_ref().is_none_or(|image| {
            image.launch().mode() != codex_hepta_supervisor::KernelLaunchMode::HistoryOnly
                || image.retirement().policy_retired()
        })
    {
        return Err(invalid(
            "unretired original history did not produce the actual history-only image",
        ));
    }
    let adopted = history
        .adopted
        .as_ref()
        .ok_or_else(|| invalid("history owner material adoption missing"))?;
    if adopted.head.last_current != terminal.current.head.last_current
        || [
            history.bundle.consumers.device.frontier,
            history.bundle.consumers.notes.frontier,
        ] != terminal.frontiers
    {
        return Err(invalid(
            "history owner changed the original Current or consumer frontiers",
        ));
    }
    evidence.emit(
        "material_adopted",
        serde_json::json!({"previous":terminal.current,"successor":adopted,
        "material_sha256":terminal.material_sha256}),
    )?;
    emit_owner(evidence, &mut history, supervisor, agent)?;
    let recovered = evidence.recovered_terminal(&terminal, &mut history)?;
    evidence.acknowledge(&recovered, &mut history)?;
    let previous = stop_owner(evidence, &mut history, supervisor, agent, deadline, true)?;
    drop(history);
    let mut manager = next_owner(
        evidence,
        previous,
        installation,
        active,
        supervisor,
        agent,
        deadline,
    )?;
    if manager.image.role != 1
        || manager.image.kernel.as_ref().is_none_or(|image| {
            image.launch().mode() != codex_hepta_supervisor::KernelLaunchMode::ManagerRecovery
                || !image.retirement().policy_retired()
        })
    {
        return Err(invalid(
            "fully retired original history did not admit a fresh real Manager pair",
        ));
    }
    let restored = evidence.operation("fresh-control-after-history", 25_000_000, &mut manager)?;
    evidence.acknowledge(&restored, &mut manager)?;
    evidence.window("fresh-control-after-history", &mut manager)?;
    let original: serde_json::Value =
        serde_json::from_str(&restored.terminal_json).map_err(error)?;
    if !matches!(
        serde_json::from_value::<Hos2DeliveryObservation>(original["observation"].clone())
            .map_err(error)?,
        Hos2DeliveryObservation::Applied { .. }
    ) {
        return Err(invalid(
            "new Manager did not regain actual CPU control after history-only drain",
        ));
    }
    evidence.emit(
        "history_only_complete",
        serde_json::json!({"old_delivery":terminal.request.delivery,
        "old_occurrence_key":terminal.key,"actual_terminal_json":restored.terminal_json,
        "fresh_delivery":restored.request.delivery,"fresh_occurrence_key":restored.key,
        "kernel_launch_generation":manager.image.generation()}),
    )?;
    Ok(manager)
}
