use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyRule {
    pub principal_id: StableId,
    pub action_id: StableId,
    pub scope_digest: Digest32,
    pub allow: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyRevision {
    pub policy_id: StableId,
    pub revision: u64,
    pub rules: Vec<PolicyRule>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyDecision {
    pub policy_id: StableId,
    pub revision: u64,
    pub allowed: bool,
    pub decision_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaConfig {
    pub quota_key: StableId,
    pub revision: u64,
    pub endowment: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReservationState {
    Active,
    Settled,
    Cancelled,
    Expired,
    Quarantined,
}

impl ReservationState {
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Settled => "settled",
            Self::Cancelled => "cancelled",
            Self::Expired => "expired",
            Self::Quarantined => "quarantined",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Reservation {
    pub reservation_id: StableId,
    pub operation_id: StableId,
    pub quota_key: StableId,
    pub amount: u64,
    pub expires_at_ms: u64,
    pub policy_id: StableId,
    pub policy_revision: u64,
    pub state: ReservationState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Settlement {
    pub reservation_id: StableId,
    pub observed_cost: u64,
    pub terminal_evidence: Digest32,
    pub settlement_digest: Digest32,
}
