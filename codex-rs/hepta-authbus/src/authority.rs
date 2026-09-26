use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyEffect {
    Allow,
    Deny,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedTimeSample {
    pub(crate) wall_time_ms: u64,
    pub(crate) source_revision: u64,
    pub(crate) source_digest: Digest32,
}

impl TrustedTimeSample {
    pub(crate) fn new(
        wall_time_ms: u64,
        source_revision: u64,
        source_digest: Digest32,
    ) -> Result<Self, AuthBusAuthorityError> {
        if wall_time_ms == 0 || source_revision == 0 || source_digest.is_zero() {
            return Err(AuthBusAuthorityError::InvalidInput(
                "trusted time must bind non-zero time, revision and source digest",
            ));
        }
        Ok(Self {
            wall_time_ms,
            source_revision,
            source_digest,
        })
    }

    pub fn wall_time_ms(&self) -> u64 {
        self.wall_time_ms
    }

    pub fn source_revision(&self) -> u64 {
        self.source_revision
    }

    pub fn source_digest(&self) -> Digest32 {
        self.source_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicySpec {
    pub policy_id: StableId,
    pub principal: StableId,
    pub action: StableId,
    pub scope_digest: Digest32,
    pub effect: PolicyEffect,
    pub not_before_ms: u64,
    pub expires_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthPolicy {
    pub policy_id: StableId,
    pub principal: StableId,
    pub action: StableId,
    pub scope_digest: Digest32,
    pub effect: PolicyEffect,
    pub revision: u64,
    pub not_before_ms: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyDecision {
    policy_id: StableId,
    principal: StableId,
    action: StableId,
    scope_digest: Digest32,
    policy_revision: u64,
    allowed: bool,
    decided_at_ms: u64,
    decision_digest: Digest32,
    authority: AuthorityPosture,
}

impl PolicyDecision {
    pub fn policy_id(&self) -> &StableId {
        &self.policy_id
    }

    pub fn principal(&self) -> &StableId {
        &self.principal
    }

    pub fn action(&self) -> &StableId {
        &self.action
    }

    pub fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    pub fn policy_revision(&self) -> u64 {
        self.policy_revision
    }

    pub fn allowed(&self) -> bool {
        self.allowed
    }

    pub fn decided_at_ms(&self) -> u64 {
        self.decided_at_ms
    }

    pub fn decision_digest(&self) -> Digest32 {
        self.decision_digest
    }

    pub fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub(crate) fn new(policy: &AuthPolicy, time: &TrustedTimeSample) -> Self {
        let mut bytes = b"hepta.authbus.policy-decision.v1\0".to_vec();
        crate::push_id(&mut bytes, &policy.policy_id);
        crate::push_id(&mut bytes, &policy.principal);
        crate::push_id(&mut bytes, &policy.action);
        bytes.extend_from_slice(policy.scope_digest.as_array());
        bytes.extend_from_slice(&policy.revision.to_be_bytes());
        bytes.push(u8::from(policy.effect == PolicyEffect::Allow));
        bytes.extend_from_slice(&time.wall_time_ms.to_be_bytes());
        bytes.extend_from_slice(&time.source_revision.to_be_bytes());
        bytes.extend_from_slice(time.source_digest.as_array());
        Self {
            policy_id: policy.policy_id.clone(),
            principal: policy.principal.clone(),
            action: policy.action.clone(),
            scope_digest: policy.scope_digest,
            policy_revision: policy.revision,
            allowed: policy.effect == PolicyEffect::Allow,
            decided_at_ms: time.wall_time_ms,
            decision_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AuthBusAuthorityError {
    #[error("invalid AuthBus authority input: {0}")]
    InvalidInput(&'static str),
    #[error("corrupt AuthBus authority state: {0}")]
    CorruptState(&'static str),
    #[error("AuthBus authority storage is unavailable: {0}")]
    Storage(String),
    #[error("AuthBus authority record was not found")]
    NotFound,
    #[error("AuthBus authority record already exists")]
    AlreadyExists,
    #[error("AuthBus authority revision conflict")]
    RevisionConflict,
    #[error("AuthBus request reused an idempotency identity with different semantics")]
    IdempotencyConflict,
    #[error("AuthBus quota registry entry is missing")]
    QuotaMissing,
    #[error("AuthBus quota would exceed its configured endowment")]
    QuotaExceeded,
    #[error("AuthBus quota reservation is missing")]
    ReservationMissing,
    #[error("AuthBus settlement issuer does not match the signed evidence")]
    SettlementIssuerMismatch,
    #[error("AuthBus settlement issuer is revoked")]
    SettlementIssuerRevoked,
    #[error("AuthBus settlement evidence does not match the reservation")]
    SettlementEvidenceMismatch,
    #[error("AuthBus settlement evidence is invalid or outside its validity window")]
    InvalidSettlementEvidence,
    #[error("AuthBus settlement evidence signature is invalid")]
    InvalidSettlementSignature,
    #[error("observed settlement cost exceeds the held reservation")]
    ObservedCostExceedsReservation,
    #[error("AuthBus issuer registration is missing")]
    IssuerMissing,
    #[error("AuthBus issuer key epoch did not advance monotonically")]
    KeyEpochRegression,
    #[error("trusted-time attestation does not name an active time issuer")]
    TrustedTimeIssuerMismatch,
    #[error("trusted-time attestation signature is invalid")]
    InvalidTrustedTimeSignature,
    #[error("invalid AuthBus authority state transition")]
    InvalidTransition,
    #[error("trusted AuthBus time moved backwards")]
    ClockRollback,
    #[error("trusted AuthBus time revision was reused with different content")]
    TimeConflict,
    #[error("AuthBus authorization policy is missing")]
    PolicyMissing,
    #[error("AuthBus authorization policy is revoked or outside its validity window")]
    PolicyUnavailable,
    #[error("AuthBus authorization policy revision is stale")]
    StalePolicyRevision,
    #[error("AuthBus authority state capacity exceeded")]
    CapacityExceeded,
    #[error("AuthBus external authority checkpoint indicates rollback or drift")]
    RollbackDetected,
    #[error("AuthBus owner has not completed restart reconciliation")]
    RecoveryRequired,
    #[error("AuthBus authority checkpoint file is unsafe or unavailable")]
    UnsafeCheckpoint,
    #[error("AuthBus policy cannot be retired while reservations still reference it")]
    PolicyInUse,
    #[error("another AuthBus authority owner is already active")]
    OwnerAlreadyActive,
    #[error("AuthBus owner lock is unsafe or unavailable")]
    OwnerLockUnavailable,
}
