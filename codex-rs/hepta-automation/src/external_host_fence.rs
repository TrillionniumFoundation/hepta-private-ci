//! Authenticated external host-fence evidence for automation cross-host recovery.
//!
//! The deployment controller remains responsible for physically fencing the
//! source host. This module verifies that the controller's signed receipt binds
//! the exact owner, hosts, checkpoint and monotone writer-epoch transition
//! before the recovery manifest or target admission can consume it.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::AutomationError;

pub const AUTOMATION_HOST_FENCE_SCHEMA_VERSION: u32 = 1;
const MAX_IDENTIFIER_BYTES: usize = 256;
const MAX_FENCE_LIFETIME_MS: u64 = 15 * 60 * 1_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationHostFenceTrustV1 {
    pub schema_version: u32,
    pub controller_id: String,
    pub authority_epoch: u64,
    pub verifying_key: [u8; 32],
}

impl AutomationHostFenceTrustV1 {
    pub fn validate(&self) -> Result<(), AutomationError> {
        validate_identifier(&self.controller_id)?;
        if self.schema_version != AUTOMATION_HOST_FENCE_SCHEMA_VERSION
            || self.authority_epoch == 0
            || VerifyingKey::from_bytes(&self.verifying_key).is_err()
        {
            return Err(AutomationError::Invalid);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationHostFenceClaimsV1 {
    pub schema_version: u32,
    pub fence_id: String,
    pub controller_id: String,
    pub authority_epoch: u64,
    pub owner_agent_id: String,
    pub source_host_id: String,
    pub target_host_id: String,
    pub source_writer_epoch: u64,
    pub required_target_writer_epoch: u64,
    pub sqlite_checkpoint_digest: Sha256Digest,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
}

impl AutomationHostFenceClaimsV1 {
    pub fn validate(&self) -> Result<(), AutomationError> {
        validate_identifier(&self.fence_id)?;
        validate_identifier(&self.controller_id)?;
        validate_identifier(&self.source_host_id)?;
        validate_identifier(&self.target_host_id)?;
        validate_digest(&self.sqlite_checkpoint_digest)?;
        if self.schema_version != AUTOMATION_HOST_FENCE_SCHEMA_VERSION
            || self.authority_epoch == 0
            || AgentId::parse(&self.owner_agent_id).is_err()
            || self.source_host_id == self.target_host_id
            || self.source_writer_epoch == 0
            || self.required_target_writer_epoch
                != self
                    .source_writer_epoch
                    .checked_add(1)
                    .ok_or(AutomationError::Invalid)?
            || self.issued_at_ms == 0
            || self.expires_at_ms <= self.issued_at_ms
            || self.expires_at_ms.saturating_sub(self.issued_at_ms) > MAX_FENCE_LIFETIME_MS
        {
            return Err(AutomationError::Invalid);
        }
        Ok(())
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, AutomationError> {
        self.validate()?;
        let mut bytes = b"hepta.automation.host-fence.v1\0".to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        push_text(&mut bytes, &self.fence_id)?;
        push_text(&mut bytes, &self.controller_id)?;
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        push_text(&mut bytes, &self.owner_agent_id)?;
        push_text(&mut bytes, &self.source_host_id)?;
        push_text(&mut bytes, &self.target_host_id)?;
        bytes.extend_from_slice(&self.source_writer_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.required_target_writer_epoch.to_be_bytes());
        push_text(&mut bytes, self.sqlite_checkpoint_digest.as_str())?;
        bytes.extend_from_slice(&self.issued_at_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_ms.to_be_bytes());
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedAutomationHostFenceV1 {
    pub claims: AutomationHostFenceClaimsV1,
    #[serde(with = "signature_bytes")]
    pub signature: [u8; 64],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAutomationHostFenceV1 {
    claims: AutomationHostFenceClaimsV1,
    receipt_digest: Sha256Digest,
}

impl VerifiedAutomationHostFenceV1 {
    pub fn verify(
        trust: &AutomationHostFenceTrustV1,
        signed: &SignedAutomationHostFenceV1,
        now_ms: u64,
    ) -> Result<Self, AutomationError> {
        trust.validate()?;
        signed.claims.validate()?;
        if signed.claims.controller_id != trust.controller_id
            || signed.claims.authority_epoch != trust.authority_epoch
            || now_ms < signed.claims.issued_at_ms
            || now_ms >= signed.claims.expires_at_ms
        {
            return Err(AutomationError::AccessDenied);
        }
        VerifyingKey::from_bytes(&trust.verifying_key)
            .map_err(|_| AutomationError::Invalid)?
            .verify_strict(
                &signed.claims.signing_bytes()?,
                &Signature::from_bytes(&signed.signature),
            )
            .map_err(|_| AutomationError::AccessDenied)?;
        let mut digest_bytes = b"hepta.automation.verified-host-fence.v1\0".to_vec();
        digest_bytes.extend_from_slice(&signed.claims.signing_bytes()?);
        digest_bytes.extend_from_slice(&signed.signature);
        Ok(Self {
            claims: signed.claims.clone(),
            receipt_digest: Sha256Digest::for_bytes(&digest_bytes),
        })
    }

    pub fn validate_current(&self, now_ms: u64) -> Result<(), AutomationError> {
        self.claims.validate()?;
        validate_digest(&self.receipt_digest)?;
        if now_ms < self.claims.issued_at_ms || now_ms >= self.claims.expires_at_ms {
            return Err(AutomationError::TimerFenced);
        }
        Ok(())
    }

    pub fn claims(&self) -> &AutomationHostFenceClaimsV1 {
        &self.claims
    }

    pub fn receipt_digest(&self) -> &Sha256Digest {
        &self.receipt_digest
    }
}

fn validate_identifier(value: &str) -> Result<(), AutomationError> {
    if value.is_empty() || value.len() > MAX_IDENTIFIER_BYTES || value.chars().any(char::is_control)
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn validate_digest(value: &Sha256Digest) -> Result<(), AutomationError> {
    let text = value.as_str();
    if text.len() != 64 || text.bytes().all(|byte| byte == b'0') {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) -> Result<(), AutomationError> {
    let len = u32::try_from(value.len()).map_err(|_| AutomationError::Invalid)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

// Keep the public fixed-size signature and the JSON array encoding. Decode
// directly into fixed storage rather than allocating an unbounded Vec first.
mod signature_bytes {
    use std::fmt;

    use serde::Deserializer;
    use serde::Serializer;
    use serde::de::Error;
    use serde::de::SeqAccess;
    use serde::de::Visitor;
    use serde::ser::SerializeTuple;

    pub(super) fn serialize<S>(value: &[u8; 64], serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut sequence = serializer.serialize_tuple(64)?;
        for byte in value {
            sequence.serialize_element(byte)?;
        }
        sequence.end()
    }

    pub(super) fn deserialize<'de, D>(deserializer: D) -> Result<[u8; 64], D::Error>
    where
        D: Deserializer<'de>,
    {
        struct SignatureVisitor;

        impl<'de> Visitor<'de> for SignatureVisitor {
            type Value = [u8; 64];

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("exactly 64 signature bytes")
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut bytes = [0_u8; 64];
                for (index, byte) in bytes.iter_mut().enumerate() {
                    *byte = sequence
                        .next_element()?
                        .ok_or_else(|| A::Error::invalid_length(index, &self))?;
                }
                if sequence.next_element::<u8>()?.is_some() {
                    return Err(A::Error::invalid_length(65, &self));
                }
                Ok(bytes)
            }
        }

        deserializer.deserialize_tuple(64, SignatureVisitor)
    }
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;

    #[test]
    fn signed_fence_json_has_exactly_sixty_four_bytes() {
        let (trust, signed) = signed_fence();
        let bytes = serde_json::to_vec(&signed).expect("encode fixed signature");
        let decoded: SignedAutomationHostFenceV1 =
            serde_json::from_slice(&bytes).expect("decode fixed signature");
        assert_eq!(decoded, signed);
        VerifiedAutomationHostFenceV1::verify(&trust, &decoded, 2_000)
            .expect("decoded signature remains authentic");

        for length in [0, 63, 65, 1_024] {
            let mut value = serde_json::to_value(&signed).expect("signature JSON");
            value["signature"] = serde_json::json!(vec![0_u8; length]);
            assert!(serde_json::from_value::<SignedAutomationHostFenceV1>(value).is_err());
        }
        for invalid_byte in [
            serde_json::json!(-1),
            serde_json::json!(256),
            serde_json::json!(true),
        ] {
            let mut value = serde_json::to_value(&signed).expect("signature JSON");
            value["signature"][0] = invalid_byte;
            assert!(serde_json::from_value::<SignedAutomationHostFenceV1>(value).is_err());
        }
    }

    fn signed_fence() -> (AutomationHostFenceTrustV1, SignedAutomationHostFenceV1) {
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = AutomationHostFenceTrustV1 {
            schema_version: AUTOMATION_HOST_FENCE_SCHEMA_VERSION,
            controller_id: "deployment-controller-a".to_string(),
            authority_epoch: 9,
            verifying_key: signing_key.verifying_key().to_bytes(),
        };
        let claims = AutomationHostFenceClaimsV1 {
            schema_version: AUTOMATION_HOST_FENCE_SCHEMA_VERSION,
            fence_id: "fence-0001".to_string(),
            controller_id: trust.controller_id.clone(),
            authority_epoch: trust.authority_epoch,
            owner_agent_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".to_string(),
            source_host_id: "host-a".to_string(),
            target_host_id: "host-b".to_string(),
            source_writer_epoch: 7,
            required_target_writer_epoch: 8,
            sqlite_checkpoint_digest: Sha256Digest::for_bytes(b"checkpoint"),
            issued_at_ms: 1_000,
            expires_at_ms: 61_000,
        };
        let signature = signing_key.sign(&claims.signing_bytes().expect("signing bytes"));
        (
            trust,
            SignedAutomationHostFenceV1 {
                claims,
                signature: signature.to_bytes(),
            },
        )
    }

    #[test]
    fn signed_fence_binds_exact_recovery_tuple() {
        let (trust, signed) = signed_fence();
        let verified =
            VerifiedAutomationHostFenceV1::verify(&trust, &signed, 2_000).expect("verified");
        assert_eq!(verified.claims().source_writer_epoch, 7);
        assert_eq!(verified.claims().required_target_writer_epoch, 8);
        verified.validate_current(60_999).expect("current");
        assert_eq!(verified.receipt_digest().as_str().len(), 64);
    }

    #[test]
    fn changed_checkpoint_or_signature_is_rejected() {
        let (trust, mut signed) = signed_fence();
        signed.claims.sqlite_checkpoint_digest = Sha256Digest::for_bytes(b"other-checkpoint");
        assert_eq!(
            VerifiedAutomationHostFenceV1::verify(&trust, &signed, 2_000),
            Err(AutomationError::AccessDenied)
        );
    }

    #[test]
    fn stale_fence_is_rejected_before_manifest_or_target_admission() {
        let (trust, signed) = signed_fence();
        assert_eq!(
            VerifiedAutomationHostFenceV1::verify(&trust, &signed, 61_000),
            Err(AutomationError::AccessDenied)
        );
    }

    #[test]
    fn wrong_controller_epoch_is_rejected() {
        let (mut trust, signed) = signed_fence();
        trust.authority_epoch += 1;
        assert_eq!(
            VerifiedAutomationHostFenceV1::verify(&trust, &signed, 2_000),
            Err(AutomationError::AccessDenied)
        );
    }
}
