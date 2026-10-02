//! Existing bounded resource reader and ordinary typed Agentd delivery.
use super::*;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::FleetExecutionResourceObservationV1;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_contracts::AgentId;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Observation {
    observed_at_ms: u64,
    boot_identity: String,
    resource_authority_epoch: u64,
    observation: FleetExecutionResourceObservationV1,
}
impl PartialEq for Observation {
    fn eq(&self, other: &Self) -> bool {
        // Renewal may advance the lease while the same exact execution stays
        // current. Each observation separately verifies its actual live grant.
        self.boot_identity == other.boot_identity
            && self.resource_authority_epoch == other.resource_authority_epoch
            && self.observation.context == other.observation.context
            && self.observation.process_id == other.observation.process_id
            && self.observation.process_start_ticks == other.observation.process_start_ticks
    }
}

pub(super) fn observe(cfg: &Configuration) -> HostResult<Observation> {
    let program = model_use_program::Program::open(cfg.fleetctl.clone())?;
    let worker = model_use_program::Program::open(cfg.worker_program.clone())?;
    cfg.local_host_policy.read(64 * 1024)?;
    let mut child = Command::new(&cfg.fleetctl.path)
        .arg("--fleet-root")
        .arg(&cfg.fleet_root)
        .arg("resource-observe")
        .arg("--local-host-policy")
        .arg(&cfg.local_host_policy.path)
        .arg("--require-program-sha256")
        .arg(&cfg.worker_program.digest)
        .arg(&cfg.agent_id)
        .arg(cfg.process_id.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(3);
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if Instant::now() >= deadline {
            child.kill()?;
            child.wait()?;
            return Err("original bounded resource observer timed out".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    let mut bytes = Vec::new();
    child
        .stdout
        .take()
        .ok_or("resource observation stdout")?
        .take(16_385)
        .read_to_end(&mut bytes)?;
    if !status.success() || bytes.len() > 16_384 {
        return Err("original current resource observation rejected".into());
    }
    program.revalidate()?;
    worker.revalidate()?;
    let observed: Observation = serde_json::from_slice(&bytes)?;
    let grant = observed
        .observation
        .allocation
        .as_ref()
        .ok_or("no current original allocation")?;
    let now = now_ms()?;
    if observed.observed_at_ms > now
        || now.saturating_sub(observed.observed_at_ms) > 3_000
        || observed.resource_authority_epoch == 0
        || observed.boot_identity.is_empty()
        || observed.observation.process_id != cfg.process_id
        || observed.observation.context.principal_id != cfg.agent_id
        || observed.observation.process_start_ticks == 0
        || grant.principal_id != cfg.agent_id
        || grant.revoked
        || grant.expires_at_ms <= now
        || grant.authority_epoch != observed.resource_authority_epoch
        || grant.allocation_id != observed.observation.context.allocation_id
        || grant.resources != observed.observation.context.resources
    {
        return Err("current original resource tuple unavailable".into());
    }
    Ok(observed)
}

async fn client_for_packet(
    path: &Path,
    pin: Digest32,
) -> HostResult<(Source, Packet, AgentdClient)> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let packet: Packet = serde_json::from_slice(&bytes)?;
    if packet.schema != "hepta.cpu-neuron.root-signed-objective-packet.v1"
        || packet.ingress.issuer_id != ADAPTER
        || packet.ingress.key_epoch != 1
        || packet.state_mode
            != codex_hepta_agentd::ConservativeCpuStateModeV1::InactiveForConservativeAbstentionV1
    {
        return Err("closed signed CPU objective packet expired or invalid".into());
    }
    let cfg_bytes = packet.configuration.read(32 * 1024)?;
    let cfg: Configuration = serde_json::from_slice(&cfg_bytes)?;
    let agent: AgentId = packet.agent_id.parse()?;
    let registry = FleetRegistry::open_existing_for_agent(
        HeptaFleetRoot::parse(cfg.fleet_root.clone())?,
        &agent,
    )?;
    let record = registry.load_agent(&agent)?;
    let home = std::fs::metadata(record.layout.home_root())?;
    if rustix::process::geteuid().as_raw() != home.uid()
        || rustix::process::getegid().as_raw() != home.gid()
        || record.lifecycle.lifecycle != AgentLifecycle::Running
        || packet.agent_id != cfg.agent_id
        || packet.process_id != cfg.process_id
        || packet.ingress.body.spawn_generation != cfg.spawn_generation
        || packet.ingress.body.run_id != cfg.run_id
        || packet.ingress.message_id != cfg.message_id
        || packet.ingress.sequence != cfg.sequence
    {
        return Err("delivery differs from original workload owner or request".into());
    }
    let client = AgentdClient::new(
        record.layout.agentd_control_socket().to_owned(),
        agent,
        cfg.spawn_generation,
    )?;
    let health = client.health().await?;
    if !health.ready
        || health.fenced
        || health.process_id != cfg.process_id
        || health.home_root != record.layout.home_root()
        || health.run_root != record.layout.run_root()
        || health.lifecycle != AgentLifecycle::Running
        || source.read(64 * 1024)? != bytes
    {
        return Err("original live Agentd tuple changed before delivery".into());
    }
    Ok((source, packet, client))
}

pub(super) async fn deliver(path: &Path, pin: Digest32) -> HostResult<Value> {
    let (source, packet, client) = client_for_packet(path, pin).await?;
    if packet.ingress.expires_at_ms <= now_ms()? {
        return Err("signed objective expired before dispatch".into());
    }
    // One dispatch only. An EOF/timeout remains Unknown to the caller; inspect
    // the original run ID rather than minting another signature or request.
    let outcome = client.objective_start(packet.ingress).await?;
    Ok(serde_json::json!({
        "schema": "hepta.cpu-neuron.ordinary-objective-delivery.v1",
        "signed_packet": source, "outcome": outcome,
        "model_improvement_claimed": false,
    }))
}

pub(super) async fn inspect(path: &Path, pin: Digest32) -> HostResult<Value> {
    let (source, packet, client) = client_for_packet(path, pin).await?;
    let run = client.run_status(packet.ingress.body.run_id).await?;
    Ok(serde_json::json!({
        "schema": "hepta.cpu-neuron.ordinary-objective-inspection.v1",
        "signed_packet": source, "run": run, "dispatched": false,
    }))
}
