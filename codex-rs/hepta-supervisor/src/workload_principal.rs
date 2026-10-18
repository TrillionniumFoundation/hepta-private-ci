//! Kernel workload identities projected from the existing root-owned host policy.
//! The shared GID grants transport/read-only release access, never private homes.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
#[cfg(any(test, feature = "local-model-authority"))]
use serde::Deserialize;

pub(crate) type AgentWorkloadUids = BTreeMap<AgentId, u32>;

pub(crate) fn validate(
    default_uid: u32,
    shared_gid: u32,
    agents: Option<&AgentWorkloadUids>,
) -> anyhow::Result<()> {
    anyhow::ensure!(
        default_uid != 0 && shared_gid != 0,
        "workloads must be non-root"
    );
    if let Some(agents) = agents {
        anyhow::ensure!(
            (1..=1024).contains(&agents.len()),
            "per-Agent workload identities must be explicitly bounded and nonempty"
        );
        let mut distinct = BTreeSet::new();
        for uid in agents.values() {
            anyhow::ensure!(
                *uid != 0 && distinct.insert(*uid),
                "each Agent requires a unique non-root workload UID"
            );
        }
    }
    Ok(())
}

pub(crate) fn uid_for(
    default_uid: u32,
    agents: Option<&AgentWorkloadUids>,
    agent: &AgentId,
) -> anyhow::Result<u32> {
    match agents {
        Some(agents) => agents
            .get(agent)
            .copied()
            .ok_or_else(|| anyhow::anyhow!("Agent has no enrolled workload UID")),
        None => Ok(default_uid),
    }
}

pub(crate) fn enrolled_uids(default_uid: u32, agents: Option<&AgentWorkloadUids>) -> BTreeSet<u32> {
    match agents {
        Some(agents) => agents.values().copied().collect(),
        None => BTreeSet::from([default_uid]),
    }
}

// The host retains its complete strict policy decoder. The model endpoint reads
// only these finite identity fields from that same protected file, not a second
// enrollment list or mutable authority store.
#[cfg(any(test, feature = "local-model-authority"))]
#[derive(Deserialize)]
pub(crate) struct HostPrincipalPolicy {
    pub version: u32,
    pub workload_uid: u32,
    pub workload_gid: u32,
    pub cgroup_root: String,
    #[serde(default)]
    pub agent_workload_uids: Option<AgentWorkloadUids>,
    #[serde(default)]
    pub resource_authority_frontier: Option<std::path::PathBuf>,
}

#[cfg(any(test, feature = "local-model-authority"))]
impl HostPrincipalPolicy {
    pub(crate) fn validate(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.version == 1,
            "unsupported host workload policy version"
        );
        validate(
            self.workload_uid,
            self.workload_gid,
            self.agent_workload_uids.as_ref(),
        )
    }
}

#[cfg(test)]
#[path = "workload_principal_tests.rs"]
mod tests;
