//! Production-control wrappers for the final-use authority primitive.
//!
//! `FinalUseAuthority` deliberately owns only final-use verification and local
//! nonce/revocation durability. This module adds two independently pinned
//! controls used by trusted hosts without giving adapters signing authority:
//!
//! - an operator approval signature over the exact owner grant semantics; and
//! - an authenticated revocation-feed signature over each monotonic head.
//!
//! A production host can therefore require three distinct roles: grant issuer,
//! operator approver, and revocation distributor. Possession of the grant
//! issuer key alone is not sufficient on that host path.

use std::fmt;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::FinalUseAuthority;
use crate::FinalUseError;
use crate::FinalUseGrant;
use crate::FinalUseRevocations;
use crate::SignedFinalUseGrant;

const CONTROL_SCHEMA_VERSION: u32 = 1;
const MAX_REVOCATIONS: usize = 16_384;

/// Independent operator approval for one exact grant semantic payload.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseApproval {
    pub schema_version: u32,
    pub approver_id: String,
    pub signer_id: String,
    pub grant_id: String,
    pub authority_epoch: u64,
    pub grant_sha256: [u8; 32],
}

impl FinalUseApproval {
    pub fn for_grant(
        approver_id: String,
        grant: &FinalUseGrant,
    ) -> Result<Self, FinalUseControlError> {
        if !identifier(&approver_id) {
            return Err(FinalUseControlError::InvalidApproval);
        }
        let grant_sha256 = grant_digest(grant)?;
        Ok(Self {
            schema_version: CONTROL_SCHEMA_VERSION,
            approver_id,
            signer_id: grant.signer_id.clone(),
            grant_id: grant.grant_id.clone(),
            authority_epoch: grant.authority_epoch,
            grant_sha256,
        })
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, FinalUseControlError> {
        if self.schema_version != CONTROL_SCHEMA_VERSION
            || !identifier(&self.approver_id)
            || !identifier(&self.signer_id)
            || !identifier(&self.grant_id)
            || self.authority_epoch == 0
            || self.grant_sha256 == [0; 32]
        {
            return Err(FinalUseControlError::InvalidApproval);
        }
        let mut bytes = b"hepta.kernel.authority.final-use-approval.v1\0".to_vec();
        bytes.extend(
            serde_json::to_vec(self).map_err(|_| FinalUseControlError::InvalidApproval)?,
        );
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedFinalUseApproval {
    pub approval: FinalUseApproval,
    pub signature: Vec<u8>,
}

/// Pinned independent operator-approval verifier.
#[derive(Clone)]
pub struct FinalUseApprovalVerifier {
    approver_id: String,
    key: VerifyingKey,
}

impl fmt::Debug for FinalUseApprovalVerifier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("FinalUseApprovalVerifier([PINNED APPROVER TRUST])")
    }
}

impl FinalUseApprovalVerifier {
    pub fn new(
        approver_id: String,
        verifying_key: [u8; 32],
    ) -> Result<Self, FinalUseControlError> {
        let key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| FinalUseControlError::InvalidTrust)?;
        if !identifier(&approver_id) || key.is_weak() {
            return Err(FinalUseControlError::InvalidTrust);
        }
        Ok(Self { approver_id, key })
    }

    /// Verify an independent approval against the exact grant semantics.
    /// The issuer signature itself is still verified by `FinalUseAuthority`.
    pub fn verify(
        &self,
        grant: &SignedFinalUseGrant,
        signed: &SignedFinalUseApproval,
    ) -> Result<(), FinalUseControlError> {
        if signed.approval.approver_id != self.approver_id
            || signed.approval.signer_id != grant.grant.signer_id
            || signed.approval.grant_id != grant.grant.grant_id
            || signed.approval.authority_epoch != grant.grant.authority_epoch
            || signed.approval.grant_sha256 != grant_digest(&grant.grant)?
        {
            return Err(FinalUseControlError::InvalidApproval);
        }
        let input = signed.approval.signing_bytes()?;
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FinalUseControlError::InvalidSignature)?;
        self.key
            .verify_strict(&input, &signature)
            .map_err(|_| FinalUseControlError::InvalidSignature)
    }
}

/// Authenticated monotonic revocation-head payload distributed to authority
/// owners. Transport may retry this object; the authority store rejects stale
/// revisions and rollback.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseRevocationUpdate {
    pub schema_version: u32,
    pub distributor_id: String,
    pub head: FinalUseRevocations,
}

impl FinalUseRevocationUpdate {
    pub fn new(distributor_id: String, head: FinalUseRevocations) -> Self {
        Self {
            schema_version: CONTROL_SCHEMA_VERSION,
            distributor_id,
            head,
        }
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, FinalUseControlError> {
        if self.schema_version != CONTROL_SCHEMA_VERSION
            || !identifier(&self.distributor_id)
            || self.head.authority_epoch == 0
            || self.head.revision == 0
            || self.head.revoked_grant_ids.len() > MAX_REVOCATIONS
            || !self.head.revoked_grant_ids.iter().all(|id| identifier(id))
        {
            return Err(FinalUseControlError::InvalidRevocationUpdate);
        }
        let mut bytes = b"hepta.kernel.authority.revocation-feed.v1\0".to_vec();
        bytes.extend(
            serde_json::to_vec(self)
                .map_err(|_| FinalUseControlError::InvalidRevocationUpdate)?,
        );
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedFinalUseRevocationUpdate {
    pub update: FinalUseRevocationUpdate,
    pub signature: Vec<u8>,
}

/// Pinned verifier for one independently operated revocation distributor.
#[derive(Clone)]
pub struct FinalUseRevocationFeedVerifier {
    distributor_id: String,
    key: VerifyingKey,
}

impl fmt::Debug for FinalUseRevocationFeedVerifier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("FinalUseRevocationFeedVerifier([PINNED FEED TRUST])")
    }
}

impl FinalUseRevocationFeedVerifier {
    pub fn new(
        distributor_id: String,
        verifying_key: [u8; 32],
    ) -> Result<Self, FinalUseControlError> {
        let key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| FinalUseControlError::InvalidTrust)?;
        if !identifier(&distributor_id) || key.is_weak() {
            return Err(FinalUseControlError::InvalidTrust);
        }
        Ok(Self {
            distributor_id,
            key,
        })
    }

