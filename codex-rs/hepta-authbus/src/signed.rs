use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use tokio::sync::OwnedRwLockReadGuard;

use crate::Error;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::PreverifiedAuthEnvelope;
use crate::ReplayWindow;
use crate::TrustedReplayContext;
use crate::VerificationReceipt;
use crate::VerifiedIssuerHandle;
use crate::push_id;

/// Internal compatibility projection used only by the durable registry module.
/// It is not exported and cannot be constructed by product callers.
pub(crate) struct IssuerRegistration {
    pub(crate) issuer_id: StableId,
    pub(crate) key_epoch: Generation,
    pub(crate) verifying_key: VerifyingKey,
    pub(crate) revoked: bool,
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

/// Cryptographically admitted message. Construction is private. The embedded
/// registry read guard keeps issuer rotation/revocation fenced until the caller
/// commits or rolls back the durable replay/admission transaction.
pub struct AuthenticatedMessage {
    claims: SignedMessageClaims,
    receipt: VerificationReceipt,
    issuer_key_digest: Digest32,
    issuer_revision: u64,
    _registry_guard: OwnedRwLockReadGuard<()>,
}

impl SignedMessage {
    pub(crate) fn authenticate(
        &self,
        issuer: VerifiedIssuerHandle,
        expected_scope: Digest32,
        expected_payload: Digest32,
        now_ms: u64,
    ) -> Result<AuthenticatedMessage, Error> {
        if issuer.purpose() != IssuerPurpose::Message
            || self.claims.issuer_id != *issuer.issuer_id()
            || self.claims.key_epoch != issuer.key_epoch()
        {
            return Err(Error::IssuerMismatch);
        }
        if issuer.state() != IssuerLifecycleState::Active {
            return Err(Error::Revoked);
        }
        issuer
            .verifying_key()
            .verify_strict(
                &self.claims.signing_bytes(),
                &Signature::from_bytes(&self.signature),
            )
            .map_err(|_| Error::InvalidSignature)?;
        // Structural, expiry and route checks are shared with the legacy replay
        // verifier. Durable replay consumption remains the caller's transaction.
        let receipt = ReplayWindow::new(/*maximum_replay_keys*/ 1).verify(
            TrustedReplayContext {
                issuer_id: issuer.issuer_id().clone(),
                key_epoch: issuer.key_epoch(),
                now_ms,
                revoked: false,
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
        let issuer_key_digest = issuer.verifying_key_digest();
        let issuer_revision = issuer.revision();
        let registry_guard = issuer.into_registry_guard();
        Ok(AuthenticatedMessage {
            claims: self.claims.clone(),
            receipt,
            issuer_key_digest,
            issuer_revision,
            _registry_guard: registry_guard,
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

    pub fn issuer_key_digest(&self) -> Digest32 {
        self.issuer_key_digest
    }

    pub fn issuer_revision(&self) -> u64 {
        self.issuer_revision
    }
}

#[cfg(test)]
#[path = "signed_tests.rs"]
mod tests;
