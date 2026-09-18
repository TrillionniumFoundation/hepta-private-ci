use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::FleetAllocationStateV1;
use crate::FleetResourceVectorV1;
use crate::lease_ledger::AllocationGrant;

pub const FLEET_ALLOCATION_GRANT_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationGrantV1 {
    pub schema_version: u32,
    pub allocation_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub host_observation_revision: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub predecessor_lease_generation: Option<u64>,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub resources: FleetResourceVectorV1,
    pub semantic_digest: String,
}

impl From<&AllocationGrant> for FleetAllocationGrantV1 {
    fn from(grant: &AllocationGrant) -> Self {
        Self {
            schema_version: FLEET_ALLOCATION_GRANT_SCHEMA_VERSION,
            allocation_id: grant.allocation_id.clone(),
            request_id: grant.request_id.clone(),
            principal_id: grant.principal_id.clone(),
            host_id: grant.host_id.clone(),
            failure_domain_id: grant.failure_domain_id.clone(),
            host_generation: grant.host_generation,
            host_observation_revision: grant.host_observation_revision,
            authority_epoch: grant.authority_epoch,
            lease_generation: grant.lease_generation,
            predecessor_lease_generation: grant.predecessor_lease_generation,
            issued_at_ms: grant.issued_at_ms,
            expires_at_ms: grant.expires_at_ms,
            resources: grant.resources,
            semantic_digest: grant.semantic_digest.clone(),
        }
    }
}

/// Authoritative read cut over one fsynced allocation generation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationGrantReadV1 {
    pub schema_version: u32,
    pub state_revision: u64,
    pub state_digest: Sha256Digest,
    pub grants: Vec<FleetAllocationGrantV1>,
}

impl FleetAllocationGrantReadV1 {
    pub fn from_state(
        state: &FleetAllocationStateV1,
        authority_epoch: u64,
        now_ms: u64,
    ) -> Self {
        let grants = state
            .ledger
            .grants()
            .filter(|grant| {
                grant.authority_epoch == authority_epoch
                    && !grant.revoked
                    && grant.expires_at_ms > now_ms
            })
            .map(FleetAllocationGrantV1::from)
            .collect();
        Self {
            schema_version: FLEET_ALLOCATION_GRANT_SCHEMA_VERSION,
            state_revision: state.revision,
            state_digest: state.state_digest.clone(),
            grants,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::FLEET_ALLOCATION_STORE_SCHEMA_VERSION;
    use crate::lease_ledger::LeaseLedger;

    #[test]
    fn empty_read_is_bound_to_durable_state_generation() {
        let state = FleetAllocationStateV1 {
            schema_version: FLEET_ALLOCATION_STORE_SCHEMA_VERSION,
            revision: 7,
            predecessor_revision: Some(6),
            predecessor_state_digest: Some(Sha256Digest::for_bytes(b"predecessor")),
            writer_epoch: 9,
            committed_at_ms: 100,
            ledger: LeaseLedger::new(),
            state_digest: Sha256Digest::for_bytes(b"state"),
        };
        let read = FleetAllocationGrantReadV1::from_state(&state, 9, 100);
        assert_eq!(read.state_revision, 7);
        assert_eq!(read.state_digest, state.state_digest);
        assert!(read.grants.is_empty());
    }
}
