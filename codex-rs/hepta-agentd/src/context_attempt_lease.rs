//! External idempotency/lease contract for provider-bound context attempts.
//!
//! This module deliberately supplies no process-local fallback. A production
//! `AgentdPromptProductOwnerV3` must receive a host-owned implementation backed
//! by the deployment's distributed lease/idempotency authority. Reusing an
//! attempt or exact-body key with different semantics is a hard conflict.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const REQUEST_DOMAIN: &[u8] = b"hepta.context-attempt-lease-request.v3";
const GRANT_DOMAIN: &[u8] = b"hepta.context-attempt-lease-grant.v3";
const SETTLEMENT_DOMAIN: &[u8] = b"hepta.context-attempt-lease-settlement.v3";

#[derive(Clone, Eq, PartialEq)]
pub struct ContextAttemptLeaseRequestV3 {
    pub thread_id: StableId,
    pub turn_id: StableId,
    pub attempt_id: StableId,
    pub idempotency_key: Digest32,
    pub exact_body_digest: Digest32,
    pub provider_wire_semantic_digest: Digest32,
    pub owner_generation: u64,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    request_digest: Digest32,
}

impl ContextAttemptLeaseRequestV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        thread_id: StableId,
        turn_id: StableId,
        attempt_id: StableId,
        idempotency_key: Digest32,
        exact_body_digest: Digest32,
        provider_wire_semantic_digest: Digest32,
        owner_generation: u64,
        issued_unix_ms: u64,
        expires_unix_ms: u64,
    ) -> Result<Self, ContextAttemptLeaseErrorV3> {
        let mut value = Self {
            thread_id,
            turn_id,
            attempt_id,
            idempotency_key,
            exact_body_digest,
            provider_wire_semantic_digest,
            owner_generation,
            issued_unix_ms,
            expires_unix_ms,
            request_digest: Digest32::ZERO,
        };
        value.request_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContextAttemptLeaseErrorV3> {
        if self.idempotency_key.is_zero()
            || self.exact_body_digest.is_zero()
            || self.provider_wire_semantic_digest.is_zero()
            || self.owner_generation == 0
            || self.issued_unix_ms == 0
            || self.expires_unix_ms <= self.issued_unix_ms
            || self.request_digest != self.compute_digest()
        {
            return Err(ContextAttemptLeaseErrorV3::InvalidRequest);
        }
        Ok(())
    }

    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = REQUEST_DOMAIN.to_vec();
        for value in [&self.thread_id, &self.turn_id, &self.attempt_id] {
            push_id(&mut bytes, value);
        }
        bytes.extend_from_slice(self.idempotency_key.as_array());
        bytes.extend_from_slice(self.exact_body_digest.as_array());
        bytes.extend_from_slice(self.provider_wire_semantic_digest.as_array());
        bytes.extend_from_slice(&self.owner_generation.to_be_bytes());
        bytes.extend_from_slice(&self.issued_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for ContextAttemptLeaseRequestV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextAttemptLeaseRequestV3")
            .field("thread_id", &self.thread_id)
            .field("turn_id", &self.turn_id)
            .field("attempt_id", &self.attempt_id)
            .field("idempotency_key", &self.idempotency_key)
            .field("exact_body_digest", &self.exact_body_digest)
            .field(
                "provider_wire_semantic_digest",
                &self.provider_wire_semantic_digest,
            )
            .field("owner_generation", &self.owner_generation)
            .field("issued_unix_ms", &self.issued_unix_ms)
            .field("expires_unix_ms", &self.expires_unix_ms)
            .field("request_digest", &self.request_digest)
            .finish()
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct ContextAttemptLeaseGrantV3 {
    pub lease_id: StableId,
    pub request_digest: Digest32,
    pub authority_digest: Digest32,
    pub authority_epoch: u64,
    pub granted_unix_ms: u64,
    pub expires_unix_ms: u64,
    grant_digest: Digest32,
}

impl ContextAttemptLeaseGrantV3 {
    pub fn from_authority(
        lease_id: StableId,
        request_digest: Digest32,
        authority_digest: Digest32,
        authority_epoch: u64,
        granted_unix_ms: u64,
        expires_unix_ms: u64,
    ) -> Result<Self, ContextAttemptLeaseErrorV3> {
        let mut value = Self {
            lease_id,
            request_digest,
            authority_digest,
            authority_epoch,
            granted_unix_ms,
            expires_unix_ms,
            grant_digest: Digest32::ZERO,
        };
        value.grant_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContextAttemptLeaseErrorV3> {
        if self.request_digest.is_zero()
            || self.authority_digest.is_zero()
            || self.authority_epoch == 0
            || self.granted_unix_ms == 0
            || self.expires_unix_ms <= self.granted_unix_ms
            || self.grant_digest != self.compute_digest()
        {
            return Err(ContextAttemptLeaseErrorV3::InvalidGrant);
        }
        Ok(())
    }

    pub fn validate_for(
        &self,
        request: &ContextAttemptLeaseRequestV3,
        authority_digest: Digest32,
        now_unix_ms: u64,
    ) -> Result<(), ContextAttemptLeaseErrorV3> {
        self.validate()?;
        request.validate()?;
        if self.request_digest != request.request_digest() {
            return Err(ContextAttemptLeaseErrorV3::BindingMismatch);
        }
        if self.authority_digest != authority_digest || authority_digest.is_zero() {
            return Err(ContextAttemptLeaseErrorV3::AuthorityMismatch);
        }
        if self.granted_unix_ms < request.issued_unix_ms
            || self.expires_unix_ms > request.expires_unix_ms
        {
            return Err(ContextAttemptLeaseErrorV3::InvalidGrant);
        }
        if now_unix_ms < self.granted_unix_ms || now_unix_ms >= self.expires_unix_ms {
            return Err(ContextAttemptLeaseErrorV3::Expired);
        }
        Ok(())
    }

    #[must_use]
    pub const fn grant_digest(&self) -> Digest32 {
        self.grant_digest
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = GRANT_DOMAIN.to_vec();
        push_id(&mut bytes, &self.lease_id);
        bytes.extend_from_slice(self.request_digest.as_array());
        bytes.extend_from_slice(self.authority_digest.as_array());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.granted_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for ContextAttemptLeaseGrantV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextAttemptLeaseGrantV3")
            .field("lease_id", &self.lease_id)
            .field("request_digest", &self.request_digest)
            .field("authority_digest", &self.authority_digest)
            .field("authority_epoch", &self.authority_epoch)
            .field("granted_unix_ms", &self.granted_unix_ms)
            .field("expires_unix_ms", &self.expires_unix_ms)
            .field("grant_digest", &self.grant_digest)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAttemptLeaseSettlementV3 {
    pub grant_digest: Digest32,
    pub exact_body_digest: Digest32,
    pub terminal_receipt_digest: Digest32,
    pub settled_unix_ms: u64,
    pub settlement_digest: Digest32,
}

impl ContextAttemptLeaseSettlementV3 {
    pub fn new(
        grant: &ContextAttemptLeaseGrantV3,
        exact_body_digest: Digest32,
        terminal_receipt_digest: Digest32,
        settled_unix_ms: u64,
    ) -> Result<Self, ContextAttemptLeaseErrorV3> {
        grant.validate()?;
        if exact_body_digest.is_zero()
            || terminal_receipt_digest.is_zero()
            || settled_unix_ms < grant.granted_unix_ms
        {
            return Err(ContextAttemptLeaseErrorV3::InvalidSettlement);
        }
        let mut bytes = SETTLEMENT_DOMAIN.to_vec();
        bytes.extend_from_slice(grant.grant_digest().as_array());
        bytes.extend_from_slice(exact_body_digest.as_array());
        bytes.extend_from_slice(terminal_receipt_digest.as_array());
        bytes.extend_from_slice(&settled_unix_ms.to_be_bytes());
        Ok(Self {
            grant_digest: grant.grant_digest(),
            exact_body_digest,
            terminal_receipt_digest,
            settled_unix_ms,
            settlement_digest: Digest32::of_bytes(&bytes),
        })
    }
}

pub trait ContextAttemptLeaseAuthorityV3: Send + Sync {
    fn authority_digest(&self) -> Digest32;

    fn acquire(
        &self,
        request: &ContextAttemptLeaseRequestV3,
    ) -> Result<ContextAttemptLeaseGrantV3, String>;

    fn settle(&self, settlement: &ContextAttemptLeaseSettlementV3) -> Result<(), String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContextAttemptLeaseErrorV3 {
    InvalidRequest,
    InvalidGrant,
    BindingMismatch,
    AuthorityMismatch,
    Expired,
    InvalidSettlement,
    AuthorityRejected,
    SettlementRejected,
}

impl ContextAttemptLeaseErrorV3 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidRequest => "context_attempt_lease_invalid_request",
            Self::InvalidGrant => "context_attempt_lease_invalid_grant",
            Self::BindingMismatch => "context_attempt_lease_binding_mismatch",
            Self::AuthorityMismatch => "context_attempt_lease_authority_mismatch",
            Self::Expired => "context_attempt_lease_expired",
            Self::InvalidSettlement => "context_attempt_lease_invalid_settlement",
            Self::AuthorityRejected => "context_attempt_lease_authority_rejected",
            Self::SettlementRejected => "context_attempt_lease_settlement_rejected",
        }
    }
}

impl fmt::Display for ContextAttemptLeaseErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl std::error::Error for ContextAttemptLeaseErrorV3 {}

pub fn acquire_context_attempt_lease_v3(
    authority: &impl ContextAttemptLeaseAuthorityV3,
    request: &ContextAttemptLeaseRequestV3,
    now_unix_ms: u64,
) -> Result<ContextAttemptLeaseGrantV3, ContextAttemptLeaseErrorV3> {
    request.validate()?;
    let authority_digest = authority.authority_digest();
    if authority_digest.is_zero() {
        return Err(ContextAttemptLeaseErrorV3::AuthorityMismatch);
    }
    let grant = authority
        .acquire(request)
        .map_err(|_| ContextAttemptLeaseErrorV3::AuthorityRejected)?;
    grant.validate_for(request, authority_digest, now_unix_ms)?;
    Ok(grant)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Authority {
        digest: Digest32,
    }

    impl ContextAttemptLeaseAuthorityV3 for Authority {
        fn authority_digest(&self) -> Digest32 {
            self.digest
        }

        fn acquire(
            &self,
            request: &ContextAttemptLeaseRequestV3,
        ) -> Result<ContextAttemptLeaseGrantV3, String> {
            ContextAttemptLeaseGrantV3::from_authority(
                id("lease-1"),
                request.request_digest(),
                self.digest,
                9,
                101,
                190,
            )
            .map_err(|error| error.to_string())
        }

        fn settle(&self, _settlement: &ContextAttemptLeaseSettlementV3) -> Result<(), String> {
            Ok(())
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|_| panic!("invalid test id"))
    }

    fn request() -> ContextAttemptLeaseRequestV3 {
        ContextAttemptLeaseRequestV3::new(
            id("thread-1"),
            id("turn-1"),
            id("attempt-1"),
            Digest32::of_bytes(b"idempotency"),
            Digest32::of_bytes(b"body"),
            Digest32::of_bytes(b"wire"),
            5,
            100,
            200,
        )
        .unwrap_or_else(|_| panic!("valid request"))
    }

    #[test]
    fn external_authority_binds_exact_attempt() {
        let authority = Authority {
            digest: Digest32::of_bytes(b"lease-authority"),
        };
        let request = request();
        let grant = acquire_context_attempt_lease_v3(&authority, &request, 110)
            .unwrap_or_else(|_| panic!("lease should be granted"));
        assert_eq!(grant.request_digest, request.request_digest());
        assert!(!grant.grant_digest().is_zero());
    }

    #[test]
    fn exact_body_drift_changes_idempotency_request() {
        let left = request();
        let right = ContextAttemptLeaseRequestV3::new(
            left.thread_id.clone(),
            left.turn_id.clone(),
            left.attempt_id.clone(),
            left.idempotency_key,
            Digest32::of_bytes(b"different-body"),
            left.provider_wire_semantic_digest,
            left.owner_generation,
            left.issued_unix_ms,
            left.expires_unix_ms,
        )
        .unwrap_or_else(|_| panic!("valid drift fixture"));
        assert_ne!(left.request_digest(), right.request_digest());
    }
}
