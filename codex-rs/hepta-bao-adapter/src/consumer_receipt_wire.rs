//! V2 preparation binds the actual provider receipt without changing V1 ACK bytes.
use super::ConsumerPortError;
use super::consumer_wire::ConsumerIntent;
use crate::BaoSecretReceipt;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use hmac::Hmac;
use hmac::Mac;
use serde::Deserialize;
use serde::Serialize;
use sha2::Sha256;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PreparedCredentialUse {
    pub intent: ConsumerIntent,
    pub receipt: BaoSecretReceipt,
    pub grant_sha256: [u8; 32],
    pub approval_sha256: [u8; 32],
    pub nonce: [u8; 32],
    pub expires_at_ms: u64,
}
impl PreparedCredentialUse {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, ConsumerPortError> {
        self.intent.validate()?;
        if self.nonce == [0; 32]
            || self.grant_sha256 == [0; 32]
            || self.approval_sha256 == [0; 32]
            || self.expires_at_ms == 0
            || self.receipt.response_sha256 == [0; 32]
        {
            return Err(ConsumerPortError::Invalid);
        }
        let mut bytes = b"hepta.secrets.credential-consumer.prepared-receipt.v2\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(self).map_err(unavailable)?);
        Ok(bytes)
    }
    pub fn digest(&self) -> Result<[u8; 32], ConsumerPortError> {
        Ok(Digest32::of_bytes(&self.signing_bytes()?).into_array())
    }
    pub fn proof(&self, credential: &[u8]) -> Result<[u8; 32], ConsumerPortError> {
        if credential.is_empty() || credential.len() > 8192 {
            return Err(ConsumerPortError::Invalid);
        }
        let mut mac = Hmac::<Sha256>::new_from_slice(credential).map_err(unavailable)?;
        mac.update(&self.signing_bytes()?);
        Ok(mac.finalize().into_bytes().into())
    }
    pub fn verify_proof(
        &self,
        credential: &[u8],
        proof: &[u8; 32],
    ) -> Result<(), ConsumerPortError> {
        let mut mac = Hmac::<Sha256>::new_from_slice(credential).map_err(unavailable)?;
        mac.update(&self.signing_bytes()?);
        mac.verify_slice(proof)
            .map_err(|_| ConsumerPortError::Rejected)
    }
}
#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignedPreparedCredentialUse {
    pub preparation: PreparedCredentialUse,
    pub signature: Vec<u8>,
}
impl SignedPreparedCredentialUse {
    pub fn verify(&self, key: &[u8; 32]) -> Result<(), ConsumerPortError> {
        let key = VerifyingKey::from_bytes(key).map_err(unavailable)?;
        if key.is_weak() {
            return Err(ConsumerPortError::Invalid);
        }
        key.verify_strict(
            &self.preparation.signing_bytes()?,
            &Signature::from_slice(&self.signature).map_err(unavailable)?,
        )
        .map_err(unavailable)
    }
}
fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
