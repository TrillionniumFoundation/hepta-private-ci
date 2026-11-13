//! Same-key original writer rotation for the exact future Supervisor generation.
use super::boot::Boot;
use super::paths;
use super::provision;
use codex_hepta_agentd::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use std::path::Path;

pub(super) const CONFIG: &str = "/state/service-successor.json";
pub(super) const REGISTRATION: &str = "/state/registration-successor.json";

pub(super) fn rotate(
    boot: &Boot,
    registry: &FleetRegistry,
    agent: &AgentId,
    prior: &HostAuthorityServiceConfig,
    old_registration: &HostAuthorityRegistration,
    predecessor_proof: &HostSignedWriterAuthorizationV1,
    old_current: &CognitiveCheckpointReceipt,
) -> Result<(HostAuthorityServiceConfig, HostSignedWriterAuthorizationV1), Box<dyn std::error::Error>>
{
    let record = registry.load_agent(agent)?;
    let predecessor = prior
        .writer
        .as_ref()
        .ok_or("original registered writer absent")?;
    let mut successor = predecessor.clone();
    let now = provision::now_ms()?;
    successor.spawn_generation = record.lifecycle.generation;
    successor.owner_epoch = predecessor
        .owner_epoch
        .checked_add(1)
        .ok_or("owner epoch exhausted")?;
    successor.local_lease_generation = predecessor
        .local_lease_generation
        .checked_add(1)
        .ok_or("local generation exhausted")?;
    // Canonical registry leases are distinct, even though the LOCAL durable
    // writer lease retains its original ID and increments exactly once.
    successor.authority_lease.lease_id = format!(
        "native-g2-original-writer-authority-spawn-{}",
        record.lifecycle.generation
    );
    successor.authority_lease.revision = 1;
    successor.authority_lease.issued_at_unix_ms = now;
    successor.authority_lease.expires_at_unix_ms = now
        .checked_add(provision::WRITER_LIFETIME_MS)
        .ok_or("authority expiry overflow")?;
    // The original rotate API retains the issuer key/counter and canonical
    // authority epoch. Its own exact predecessor/proof/CAS checks still apply.
    let mut config = prior.clone();
    config.writer = Some(successor);
    let mut registration = old_registration.clone();
    registration.peer_pid = boot.pids[2];
    registration.process_start_ticks = provision::start_ticks(boot.pids[2])?;
    registration.registered_identity.spawn_generation = record.lifecycle.generation;
    registration.publisher_epoch = old_current
        .head
        .publisher_epoch
        .checked_add(1)
        .ok_or("publisher epoch exhausted")?;
    paths::root_json(Path::new(CONFIG), &config)?;
    paths::root_json(Path::new(REGISTRATION), &registration)?;
    let proof =
        rotate_host_writer_authorization(Path::new(CONFIG), predecessor, predecessor_proof)?;
    Ok((config, proof))
}
