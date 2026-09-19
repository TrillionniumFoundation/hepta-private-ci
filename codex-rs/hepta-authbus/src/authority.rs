use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const AUTHBUS_POLICY_DOMAIN: &[u8] = b"hepta.authbus.policy.v1\0";
const AUTHBUS_RESERVATION_DOMAIN: &[u8] = b"hepta.authbus.reservation.v1\0";
const AUTHBUS_SETTLEMENT_DOMAIN: &[u8] = b"hepta.authbus.settlement.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthPolicy {
    pub policy_id: StableId,
    pub principal_id: StableId,
    pub action_id: StableId,
    pub scope_digest: Digest32,
    pub revision: u64,
    pub allowed: bool,
    pub revoked: bool,
}

impl AuthPolicy {
    pub fn validate(&self) -> Result<(), Error> {
        if self.scope_digest.is_zero() {
            return Err(Error::EmptyDigest("policy scope"));
        }
        if self.revision == 0 {
            return Err(Error::ZeroRevision);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = AUTHBUS_POLICY_DOMAIN.to_vec();
        push_id(&mut bytes, &self.policy_id);
        push_id(&mut bytes, &self.principal_id);
        push_id(&mut bytes, &self.action_id);
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(&self.revision.to_be_bytes());
        bytes.push(u8::from(self.allowed));
        bytes.push(u8::from(self.revoked));
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyDecision {
    pub policy_id: StableId,
    pub principal_id: StableId,
    pub action_id: StableId,
    pub scope_digest: Digest32,
    pub policy_revision: u64,
    pub allowed: bool,
    pub decision_digest: Digest32,
}

impl PolicyDecision {
    #[must_use]
    pub fn from_policy(policy: &AuthPolicy) -> Self {
        let allowed = policy.allowed && !policy.revoked;
        Self {
            policy_id: policy.policy_id.clone(),
            principal_id: policy.principal_id.clone(),
            action_id: policy.action_id.clone(),
            scope_digest: policy.scope_digest,
            policy_revision: policy.revision,
            allowed,
            decision_digest: policy.digest(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaDefinition {
    pub quota_key: StableId,
    pub limit: u64,
    pub revision: u64,
}

impl QuotaDefinition {
    pub fn validate(&self) -> Result<(), Error> {
        if self.limit == 0 {
            return Err(Error::ZeroQuotaLimit);
        }
        if self.revision == 0 {
            return Err(Error::ZeroRevision);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReservationState {
    Held,
    Indeterminate,
    Settled,
    Cancelled,
    Expired,
    Quarantined,
}

impl ReservationState {
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Settled | Self::Cancelled | Self::Expired | Self::Quarantined
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaReservation {
    pub reservation_id: StableId,
    pub quota_key: StableId,
    pub operation_id: StableId,
    pub amount: u64,
    pub expires_at_ms: u64,
    pub quota_revision: u64,
    pub state: ReservationState,
    pub observed_cost: Option<u64>,
    pub reservation_digest: Digest32,
}

impl QuotaReservation {
    pub fn new(
        reservation_id: StableId,
        quota_key: StableId,
        operation_id: StableId,
        amount: u64,
        expires_at_ms: u64,
        quota_revision: u64,
    ) -> Result<Self, Error> {
        if amount == 0 {
            return Err(Error::ZeroReservation);
        }
        if quota_revision == 0 {
            return Err(Error::ZeroRevision);
        }
        let mut bytes = AUTHBUS_RESERVATION_DOMAIN.to_vec();
        push_id(&mut bytes, &reservation_id);
        push_id(&mut bytes, &quota_key);
        push_id(&mut bytes, &operation_id);
        bytes.extend_from_slice(&amount.to_be_bytes());
        bytes.extend_from_slice(&expires_at_ms.to_be_bytes());
        bytes.extend_from_slice(&quota_revision.to_be_bytes());
        Ok(Self {
            reservation_id,
            quota_key,
            operation_id,
            amount,
            expires_at_ms,
            quota_revision,
            state: ReservationState::Held,
            observed_cost: None,
            reservation_digest: Digest32::of_bytes(&bytes),
        })
    }

    #[must_use]
    pub fn settlement_digest(&self, observed_cost: u64, evidence: Digest32) -> Digest32 {
        let mut bytes = AUTHBUS_SETTLEMENT_DOMAIN.to_vec();
        bytes.extend_from_slice(self.reservation_digest.as_array());
        bytes.extend_from_slice(&observed_cost.to_be_bytes());
        bytes.extend_from_slice(evidence.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayCheckpoint {
    pub checkpoint_id: StableId,
    pub generation: u64,
    pub replay_root: Digest32,
    pub observed_at_ms: u64,
}

impl ReplayCheckpoint {
    pub fn validate(&self) -> Result<(), Error> {
        if self.generation == 0 {
            return Err(Error::ZeroRevision);
        }
        if self.replay_root.is_zero() {
            return Err(Error::EmptyDigest("replay checkpoint"));
        }
        if self.observed_at_ms == 0 {
            return Err(Error::InvalidTime);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedTime {
    pub source_id: StableId,
    pub generation: u64,
    pub now_ms: u64,
    pub uncertainty_ms: u64,
}

impl TrustedTime {
    pub fn validate(&self, maximum_uncertainty_ms: u64) -> Result<(), Error> {
        if self.generation == 0 || self.now_ms == 0 {
            return Err(Error::InvalidTime);
        }
        if self.uncertainty_ms > maximum_uncertainty_ms {
            return Err(Error::UntrustedTime);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    ZeroRevision,
    ZeroQuotaLimit,
    ZeroReservation,
    InvalidTime,
    UntrustedTime,
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
