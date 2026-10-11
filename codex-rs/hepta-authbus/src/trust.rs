use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::AuthBusAuthorityError;
use crate::push_id;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IssuerPurpose {
    Message,
    Settlement,
    TrustedTime,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IssuerLifecycleState {
    Active,
    Revoked,
    Retired,
}

pub struct IssuerSpec {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
}

#[derive(Clone, Debug)]
pub struct IssuerRecord {
    pub issuer_id: StableId,
    pub purpose: IssuerPurpose,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
    pub state: IssuerLifecycleState,
    pub revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedTimeAttestationClaims {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub wall_time_ms: u64,
    pub source_revision: u64,
    pub source_digest: Digest32,
}

impl TrustedTimeAttestationClaims {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.authbus.trusted-time.v1\0".to_vec();
        push_id(&mut bytes, &self.issuer_id);
        bytes.extend_from_slice(&self.key_epoch.get().to_be_bytes());
        bytes.extend_from_slice(&self.wall_time_ms.to_be_bytes());
        bytes.extend_from_slice(&self.source_revision.to_be_bytes());
        bytes.extend_from_slice(self.source_digest.as_array());
        bytes
    }
}

pub struct SignedTrustedTimeAttestation {
    pub claims: TrustedTimeAttestationClaims,
    pub signature: [u8; 64],
}

impl SignedTrustedTimeAttestation {
    pub(crate) fn verify(
        &self,
        record: &IssuerRecord,
    ) -> Result<crate::TrustedTimeSample, AuthBusAuthorityError> {
        if record.purpose != IssuerPurpose::TrustedTime
            || record.state != IssuerLifecycleState::Active
            || self.claims.issuer_id != record.issuer_id
            || self.claims.key_epoch != record.key_epoch
        {
            return Err(AuthBusAuthorityError::TrustedTimeIssuerMismatch);
        }
        record
            .verifying_key
            .verify_strict(
                &self.claims.signing_bytes(),
                &Signature::from_bytes(&self.signature),
            )
            .map_err(|_| AuthBusAuthorityError::InvalidTrustedTimeSignature)?;
        crate::TrustedTimeSample::new(
            self.claims.wall_time_ms,
            self.claims.source_revision,
            self.claims.source_digest,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IssuerRetirement {
    issuer_id: StableId,
    purpose: IssuerPurpose,
    key_epoch: Generation,
    revision: u64,
    retirement_digest: Digest32,
}

impl IssuerRetirement {
    pub fn issuer_id(&self) -> &StableId {
        &self.issuer_id
    }

    pub fn purpose(&self) -> IssuerPurpose {
        self.purpose
    }

    pub fn key_epoch(&self) -> Generation {
        self.key_epoch
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub fn retirement_digest(&self) -> Digest32 {
        self.retirement_digest
    }

    pub(crate) fn from_record(record: &IssuerRecord) -> Self {
        let mut bytes = b"hepta.authbus.issuer-retirement.v1\0".to_vec();
        push_id(&mut bytes, &record.issuer_id);
        bytes.push(match record.purpose {
            IssuerPurpose::Message => 1,
            IssuerPurpose::Settlement => 2,
            IssuerPurpose::TrustedTime => 3,
        });
        bytes.extend_from_slice(&record.key_epoch.get().to_be_bytes());
        bytes.extend_from_slice(&record.revision.to_be_bytes());
        bytes.extend_from_slice(&record.verifying_key.to_bytes());
        Self {
            issuer_id: record.issuer_id.clone(),
            purpose: record.purpose,
            key_epoch: record.key_epoch,
            revision: record.revision,
            retirement_digest: Digest32::of_bytes(&bytes),
        }
    }
}
