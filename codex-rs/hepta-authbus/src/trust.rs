use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use tokio::sync::OwnedRwLockReadGuard;

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

/// Administrative enrollment input. It is not a trusted registration and is
/// never accepted by message or settlement verification paths.
pub struct IssuerSpec {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
}

/// Persisted issuer metadata. Trusted fields are read-only outside this crate;
/// constructing a value with the same data cannot create verification authority.
#[derive(Clone)]
pub struct IssuerRecord {
    pub(crate) issuer_id: StableId,
    pub(crate) purpose: IssuerPurpose,
    pub(crate) key_epoch: Generation,
    pub(crate) verifying_key: VerifyingKey,
    pub(crate) state: IssuerLifecycleState,
    pub(crate) revision: u64,
}

impl fmt::Debug for IssuerRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("IssuerRecord")
            .field("issuer_id", &self.issuer_id)
            .field("purpose", &self.purpose)
            .field("key_epoch", &self.key_epoch)
            .field("verifying_key_digest", &self.verifying_key_digest())
            .field("state", &self.state)
            .field("revision", &self.revision)
            .finish()
    }
}

impl IssuerRecord {
    pub fn issuer_id(&self) -> &StableId {
        &self.issuer_id
    }

    pub fn purpose(&self) -> IssuerPurpose {
        self.purpose
    }

    pub fn key_epoch(&self) -> Generation {
        self.key_epoch
    }

    pub fn verifying_key_digest(&self) -> Digest32 {
        Digest32::of_bytes(self.verifying_key.as_bytes())
    }

    pub fn state(&self) -> IssuerLifecycleState {
        self.state
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }
}

/// Opaque, registry-resolved issuer capability. Only `AuthBusAuthorityHost` can
/// construct one. The owned read guard fences issuer rotation/revocation until
/// the consuming transaction has committed or rolled back.
pub struct VerifiedIssuerHandle {
    issuer_id: StableId,
    purpose: IssuerPurpose,
    key_epoch: Generation,
    verifying_key: VerifyingKey,
    state: IssuerLifecycleState,
    revision: u64,
    registry_guard: OwnedRwLockReadGuard<()>,
}

impl fmt::Debug for VerifiedIssuerHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedIssuerHandle")
            .field("issuer_id", &self.issuer_id)
            .field("purpose", &self.purpose)
            .field("key_epoch", &self.key_epoch)
            .field("verifying_key_digest", &self.verifying_key_digest())
            .field("state", &self.state)
            .field("revision", &self.revision)
            .finish_non_exhaustive()
    }
}

impl VerifiedIssuerHandle {
    pub fn issuer_id(&self) -> &StableId {
        &self.issuer_id
    }

    pub fn purpose(&self) -> IssuerPurpose {
        self.purpose
    }

    pub fn key_epoch(&self) -> Generation {
        self.key_epoch
    }

    pub fn verifying_key_digest(&self) -> Digest32 {
        Digest32::of_bytes(self.verifying_key.as_bytes())
    }

    pub fn state(&self) -> IssuerLifecycleState {
        self.state
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub(crate) fn from_record(
        record: IssuerRecord,
        registry_guard: OwnedRwLockReadGuard<()>,
    ) -> Self {
        Self {
            issuer_id: record.issuer_id,
            purpose: record.purpose,
            key_epoch: record.key_epoch,
            verifying_key: record.verifying_key,
            state: record.state,
            revision: record.revision,
            registry_guard,
        }
    }

    pub(crate) fn verifying_key(&self) -> &VerifyingKey {
        &self.verifying_key
    }

    pub(crate) fn into_registry_guard(self) -> OwnedRwLockReadGuard<()> {
        self.registry_guard
    }
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