    /// Authenticate one head and atomically hand it to the durable authority
    /// owner. Replays, rollback and same-epoch revocation removal are rejected
    /// by `FinalUseAuthority::update_revocations`.
    pub fn apply(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseRevocationUpdate,
    ) -> Result<(), FinalUseControlError> {
        if signed.update.distributor_id != self.distributor_id {
            return Err(FinalUseControlError::InvalidRevocationUpdate);
        }
        let input = signed.update.signing_bytes()?;
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FinalUseControlError::InvalidSignature)?;
        self.key
            .verify_strict(&input, &signature)
            .map_err(|_| FinalUseControlError::InvalidSignature)?;
        authority
            .update_revocations(signed.update.head.clone())
            .map_err(FinalUseControlError::Authority)
    }
}

fn grant_digest(grant: &FinalUseGrant) -> Result<[u8; 32], FinalUseControlError> {
    let bytes = grant
        .signing_bytes()
        .map_err(FinalUseControlError::Authority)?;
    Ok(Sha256::digest(bytes).into())
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FinalUseControlError {
    InvalidTrust,
    InvalidApproval,
    InvalidRevocationUpdate,
    InvalidSignature,
    Authority(FinalUseError),
}

impl fmt::Display for FinalUseControlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for FinalUseControlError {}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use crate::FinalUseBinding;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    fn fixture() -> (
        FinalUseAuthority,
        SignedFinalUseGrant,
        tempfile::TempDir,
        SigningKey,
        SigningKey,
    ) {
        let issuer = SigningKey::from_bytes(&[41; 32]);
        let approver = SigningKey::from_bytes(&[42; 32]);
        let distributor = SigningKey::from_bytes(&[43; 32]);
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 11,
            grant_id: "approved-use".into(),
            nonce: [7; 32],
            binding: FinalUseBinding {
                subject_id: "agent-one".into(),
                destination_id: "provider:heptabao".into(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: now - 1_000,
            expires_at_unix_ms: now + 30_000,
        };
        let signature = issuer.sign(&grant.signing_bytes().unwrap()).to_bytes().to_vec();
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 11,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .unwrap();
        (
            authority,
            SignedFinalUseGrant { grant, signature },
            directory,
            approver,
            distributor,
        )
    }

    #[test]
    fn independent_approval_binds_exact_grant_semantics() {
        let (_authority, grant, _directory, approver, _distributor) = fixture();
        let approval = FinalUseApproval::for_grant("operator-approver".into(), &grant.grant)
            .unwrap();
        let signature = approver
            .sign(&approval.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        let signed = SignedFinalUseApproval { approval, signature };
        let verifier = FinalUseApprovalVerifier::new(
            "operator-approver".into(),
            approver.verifying_key().to_bytes(),
        )
        .unwrap();
        assert_eq!(verifier.verify(&grant, &signed), Ok(()));

        let mut drifted = grant.clone();
        drifted.grant.binding.payload_sha256 = [99; 32];
        assert_eq!(
            verifier.verify(&drifted, &signed),
            Err(FinalUseControlError::InvalidApproval)
        );
    }

    #[test]
    fn signed_revocation_feed_is_authenticated_and_monotonic() {
        let (authority, grant, _directory, _approver, distributor) = fixture();
        let token = authority.claim(&grant, &grant.grant.binding).unwrap();
        let update = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 11,
                revision: 2,
                revoked_grant_ids: BTreeSet::from([grant.grant.grant_id.clone()]),
            },
        );
        let signature = distributor
            .sign(&update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        let signed = SignedFinalUseRevocationUpdate { update, signature };
        let verifier = FinalUseRevocationFeedVerifier::new(
            "revocation-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )
        .unwrap();
        assert_eq!(verifier.apply(&authority, &signed), Ok(()));
        assert_eq!(
            authority.with_verified_use(token, &grant.grant.binding, || ()),
            Err(FinalUseError::Revoked)
        );
        assert_eq!(
            verifier.apply(&authority, &signed),
            Err(FinalUseControlError::Authority(
                FinalUseError::StaleRevocationHead
            ))
        );
    }

    #[test]
    fn forged_revocation_feed_never_updates_authority() {
        let (authority, grant, _directory, _approver, distributor) = fixture();
        let update = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 11,
                revision: 2,
                revoked_grant_ids: BTreeSet::from([grant.grant.grant_id.clone()]),
            },
        );
        let attacker = SigningKey::from_bytes(&[91; 32]);
        let signed = SignedFinalUseRevocationUpdate {
            signature: attacker
                .sign(&update.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            update,
        };
        let verifier = FinalUseRevocationFeedVerifier::new(
            "revocation-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )
        .unwrap();
        assert_eq!(
            verifier.apply(&authority, &signed),
            Err(FinalUseControlError::InvalidSignature)
        );
        assert!(authority.claim(&grant, &grant.grant.binding).is_ok());
    }
}
