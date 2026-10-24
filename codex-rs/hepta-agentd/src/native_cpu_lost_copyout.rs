//! Real response loss at the original FileTransport and original owner recovery.
//! All K/D, terminal, Current, nonce frontier and child custody values come from
//! their existing owners. This module only plans faults and checks observations.

use super::*;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::Hos2DeliveryObservation;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionDispatchReceipt;
use codex_hepta_memory::ProductionOutcomeReceipt;
use codex_hepta_memory::ProductionTargetDisposition;
use codex_hepta_supervisor::ProcessDriverError;
use serde::Deserialize;
use serde::Serialize;
use std::os::fd::BorrowedFd;

#[path = "native_cpu_prior_boot.rs"]
pub(super) mod prior_boot;

struct Prepared {
    operation: &'static str,
    key: String,
    request: Hos2InstallBudgetV1,
    payload: String,
    payload_sha256: codex_hepta_contracts::Sha256Digest,
    before: serde_json::Value,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Diagnostic {
    install_ioctl_count: u64,
    selected_ioctl_count: u64,
    efault_count: u64,
    request_sha256: [u8; 32],
    request_bytes: usize,
    response_capacity: usize,
    syscall_return: i32,
    errno: Option<i32>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Snapshot {
    install_ioctl_count: u64,
    selected_ioctl_count: u64,
    efault_count: u64,
    armed: bool,
    last: Option<Diagnostic>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FaultBoundary {
    phase: String,
    pid: u32,
    occurrence_key: String,
    diagnostic: Diagnostic,
    observed_boottime_ns: u64,
    pending_until_boottime_ns: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalTerminal {
    schema_version: u32,
    request: Hos2InstallBudgetV1,
    observation: Hos2DeliveryObservation,
}

fn prepared(
    evidence: &mut evidence::Evidence,
    active: &mut Active,
    operation: &'static str,
) -> io::Result<Prepared> {
    let inspected = active.rpc.call(commands::Command::Inspect)?;
    require_snapshot(&inspected["copyout"], None, 0)?;
    let value = active.rpc.call(commands::Command::Prepare {
        operation: operation.into(),
        cap_ns: 25_000_000,
    })?;
    let key = value["occurrence_key"]
        .as_str()
        .ok_or_else(|| invalid("original prepared K absent"))?
        .to_owned();
    let payload = value["request_json"]
        .as_str()
        .ok_or_else(|| invalid("original prepared payload absent"))?
        .to_owned();
    let request = Hos2InstallBudgetV1::from_json(&payload).map_err(error)?;
    let payload_sha256 = codex_hepta_contracts::Sha256Digest::for_bytes(payload.as_bytes());
    if value["pid"].as_u64() != Some(u64::from(active.registration.peer_pid))
        || value["operation"].as_str() != Some(operation)
        || value["payload_sha256"] != serde_json::to_value(&payload_sha256).map_err(error)?
        || request.cap_ns != 25_000_000
        || request.delivery.sequence().map_err(error)? != 1
        || inspected["usage"]["revision"].as_u64() != Some(request.expected_revision)
    {
        return Err(invalid(
            "prepared copyout operation differs from original first K/D",
        ));
    }
    evidence.emit("prepared", value)?;
    Ok(Prepared {
        operation,
        key,
        request,
        payload,
        payload_sha256,
        before: inspected["usage"].clone(),
    })
}

/// Independent identity check of the existing fixed Install codec. These bytes
/// are hashed for observation only; they are never submitted to the device.
fn expected_wire_sha256(request: &Hos2InstallBudgetV1) -> io::Result<[u8; 32]> {
    request.to_json().map_err(error)?;
    let mut frame = [0_u8; 96];
    frame[..4].copy_from_slice(b"HOS2");
    frame[4..6].copy_from_slice(&2_u16.to_le_bytes());
    frame[8..10].copy_from_slice(&3_u16.to_le_bytes());
    frame[12..16].copy_from_slice(&64_u32.to_le_bytes());
    frame[16..20].copy_from_slice(&32_u32.to_le_bytes());
    for (offset, value) in [
        (24, request.delivery.sequence().map_err(error)?),
        (40, request.manage_slot),
        (48, request.manage_generation),
        (64, request.expected_revision),
        (72, request.period_ns),
        (80, request.cap_ns),
    ] {
        frame[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    Ok(Sha256::digest(frame).into())
}

fn require_diagnostic(value: &Diagnostic, request: &Hos2InstallBudgetV1) -> io::Result<()> {
    if value.install_ioctl_count != 1
        || value.selected_ioctl_count != 1
        || value.efault_count != 1
        || value.request_bytes != 96
        || value.response_capacity != 128
        || value.syscall_return != -1
        || value.errno != Some(libc::EFAULT)
        || value.request_sha256 != expected_wire_sha256(request)?
    {
        return Err(invalid(
            "actual original FileTransport did not observe the exact one-shot EFAULT",
        ));
    }
    Ok(())
}

fn require_snapshot(
    value: &serde_json::Value,
    request: Option<&Hos2InstallBudgetV1>,
    calls: u64,
) -> io::Result<()> {
    let value: Snapshot = serde_json::from_value(value.clone()).map_err(error)?;
    if value.armed || value.install_ioctl_count != calls {
        return Err(invalid(
            "original copyout descriptor dispatched an unexpected number of Installs",
        ));
    }
    match (calls, request, value.last.as_ref()) {
        (0, None, None) if value.selected_ioctl_count == 0 && value.efault_count == 0 => Ok(()),
        (1, Some(request), Some(diagnostic))
            if value.selected_ioctl_count == 1 && value.efault_count == 1 =>
        {
            require_diagnostic(diagnostic, request)
        }
        _ => Err(invalid(
            "copyout observation belongs to a different original descriptor",
        )),
    }
}

fn reconcile(
    evidence: &mut evidence::Evidence,
    active: &mut Active,
    prepared: &Prepared,
    previous_calls: u64,
) -> io::Result<evidence::SourceTerminal> {
    let actual = active.rpc.call(commands::Command::ReconcileCopyout {
        occurrence_key: prepared.key.clone(),
    })?;
    let request = Hos2InstallBudgetV1::from_json(
        actual["request_json"]
            .as_str()
            .ok_or_else(|| invalid("original observed request absent"))?,
    )
    .map_err(error)?;
    let receipt: ProductionOutcomeReceipt =
        serde_json::from_value(actual["receipt"].clone()).map_err(error)?;
    let terminal_json = actual["terminal_json"]
        .as_str()
        .ok_or_else(|| invalid("original observed terminal absent"))?
        .to_owned();
    let terminal: OriginalTerminal = serde_json::from_str(&terminal_json).map_err(error)?;
    if request != prepared.request
        || terminal.request != request
        || terminal.schema_version != 1
        || serde_json::to_string(&terminal).map_err(error)? != terminal_json
        || actual["before_payload_json"].as_str() != Some(prepared.payload.as_str())
        || receipt.occurrence_key != prepared.key
        || receipt.state != LocalOutcomeState::Committed
        || receipt.external_effect
        || receipt.event_id.is_empty()
        || actual["pid"].as_u64() != Some(u64::from(active.registration.peer_pid))
    {
        return Err(invalid(
            "original observed copyout terminal changed the immutable K/D",
        ));
    }
    match terminal.observation {
        Hos2DeliveryObservation::Applied {
            stable_object_id,
            previous_revision,
            revision,
            effective_ns,
            consumed_ns,
        } if stable_object_id != [0; 16]
            && previous_revision == request.expected_revision
            && previous_revision.checked_add(1) == Some(revision)
            && consumed_ns <= effective_ns % request.period_ns => {}
        _ => {
            return Err(invalid(
                "lost copyout did not resolve to its actual original Applied receipt",
            ));
        }
    }
    require_snapshot(
        &actual["copyout"],
        (previous_calls == 1).then_some(&request),
        previous_calls,
    )?;
    let mut observation = actual
        .as_object()
        .cloned()
        .ok_or_else(|| invalid("original copyout reconciliation shape"))?;
    observation.insert("operation".into(), serde_json::json!(prepared.operation));
    observation.insert("occurrence_key".into(), serde_json::json!(prepared.key));
    evidence.emit("copyout_reconciled", observation)?;
    evidence.reconciled_copyout_terminal(
        prepared.operation,
        prepared.key.clone(),
        request,
        receipt,
        terminal_json,
        active,
    )
}

pub(super) fn live(evidence: &mut evidence::Evidence, active: &mut Active) -> io::Result<()> {
    let prepared = prepared(evidence, active, "lost-copyout-live")?;
    let actual = active.rpc.call(commands::Command::DispatchCopyout {
        occurrence_key: prepared.key.clone(),
        hold_until_exit: false,
    })?;
    let receipt: ProductionDispatchReceipt =
        serde_json::from_value(actual["receipt"].clone()).map_err(error)?;
    if receipt.request.occurrence_key != prepared.key
        || receipt.request.idempotency_key != prepared.key
        || receipt.request.payload_json != prepared.payload
        || receipt.request.payload_sha256 != prepared.payload_sha256
        || receipt.request.topic != codex_hepta_memory::HOS2_INSTALL_TOPIC_V1
        || receipt.state != LocalOutcomeState::Indeterminate
        || receipt.target_disposition != ProductionTargetDisposition::Indeterminate
        || receipt.target_receipt.is_some()
        || receipt.external_effect
        || receipt.local_event_id.is_empty()
    {
        return Err(invalid(
            "original returned copyout receipt was not Indeterminate",
        ));
    }
    require_snapshot(&actual["copyout"], Some(&prepared.request), 1)?;
    let mut observation = actual
        .as_object()
        .cloned()
        .ok_or_else(|| invalid("actual copyout response shape"))?;
    observation.insert("operation".into(), serde_json::json!(prepared.operation));
    observation.insert("occurrence_key".into(), serde_json::json!(prepared.key));
    // The immutable returned receipt was Unknown. The monitor is free to
    // reconcile; a later Current is never mislabeled as the old Unknown cut.
    evidence.emit("copyout_indeterminate", observation)?;
    let terminal = reconcile(evidence, active, &prepared, 1)?;
    evidence.acknowledge(&terminal, active)?;
    evidence.window(prepared.operation, active)
}

pub(super) fn before_terminal<F>(
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
    let prepared = prepared(evidence, &mut old, "lost-before-terminal")?;
    old.rpc.send(&commands::Command::DispatchCopyout {
        occurrence_key: prepared.key.clone(),
        hold_until_exit: true,
    })?;
    let boundary: FaultBoundary = old.rpc.read()?;
    require_diagnostic(&boundary.diagnostic, &prepared.request)?;
    if boundary.phase != "copyout_fault_boundary"
        || boundary.occurrence_key != prepared.key
        || boundary.pid != old.registration.peer_pid
        || boundary
            .pending_until_boottime_ns
            .checked_sub(boundary.observed_boottime_ns)
            .is_none_or(|span| span == 0 || span > 2_000_000_000)
        || now()? < boundary.observed_boottime_ns
    {
        return Err(invalid(
            "copyout boundary differs from the one outstanding original command",
        ));
    }
    remaining(boundary.pending_until_boottime_ns)?;
    let current = old.service.native_cpu_current()?;
    // This is the Root's original protected capture, not the blocked Host's
    // FinalUseAuthority::frontier() or another consumer/store incarnation.
    let protected = old.service.capture_public_bootstrap()?;
    if protected.checkpoint != current.head
        || current.head.phase != CognitiveCheckpointPhase::Current
        || current.head.peer_lifetime != *old.retained.lifetime()
    {
        return Err(invalid(
            "pre-effect original Current changed at the copyout boundary",
        ));
    }
    let frontiers = [
        protected.consumers.device.frontier,
        protected.consumers.notes.frontier,
    ];
    let material_sha256 = evidence::material(&old, &current)?.1;
    remaining(boundary.pending_until_boottime_ns)?;
    evidence.emit("copyout_boundary", serde_json::json!({"operation":prepared.operation,"pid":boundary.pid,
        "occurrence_key":prepared.key,"request_json":prepared.payload,"payload_sha256":prepared.payload_sha256,
        "before":prepared.before,"diagnostic":boundary.diagnostic,
        "observed_boottime_ns":boundary.observed_boottime_ns,"pending_until_boottime_ns":boundary.pending_until_boottime_ns,
        "current":current,"material_sha256":material_sha256,"device_frontier":frontiers[0],"notes_frontier":frontiers[1]}))?;
    let mut next = recovery::recover_after_crash(
        evidence,
        old,
        recovery::CrashCheckpoint {
            current,
            material_sha256,
            frontiers,
            kill_before: Some(boundary.pending_until_boottime_ns),
        },
        installation,
        active,
        supervisor,
        agent,
        deadline,
    )?;
    let inspected = next.rpc.call(commands::Command::Inspect)?;
    let captured: Vec<commands::StartupRetained> =
        serde_json::from_value(inspected["startup_retained"].clone()).map_err(error)?;
    if captured.len() != 1
        || captured[0].occurrence_key != prepared.key
        || captured[0].topic != codex_hepta_memory::HOS2_INSTALL_TOPIC_V1
        || captured[0].payload_json != prepared.payload
        || captured[0].state != LocalOutcomeState::Indeterminate
    {
        return Err(invalid(
            "original recovered writer did not capture the same Unknown before monitor startup",
        ));
    }
    require_snapshot(&inspected["copyout"], None, 0)?;
    evidence.emit(
        "copyout_recovery_startup",
        serde_json::json!({"pid":next.registration.peer_pid,
        "occurrence_key":prepared.key,"capture_point":"original_recovery_before_monitor",
        "captured":captured,"copyout":inspected["copyout"]}),
    )?;
    let terminal = reconcile(evidence, &mut next, &prepared, 0)?;
    if terminal.frontiers != frontiers {
        return Err(invalid(
            "observing the original lost D changed retained FinalUse frontiers",
        ));
    }
    evidence.acknowledge(&terminal, &mut next)?;
    evidence.window(prepared.operation, &mut next)?;
    Ok(next)
}
