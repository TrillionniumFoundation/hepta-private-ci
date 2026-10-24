//! Real repeated original owners beyond both initial finite kernel grants.
use super::*;
use std::collections::BTreeSet;

pub(in super::super) fn renewal<F>(
    evidence: &mut evidence::Evidence,
    mut owner: Active,
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
    let first = owner.rpc.call(commands::Command::Inspect)?;
    let sample = first["usage"]["sample_boottime_ns"]
        .as_u64()
        .ok_or_else(|| invalid("initial actual CPU sample absent"))?;
    let threshold = sample
        .checked_add(330_000_000_000)
        .ok_or_else(|| invalid("initial finite grant endpoint overflow"))?;
    evidence.emit(
        "renewal_origin",
        serde_json::json!({"initial_usage":first["usage"],"after_boottime_ns":threshold,
        "initial_root_lease":owner.root_lease,"initial_writer":owner.bundle.writer}),
    )?;
    emit_owner(evidence, &mut owner, supervisor, agent)?;
    let mut fresh_pairs = BTreeSet::new();
    for _ in 0..64 {
        remaining(deadline)?;
        if owner.image.role != 1 {
            return Err(invalid(
                "continued CPU effect requires the actual Manager image",
            ));
        }
        if owner.image.generation() > 0 {
            fresh_pairs.insert(owner.image.generation());
        }
        let terminal = evidence.operation("continued-control", 25_000_000, &mut owner)?;
        evidence.acknowledge(&terminal, &mut owner)?;
        evidence.window("continued-control", &mut owner)?;
        let original: serde_json::Value =
            serde_json::from_str(&terminal.terminal_json).map_err(error)?;
        let observed: Hos2DeliveryObservation =
            serde_json::from_value(original["observation"].clone()).map_err(error)?;
        let Hos2DeliveryObservation::Applied { effective_ns, .. } = observed else {
            return Err(invalid(
                "continued original Manager did not produce an actual Applied effect",
            ));
        };
        if effective_ns > threshold && fresh_pairs.len() >= 2 {
            evidence.emit("renewal_endpoint",serde_json::json!({"initial_sample_boottime_ns":sample,
                "after_boottime_ns":threshold,"actual_terminal_json":terminal.terminal_json,
                "occurrence_key":terminal.key,"delivery":terminal.request.delivery,
                "fresh_kernel_generations":fresh_pairs,"root_lease":owner.root_lease,"writer":owner.bundle.writer}))?;
            return Ok(owner);
        }
        // Keep this same actual Manager controlling the original workload for
        // part of its finite writer lease. Reserve the final eight seconds for
        // ordinary drain, terminal Current, authenticated observation and exit.
        let hold_until = owner
            .bundle
            .writer
            .authority_lease
            .issued_at_unix_ms
            .checked_add(12_000)
            .ok_or_else(|| invalid("finite owner hold overflow"))?;
        loop {
            remaining(deadline)?;
            let unix = installation
                .lock()
                .map_err(error)?
                .clock
                .now_unix_ms()
                .map_err(error)?;
            if unix >= hold_until {
                break;
            }
            let report = supervisor.tick(Instant::now());
            if !report.faults.is_empty()
                || !supervisor
                    .snapshot(agent)
                    .is_some_and(|snapshot| snapshot.healthy)
            {
                return Err(invalid(
                    "original Manager lost health during continued CPU control",
                ));
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        let previous = stop_owner(evidence, &mut owner, supervisor, agent, deadline, true)?;
        drop(owner);
        owner = next_owner(
            evidence,
            previous,
            installation,
            active,
            supervisor,
            agent,
            deadline,
        )?;
        if owner.image.role != 3 {
            return Err(invalid(
                "original finite pair did not provide its Recovery slot",
            ));
        }
        let previous = stop_owner(evidence, &mut owner, supervisor, agent, deadline, true)?;
        drop(owner);
        owner = next_owner(
            evidence,
            previous,
            installation,
            active,
            supervisor,
            agent,
            deadline,
        )?;
    }
    Err(invalid(
        "bounded continuity campaign did not reach a real effect after the initial finite grants",
    ))
}
