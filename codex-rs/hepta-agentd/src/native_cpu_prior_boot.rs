//! Two real kernel boots over the same retained installation. The saved cut is
//! an observation only; original cold-open factories provide every authority.
use super::*;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointToken;

#[path = "native_cpu_prior_boot_state.rs"]
mod state;
use state::PinObservation;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SavedCut {
    schema_version: u32,
    nonce: String,
    kernel_boot: [u8; 16],
    current_token: CognitiveCheckpointToken,
    occurrence_key: String,
    payload_json: String,
    material_sha256: String,
    frontiers: [FinalUseFrontier; 2],
    boundary: FaultBoundary,
    installation: PinObservation,
    source_database: serde_json::Value,
    authority_before_sha256: codex_hepta_contracts::Sha256Digest,
    issuer_sequence_at_cut: u64,
}

pub(crate) fn run(
    evidence: &mut evidence::Evidence,
    boot: &NativeBootstrap,
    active: &mut Active,
    installation: &Arc<Mutex<Installation>>,
) -> io::Result<()> {
    let pin = state::pin(&installation.lock().map_err(error)?.config)?;
    let cold = installation.lock().map_err(error)?.cold_observation.clone();
    evidence.emit(
        "boot_phase",
        serde_json::json!({"phase":if cold.is_some(){"retained"}else{"fresh"},
        "kernel_boot":boot.id(96),"installation":pin}),
    )?;
    match cold {
        None => {
            evidence.begin(boot, active)?;
            source_cut(evidence, boot, active, installation, pin)
        }
        Some(cold) => reopened(evidence, boot, active, installation, pin, cold),
    }
}

