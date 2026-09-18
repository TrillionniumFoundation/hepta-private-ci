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

/// One fixed quota window. `unit_id` is immutable for a quota key; a later
/// revision may either adjust the same window after all held reservations are
/// gone, or advance to a non-overlapping window.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaConfig {
    pub quota_key: StableId,
    pub revision: u64,
    pub unit_id: StableId,
    pub window_start_ms: u64,
    pub window_end_ms: u64,
    pub endowment: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReservationState {
    Active,
    /// Durable final-use intent. Once this state commits, cancellation and
    /// expiry may no longer refund quota because the external effect may occur.
    EffectStarted,
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
            Self::EffectStarted => "effect_started",
            Self::Settled => "settled",
            Self::Cancelled => "cancelled",
            Self::Expired => "expired",
            Self::Quarantined => "quarantined",
        }
    }
}

/// Durable semantic binding for one reservation. The final effect digest is
/// supplied by the effect adapter and must cover its complete final-use binding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Reservation {
    pub reservation_id: StableId,
    pub operation_id: StableId,
    pub principal_id: StableId,
    pub action_id: StableId,
    pub scope_digest: Digest32,
    pub quota_key: StableId,
    pub quota_revision: u64,
    pub amount: u64,
    pub expires_at_ms: u64,
    pub policy_id: StableId,
    pub policy_revision: u64,
    pub effect_digest: Digest32,
    pub binding_digest: Digest32,
    pub state: ReservationState,
    pub effect_started_at_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Settlement {
    pub reservation_id: StableId,
    pub observed_cost: u64,
    pub terminal_evidence: Digest32,
    pub settlement_digest: Digest32,
}
