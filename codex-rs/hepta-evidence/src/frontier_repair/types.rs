use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::EvidenceError;
use crate::EvidenceFrontierBackendError;
use crate::EvidenceFrontierDurableAckV1;
use crate::EvidenceRecoveryFrontierV2;
use crate::FrontierMergeDecision;
use crate::FrontierRepairAuthorityV1;
use crate::FrontierRepairAuthorizationV1;
use crate::FrontierRepairReasonV1;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::classify_frontier_merge;
use crate::evidence_recovery_frontier_v2_sha256;
use crate::schema_validation::classify_sqlx_error;
use crate::verify_frontier_repair_authorization;

pub const EVIDENCE_FRONTIER_REPAIR_EVENT_SCHEMA_VERSION: u32 = 1;
pub const EVIDENCE_FRONTIER_REPAIR_MAX_ROWS: i64 = 100_000;
pub const EVIDENCE_FRONTIER_REPAIR_MAX_CANONICAL_BYTES: i64 = 512 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceFrontierRepairStateV1 {
    Prepared,
    Dispatching,
    Indeterminate,
    Acknowledged,
    Conflicted,
}

impl EvidenceFrontierRepairStateV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatching => "dispatching",
            Self::Indeterminate => "indeterminate",
            Self::Acknowledged => "acknowledged",
            Self::Conflicted => "conflicted",
        }
    }

    fn parse(value: &str) -> Result<Self, EvidenceError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "dispatching" => Ok(Self::Dispatching),
            "indeterminate" => Ok(Self::Indeterminate),
            "acknowledged" => Ok(Self::Acknowledged),
            "conflicted" => Ok(Self::Conflicted),
            _ => Err(corrupt("unknown evidence frontier repair state")),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvidenceFrontierRepairActionV1 {
    DispatchExactTransition,
    ObserveExactOperation,
    Complete,
    Conflict,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EvidenceFrontierRepairOperationV1 {
    pub repair_id: String,
    pub store_id: String,
    pub state: EvidenceFrontierRepairStateV1,
    pub nonce_hex: String,
    pub operator_principal_id: String,
    pub reason_code: FrontierRepairReasonV1,
    pub authority_key_id: String,
    pub authority_key_epoch: u64,
    pub trust_root_generation: u64,
    pub current_frontier: EvidenceRecoveryFrontierV2,
    pub target_frontier: EvidenceRecoveryFrontierV2,
    pub authorization: FrontierRepairAuthorizationV1,
    pub authority: FrontierRepairAuthorityV1,
    pub dispatch_token: Option<String>,
    pub backend_identity_sha256: Option<Sha256Digest>,
    pub durable_audit_sequence: Option<u64>,
    pub conflict_generation: Option<u64>,
    pub conflict_frontier_sha256: Option<Sha256Digest>,
    pub created_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
}

impl EvidenceFrontierRepairOperationV1 {
    pub fn next_action(&self) -> EvidenceFrontierRepairActionV1 {
        match self.state {
            EvidenceFrontierRepairStateV1::Prepared => {
                EvidenceFrontierRepairActionV1::DispatchExactTransition
            }
            EvidenceFrontierRepairStateV1::Dispatching
            | EvidenceFrontierRepairStateV1::Indeterminate => {
                EvidenceFrontierRepairActionV1::ObserveExactOperation
            }
            EvidenceFrontierRepairStateV1::Acknowledged => {
                EvidenceFrontierRepairActionV1::Complete
            }
            EvidenceFrontierRepairStateV1::Conflicted => {
                EvidenceFrontierRepairActionV1::Conflict
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EvidenceFrontierRepairBackendObservationV1 {
    Pending,
    Acknowledged(EvidenceFrontierDurableAckV1),
    Conflict {
        actual_generation: u64,
        actual_frontier_sha256: Sha256Digest,
    },
}

/// Separate repair capability. Ordinary `EvidenceFrontierBackend::compare_and_swap`
/// never consumes a repair authorization and remains restricted to automatic
/// `IncomingWins` transitions.
pub trait EvidenceFrontierRepairBackend {
    fn repair_compare_and_swap(
        &mut self,
        repair_id: &str,
        dispatch_token: &str,
        current: &EvidenceRecoveryFrontierV2,
        target: &EvidenceRecoveryFrontierV2,
        authorization: &FrontierRepairAuthorizationV1,
        authority: &FrontierRepairAuthorityV1,
    ) -> Result<EvidenceFrontierDurableAckV1, EvidenceFrontierBackendError>;

    fn observe_repair(
        &mut self,
        repair_id: &str,
        dispatch_token: &str,
    ) -> Result<Option<EvidenceFrontierRepairBackendObservationV1>, EvidenceFrontierBackendError>;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceFrontierRepairEventV1 {
    schema_version: u32,
    repair_id: String,
    event_index: u64,
    event_kind: EvidenceFrontierRepairStateV1,
    store_id: String,
    nonce_hex: String,
    current_frontier_sha256: Sha256Digest,
    target_frontier_sha256: Sha256Digest,
    dispatch_token: Option<String>,
    backend_identity_sha256: Option<Sha256Digest>,
    durable_audit_sequence: Option<u64>,
    conflict_generation: Option<u64>,
    conflict_frontier_sha256: Option<Sha256Digest>,
    observed_at_unix_ms: u64,
    previous_event_sha256: Option<Sha256Digest>,
}

