use codex_hepta_contracts::SignedFinalUseRevocationAck;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::AllocationGrant;
use crate::FleetAuthorityError;
use crate::ResourceVectorV1;

pub const DURABLE_FLEET_SCHEMA_VERSION: i64 = 2;
pub const DURABLE_FLEET_LINEAGE: &str = "hepta.runtime.fleet.supervisor-owner.v1";
pub const MAX_DURABLE_ACTIVE_GRANTS: i64 = 16_384;
pub const MAX_DURABLE_HISTORY_ROWS: i64 = 65_536;
pub const MAX_DURABLE_EXPIRY_BATCH: i64 = 4_096;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetMutationKindV1 {
    HostObservation,
    Issue,
    Renew,
    Revoke,
    Expire,
    Fence,
    WorkspaceReserve,
    WorkspaceRelease,
    RevocationUpdate,
    RevocationAck,
    Compact,
}

impl FleetMutationKindV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::HostObservation => "host_observation",
            Self::Issue => "issue",
            Self::Renew => "renew",
            Self::Revoke => "revoke",
            Self::Expire => "expire",
            Self::Fence => "fence",
            Self::WorkspaceReserve => "workspace_reserve",
            Self::WorkspaceRelease => "workspace_release",
            Self::RevocationUpdate => "revocation_update",
            Self::RevocationAck => "revocation_ack",
            Self::Compact => "compact",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetMutationOutcomeV1 {
    Inserted,
    Updated,
    Revoked,
    Expired,
    Fenced,
    Unchanged,
    Compacted,
}

impl FleetMutationOutcomeV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Inserted => "inserted",
            Self::Updated => "updated",
            Self::Revoked => "revoked",
            Self::Expired => "expired",
            Self::Fenced => "fenced",
            Self::Unchanged => "unchanged",
            Self::Compacted => "compacted",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetOperationReceiptV1 {
    pub operation_id: String,
    pub kind: FleetMutationKindV1,
    pub subject_id: String,
    pub outcome: FleetMutationOutcomeV1,
    pub semantic_digest: String,
    pub authority_witness: Option<VerifiedUseTokenWitnessV1>,
    pub committed_at_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DurableGrantReceiptV1 {
    pub grant: AllocationGrant,
    pub operation: FleetOperationReceiptV1,
}

/// A ledger check result, not independent authority or permission to spawn.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetUsePermitV1 {
    pub allocation_id: String,
    pub principal_id: String,
    pub host_id: String,
    pub host_generation: u64,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub resources: ResourceVectorV1,
    pub semantic_digest: String,
    pub checked_at_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableLeaseDispositionV1 {
    Renew { expires_at_ms: u64 },
    Revoke,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkspaceReservationV1 {
    pub agent_id: String,
    pub workspace: String,
    pub workspace_digest: String,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DurableRevocationStateV1 {
    pub update: SignedFinalUseRevocationUpdate,
    pub acknowledgements: Vec<SignedFinalUseRevocationAck>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetHostResourcesV1 {
    pub host_id: String,
    pub observed: ResourceVectorV1,
    pub reserved: ResourceVectorV1,
    pub observation_valid_until_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetResultCounterV1 {
    pub operation: String,
    pub result: String,
    pub value: u64,
}

/// Unreleased candidate metrics: operational observations are nullable. Consumers
/// must retain `None`/JSON null as unknown and never coerce it to zero.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetMetricsSnapshotV1 {
    pub active_grants: u64,
    pub expired_uncollected_grants: u64,
    pub revoked_uncompacted_grants: u64,
    pub host_resources: Vec<FleetHostResourcesV1>,
    pub stale_hosts: u64,
    pub result_counters: Vec<FleetResultCounterV1>,
    pub revocation_lag_ms: Option<u64>,
    pub revocation_update_age_ms: Option<u64>,
    pub registry_conflicts: Option<u64>,
    pub indeterminate_commits: Option<u64>,
    pub staging_debris: Option<u64>,
    pub compaction_backlog: u64,
}

#[derive(Debug, Eq, Error, PartialEq)]
pub enum DurableFleetError {
    #[error("invalid durable fleet value: {0}")]
    Invalid(String),
    #[error("durable fleet state conflicts for {0}")]
    Conflict(String),
    #[error("durable fleet state is missing for {0}")]
    Missing(String),
    #[error("durable fleet generation or revision is stale")]
    Stale,
    #[error("durable fleet capacity is exhausted")]
    Capacity,
    #[error("durable fleet clock is unavailable")]
    ClockUnavailable,
    #[error("durable fleet clock moved behind its accepted frontier")]
    ClockRollback,
    #[error("corrupt durable fleet state: {0}")]
    Corrupt(String),
    #[error("durable fleet storage is unavailable: {0}")]
    Unavailable(String),
    #[error(
        "durable fleet mutation may have committed; reconcile operation {operation_id} for {subject_id}"
    )]
    IndeterminateCommit {
        operation_id: String,
        subject_id: String,
    },
    #[error(transparent)]
    Authority(#[from] FleetAuthorityError),
}
