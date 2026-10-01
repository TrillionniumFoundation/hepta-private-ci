use std::ops::Deref;

use codex_hepta_types::AuthorityPosture;
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
use crate::VerificationReceipt;
use crate::push_id;

/// Read-only issuer attributes exposed by an opaque registration handle.
///
/// Constructing this view does not create a trusted registration. AuthBus APIs
/// accept only `IssuerRegistration`, whose constructors are confined to the
/// durable registry and private-file registry loaders.
#[derive(Clone, Debug)]
pub struct IssuerRegistrationView {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
    pub revoked: bool,
}

/// Sealed registration obtained from a persisted trusted issuer registry.
#[derive(Clone, Debug)]
pub struct IssuerRegistration {
    view: IssuerRegistrationView,
    registry_digest: Digest32,
    registry_revision: u64,
}

impl Deref for IssuerRegistration {
    type Target = IssuerRegistrationView;

    fn deref(&self) -> &Self::Target {
        &self.view
    }
}

impl IssuerRegistration {
    pub fn registry_digest(&self) -> Digest32 {
        self.registry_digest
    }

    pub fn registry_revision(&self) -> u64 {
        self.registry_revision
    }

    pub(crate) fn from_record(record: &IssuerRecord) -> Result<Self, AuthBusAuthorityError> {
        if record.purpose != IssuerPurpose::Message {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        let view = IssuerRegistrationView {
            issuer_id: record.issuer_id.clone(),
            key_epoch: record.key_epoch,
            verifying_key: record.verifying_key,
            revoked: record.state != IssuerLifecycleState::Active,
        };
        let mut bytes = b"hepta.authbus.message-issuer-registration.v1\0".to_vec();
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

    pub(crate) fn from_registry_view(
        view: IssuerRegistrationView,
        registry_digest: Digest32,
    ) -> Self {
        Self {
            view,
            registry_digest,
            registry_revision: 1,
        }
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
        if self.claims.scope_digest.is_zero() {
            return Err(Error::EmptyDigest("scope"));
        }
        if self.claims.payload_digest.is_zero() {
            return Err(Error::EmptyDigest("payload"));
        }
        if self.claims.sequence == 0 {
            return Err(Error::ZeroSequence);
        }
        if issuer.revoked {
            return Err(Error::Revoked);
        }
        if now_ms >= self.claims.expires_at_ms {
            return Err(Error::Expired);
        }
        if self.claims.scope_digest != expected_scope {
            return Err(Error::ScopeMismatch);
        }
        if self.claims.payload_digest != expected_payload {
            return Err(Error::PayloadMismatch);
        }

        let signature_digest = Digest32::of_bytes(&self.signature);
        if signature_digest.is_zero() {
            return Err(Error::EmptyDigest("signature"));
        }
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.authbus.preverified-replay.v1\0");
        push_id(&mut bytes, &issuer.issuer_id);
        bytes.extend_from_slice(&issuer.key_epoch.get().to_be_bytes());
        push_id(&mut bytes, &self.claims.message_id);
        push_id(&mut bytes, &self.claims.subject_id);
        bytes.extend_from_slice(self.claims.scope_digest.as_array());
        bytes.extend_from_slice(self.claims.payload_digest.as_array());
        bytes.extend_from_slice(signature_digest.as_array());
        bytes.extend_from_slice(&self.claims.sequence.to_be_bytes());
        bytes.extend_from_slice(&self.claims.expires_at_ms.to_be_bytes());

        let receipt = VerificationReceipt {
            message_id: self.claims.message_id.clone(),
            issuer_id: issuer.issuer_id.clone(),
            key_epoch: issuer.key_epoch,
            subject_id: self.claims.subject_id.clone(),
            sequence: self.claims.sequence,
            envelope_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        };
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
