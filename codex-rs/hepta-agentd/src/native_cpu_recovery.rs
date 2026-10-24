//! Same-boot cold handoff through the original publisher/material/writer owners.
//! A Manager crash never becomes a successful drain or a lease-release claim.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use codex_hepta_supervisor::ProcessDriverError;
use std::os::fd::AsRawFd;
use std::os::fd::BorrowedFd;

pub(super) struct PreparedRecovery {
    pub(super) previous: CognitiveCheckpointReceipt,
    pub(super) writer: crate::HostAuthorityWriterRegistration,
    pub(super) proof: crate::HostSignedWriterAuthorizationV1,
    pub(super) retired: crate::RetiredCheckpointPublisher,
    pub(super) material: VerifiedCognitiveMaterial,
    pub(super) frontiers: [codex_hepta_contracts::FinalUseFrontier; 2],
}

impl Installation {
    pub(super) fn recovered_writer(
        &self,
        spec: &SpawnSpec,
        previous: &PreparedRecovery,
    ) -> io::Result<crate::HostAuthorityWriterRegistration> {
        if previous.writer.registered_agent_id != spec.agent_id
            || spec.generation <= previous.writer.spawn_generation
        {
            return Err(invalid(
                "original Supervisor successor does not advance the same Agent",
            ));
        }
        // The old signed proof is authenticated as a retired predecessor by
        // the original registry rotation, not accepted as a live authority.
        self.leases
            .revoke(
                &previous.writer.authority_lease.lease_id,
                previous.writer.authority_lease.revision,
                Sha256::digest(
                    serde_json::to_vec(&previous.previous.head.peer_lifetime).map_err(error)?,
                )
                .into(),
            )
            .map_err(error)?;
        let mut writer = previous.writer.clone();
        writer.spawn_generation = spec.generation;
        writer.owner_epoch = writer
            .owner_epoch
            .checked_add(1)
            .ok_or_else(|| invalid("original owner epoch overflow"))?;
        writer.local_lease_generation = writer
            .local_lease_generation
            .checked_add(1)
            .ok_or_else(|| invalid("original local generation overflow"))?;
        writer.authority_lease.lease_id =
            format!("native-cpu-writer-{}", writer.local_lease_generation);
        writer.authority_lease.revision = 1;
        writer.authority_lease.issued_at_unix_ms = self.clock.now_unix_ms().map_err(error)?;
        writer.authority_lease.expires_at_unix_ms = writer
            .authority_lease
            .issued_at_unix_ms
            .checked_add(ORIGINAL_WRITER_LIFETIME_MS)
            .ok_or_else(|| invalid("successor authority expiry overflow"))?;
        writer.authority_lease.binding.payload_sha256 = Sha256::digest(
            serde_json::to_vec(&(
                &previous.previous.head.last_current,
                writer.spawn_generation,
                writer.local_lease_generation,
            ))
            .map_err(error)?,
        )
        .into();
        self.leases
            .put_lease(writer.authority_lease.clone(), 0)
            .map_err(error)?;
        self.issuer
            .rotate_writer_authorization(&previous.writer, &previous.proof, &writer)?;
        Ok(writer)
    }
}

pub(super) struct CrashCheckpoint {
    pub(super) current: CognitiveCheckpointReceipt,
    pub(super) material_sha256: String,
    pub(super) frontiers: [codex_hepta_contracts::FinalUseFrontier; 2],
    // Only the real copyout boundary supplies a bound. An ordinary completed
    // terminal retains its existing crash ceremony without a new timer.
    pub(super) kill_before: Option<u64>,
}

pub(super) fn after_terminal<F>(
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
    let terminal = evidence.operation("pending-retirement", 25_000_000, &mut old)?;
    let mut next = recover_after_crash(
        evidence,
        old,
        CrashCheckpoint {
            current: terminal.current.clone(),
            material_sha256: terminal.material_sha256.clone(),
            frontiers: terminal.frontiers,
            kill_before: None,
        },
        installation,
        active,
        supervisor,
        agent,
        deadline,
    )?;
    let recovered = evidence.recovered_terminal(&terminal, &mut next)?;
    evidence.acknowledge(&recovered, &mut next)?;
    let refused = evidence.operation("used-recovery-allowance", 50_000_000, &mut next)?;
    evidence.acknowledge(&refused, &mut next)?;
    evidence.window("used-recovery-allowance", &mut next)?;
    Ok(next)
}

