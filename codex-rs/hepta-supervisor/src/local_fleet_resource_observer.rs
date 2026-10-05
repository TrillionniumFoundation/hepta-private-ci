//! Root-local observation of the existing resource owner, without opening it.

use std::io::Read;
use std::path::Path;
use std::time::Duration;

use anyhow::Context;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_fleet::FleetExecutionResourceObservationV1;
use codex_hepta_fleet::FleetExecutionVerifier;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde::Serialize;

use super::Policy;
use super::trust;

/// A current read, not a grant or an atomic view of SQL and the kernel. The
/// consumer must repeat it at physical use and compare its execution witness.
#[derive(Debug, Serialize)]
pub struct LocalFleetResourceObservationV1 {
    pub observed_at_ms: u64,
    pub boot_identity: String,
    pub resource_authority_epoch: u64,
    pub observation: FleetExecutionResourceObservationV1,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Frontier {
    owner_id: String,
    frontier: AuthorityLeaseFrontier,
}

/// Read only the enrolled Agent's current resources through the original
/// kernel verifier and protected host policy. No registry migration, resource
/// owner, clock publication, lease renewal or grant creation occurs here.
pub async fn observe_local_fleet_resources(
    fleet_root: &HeptaFleetRoot,
    policy_path: &Path,
    agent: &AgentId,
    process_id: u32,
) -> anyhow::Result<LocalFleetResourceObservationV1> {
    observe_bounded(
        fleet_root,
        policy_path,
        agent,
        process_id,
        /*program_sha256*/ None,
    )
    .await
}

/// Additionally require the program held by the same original prepared execution.
/// The supplied digest is a selector, never a substitute for the durable proof.
pub async fn observe_local_fleet_resources_for_program(
    fleet_root: &HeptaFleetRoot,
    policy_path: &Path,
    agent: &AgentId,
    process_id: u32,
    program_sha256: &str,
) -> anyhow::Result<LocalFleetResourceObservationV1> {
    observe_bounded(
        fleet_root,
        policy_path,
        agent,
        process_id,
        Some(program_sha256),
    )
    .await
}

async fn observe_bounded(
    fleet_root: &HeptaFleetRoot,
    policy_path: &Path,
    agent: &AgentId,
    process_id: u32,
    program_sha256: Option<&str>,
) -> anyhow::Result<LocalFleetResourceObservationV1> {
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "resource observation requires root"
    );
    anyhow::ensure!(process_id != 0, "resource process identity must be nonzero");
    tokio::time::timeout(
        Duration::from_secs(2),
        observe(fleet_root, policy_path, agent, process_id, program_sha256),
    )
    .await
    .context("resource observation exceeded its deadline")?
}

