//! Original trusted-launch registration record, never an ordinary request grant.
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use serde::Deserialize;
use serde::Serialize;

/// Exact trusted launcher inputs. This is an administrative registration,
/// never a value accepted from an ordinary service request or audit witness.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityWriterRegistration {
    pub registered_agent_id: AgentId,
    pub spawn_generation: u64,
    pub owner_epoch: u64,
    pub local_lease_id: String,
    pub local_lease_generation: u64,
    pub authority_lease: AuthorityLease,
}
