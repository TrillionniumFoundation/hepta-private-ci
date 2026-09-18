use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const AUTHBUS_CONTROL_SCHEMA_VERSION: u32 = 1;
pub const AUTHBUS_MAX_RESERVATIONS: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthPolicy {
    pub policy_id: StableId,
    pub revision: u64,
    pub principal_id: StableId,
    pub action: StableId,
    pub resource_digest: Digest32,
    pub scope_digest: Digest32,
    pub audience: StableId,
    pub quota_key: StableId,
    pub max_reservation: u64,
    pub enabled: bool,
}

impl AuthPolicy {
    pub fn validate(&self) -> bool {
        self.revision > 0
            && self.max_reservation > 0
            && !self.resource_digest.is_zero()
            && !self.scope_digest.is_zero()
    }

    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.authbus.policy.v1\0".to_vec();
        push_id(&mut bytes, &self.policy_id);
        bytes.extend_from_slice(&self.revision.to_be_bytes());
        push_id(&mut bytes, &self.principal_id);
        push_id(&mut bytes, &self.action);
        bytes.extend_from_slice(self.resource_digest.as_array());
        bytes.extend_from_slice(self.scope_digest.as_array());
        push_id(&mut bytes, &self.audience);
        push_id(&mut bytes, &self.quota_key);
        bytes.extend_from_slice(&self.max_reservation.to_be_bytes());
        bytes.push(u8::from(self.enabled));
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizationRequest {
    pub principal_id: StableId,
    pub action: StableId,
    pub resource_digest: Digest32,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub audience: StableId,
    pub policy_id: StableId,
    pub expected_policy_revision: u64,
}

impl AuthorizationRequest {
    pub fn validate(&self) -> bool {
        self.expected_policy_revision > 0
            && !self.resource_digest.is_zero()
            && !self.scope_digest.is_zero()
            && !self.payload_digest.is_zero()
    }

    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.authbus.authorization-request.v1\0".to_vec();
        push_id(&mut bytes, &self.principal_id);
        push_id(&mut bytes, &self.action);
        bytes.extend_from_slice(self.resource_digest.as_array());
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        push_id(&mut bytes, &self.audience);
        push_id(&mut bytes, &self.policy_id);
        bytes.extend_from_slice(&self.expected_policy_revision.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyDecisionKind {
    Allowed,
    Denied,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyDenyReason {
    MissingPolicy,
    Disabled,
    StaleRevision,
    PrincipalMismatch,
    ActionMismatch,
    ResourceMismatch,
    ScopeMismatch,
    AudienceMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizationDecision {
    pub kind: PolicyDecisionKind,
    pub request_digest: Digest32,
    pub policy_id: Option<StableId>,
    pub policy_revision: Option<u64>,
    pub policy_digest: Option<Digest32>,
    pub quota_key: Option<StableId>,
    pub max_reservation: Option<u64>,
    pub deny_reason: Option<PolicyDenyReason>,
}

impl AuthorizationDecision {
    #[must_use]
    pub fn allowed(request: &AuthorizationRequest, policy: &AuthPolicy) -> Self {
        Self {
            kind: PolicyDecisionKind::Allowed,
            request_digest: request.digest(),
            policy_id: Some(policy.policy_id.clone()),
            policy_revision: Some(policy.revision),
            policy_digest: Some(policy.digest()),
            quota_key: Some(policy.quota_key.clone()),
            max_reservation: Some(policy.max_reservation),
            deny_reason: None,
        }
    }

    #[must_use]
    pub fn denied(request: &AuthorizationRequest, reason: PolicyDenyReason) -> Self {
        Self {
            kind: PolicyDecisionKind::Denied,
            request_digest: request.digest(),
            policy_id: None,
            policy_revision: None,
            policy_digest: None,
            quota_key: None,
            max_reservation: None,
            deny_reason: Some(reason),
        }
    }

    pub fn permits(&self, reservation: &ReservationRequest) -> bool {
        self.kind == PolicyDecisionKind::Allowed
            && self.policy_digest == Some(reservation.policy_digest)
            && self.request_digest == reservation.authorization_digest
            && self.quota_key.as_ref() == Some(&reservation.quota_key)
            && self
                .max_reservation
                .is_some_and(|maximum| reservation.amount <= maximum)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaSpec {
    pub quota_key: StableId,
    pub config_revision: u64,
    pub capacity: u64,
    pub period_start_ms: u64,
    pub period_end_ms: u64,
}

impl QuotaSpec {
    pub fn validate(&self) -> bool {
        self.config_revision > 0
            && self.capacity > 0
            && self.period_start_ms > 0
            && self.period_end_ms > self.period_start_ms
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuotaState {
    pub spec: QuotaSpec,
    pub ledger_revision: u64,
    pub reserved: u64,
    pub consumed: u64,
}

impl QuotaState {
    pub fn available(&self) -> Option<u64> {
        self.spec
            .capacity
            .checked_sub(self.reserved.checked_add(self.consumed)?)
    }

    pub fn invariant_holds(&self) -> bool {
        self.ledger_revision > 0 && self.available().is_some()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReservationRequest {
    pub reservation_id: StableId,
    pub operation_id: StableId,
    pub quota_key: StableId,
    pub amount: u64,
    pub expected_quota_revision: u64,
    pub expires_at_ms: u64,
    pub policy_digest: Digest32,
    pub authorization_digest: Digest32,
}

impl ReservationRequest {
    pub fn validate(&self) -> bool {
        self.amount > 0
            && self.expected_quota_revision > 0
            && self.expires_at_ms > 0
            && !self.policy_digest.is_zero()
            && !self.authorization_digest.is_zero()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReservationState {
    Active,
    Settled,
    Cancelled,
    Expired,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReservationRecord {
    pub reservation_id: StableId,
    pub operation_id: StableId,
    pub quota_key: StableId,
    pub amount: u64,
    pub state: ReservationState,
    pub expires_at_ms: u64,
    pub policy_digest: Digest32,
    pub authorization_digest: Digest32,
    pub quota_revision_at_reserve: u64,
    pub observed_cost: Option<u64>,
    pub terminal_evidence: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusRollbackCheckpoint {
    pub generation: u64,
    pub chain_digest: Digest32,
}

impl AuthBusRollbackCheckpoint {
    pub fn validate(&self) -> bool {
        !self.chain_digest.is_zero()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReservationResolution {
    NoEffect { evidence: Digest32 },
    Consumed { observed_cost: u64, evidence: Digest32 },
    Indeterminate { evidence: Digest32 },
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
