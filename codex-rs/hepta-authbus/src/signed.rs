use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::Error;
use crate::PreverifiedAuthEnvelope;
use crate::ReplayWindow;
use crate::TrustedReplayContext;
use crate::VerificationReceipt;
use crate::push_id;

/// Registration obtained from the host's trusted identity/policy store, never
/// from the message being admitted. Revocation must be refreshed for each call.
pub struct IssuerRegistration {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub verifying_key: VerifyingKey,
    pub revoked: bool,
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
