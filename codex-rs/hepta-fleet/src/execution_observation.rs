//! Portable metadata contracts for the existing Fleet execution owner.
//! These data types neither open its store nor grant process authority.

use serde::Deserialize;
use serde::Serialize;

use crate::ResourceVectorV1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetExecutionContextV1 {
    pub execution_id: String,
    pub allocation_id: String,
    pub principal_id: String,
    /// Selected execution-host identity, independently supplied by its owner.
    pub host_id: String,
    pub host_generation: u64,
    pub lease_generation: u64,
    /// Digest of the actual immutable execution configuration.
    pub manifest_digest: String,
    /// Exact budget consumed by that configuration, including logical axes.
    pub resources: ResourceVectorV1,
    /// Root-owned cgroup v2 relative path, not writable by the workload.
    pub containment: String,
}

/// One read-only observation of the original resource owner's live execution.
/// This is metadata, never a grant issuer or an authorization token. A missing
/// allocation remains missing after expiry or revocation; the reader cannot
/// recover authority from the still-held execution context.
#[derive(Clone, Debug, serde::Deserialize, Eq, PartialEq, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetExecutionResourceObservationV1 {
    pub context: FleetExecutionContextV1,
    pub process_id: u32,
    pub process_start_ticks: u64,
    pub allocation: Option<crate::AllocationGrant>,
}
