use std::ops::Deref;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::AuthBusAuthorityError;
use crate::Error;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::PreverifiedAuthEnvelope;
use crate::ReplayWindow;
use crate::TrustedReplayContext;
use crate::VerificationReceipt;
use crate::push_id;

/// Read-only view of a verified message-issuer registration. The view is public
/// only so existing consumers can inspect fields through `Deref`; APIs accept
/// `IssuerRegistration`, whose constructor and seal remain inside AuthBus.
#[doc(hidden)]
#[derive(Clone)]
pub struct IssuerRegistrationView {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
    pub revoked: bool,
}

/// Sealed registration resolved from a verified persistent registry. Callers
/// can inspect it but cannot construct or alter one in production builds.
#[derive(Clone)]
pub struct IssuerRegistration {
    view: IssuerRegistrationView,
    registry_digest: Digest32,
}

impl IssuerRegistration {
    pub(crate) fn from_record(record: IssuerRecord) -> Result<Self, AuthBusAuthorityError> {
        if record.purpose != IssuerPurpose::Message {
            return Err(AuthBusAuthorityError::IssuerPurposeMismatch);
        }
        let mut bytes = b"hepta.authbus.sqlite-issuer-record.v1\0".to_vec();
        push_id(&mut bytes, &record.issuer_id);
        bytes.extend_from_slice(&record.key_epoch.get().to_be_bytes());
        bytes.extend_from_slice(&record.verifying_key.to_bytes());
        bytes.push(match record.state {
            IssuerLifecycleState::Active => 1,
            IssuerLifecycleState::Revoked => 2,
            IssuerLifecycleState::Retired => 3,
        });
        bytes.extend_from_slice(&record.revision.to_be_bytes());
        Self::from_registry_parts(
            record.issuer_id,
            record.key_epoch,
            record.verifying_key,
            record.state != IssuerLifecycleState::Active,
            Digest32::of_bytes(&bytes),
        )
    }

    pub(crate) fn from_registry_parts(
        issuer_id: StableId,
        key_epoch: Generation,
        verifying_key: VerifyingKey,
        revoked: bool,
        registry_digest: Digest32,
    ) -> Result<Self, AuthBusAuthorityError> {
        if registry_digest.is_zero() {
            return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
        }
        Ok(Self {
            view: IssuerRegistrationView {
                issuer_id,
                key_epoch,
                verifying_key,
                revoked,
            },
            registry_digest,
        })
    }

    pub fn issuer_id(&self) -> &StableId {
        &self.view.issuer_id
    }

    pub fn key_epoch(&self) -> Generation {
        self.view.key_epoch
    }

    pub fn is_revoked(&self) -> bool {
        self.view.revoked
    }

    pub fn registry_digest(&self) -> Digest32 {
        self.registry_digest
    }

    /// Test-only constructor. The feature is enabled only from dependent
    /// packages' dev-dependencies and is forbidden by the API inventory gate
    /// in production dependency declarations.
    #[cfg(feature = "test-support")]
    pub fn test_only(
        issuer_id: StableId,
        key_epoch: Generation,
        verifying_key: VerifyingKey,
        revoked: bool,
    ) -> Self {
        Self::from_registry_parts(
            issuer_id,
            key_epoch,
            verifying_key,
            revoked,
            Digest32::of_bytes(b"hepta.authbus.test-only-issuer-registry.v1"),
        )
        .expect("test registry digest is non-zero")
    }
}

impl Deref for IssuerRegistration {
    type Target = IssuerRegistrationView;

    fn deref(&self) -> &Self::Target {
        &self.view
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedMessageClaims {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub message_id: StableId,
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub sequence: u64,
    pub expires_at_ms: u64,
}

impl SignedMessageClaims {
    /// Canonical, length-delimited signed preimage. The domain and every replay
    /// field are signed; signatures cannot be moved between issuers or epochs.
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(640);
        bytes.extend_from_slice(b"hepta.authbus.signed-message.v1\0");
        push_id(&mut bytes, &self.issuer_id);
        bytes.extend_from_slice(&self.key_epoch.get().to_be_bytes());
        push_id(&mut bytes, &self.message_id);
        push_id(&mut bytes, &self.subject_id);
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_ms.to_be_bytes());
        bytes
    }
}

pub struct SignedMessage {
    pub claims: SignedMessageClaims,
    pub signature: [u8; 64],
}

/// Cryptographically admitted message. Construction is private; admission alone
/// does not consume a durable replay sequence or grant effect authority.
pub struct AuthenticatedMessage {
    claims: SignedMessageClaims,
    receipt: VerificationReceipt,
}

impl SignedMessage {
    pub fn authenticate(
        &self,
        issuer: &IssuerRegistration,
        expected_scope: Digest32,
        expected_payload: Digest32,
        now_ms: u64,
    ) -> Result<AuthenticatedMessage, Error> {
        if self.claims.issuer_id != issuer.issuer_id || self.claims.key_epoch != issuer.key_epoch {
            return Err(Error::IssuerMismatch);
        }
        issuer
            .verifying_key
            .verify_strict(
                &self.claims.signing_bytes(),
                &Signature::from_bytes(&self.signature),
            )
            .map_err(|_| Error::InvalidSignature)?;
        // Reuse the structural/expiry/scope checks, but do not represent this
        // temporary single-message model as durable replay protection.
        let receipt = ReplayWindow::new(/*maximum_replay_keys*/ 1).verify(
            TrustedReplayContext {
                issuer_id: issuer.issuer_id.clone(),
                key_epoch: issuer.key_epoch,
                now_ms,
                revoked: issuer.revoked,
            },
            PreverifiedAuthEnvelope {
                message_id: self.claims.message_id.clone(),
                subject_id: self.claims.subject_id.clone(),
                scope_digest: self.claims.scope_digest,
                payload_digest: self.claims.payload_digest,
                signature_digest: Digest32::of_bytes(&self.signature),
                sequence: self.claims.sequence,
                expires_at_ms: self.claims.expires_at_ms,
            },
            expected_scope,
            expected_payload,
        )?;
        Ok(AuthenticatedMessage {
            claims: self.claims.clone(),
            receipt,
        })
    }
}

impl AuthenticatedMessage {
    pub fn claims(&self) -> &SignedMessageClaims {
        &self.claims
    }

    pub fn receipt(&self) -> &VerificationReceipt {
        &self.receipt
    }
}

#[cfg(test)]
#[path = "signed_tests.rs"]
mod tests;
