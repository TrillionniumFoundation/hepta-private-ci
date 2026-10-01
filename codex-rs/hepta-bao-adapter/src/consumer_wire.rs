//! The external credential consumer accepts HMAC proofs, never raw credentials.

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use hmac::Hmac;
use hmac::Mac;
use serde::Deserialize;
use serde::Serialize;
use sha2::Sha256;

pub(super) const MAX_FRAME_BYTES: usize = 32 * 1024;
pub(super) const MAX_CONSUMER_OPERATIONS: i64 = 65_536;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ConsumerIntent {
    pub schema_version: u32,
    pub consumer_id: String,
    pub operation_id: String,
    pub semantic_sha256: [u8; 32],
}

impl ConsumerIntent {
    pub fn validate(&self) -> Result<(), super::ConsumerPortError> {
        if self.schema_version != 1
            || !identifier(&self.consumer_id)
            || !identifier(&self.operation_id)
            || self.semantic_sha256 == [0; 32]
        {
            return Err(super::ConsumerPortError::Invalid);
        }
        Ok(())
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, super::ConsumerPortError> {
        self.validate()?;
        let mut bytes = b"hepta.secrets.credential-consumer.intent.v1\0".to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        for value in [&self.consumer_id, &self.operation_id] {
            bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
            bytes.extend_from_slice(value.as_bytes());
        }
        bytes.extend_from_slice(&self.semantic_sha256);
        Ok(bytes)
    }

    pub fn proof(&self, credential: &[u8]) -> Result<[u8; 32], super::ConsumerPortError> {
        if credential.is_empty() || credential.len() > 8192 {
            return Err(super::ConsumerPortError::Invalid);
        }
        let mut mac = Hmac::<Sha256>::new_from_slice(credential)
            .map_err(|_| super::ConsumerPortError::Invalid)?;
        mac.update(&self.signing_bytes()?);
        Ok(mac.finalize().into_bytes().into())
    }

    pub fn verify_proof(
        &self,
        credential: &[u8],
        proof: &[u8; 32],
    ) -> Result<(), super::ConsumerPortError> {
        let mut mac = Hmac::<Sha256>::new_from_slice(credential)
            .map_err(|_| super::ConsumerPortError::Invalid)?;
        mac.update(&self.signing_bytes()?);
        mac.verify_slice(proof)
            .map_err(|_| super::ConsumerPortError::Rejected)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum ConsumerRequest {
    Authenticate {
        intent: ConsumerIntent,
        proof: [u8; 32],
    },
    Status {
        intent: ConsumerIntent,
    },
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ConsumerAcknowledgement {
    pub intent: ConsumerIntent,
    pub durable_revision: u64,
}

impl ConsumerAcknowledgement {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, super::ConsumerPortError> {
        if self.durable_revision == 0 {
            return Err(super::ConsumerPortError::Invalid);
        }
        let mut bytes = b"hepta.secrets.credential-consumer.ack.v1\0".to_vec();
        bytes.extend_from_slice(&self.intent.signing_bytes()?);
        bytes.extend_from_slice(&self.durable_revision.to_be_bytes());
        Ok(bytes)
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignedConsumerAcknowledgement {
    pub acknowledgement: ConsumerAcknowledgement,
    pub signature: Vec<u8>,
}

impl SignedConsumerAcknowledgement {
    pub fn verify(
        &self,
        intent: &ConsumerIntent,
        verifying_key: &[u8; 32],
    ) -> Result<(), super::ConsumerPortError> {
        if &self.acknowledgement.intent != intent {
            return Err(super::ConsumerPortError::Conflict);
        }
        let key = VerifyingKey::from_bytes(verifying_key)
            .map_err(|_| super::ConsumerPortError::Invalid)?;
        if key.is_weak() {
            return Err(super::ConsumerPortError::Invalid);
        }
        let signature = Signature::from_slice(&self.signature)
            .map_err(|_| super::ConsumerPortError::Unavailable)?;
        key.verify_strict(&self.acknowledgement.signing_bytes()?, &signature)
            .map_err(|_| super::ConsumerPortError::Unavailable)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum ConsumerResponse {
    Confirmed {
        receipt: SignedConsumerAcknowledgement,
    },
    Unknown,
    Rejected,
    Conflict,
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
}