fn source_cut(
    evidence: &mut evidence::Evidence,
    boot: &NativeBootstrap,
    active: &mut Active,
    installation: &Arc<Mutex<Installation>>,
    pin: PinObservation,
) -> io::Result<()> {
    let transport = active.rpc.call(commands::Command::TransportObservation)?;
    state::require_zero_calls(&transport["ioctl_counts"])?;
    if transport["startup_retained"]
        .as_array()
        .is_none_or(|rows| !rows.is_empty())
    {
        return Err(invalid(
            "first boot must have no pre-existing pending operation",
        ));
    }
    let authority_before = state::authority(&*installation.lock().map_err(error)?)?;
    let prepared = prepared(evidence, active, "prior-boot-unresolved")?;
    active.rpc.send(&commands::Command::DispatchCopyout {
        occurrence_key: prepared.key.clone(),
        hold_until_exit: true,
    })?;
    let boundary: FaultBoundary = active.rpc.read()?;
    require_diagnostic(&boundary.diagnostic, &prepared.request)?;
    if boundary.phase != "copyout_fault_boundary"
        || boundary.pid != active.registration.peer_pid
        || boundary.occurrence_key != prepared.key
        || boundary
            .pending_until_boottime_ns
            .checked_sub(boundary.observed_boottime_ns)
            .is_none_or(|span| span == 0 || span > 2_000_000_000)
        || now()? < boundary.observed_boottime_ns
    {
        return Err(invalid("actual prior-boot copyout boundary differs"));
    }
    remaining(boundary.pending_until_boottime_ns)?;
    let current = active.service.native_cpu_current()?;
    let protected = active.service.capture_public_bootstrap()?;
    if protected.checkpoint != current.head
        || current.head.phase != CognitiveCheckpointPhase::Current
        || current.head.peer_lifetime != *active.retained.lifetime()
    {
        return Err(invalid(
            "original pre-effect Current is unavailable at VM fault cut",
        ));
    }
    let frontiers = [
        protected.consumers.device.frontier,
        protected.consumers.notes.frontier,
    ];
    let (material_path, material_sha256) = evidence::material(active, &current)?;
    let original = installation.lock().map_err(error)?;
    let canonical = original.issuer.retained_writer_state_for_root()?;
    if canonical.registration != active.bundle.writer
        || canonical.proof != active.bundle.writer_proof
    {
        return Err(invalid("original canonical writer changed at VM fault cut"));
    }
    let cut = SavedCut {
        schema_version: 1,
        nonce: evidence.nonce().into(),
        kernel_boot: boot.id(96),
        current_token: current.token.clone(),
        occurrence_key: prepared.key,
        payload_json: prepared.payload,
        material_sha256,
        frontiers,
        boundary,
        installation: pin,
        source_database: transport,
        authority_before_sha256: codex_hepta_contracts::Sha256Digest::for_bytes(
            &serde_json::to_vec(&authority_before).map_err(error)?,
        ),
        issuer_sequence_at_cut: canonical.sequence,
    };
    let id = state::observation_id(&current.head.peer_lifetime.boot_id, evidence.nonce());
    let bytes = serde_json::to_vec(&cut).map_err(error)?;
    let saved = original
        .launch_observations
        .save_observation(&id, &bytes)
        .map_err(error)?;
    saved.verify_durable().map_err(error)?;
    let record_path = state::observation_path(&original.config, &id);
    drop(original);
    let at_emit = now()?;
    if at_emit >= cut.boundary.pending_until_boottime_ns {
        return Err(invalid(
            "original copyout wait expired before durable VM fault cut",
        ));
    }
    evidence.emit(
        "prior_boot_cut",
        serde_json::json!({"current":current,
        "material_path":material_path,"authority_before_dispatch":authority_before,
        "observation_id":id,"observation_path":record_path,
        "durable_payload_json":std::str::from_utf8(saved.payload()).map_err(error)?,
        "durable_payload_sha256":codex_hepta_contracts::Sha256Digest::for_bytes(saved.payload()),
        "emitted_boottime_ns":at_emit}),
    )?;
    // The guest samples above bound the durable cut before callback expiry.
    // The host records its actual SIGKILL separately; no host/guest clock
    // conversion proves the kill instant. Offline live DB/WAL plus retained
    // material must independently show the old K has no source terminal.
    loop {
        remaining(cut.boundary.pending_until_boottime_ns)?;
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn reopened(
    evidence: &mut evidence::Evidence,
    boot: &NativeBootstrap,
    active: &mut Active,
    installation: &Arc<Mutex<Installation>>,
    pin: PinObservation,
    cold: serde_json::Value,
) -> io::Result<()> {
    let previous: CognitiveCheckpointReceipt =
        serde_json::from_value(cold["previous"].clone()).map_err(error)?;
    let original = installation.lock().map_err(error)?;
    let id = state::observation_id(&previous.head.peer_lifetime.boot_id, evidence.nonce());
    let saved = original
        .launch_observations
        .open_observation(&id)
        .map_err(error)?;
    let cut: SavedCut = serde_json::from_slice(saved.payload()).map_err(error)?;
    let record_path = state::observation_path(&original.config, &id);
    drop(original);
    let request = Hos2InstallBudgetV1::from_json(&cut.payload_json).map_err(error)?;
    require_diagnostic(&cut.boundary.diagnostic, &request)?;
    if cut.schema_version != 1
        || cut.nonce != evidence.nonce()
        || cut.installation != pin
        || cut.kernel_boot == boot.id(96)
        || cut.kernel_boot != request.delivery.boot_id
        || cut.current_token != previous.token
        || cut.boundary.occurrence_key != cut.occurrence_key
        || previous.head.phase != CognitiveCheckpointPhase::Current
        || cold["issuer_sequence"].as_u64() != Some(cut.issuer_sequence_at_cut)
        || evidence::material(active, &previous)?.1 != cut.material_sha256
    {
        return Err(invalid(
            "retained observation differs from original cold-open predecessor",
        ));
    }
    saved.verify_durable().map_err(error)?;
    let adopted = active
        .adopted
        .as_ref()
        .ok_or_else(|| invalid("original physical adoption receipt absent"))?;
    if adopted.head.last_current != previous.head.last_current
        || adopted.head.peer_lifetime.boot_id == previous.head.peer_lifetime.boot_id
    {
        return Err(invalid(
            "actual original physical adoption did not cross the observed boot",
        ));
    }
    evidence.emit(
        "prior_boot_adopted",
        serde_json::json!({"cold_open":cold,"successor":adopted,
        "observation_id":id,"observation_path":record_path,
        "durable_payload_json":std::str::from_utf8(saved.payload()).map_err(error)?,
        "durable_payload_sha256":codex_hepta_contracts::Sha256Digest::for_bytes(saved.payload())}),
    )?;
    evidence.begin(boot, active)?;
    let transport = active.rpc.call(commands::Command::TransportObservation)?;
    state::require_zero_calls(&transport["ioctl_counts"])?;
    let startup: Vec<commands::StartupRetained> =
        serde_json::from_value(transport["startup_retained"].clone()).map_err(error)?;
    if startup.len() != 1
        || startup[0].occurrence_key != cut.occurrence_key
        || startup[0].topic != codex_hepta_memory::HOS2_INSTALL_TOPIC_V1
        || startup[0].payload_json != cut.payload_json
        || startup[0].state != LocalOutcomeState::Indeterminate
    {
        return Err(invalid(
            "original recovered writer did not capture the prior-boot Unknown before monitor",
        ));
    }
    let first = active.rpc.call(commands::Command::ObservePreviousBoot {
        occurrence_key: cut.occurrence_key.clone(),
    })?;
    state::require_unknown(&first, &cut)?;
    state::require_zero_calls(&first["calls_before"])?;
    if first["device_frontier"] != serde_json::to_value(cut.frontiers[0]).map_err(error)?
        || first["notes_frontier"] != serde_json::to_value(cut.frontiers[1]).map_err(error)?
    {
        return Err(invalid(
            "claimed original FinalUse state was not retained across boot",
        ));
    }
    evidence.emit(
        "prior_boot_observed",
        serde_json::json!({"phase":"before_new_effect",
        "transport":transport,"observation":first}),
    )?;
    let terminal = evidence.operation("new-boot-control", 25_000_000, active)?;
    if terminal.request.delivery.boot_id != boot.id(96)
        || terminal.request.delivery == request.delivery
    {
        return Err(invalid(
            "new native effect did not use a new boot namespace",
        ));
    }
    evidence.acknowledge(&terminal, active)?;
    evidence.window("new-boot-control", active)?;
    let final_old = active.rpc.call(commands::Command::ObservePreviousBoot {
        occurrence_key: cut.occurrence_key.clone(),
    })?;
    state::require_unknown(&final_old, &cut)?;
    let current = active.service.native_cpu_current()?;
    let material = evidence::material(active, &current)?;
    let authority = state::authority(&*installation.lock().map_err(error)?)?;
    evidence.emit("prior_boot_observed", serde_json::json!({"phase":"after_new_effect",
        "transport":active.rpc.call(commands::Command::TransportObservation)?,"observation":final_old}))?;
    File::open("/state")?.sync_all()?;
    evidence.emit(
        "prior_boot_complete",
        serde_json::json!({"current":current,
        "material_path":material.0,"material_sha256":material.1,"authority":authority,
        "unresolved_occurrence_key":cut.occurrence_key,"drain_blockers":final_old["drain_blockers"],
        "shutdown":"poweroff_with_unresolved_previous_boot"}),
    )?;
    // Preserve the old Unknown and its successful original Current. No drain,
    // local-lease release, synthetic terminal or graceful-exit claim is made.
    unsafe {
        libc::sync();
        libc::reboot(libc::RB_POWER_OFF);
    }
    Err(invalid("prior-boot native poweroff returned"))
}