async fn observe(
    fleet_root: &HeptaFleetRoot,
    policy_path: &Path,
    agent: &AgentId,
    process_id: u32,
    program_sha256: Option<&str>,
) -> anyhow::Result<LocalFleetResourceObservationV1> {
    let clock = trust::HostClock::new()?;
    let policy_bytes = trust::read_root_file(policy_path, 64 * 1024)?;
    let policy: Policy = serde_json::from_slice(&policy_bytes)?;
    anyhow::ensure!(policy.version == 1, "unsupported host policy version");
    crate::workload_principal::validate(
        policy.workload_uid,
        policy.workload_gid,
        policy.agent_workload_uids.as_ref(),
    )?;
    anyhow::ensure!(
        policy.cgroup_root.starts_with("hepta-")
            && policy.cgroup_root.len() <= 80
            && policy
                .cgroup_root
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-'),
        "invalid original host containment root"
    );
    let expected_uid = policy.workload_uid_for(agent)?;
    let before = read_frontier(&policy.resource_authority_frontier)?;
    let boot_identity = current_boot_identity()?;
    let verifier = FleetExecutionVerifier::open(
        &fleet_root
            .layout()
            .state_root()
            .join("fleet-resources.sqlite3"),
    )
    .await?;
    verifier
        .verify_owner_clock_floor(clock.now_unix_ms()?)
        .await?;
    let observation = match program_sha256 {
        Some(pin) => {
            verifier
                .observe_bound_root_local_resources_for_program(
                    agent.as_str(),
                    process_id,
                    expected_uid,
                    pin,
                )
                .await?
        }
        None => {
            verifier
                .observe_bound_root_local_resources(agent.as_str(), process_id, expected_uid)
                .await?
        }
    };
    let now = clock.now_unix_ms()?;
    verifier.verify_owner_clock_floor(now).await?;
    validate(
        &policy,
        agent,
        process_id,
        process_uid(process_id)?,
        now,
        &before,
        &observation,
    )?;
    anyhow::ensure!(
        process_uid(process_id)? == expected_uid && current_boot_identity()? == boot_identity,
        "resource kernel identity changed during observation"
    );
    let after = read_frontier(&policy.resource_authority_frontier)?;
    anyhow::ensure!(
        before.owner_id == after.owner_id
            && before.frontier.authority_epoch == after.frontier.authority_epoch,
        "resource authority epoch changed during observation"
    );
    anyhow::ensure!(
        trust::read_root_file(policy_path, 64 * 1024)? == policy_bytes,
        "resource host policy changed during observation"
    );
    Ok(LocalFleetResourceObservationV1 {
        observed_at_ms: now,
        boot_identity,
        resource_authority_epoch: before.frontier.authority_epoch,
        observation,
    })
}

fn read_frontier(path: &Path) -> anyhow::Result<Frontier> {
    let frontier: Frontier = serde_json::from_slice(&trust::read_root_file(path, 4096)?)?;
    anyhow::ensure!(
        frontier.owner_id == "local-supervisor-resources"
            && frontier.frontier.authority_epoch != 0
            && frontier.frontier.state_sha256 != [0; 32],
        "invalid original resource authority frontier"
    );
    Ok(frontier)
}

fn process_uid(pid: u32) -> anyhow::Result<u32> {
    let status = read_kernel(&format!("/proc/{pid}/status"), 65_536)?;
    let values = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .context("resource process UID is unavailable")?
        .split_whitespace()
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()?;
    anyhow::ensure!(
        values.len() == 4 && values.iter().all(|uid| *uid == values[0]),
        "resource process has an unexpected credential transition"
    );
    Ok(values[0])
}

fn current_boot_identity() -> anyhow::Result<String> {
    let identity = read_kernel("/proc/sys/kernel/random/boot_id", 128)?;
    Ok(uuid::Uuid::parse_str(identity.trim())?.to_string())
}

fn read_kernel(path: &str, maximum: u64) -> anyhow::Result<String> {
    let mut value = String::new();
    std::fs::File::open(path)?
        .take(maximum + 1)
        .read_to_string(&mut value)?;
    anyhow::ensure!(
        value.len() as u64 <= maximum,
        "resource kernel metadata exceeded its bound"
    );
    Ok(value)
}

fn validate(
    policy: &Policy,
    agent: &AgentId,
    pid: u32,
    uid: u32,
    now: u64,
    frontier: &Frontier,
    observation: &FleetExecutionResourceObservationV1,
) -> anyhow::Result<()> {
    let context = &observation.context;
    let execution = uuid::Uuid::parse_str(&context.execution_id)?.to_string();
    anyhow::ensure!(
        uid == policy.workload_uid_for(agent)?
            && observation.process_id == pid
            && context.principal_id == agent.as_str()
            && execution == context.execution_id
            && context.containment
                == format!("{}/agent-{agent}/main-{execution}", policy.cgroup_root),
        "resource observation differs from the enrolled workload"
    );
    let allocation = observation
        .allocation
        .as_ref()
        .context("resource allocation is no longer active")?;
    anyhow::ensure!(
        !allocation.revoked
            && allocation.expires_at_ms > now
            && allocation.authority_epoch == frontier.frontier.authority_epoch,
        "resource allocation is expired, revoked or from another authority epoch"
    );
    Ok(())
}

#[cfg(test)]
#[path = "local_fleet_resource_observer_tests.rs"]
mod tests;
