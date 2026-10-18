use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::ResourceVectorError;
use crate::ResourceVectorV1;

pub const MAX_HOSTS: usize = 256;
pub const MAX_ACTIVE_GRANTS: usize = 16_384;
pub const MAX_LEASE_HISTORY: usize = 65_536;
pub const MAX_EXPIRED_PER_SWEEP: usize = 4_096;

/// Compatibility spelling retained for the original in-process lease API.
/// New code should use the canonical `ResourceVectorV1` name.
pub type Resources = ResourceVectorV1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostObservation {
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub capacity: ResourceVectorV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AllocationGrant {
    pub allocation_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub resources: ResourceVectorV1,
    pub semantic_digest: String,
    pub revoked: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseDisposition {
    Renew { expires_at_ms: u64 },
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOutcome {
    Issued,
    Renewed,
    Revoked,
    Expired,
    Fenced,
    Unchanged,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseReceipt {
    pub allocation_id: String,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
    pub outcome: LeaseOutcome,
    pub semantic_digest: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseHistoryState {
    Revoked,
    Expired,
    HostGenerationFenced,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseHistoryRecord {
    pub grant: AllocationGrant,
    pub state: LeaseHistoryState,
    pub retired_at_ms: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct LeaseLedgerMetrics {
    pub hosts: usize,
    pub active_grants: usize,
    pub retained_history: usize,
    pub compacted_history: u64,
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum Error {
    #[error("invalid fleet identity: {0}")]
    InvalidIdentity(&'static str),
    #[error("invalid semantic digest")]
    InvalidDigest,
    #[error("invalid fleet time interval")]
    InvalidTime,
    #[error("invalid generation")]
    InvalidGeneration,
    #[error("host capacity observation is invalid")]
    HostCapacity,
    #[error("fleet capacity is exhausted")]
    CapacityExceeded,
    #[error("active grant capacity is exhausted")]
    GrantCapacityExceeded,
    #[error("fleet host was not found")]
    HostNotFound,
    #[error("allocation was not found")]
    AllocationNotFound,
    #[error("fleet state conflicts with an existing identity")]
    Conflict,
    #[error("host observation is stale")]
    StaleHost,
    #[error("lease generation is stale")]
    StaleLease,
    #[error("lease was revoked")]
    Revoked,
    #[error("fleet arithmetic overflowed")]
    ArithmeticOverflow,
    #[error("owner clock is unavailable")]
    ClockUnavailable,
    #[error("owner clock moved behind its accepted frontier")]
    ClockRollback,
    #[error("resource arithmetic failed: {0}")]
    Resource(#[from] ResourceVectorError),
}
