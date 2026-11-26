use std::ops::Deref;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;

use crate::AuthBusAuthorityError;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::IssuerRegistrationView;
use crate::push_id;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SettlementStatus {
    Completed,
    Rejected,
}

/// Sealed settlement issuer handle. Only the durable AuthBus issuer registry
/// can construct it; callers cannot substitute their own verification key.
#[derive(Clone, Debug)]
pub struct SettlementIssuerRegistration {
    view: IssuerRegistrationView,
    registry_digest: Digest32,
    registry_revision: u64,
}

impl Deref for SettlementIssuerRegistration {
    type Target = IssuerRegistrationView;

    fn deref(&self) -> &Self::Target {
        &self.view
    }
}

impl SettlementIssuerRegistration {
    pub fn registry_digest(&self) -> Digest32 {
        self.registry_digest
    }

    pub fn registry_revision(&self) -> u64 {
        self.registry_revision
    }

    pub(crate) fn from_record(record: &IssuerRecord) -> Result<Self, AuthBusAuthorityError> {
        if record.purpose != IssuerPurpose::Settlement {
            return Err(AuthBusAuthorityError::SettlementIssuerMismatch);
        }
        let view = IssuerRegistrationView {
            issuer_id: record.issuer_id.clone(),
            key_epoch: record.key_epoch,
            verifying_key: record.verifying_key,
            revoked: record.state != IssuerLifecycleState::Active,
        };
        let mut bytes = b"hepta.authbus.settlement-issuer-registration.v1\0".to_vec();
        push_id(&mut bytes, &view.issuer_id);
        bytes.extend_from_slice(&view.key_epoch.get().to_be_bytes());
        bytes.extend_from_slice(&view.verifying_key.to_bytes());
        bytes.push(match record.state {
            IssuerLifecycleState::Active => 1,
            IssuerLifecycleState::Revoked => 2,
            IssuerLifecycleState::Retired => 3,
        });
        bytes.extend_from_slice(&record.revision.to_be_bytes());
        Ok(Self {
            view,
            registry_digest: Digest32::of_bytes(&bytes),
            registry_revision: record.revision,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SettlementEvidenceClaims {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub reservation_id: StableId,
    pub operation_id: StableId,
    pub status: SettlementStatus,
    pub observed_cost: u64,
    pub terminal_evidence_digest: Digest32,
    pub observed_at_ms: u64,
    pub expires_at_ms: u64,
}

impl SettlementEvidenceClaims {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.authbus.settlement-evidence.v1\0".to_vec();
        push_id(&mut bytes, &self.issuer_id);
        bytes.extend_from_slice(&self.key_epoch.get().to_be_bytes());
        push_id(&mut bytes, &self.reservation_id);
        push_id(&mut bytes, &self.operation_id);
        bytes.push(match self.status {
            SettlementStatus::Completed => 1,
            SettlementStatus::Rejected => 2,
        });
        bytes.extend_from_slice(&self.observed_cost.to_be_bytes());
        bytes.extend_from_slice(self.terminal_evidence_digest.as_array());
        bytes.extend_from_slice(&self.observed_at_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_ms.to_be_bytes());
        bytes
    }
}

pub struct SignedSettlementEvidence {
    pub claims: SettlementEvidenceClaims,
    pub signature: [u8; 64],
}

pub(crate) struct AuthenticatedSettlementEvidence {
    claims: SettlementEvidenceClaims,
    evidence_digest: Digest32,
}

impl SignedSettlementEvidence {
    pub(crate) fn receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.authbus.settlement-receipt.v1\0".to_vec();
        bytes.extend_from_slice(&self.claims.signing_bytes());
        bytes.extend_from_slice(&self.signature);
        Digest32::of_bytes(&bytes)
    }

    pub(crate) fn authenticate(
        &self,
        issuer: &SettlementIssuerRegistration,
        reservation_id: &StableId,
        operation_id: &StableId,
        now_ms: u64,
    ) -> Result<AuthenticatedSettlementEvidence, AuthBusAuthorityError> {
        if self.claims.issuer_id != issuer.issuer_id || self.claims.key_epoch != issuer.key_epoch {
            return Err(AuthBusAuthorityError::SettlementIssuerMismatch);
        }
        if &self.claims.reservation_id != reservation_id
            || &self.claims.operation_id != operation_id
        {
            return Err(AuthBusAuthorityError::SettlementEvidenceMismatch);
        }
        if issuer.revoked {
            return Err(AuthBusAuthorityError::SettlementIssuerRevoked);
        }
        if self.claims.terminal_evidence_digest.is_zero()
            || self.claims.observed_at_ms == 0
            || self.claims.observed_at_ms > now_ms
            || now_ms >= self.claims.expires_at_ms
            || (self.claims.status == SettlementStatus::Rejected && self.claims.observed_cost != 0)
        {
            return Err(AuthBusAuthorityError::InvalidSettlementEvidence);
        }
        issuer
            .verifying_key
            .verify_strict(
                &self.claims.signing_bytes(),
                &Signature::from_bytes(&self.signature),
            )
            .map_err(|_| AuthBusAuthorityError::InvalidSettlementSignature)?;
        Ok(AuthenticatedSettlementEvidence {
            claims: self.claims.clone(),
            evidence_digest: self.receipt_digest(),
        })
    }
}

impl AuthenticatedSettlementEvidence {
    pub(crate) fn claims(&self) -> &SettlementEvidenceClaims {
        &self.claims
    }

    pub(crate) fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Settlement {
    pub reservation_id: StableId,
    pub operation_id: StableId,
    pub state: crate::ReservationState,
    pub reserved_amount: u64,
    pub observed_cost: u64,
    pub terminal_evidence_digest: Digest32,
    pub settlement_digest: Digest32,
    pub reservation_revision: u64,
    pub authority: AuthorityPosture,
}
