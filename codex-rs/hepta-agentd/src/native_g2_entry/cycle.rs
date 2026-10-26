//! Original K/D dispatch, publication readback and durable-prefix retirement.
use super::evidence::Evidence;
use super::owner::Command;
use super::workload::Heartbeat;
use codex_hepta_agentd::HostPhysicalCurrentObservation;
use codex_hepta_agentd::PreparedHostAuthoritySession;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::ProductionDispatchReceipt;
use codex_hepta_memory::ProductionQueuedReceipt;
use serde_json::Value;
use std::time::Duration;

pub(super) fn request(
    channel: &mut HostAuthorityPeerChannel,
    command: Command,
) -> Result<Value, Box<dyn std::error::Error>> {
    Ok(serde_json::from_slice(
        &channel.request(&serde_json::to_vec(&command)?)?,
    )?)
}

pub(super) fn usage(
    channel: &mut HostAuthorityPeerChannel,
    heartbeat: &Heartbeat,
) -> Result<Value, Box<dyn std::error::Error>> {
    let mut usage = request(channel, Command::Observe)?;
    usage
        .as_object_mut()
        .ok_or("native usage was not an object")?
        .insert("heartbeat".into(), heartbeat.read().into());
    Ok(usage)
}

pub(super) fn current(
    channel: &mut HostAuthorityPeerChannel,
    root: &PreparedHostAuthoritySession,
) -> Result<(Value, HostPhysicalCurrentObservation), Box<dyn std::error::Error>> {
    let owner = request(channel, Command::Current)?;
    let physical = root.observe_physical_current()?;
    if owner["current"] != serde_json::to_value(physical.current())? {
        return Err("actual independent Root Current differs from original writer readback".into());
    }
    Ok((owner, physical))
}

pub(super) fn operate(
    evidence: &mut Evidence,
    channel: &mut HostAuthorityPeerChannel,
    root: &PreparedHostAuthoritySession,
    heartbeat: &Heartbeat,
    pid: u32,
    name: &str,
    cap: u64,
    retire: bool,
) -> Result<(ProductionQueuedReceipt, ProductionDispatchReceipt, Value), Box<dyn std::error::Error>>
{
    let before = usage(channel, heartbeat)?;
    let revision = before["revision"]
        .as_u64()
        .ok_or("actual revision absent")?;
    let queued: ProductionQueuedReceipt = serde_json::from_value(request(
        channel,
        Command::Prepare {
            operation_id: format!("native-g2-{name}"),
            expected_revision: revision,
            cap_ns: cap,
        },
    )?)?;
    let native = Hos2InstallBudgetV1::from_json(&queued.payload_json)?;
    evidence.emit(
        "prepared",
        serde_json::json!({"operation":name,"pid":pid,
        "occurrence_key":queued.occurrence_key,"request_json":queued.payload_json,
        "payload_sha256":queued.payload_sha256}),
    )?;
    // This is the sole dispatch call. Unknown/transport failure propagates;
    // there is no entry-level retry, public apply/reject or fabricated receipt.
    let dispatch: ProductionDispatchReceipt = serde_json::from_value(request(
        channel,
        Command::Dispatch {
            queued: queued.clone(),
        },
    )?)?;
    let after = usage(channel, heartbeat)?;
    let terminal = dispatch
        .target_receipt
        .as_ref()
        .ok_or("actual original terminal absent")?;
    evidence.emit(
        "native_result",
        serde_json::json!({"operation":name,"pid":pid,
        "terminal_json":terminal,"before":before,"after":after}),
    )?;
    let current = source(evidence, channel, root, pid, name, &queued, &dispatch)?;
    if retire {
        acknowledge(evidence, channel, pid, name, &queued, &current, &native)?;
        window(evidence, channel, heartbeat, pid, name)?;
    }
    Ok((queued, dispatch, current))
}

pub(super) fn source(
    evidence: &mut Evidence,
    channel: &mut HostAuthorityPeerChannel,
    root: &PreparedHostAuthoritySession,
    pid: u32,
    name: &str,
    queued: &ProductionQueuedReceipt,
    dispatch: &ProductionDispatchReceipt,
) -> Result<Value, Box<dyn std::error::Error>> {
    let (owner, physical) = current(channel, root)?;
    evidence.emit(
        "source_terminal",
        serde_json::json!({"operation":name,"pid":pid,
        "occurrence_key":queued.occurrence_key,"state":dispatch.state,
        "terminal_json":dispatch.target_receipt.as_ref().ok_or("actual retained terminal absent")?,
        "local_event_id":dispatch.local_event_id,"current":physical.current(),
        "material_sha256":physical.material_sha256(),"device_frontier":owner["device_frontier"],
        "notes_frontier":owner["notes_frontier"]}),
    )?;
    Ok(serde_json::to_value(physical.current())?)
}

pub(super) fn acknowledge(
    evidence: &mut Evidence,
    channel: &mut HostAuthorityPeerChannel,
    pid: u32,
    name: &str,
    queued: &ProductionQueuedReceipt,
    current: &Value,
    native: &Hos2InstallBudgetV1,
) -> Result<(), Box<dyn std::error::Error>> {
    let retired = request(
        channel,
        Command::Retire {
            through: native.delivery.clone(),
        },
    )?;
    evidence.emit("history_ack",serde_json::json!({"operation":name,"pid":pid,"delivery":native.delivery,
        "source_owner":queued.owner_agent_id,"source_generation":current["head"]["writer_binding"]["generation"],
        "retired_through":retired["retired_through"],"next_sequence":retired["next_sequence"],
        "current_token":current["token"]}))?;
    Ok(())
}

pub(super) fn window(
    evidence: &mut Evidence,
    channel: &mut HostAuthorityPeerChannel,
    heartbeat: &Heartbeat,
    pid: u32,
    name: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    let first = usage(channel, heartbeat)?;
    std::thread::sleep(Duration::from_millis(250));
    let second = usage(channel, heartbeat)?;
    evidence.emit(
        "usage_window",
        serde_json::json!({"operation":name,"pid":pid,"first":first,"second":second}),
    )?;
    Ok(())
}
