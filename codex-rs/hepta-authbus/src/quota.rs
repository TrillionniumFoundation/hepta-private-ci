use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReservationState {
    Held,
    DispatchAttempted,
    Indeterminate,
    Settled,
    Released,
    Expired,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaSpec {
    pub quota_key: StableId,
    pub principal: StableId,
    pub scope_digest: Digest32,
    pub unit: StableId,
    pub period_id: StableId,
    pub limit: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaSnapshot {
    pub quota_key: StableId,
    pub principal: StableId,
    pub scope_digest: Digest32,
    pub unit: StableId,
    pub period_id: StableId,
    pub limit: u64,
    pub available: u64,
    pub reserved: u64,
    pub consumed: u64,
    pub revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReservationRequest {
    pub quota_key: StableId,
    pub operation_id: StableId,
    pub amount: u64,
    pub effect_digest: Digest32,
    pub expected_quota_revision: u64,
    pub expires_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaReservation {
    pub reservation_id: StableId,
    pub operation_id: StableId,
    pub quota_key: StableId,
    pub period_id: StableId,
    pub principal: StableId,
    pub amount: u64,
    pub effect_digest: Digest32,
    pub policy_id: StableId,
    pub policy_revision: u64,
    pub policy_decision_digest: Digest32,
    pub state: ReservationState,
    pub revision: u64,
    pub expires_at_ms: u64,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
    pub dispatch_digest: Option<Digest32>,
    pub terminal_evidence: Option<Digest32>,
    pub observed_cost: Option<u64>,
    pub settlement_digest: Option<Digest32>,
}
