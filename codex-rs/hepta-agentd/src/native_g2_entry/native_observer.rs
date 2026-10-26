//! Read-only native Recovery observation while original Supervisor waits to select it.
use super::supervisor;
use codex_hepta_agentd::AgentdHos2Device;
use codex_hepta_agentd::AgentdHos2Usage;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use serde_json::Value;
use std::sync::Arc;
use std::time::Duration;

pub(super) const SOCKET: &str = "/run/hepta-g2/recovery-observer.sock";

pub(super) fn spawn(device: Arc<AgentdHos2Device>) -> std::io::Result<std::thread::JoinHandle<()>> {
    std::thread::Builder::new()
        .name("native-recovery-observe".into())
        .spawn(move || {
            let _ = serve(device);
        })
}
fn serve(device: Arc<AgentdHos2Device>) -> Result<(), Box<dyn std::error::Error>> {
    let stream = supervisor::connect_parent(std::path::Path::new(SOCKET))?;
    let mut channel = HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid: 0, pid: 1 },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(110),
            request_bound: 64,
            response_bound: 4096,
        },
        supervisor::pin(1)?,
    )?;
    while channel.exchange(|request| {
        if request != b"read-native-usage-v1" {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        let usage = device
            .read_usage(/*request_id*/ 1)
            .map_err(|_| HostIssuerTransportError::Unavailable)?;
        serde_json::to_vec(&value(usage)).map_err(|_| HostIssuerTransportError::Unavailable)
    })? {}
    Ok(())
}

pub(super) fn read(
    channel: &mut HostAuthorityPeerChannel,
    heartbeat: u64,
) -> Result<Value, Box<dyn std::error::Error>> {
    let mut value: Value = serde_json::from_slice(&channel.request(b"read-native-usage-v1")?)?;
    value
        .as_object_mut()
        .ok_or("native usage is not an object")?
        .insert("heartbeat".into(), heartbeat.into());
    Ok(value)
}

pub(super) fn value(usage: AgentdHos2Usage) -> Value {
    serde_json::json!({"boot_id":usage.boot_id,"observer_space_id":usage.observer_space_id,"revision":usage.revision,
        "sample_boottime_ns":usage.sample_boottime_ns,"cumulative_cpu_ns":usage.cumulative_cpu_ns,
        "window_start_ns":usage.window_start_ns,"window_consumed_ns":usage.window_consumed_ns,
        "active_cap_ns":usage.active_cap_ns,"active_period_ns":usage.active_period_ns,
        "event_sequence":usage.event_sequence,"dropped_events":usage.dropped_events})
}
