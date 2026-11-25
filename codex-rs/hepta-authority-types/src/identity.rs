//! Original configured identities. These values carry no writer or launch grant.

use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaAgentLayout;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIdentity {
    pub agent_id: AgentId,
    pub layout: HeptaAgentLayout,
    pub spawn_generation: u64,
    pub fleet_root: PathBuf,
    pub workspace: PathBuf,
    pub resources: ResourceBudget,
    pub home_root: PathBuf,
    pub run_root: PathBuf,
    pub control_socket: PathBuf,
    pub app_server_socket: PathBuf,
}

/// Exact original identity fields attested by the root launcher. Derived layout
/// paths come from HeptaFleetRoot; opening AgentdConfig here would incorrectly
/// compete with the actual daemon's exclusive original writer lock.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityRegisteredIdentity {
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub fleet_root: PathBuf,
    pub workspace: PathBuf,
    pub resources: ResourceBudget,
}
