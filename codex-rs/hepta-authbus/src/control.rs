use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const AUTHBUS_MAX_RESERVATION_TTL_MS: u64 = 86_400_000;
pub const AUTHBUS_MAX_ACTIVE_RESERVATIONS_PER_POLICY: u32 = 4_096;
pub const AUTHBUS_MAX_EXPIRY_SWEEP_ROWS: u32 = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyEffect {
    Allow,
    Deny,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthPolicyRule {
    pub principal_id: StableId,
    pub action_id: StableId,
    pub scope_digest: Digest32,
    pub revision: u64,
    pub effect: PolicyEffect,
    pub max_active_reservations: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyDecision {
    Allowed,
    Denied,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaRegistryEntry {
    pub quota_key: StableId,
    pub revision: u64,
    pub capacity: u64,
    pub period_start_ms: u64,
    pub period_end_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaSnapshot {
    pub quota_key: StableId,
    pub revision: u64,
    pub capacity: u64,
    pub reserved: u64,
    pub consumed: u64,
    pub period_start_ms: u64,
    pub period_end_ms: u64,
}

impl QuotaSnapshot {
    #[must_use]
    pub fn available(&self) -> u64 {
        self.capacity
            .saturating_sub(self.reserved.saturating_add(self.consumed))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReservationState {
    Reserved,
    InFlight,
    Settled,
    Cancelled,
    Expired,
    Quarantined,
}

impl ReservationState {
    #[must_use]
    pub const fn holds_quota(self) -> bool {
        matches!(self, Self::Reserved | Self::InFlight | Self::Quarantined)
    }

    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Settled | Self::Cancelled | Self::Expired)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectAdmissionRequest {
    pub operation_id: StableId,
    pub principal_id: StableId,
    pub action_id: StableId,
    pub scope_digest: Digest32,
    pub policy_revision: u64,
    pub quota_key: StableId,
    pub quota_revision: u64,
    pub amount: u64,
    pub expires_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Reservation {
    pub reservation_id: Digest32,
    pub operation_id: StableId,
    pub principal_id: StableId,
    pub action_id: StableId,
    pub scope_digest: Digest32,
    pub policy_revision: u64,
    pub quota_key: StableId,
    pub quota_revision: u64,
    pub amount: u64,
    pub state: ReservationState,
    pub observed_cost: Option<u64>,
    pub expires_at_ms: u64,
    pub terminal_evidence: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectAdmission {
    pub decision: PolicyDecision,
    pub reservation: Reservation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Settlement {
    pub reservation_id: Digest32,
    pub observed_cost: u64,
    pub terminal_evidence: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReservationReconcileOutcome {
    Settled {
        observed_cost: u64,
        terminal_evidence: Digest32,
    },
    NotApplied {
        terminal_evidence: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusReplayCheckpoint {
    pub generation: u64,
    pub replay_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusTrustHead {
    pub issuer_id: StableId,
    pub revision: u64,
    pub key_epoch: u64,
    pub verifying_key_digest: Digest32,
    pub registration_digest: Digest32,
    pub revoked: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControlWriteDisposition {
    Inserted,
    AlreadyPresent,
}
