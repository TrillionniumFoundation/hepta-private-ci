use std::fmt;

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

/// Administrative input used to enroll or rotate a durable registry entry.
/// This is not proof that the issuer has been admitted; callers receive an
/// opaque [`IssuerRecord`] after the mutation commits.
pub struct IssuerSpec {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
}

/// Durable issuer state returned by the authority owner. Trusted fields are
/// intentionally private outside this crate so callers cannot manufacture an
/// apparently active record and pass it back as authority.
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
            .field("signing_identity_digest", &self.signing_identity_digest())
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

    pub fn state(&self) -> IssuerLifecycleState {
        self.state
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub fn signing_identity_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.verifying_key.to_bytes())
    }
}

/// Read-only issuer metadata exposed through [`VerifiedIssuerHandle`]. This
/// value is intentionally inert: constructing metadata does not create a
/// verified handle and no authority API accepts it.
#[derive(Clone, Debug)]
pub struct IssuerRegistrationView {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
    pub revoked: bool,
}

/// Sealed proof that an issuer entry was resolved from an accepted persistent
/// registry. The public API deliberately exposes no constructor from a naked
/// key, epoch, revocation bit or purpose and never implements `DerefMut`.
#[derive(Clone)]
pub struct VerifiedIssuerHandle {
    view: IssuerRegistrationView,
    purpose: IssuerPurpose,
    state: IssuerLifecycleState,
    registry_revision: u64,
    registry_digest: Digest32,
}

impl std::ops::Deref for VerifiedIssuerHandle {
    type Target = IssuerRegistrationView;

    fn deref(&self) -> &Self::Target {
        &self.view
    }
}

impl fmt::Debug for VerifiedIssuerHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedIssuerHandle")
            .field("issuer_id", &self.issuer_id)
            .field("purpose", &self.purpose)
            .field("key_epoch", &self.key_epoch)
            .field("state", &self.state)
            .field("registry_revision", &self.registry_revision)
            .field("registry_digest", &self.registry_digest)
            .field("signing_identity_digest", &self.signing_identity_digest())
            .finish()
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

    pub fn state(&self) -> IssuerLifecycleState {
        self.state
    }

    pub fn is_active(&self) -> bool {
        self.state == IssuerLifecycleState::Active
    }

    pub fn is_revoked(&self) -> bool {
        self.state != IssuerLifecycleState::Active
    }

    pub fn registry_revision(&self) -> u64 {
        self.registry_revision
    }

    pub fn registry_digest(&self) -> Digest32 {
        self.registry_digest
    }

    pub fn signing_identity_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.verifying_key.to_bytes())
    }

    /// Public keys are not secret; this read-only copy lets downstream evidence
    /// bind a receipt to the exact signing identity without exposing a trusted
    /// registration constructor.
    pub fn verifying_key_bytes(&self) -> [u8; 32] {
        self.verifying_key.to_bytes()
    }

    pub(crate) fn verifying_key(&self) -> &VerifyingKey {
        &self.verifying_key
    }

    pub(crate) fn from_record(record: &IssuerRecord) -> Result<Self, AuthBusAuthorityError> {
        Self::new(
            record.issuer_id.clone(),
            record.purpose,
            record.key_epoch,
            record.verifying_key.clone(),
            record.state,
            record.revision,
            record_digest(record),
        )
    }

    pub(crate) fn from_registry_entry(
        issuer_id: StableId,
        purpose: IssuerPurpose,
        key_epoch: Generation,
        verifying_key: VerifyingKey,
        state: IssuerLifecycleState,
        registry_revision: u64,
        registry_digest: Digest32,
    ) -> Result<Self, AuthBusAuthorityError> {
        Self::new(
            issuer_id,
            purpose,
            key_epoch,
            verifying_key,
            state,
            registry_revision,
            registry_digest,
        )
    }

    fn new(
        issuer_id: StableId,
        purpose: IssuerPurpose,
        key_epoch: Generation,
        verifying_key: VerifyingKey,
        state: IssuerLifecycleState,
        registry_revision: u64,
        registry_digest: Digest32,
    ) -> Result<Self, AuthBusAuthorityError> {
        if registry_revision == 0 || registry_digest.is_zero() {
            return Err(AuthBusAuthorityError::InvalidIssuerRegistry);
        }
        Ok(Self {
            view: IssuerRegistrationView {
                issuer_id,
                key_epoch,
                verifying_key,
                revoked: state != IssuerLifecycleState::Active,
            },
            purpose,
            state,
            registry_revision,
            registry_digest,
        })
    }
}

fn record_digest(record: &IssuerRecord) -> Digest32 {
    let mut bytes = b"hepta.authbus.verified-issuer-record.v1\0".to_vec();
    push_id(&mut bytes, &record.issuer_id);
    bytes.push(purpose_code(record.purpose));
    bytes.extend_from_slice(&record.key_epoch.get().to_be_bytes());
    bytes.extend_from_slice(&record.verifying_key.to_bytes());
    bytes.push(state_code(record.state));
    bytes.extend_from_slice(&record.revision.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub(crate) fn purpose_code(purpose: IssuerPurpose) -> u8 {
    match purpose {
        IssuerPurpose::Message => 1,
        IssuerPurpose::Settlement => 2,
        IssuerPurpose::TrustedTime => 3,
    }
}

pub(crate) fn state_code(state: IssuerLifecycleState) -> u8 {
    match state {
        IssuerLifecycleState::Active => 1,
        IssuerLifecycleState::Revoked => 2,
        IssuerLifecycleState::Retired => 3,
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
        bytes.push(purpose_code(record.purpose));
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