pub(super) fn recover_after_crash<F>(
    evidence: &mut evidence::Evidence,
    mut old: Active,
    cut: CrashCheckpoint,
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
    let material = evidence::retained_material(&old, &cut.current)?;
    material.verify_unchanged().map_err(error)?;
    let lifetime = old.retained.lifetime().clone();
    if lifetime != cut.current.head.peer_lifetime || lifetime.pid != 2 {
        return Err(invalid(
            "retained original Manager lifetime differs from Current",
        ));
    }
    let held = pidfd(lifetime.pid)?;
    if peer(lifetime.pid, lifetime.uid)? != lifetime {
        return Err(invalid("Manager identity changed before actual fault"));
    }
    if old
        .server
        .as_ref()
        .is_none_or(|server| server.is_finished())
    {
        return Err(invalid("original service ended before the Manager crash"));
    }
    if let Some(bound) = cut.kill_before {
        remaining(bound)?;
    }
    // This is an actual crash of the retained native Process. The Supervisor
    // remains Running until its normal poll observes and reaps the same child.
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
    let killed_at = if let Some(bound) = cut.kill_before {
        let completed = now()?;
        if completed >= bound {
            return Err(invalid(
                "actual copyout callback deadline elapsed before Manager kill completed",
            ));
        }
        Some(completed)
    } else {
        None
    };
    let (revents, signal) = observe_child_exit(lifetime.pid, &held, deadline)?;
    let retired = crate::RetiredCheckpointPublisher::observe(lifetime.clone()).map_err(error)?;
    let mut exited = serde_json::json!({"pid":lifetime.pid,"start_ticks":lifetime.process_start_ticks,
        "root_pid":std::process::id(),"root_start_ticks":peer(1,0)?.process_start_ticks,
        "signal":libc::SIGKILL,"wait_kind":"signaled","wait_value":signal,"pidfd_revents":revents,
        "old_current_token":cut.current.token,"old_material_sha256":cut.material_sha256});
    if let Some(killed_at) = killed_at {
        exited["kill_boottime_ns"] = serde_json::json!(killed_at);
    }
    evidence.emit("manager_retired", exited)?;
    // Joining ends old worker custody only. Inner errors remain diagnostics,
    // not a successful-service claim or the independent retirement witness.
    old.join_retired_lanes()?;
    let previous = PreparedRecovery {
        previous: cut.current.clone(),
        writer: old.bundle.writer.clone(),
        proof: old.bundle.writer_proof.clone(),
        retired,
        material,
        frontiers: cut.frontiers.clone(),
    };
    drop(old);
    let (first_stat, second_stat) = observe_watchdog(deadline)?;
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
    {
        let mut installation = installation.lock().map_err(error)?;
        if installation.recovery.is_some() {
            return Err(invalid("original recovery already pending"));
        }
        installation.recovery = Some(previous);
    }
    // The original poll owns Failed, restart budget, Starting, process lease,
    // generation assignment and exact Health promotion. No state is written
    // by this ceremony; the driver merely consumes its second real slot.
    loop {
        remaining(deadline)?;
        let report = supervisor.tick(Instant::now());
        if !report.faults.is_empty() {
            return Err(invalid("original Supervisor cold recovery failed"));
        }
        if supervisor
            .snapshot(agent)
            .is_some_and(|snapshot| snapshot.healthy && snapshot.process_system_id == Some(4))
        {
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let mut next = active
        .lock()
        .map_err(error)?
        .take()
        .ok_or_else(|| invalid("original successor activation missing"))?;
    let inspected = next.rpc.call(commands::Command::Inspect)?;
    let frontiers: [codex_hepta_contracts::FinalUseFrontier; 2] = [
        serde_json::from_value(inspected["device_frontier"].clone()).map_err(error)?,
        serde_json::from_value(inspected["notes_frontier"].clone()).map_err(error)?,
    ];
    if frontiers != cut.frontiers {
        return Err(invalid("cold handoff reset an original FinalUse frontier"));
    }
    evidence.emit("watchdog",serde_json::json!({"first_cpu_stat":first_stat,"second_cpu_stat":second_stat,"usage":inspected["usage"]}))?;
    evidence.emit(
        "local_lease_retired",
        serde_json::json!({"lease_id":cut.current.head.writer_binding.lease_id,
        "generation":cut.current.head.writer_binding.generation,"mode":"expired",
        "observed_unix_seconds":observed,"expires_at_unix_seconds":expiry}),
    )?;
    let adopted = next
        .adopted
        .as_ref()
        .ok_or_else(|| invalid("original successor adoption receipt absent"))?;
    evidence.emit(
        "material_adopted",
        serde_json::json!({"previous":cut.current,"successor":adopted,
        "material_sha256":cut.material_sha256}),
    )?;
    evidence.owner_ready("recovery", &mut next)?;
    Ok(next)
}

fn observe_child_exit(pid: u32, held: &OwnedFd, deadline: u64) -> io::Result<(i16, i32)> {
    loop {
        remaining(deadline)?;
        let mut poll = libc::pollfd {
            fd: held.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        let result = unsafe { libc::poll(&mut poll, 1, 0) };
        match (result, poll.revents) {
            (0, 0) => {
                std::thread::sleep(Duration::from_millis(5));
                continue;
            }
            (1, libc::POLLIN) => {}
            _ => {
                return Err(invalid(
                    "retained Manager pidfd did not provide a definite exit",
                ));
            }
        }
        let mut info = unsafe { std::mem::zeroed::<libc::siginfo_t>() };
        // WNOWAIT observes the actual exit status without stealing the
        // original Supervisor driver's exclusive waitpid/reap responsibility.
        let result = unsafe {
            libc::waitid(
                libc::P_PID,
                pid,
                &mut info,
                libc::WEXITED | libc::WNOHANG | libc::WNOWAIT,
            )
        };
        if result < 0 {
            return Err(io::Error::last_os_error());
        }
        if info.si_signo != libc::SIGCHLD
            || info.si_code != libc::CLD_KILLED
            || unsafe { info.si_pid() } != pid as i32
            || unsafe { info.si_status() } != libc::SIGKILL
        {
            return Err(invalid(
                "actual Manager wait status differs from the requested crash",
            ));
        }
        return Ok((poll.revents, unsafe { info.si_status() }));
    }
}

fn observe_watchdog(deadline: u64) -> io::Result<(String, String)> {
    let membership = std::fs::read_to_string("/proc/3/cgroup")?;
    let path = membership
        .strip_prefix("0::")
        .and_then(|value| value.strip_suffix('\n'))
        .ok_or_else(|| invalid("actual workload cgroup membership unavailable"))?;
    if !path.starts_with('/')
        || path.contains('\n')
        || path.len() > 4096
        || Path::new(path).components().any(|part| {
            matches!(
                part,
                std::path::Component::ParentDir | std::path::Component::CurDir
            )
        })
    {
        return Err(invalid("actual workload cgroup path differs"));
    }
    let path = PathBuf::from(format!("/sys/fs/cgroup{path}")).join("cpu.stat");
    let read = || -> io::Result<String> {
        let bytes = std::fs::read_to_string(&path)?;
        if bytes.len() > 32 * 1024 {
            return Err(invalid("CPU accounting observation bound"));
        }
        Ok(bytes)
    };
    let first = loop {
        remaining(deadline)?;
        let value = read()?;
        if value.lines().any(|line| {
            line.split_whitespace().collect::<Vec<_>>() == ["hepta_watchdog_status", "1"]
        }) {
            break value;
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    std::thread::sleep(Duration::from_millis(20));
    Ok((first, read()?))
}
