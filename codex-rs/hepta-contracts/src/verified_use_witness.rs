//! Serializable observation emitted only after an opaque VerifiedUse token
//! passes its final live-authority check.
//!
//! A witness is evidence, never a bearer capability. No authority API accepts
//! it as authorization input and it cannot be converted back into an opaque
//! token.

use serde::Deserialize;
use serde::Serialize;
use std::fmt;

pub const VERIFIED_USE_TOKEN_WITNESS_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum VerifiedUseBoundaryV1 {
    ConsumerEntry,
    DispatchEntry,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseWitnessRefV1 {
    pub signer_id: String,
    pub grant_id: String,
    pub revocation_revision: u64,
    pub binding_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityLeaseWitnessRefV1 {
    pub owner_id: String,
    pub lease_id: String,
    pub lease_revision: u64,
    pub store_revision: u64,
    pub binding_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "authority_family", content = "authority", rename_all = "snake_case")]
pub enum VerifiedUseAuthorityRefV1 {
    FinalUse(FinalUseWitnessRefV1),
    AuthorityLease(AuthorityLeaseWitnessRefV1),
}

/// Canonical V1 audit/evidence witness for a successful final authority check.
///
/// This record cannot grant, delegate, refresh or revive authority. It records
/// one already-completed verification linearization point.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VerifiedUseTokenWitnessV1 {
    pub schema_version: u32,
    pub authority_epoch: u64,
    pub verified_at_unix_ms: u64,
    pub boundary: VerifiedUseBoundaryV1,
    pub authority_ref: VerifiedUseAuthorityRefV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VerifiedUseWitnessError {
    Invalid,
}

impl fmt::Display for VerifiedUseWitnessError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("invalid verified-use witness")
    }
}

impl std::error::Error for VerifiedUseWitnessError {}

impl VerifiedUseTokenWitnessV1 {
    pub fn validate(&self) -> Result<(), VerifiedUseWitnessError> {
        if self.schema_version != VERIFIED_USE_TOKEN_WITNESS_SCHEMA_VERSION
            || self.authority_epoch == 0
        {
            return Err(VerifiedUseWitnessError::Invalid);
        }
        let valid = match &self.authority_ref {
            VerifiedUseAuthorityRefV1::FinalUse(reference) => {
                identifier(&reference.signer_id)
                    && identifier(&reference.grant_id)
                    && reference.revocation_revision > 0
                    && reference.binding_sha256 != [0; 32]
            }
            VerifiedUseAuthorityRefV1::AuthorityLease(reference) => {
                identifier(&reference.owner_id)
                    && identifier(&reference.lease_id)
                    && reference.lease_revision > 0
                    && reference.store_revision > 0
                    && reference.binding_sha256 != [0; 32]
            }
        };
        if valid {
            Ok(())
        } else {
            Err(VerifiedUseWitnessError::Invalid)
        }
    }

    pub(crate) fn final_use(
        signer_id: String,
        grant_id: String,
        authority_epoch: u64,
        revocation_revision: u64,
        verified_at_unix_ms: u64,
        boundary: VerifiedUseBoundaryV1,
        binding_sha256: [u8; 32],
    ) -> Self {
        Self {
            schema_version: VERIFIED_USE_TOKEN_WITNESS_SCHEMA_VERSION,
            authority_epoch,
            verified_at_unix_ms,
            boundary,
            authority_ref: VerifiedUseAuthorityRefV1::FinalUse(FinalUseWitnessRefV1 {
                signer_id,
                grant_id,
                revocation_revision,
                binding_sha256,
            }),
        }
    }

    pub(crate) fn authority_lease(
        owner_id: String,
        lease_id: String,
        authority_epoch: u64,
        lease_revision: u64,
        store_revision: u64,
        verified_at_unix_ms: u64,
        boundary: VerifiedUseBoundaryV1,
        binding_sha256: [u8; 32],
    ) -> Self {
        Self {
            schema_version: VERIFIED_USE_TOKEN_WITNESS_SCHEMA_VERSION,
            authority_epoch,
            verified_at_unix_ms,
            boundary,
            authority_ref: VerifiedUseAuthorityRefV1::AuthorityLease(
                AuthorityLeaseWitnessRefV1 {
                    owner_id,
                    lease_id,
                    lease_revision,
                    store_revision,
                    binding_sha256,
                },
            ),
        }
    }
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn witness_round_trip_is_evidence_only_and_strict() {
        let witness = VerifiedUseTokenWitnessV1::authority_lease(
            "security-authority".into(),
            "lease-1".into(),
            3,
            7,
            12,
            100,
            VerifiedUseBoundaryV1::ConsumerEntry,
            [9; 32],
        );
        witness.validate().unwrap();
        let encoded = serde_json::to_vec(&witness).unwrap();
        let decoded: VerifiedUseTokenWitnessV1 = serde_json::from_slice(&encoded).unwrap();
        assert_eq!(decoded, witness);

        let mut value: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
        value
            .as_object_mut()
            .unwrap()
            .insert("authority_delta".into(), serde_json::json!("grant"));
        assert!(serde_json::from_value::<VerifiedUseTokenWitnessV1>(value).is_err());
    }

    #[test]
    fn malformed_witness_fails_validation() {
        let witness = VerifiedUseTokenWitnessV1::final_use(
            "issuer".into(),
            "grant".into(),
            1,
            1,
            100,
            VerifiedUseBoundaryV1::ConsumerEntry,
            [0; 32],
        );
        assert_eq!(witness.validate(), Err(VerifiedUseWitnessError::Invalid));
    }
}
