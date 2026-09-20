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

use std::collections::BTreeMap;
use std::collections::BTreeSet;
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

const APPROVAL_SCHEMA_VERSION: u32 = 1;
const REVOCATION_FEED_SCHEMA_VERSION: u32 = 2;
const MAX_REVOCATIONS: usize = 16_384;
const MAX_CONTROL_KEYS: usize = 8;
const MAX_REVOCATION_NODES: usize = 256;
const REVOCATION_ACK_SCHEMA_VERSION: u32 = 1;
pub const MAX_REVOCATION_FEED_LIFETIME_MS: u64 = 300_000;

/// One bounded trust-key generation. Epoch windows permit staged overlap and
/// deterministic retirement without accepting a key outside its intended
/// authority generation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalUseTrustKey {
    pub key_id: String,
    pub verifying_key: [u8; 32],
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

#[derive(Clone)]
struct PinnedControlKey {
    key_id: String,
    key: VerifyingKey,
    not_before_authority_epoch: u64,
    not_after_authority_epoch: u64,
}

fn pin_keys(keys: Vec<FinalUseTrustKey>) -> Result<Vec<PinnedControlKey>, FinalUseControlError> {
    if keys.is_empty() || keys.len() > MAX_CONTROL_KEYS {
        return Err(FinalUseControlError::InvalidTrust);
    }
    let mut pinned = Vec::with_capacity(keys.len());
    let mut ids = std::collections::BTreeSet::new();
    let mut public_keys = std::collections::BTreeSet::new();
    for candidate in keys {
        let key = VerifyingKey::from_bytes(&candidate.verifying_key)
            .map_err(|_| FinalUseControlError::InvalidTrust)?;
        if !identifier(&candidate.key_id)
            || key.is_weak()
            || candidate.not_before_authority_epoch == 0
            || candidate.not_after_authority_epoch < candidate.not_before_authority_epoch
            || !ids.insert(candidate.key_id.clone())
            || !public_keys.insert(candidate.verifying_key)
        {
            return Err(FinalUseControlError::InvalidTrust);
        }
        pinned.push(PinnedControlKey {
            key_id: candidate.key_id,
            key,
            not_before_authority_epoch: candidate.not_before_authority_epoch,
            not_after_authority_epoch: candidate.not_after_authority_epoch,
        });
    }
    Ok(pinned)
}

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
            schema_version: APPROVAL_SCHEMA_VERSION,
            approver_id,
            signer_id: grant.signer_id.clone(),
            grant_id: grant.grant_id.clone(),
            authority_epoch: grant.authority_epoch,
            grant_sha256,
        })
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, FinalUseControlError> {
        if self.schema_version != APPROVAL_SCHEMA_VERSION
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
    keys: Vec<PinnedControlKey>,
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
        Self::new_with_keys(
            approver_id,
            vec![FinalUseTrustKey {
                key_id: "single-key".into(),
                verifying_key,
                not_before_authority_epoch: 1,
                not_after_authority_epoch: u64::MAX,
            }],
        )
    }

    pub fn new_with_keys(
        approver_id: String,
        keys: Vec<FinalUseTrustKey>,
    ) -> Result<Self, FinalUseControlError> {
        if !identifier(&approver_id) {
            return Err(FinalUseControlError::InvalidTrust);
        }
        Ok(Self {
            approver_id,
            keys: pin_keys(keys)?,
        })
    }

    /// Verify an independent approval against the exact grant semantics.
    /// The issuer signature itself is still verified by `FinalUseAuthority`.
    pub fn verify(
        &self,
        grant: &SignedFinalUseGrant,
        signed: &SignedFinalUseApproval,
    ) -> Result<(), FinalUseControlError> {
        self.verify_with_key_id(grant, signed).map(|_| ())
    }

    /// Return the exact configured trust-key id that authenticated the approval.
    /// This is useful for audit receipts during staged key rotation.
    pub fn verify_with_key_id(
        &self,
        grant: &SignedFinalUseGrant,
        signed: &SignedFinalUseApproval,
    ) -> Result<&str, FinalUseControlError> {
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
        verify_key_ring(
            &self.keys,
            signed.approval.authority_epoch,
            &input,
            &signature,
        )
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
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl FinalUseRevocationUpdate {
    pub fn new(
        distributor_id: String,
        head: FinalUseRevocations,
        issued_at_unix_ms: u64,
        expires_at_unix_ms: u64,
    ) -> Self {
        Self {
            schema_version: REVOCATION_FEED_SCHEMA_VERSION,
            distributor_id,
            head,
            issued_at_unix_ms,
            expires_at_unix_ms,
        }
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, FinalUseControlError> {
        if self.schema_version != REVOCATION_FEED_SCHEMA_VERSION
            || !identifier(&self.distributor_id)
            || self.head.authority_epoch == 0
            || self.head.revision == 0
            || self.head.revoked_grant_ids.len() > MAX_REVOCATIONS
            || !self.head.revoked_grant_ids.iter().all(|id| identifier(id))
            || self.issued_at_unix_ms == 0
            || self.expires_at_unix_ms <= self.issued_at_unix_ms
            || self.expires_at_unix_ms - self.issued_at_unix_ms > MAX_REVOCATION_FEED_LIFETIME_MS
        {
            return Err(FinalUseControlError::InvalidRevocationUpdate);
        }
        let mut bytes = b"hepta.kernel.authority.revocation-feed.v2\0".to_vec();
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


/// Signed acknowledgement that one enrolled host has applied one exact
/// revocation update. It is evidence of local catch-up, never revocation
/// authority by itself.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseRevocationAck {
    pub schema_version: u32,
    pub node_id: String,
    pub distributor_id: String,
    pub authority_epoch: u64,
    pub revision: u64,
    pub update_sha256: [u8; 32],
    pub applied_at_unix_ms: u64,
}

impl FinalUseRevocationAck {
    pub fn for_update(
        node_id: String,
        update: &FinalUseRevocationUpdate,
        applied_at_unix_ms: u64,
    ) -> Result<Self, FinalUseControlError> {
        let update_sha256 = revocation_update_digest(update)?;
        let ack = Self {
            schema_version: REVOCATION_ACK_SCHEMA_VERSION,
            node_id,
            distributor_id: update.distributor_id.clone(),
            authority_epoch: update.head.authority_epoch,
            revision: update.head.revision,
            update_sha256,
            applied_at_unix_ms,
        };
        ack.validate_against(update)?;
        Ok(ack)
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, FinalUseControlError> {
        if self.schema_version != REVOCATION_ACK_SCHEMA_VERSION
            || !identifier(&self.node_id)
            || !identifier(&self.distributor_id)
            || self.authority_epoch == 0
            || self.revision == 0
            || self.update_sha256 == [0; 32]
            || self.applied_at_unix_ms == 0
        {
            return Err(FinalUseControlError::InvalidRevocationAck);
        }
        let mut bytes = b"hepta.kernel.authority.revocation-ack.v1\0".to_vec();
        bytes.extend(
            serde_json::to_vec(self).map_err(|_| FinalUseControlError::InvalidRevocationAck)?,
        );
        Ok(bytes)
    }

    fn validate_against(
        &self,
        update: &FinalUseRevocationUpdate,
    ) -> Result<(), FinalUseControlError> {
        if self.schema_version != REVOCATION_ACK_SCHEMA_VERSION
            || self.distributor_id != update.distributor_id
            || self.authority_epoch != update.head.authority_epoch
            || self.revision != update.head.revision
            || self.update_sha256 != revocation_update_digest(update)?
            || self.applied_at_unix_ms < update.issued_at_unix_ms
            || self.applied_at_unix_ms >= update.expires_at_unix_ms
        {
            return Err(FinalUseControlError::InvalidRevocationAck);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedFinalUseRevocationAck {
    pub ack: FinalUseRevocationAck,
    pub signature: Vec<u8>,
}

/// Pinned enrolled-node trust for convergence acknowledgement verification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalUseRevocationNodeTrust {
    pub node_id: String,
    pub keys: Vec<FinalUseTrustKey>,
}

/// Cryptographic convergence receipt for one still-fresh update.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalUseRevocationConvergenceReport {
    pub authority_epoch: u64,
    pub revision: u64,
    pub expected_nodes: Vec<String>,
    pub acknowledged_nodes: Vec<String>,
    pub missing_nodes: Vec<String>,
}

impl FinalUseRevocationConvergenceReport {
    pub fn converged(&self) -> bool {
        self.missing_nodes.is_empty()
            && self.acknowledged_nodes.len() == self.expected_nodes.len()
    }
}

/// Verifies signed host acknowledgements against a closed enrolled-node set.
pub struct FinalUseRevocationConvergenceVerifier {
    nodes: BTreeMap<String, Vec<PinnedControlKey>>,
}

impl fmt::Debug for FinalUseRevocationConvergenceVerifier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("FinalUseRevocationConvergenceVerifier([PINNED NODE TRUST])")
    }
}

impl FinalUseRevocationConvergenceVerifier {
    pub fn new(
        nodes: impl IntoIterator<Item = FinalUseRevocationNodeTrust>,
    ) -> Result<Self, FinalUseControlError> {
        let mut pinned = BTreeMap::new();
        for node in nodes {
            if !identifier(&node.node_id)
                || pinned.len() >= MAX_REVOCATION_NODES
                || pinned
                    .insert(node.node_id, pin_keys(node.keys)?)
                    .is_some()
            {
                return Err(FinalUseControlError::InvalidRevocationNodeTrust);
            }
        }
        if pinned.is_empty() {
            return Err(FinalUseControlError::InvalidRevocationNodeTrust);
        }
        Ok(Self { nodes: pinned })
    }

    /// Verify all supplied acknowledgements and report the exact missing node
    /// set. The update must still be fresh at report time; a stale head can
    /// never be declared converged for new effects.
    pub fn verify(
        &self,
        update: &FinalUseRevocationUpdate,
        acknowledgements: &[SignedFinalUseRevocationAck],
        now_unix_ms: u64,
    ) -> Result<FinalUseRevocationConvergenceReport, FinalUseControlError> {
        update.signing_bytes()?;
        if now_unix_ms < update.issued_at_unix_ms {
            return Err(FinalUseControlError::RevocationFeedNotYetValid);
        }
        if now_unix_ms >= update.expires_at_unix_ms {
            return Err(FinalUseControlError::RevocationFeedStale);
        }
        if acknowledgements.len() > self.nodes.len() {
            return Err(FinalUseControlError::InvalidRevocationAck);
        }

        let mut acknowledged = BTreeSet::new();
        for signed in acknowledgements {
            signed.ack.validate_against(update)?;
            let keys = self
                .nodes
                .get(&signed.ack.node_id)
                .ok_or(FinalUseControlError::UnknownRevocationNode)?;
            if !acknowledged.insert(signed.ack.node_id.clone()) {
                return Err(FinalUseControlError::DuplicateRevocationAck);
            }
            let input = signed.ack.signing_bytes()?;
            let signature = Signature::from_slice(&signed.signature)
                .map_err(|_| FinalUseControlError::InvalidSignature)?;
            verify_key_ring(
                keys,
                signed.ack.authority_epoch,
                &input,
                &signature,
            )?;
        }

        let expected_nodes: Vec<String> = self.nodes.keys().cloned().collect();
        let acknowledged_nodes: Vec<String> = acknowledged.iter().cloned().collect();
        let missing_nodes = self
            .nodes
            .keys()
            .filter(|node| !acknowledged.contains(*node))
            .cloned()
            .collect();
        Ok(FinalUseRevocationConvergenceReport {
            authority_epoch: update.head.authority_epoch,
            revision: update.head.revision,
            expected_nodes,
            acknowledged_nodes,
            missing_nodes,
        })
    }
}

/// Pinned verifier for one independently operated revocation distributor.
#[derive(Clone)]
pub struct FinalUseRevocationFeedVerifier {
    distributor_id: String,
    keys: Vec<PinnedControlKey>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalUseRevocationReceipt {
    pub distributor_id: String,
    pub trust_key_id: String,
    pub authority_epoch: u64,
    pub revision: u64,
    pub valid_until_unix_ms: u64,
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
        Self::new_with_keys(
            distributor_id,
            vec![FinalUseTrustKey {
                key_id: "single-key".into(),
                verifying_key,
                not_before_authority_epoch: 1,
                not_after_authority_epoch: u64::MAX,
            }],
        )
    }

    pub fn new_with_keys(
        distributor_id: String,
        keys: Vec<FinalUseTrustKey>,
    ) -> Result<Self, FinalUseControlError> {
        if !identifier(&distributor_id) {
            return Err(FinalUseControlError::InvalidTrust);
        }
        Ok(Self {
            distributor_id,
            keys: pin_keys(keys)?,
        })
    }

    /// Authenticate one fresh head and atomically hand it to the durable
    /// authority owner. Replays, rollback and same-epoch revocation removal are
    /// rejected by `FinalUseAuthority::update_revocations`.
    pub fn apply(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseRevocationUpdate,
        now_unix_ms: u64,
    ) -> Result<FinalUseRevocationReceipt, FinalUseControlError> {
        if signed.update.distributor_id != self.distributor_id {
            return Err(FinalUseControlError::InvalidRevocationUpdate);
        }
        let input = signed.update.signing_bytes()?;
        if now_unix_ms < signed.update.issued_at_unix_ms {
            return Err(FinalUseControlError::RevocationFeedNotYetValid);
        }
        if now_unix_ms >= signed.update.expires_at_unix_ms {
            return Err(FinalUseControlError::RevocationFeedStale);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FinalUseControlError::InvalidSignature)?;
        let key_id = verify_key_ring(
            &self.keys,
            signed.update.head.authority_epoch,
            &input,
            &signature,
        )?
        .to_owned();
        authority
            .update_revocations(signed.update.head.clone())
            .map_err(FinalUseControlError::Authority)?;
        Ok(FinalUseRevocationReceipt {
            distributor_id: self.distributor_id.clone(),
            trust_key_id: key_id,
            authority_epoch: signed.update.head.authority_epoch,
            revision: signed.update.head.revision,
            valid_until_unix_ms: signed.update.expires_at_unix_ms,
        })
    }
}

fn verify_key_ring<'a>(
    keys: &'a [PinnedControlKey],
    authority_epoch: u64,
    input: &[u8],
    signature: &Signature,
) -> Result<&'a str, FinalUseControlError> {
    for candidate in keys {
        if authority_epoch < candidate.not_before_authority_epoch
            || authority_epoch > candidate.not_after_authority_epoch
        {
            continue;
        }
        if candidate.key.verify_strict(input, signature).is_ok() {
            return Ok(&candidate.key_id);
        }
    }
    Err(FinalUseControlError::InvalidSignature)
}

fn revocation_update_digest(
    update: &FinalUseRevocationUpdate,
) -> Result<[u8; 32], FinalUseControlError> {
    let bytes = update.signing_bytes()?;
    let mut hash = Sha256::new();
    hash.update(b"hepta.kernel.authority.revocation-update-digest.v1\0");
    hash.update(bytes);
    Ok(hash.finalize().into())
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
    InvalidRevocationAck,
    InvalidRevocationNodeTrust,
    UnknownRevocationNode,
    DuplicateRevocationAck,
    RevocationFeedNotYetValid,
    RevocationFeedStale,
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
            1_000,
            31_000,
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
        let receipt = verifier.apply(&authority, &signed, 2_000).unwrap();
        assert_eq!(receipt.trust_key_id, "single-key");
        assert_eq!(receipt.valid_until_unix_ms, 31_000);
        assert_eq!(
            authority.with_verified_use(token, &grant.grant.binding, || ()),
            Err(FinalUseError::Revoked)
        );
        assert_eq!(
            verifier.apply(&authority, &signed, 2_001),
            Err(FinalUseControlError::Authority(
                FinalUseError::StaleRevocationHead
            ))
        );
    }

    #[test]
    fn revocation_feed_freshness_fails_closed() {
        let (authority, grant, _directory, _approver, distributor) = fixture();
        let update = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 11,
                revision: 2,
                revoked_grant_ids: BTreeSet::from([grant.grant.grant_id.clone()]),
            },
            1_000,
            2_000,
        );
        let signed = SignedFinalUseRevocationUpdate {
            signature: distributor
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
            verifier.apply(&authority, &signed, 999),
            Err(FinalUseControlError::RevocationFeedNotYetValid)
        );
        assert_eq!(
            verifier.apply(&authority, &signed, 2_000),
            Err(FinalUseControlError::RevocationFeedStale)
        );
    }

    #[test]
    fn approval_key_ring_enforces_epoch_windows_and_reports_selected_key() {
        let (_authority, grant, _directory, approver, _distributor) = fixture();
        let next = SigningKey::from_bytes(&[44; 32]);
        let verifier = FinalUseApprovalVerifier::new_with_keys(
            "operator-approver".into(),
            vec![
                FinalUseTrustKey {
                    key_id: "old".into(),
                    verifying_key: approver.verifying_key().to_bytes(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 11,
                },
                FinalUseTrustKey {
                    key_id: "next".into(),
                    verifying_key: next.verifying_key().to_bytes(),
                    not_before_authority_epoch: 11,
                    not_after_authority_epoch: 20,
                },
            ],
        )
        .unwrap();
        let approval = FinalUseApproval::for_grant("operator-approver".into(), &grant.grant)
            .unwrap();
        let old_signed = SignedFinalUseApproval {
            signature: approver
                .sign(&approval.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            approval: approval.clone(),
        };
        assert_eq!(
            verifier.verify_with_key_id(&grant, &old_signed),
            Ok("old")
        );
        let next_signed = SignedFinalUseApproval {
            signature: next
                .sign(&approval.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            approval,
        };
        assert_eq!(
            verifier.verify_with_key_id(&grant, &next_signed),
            Ok("next")
        );
    }

    #[test]
    fn convergence_report_requires_every_enrolled_node_ack() {
        let (_authority, grant, _directory, _approver, distributor) = fixture();
        let node_a = SigningKey::from_bytes(&[71; 32]);
        let node_b = SigningKey::from_bytes(&[72; 32]);
        let update = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 11,
                revision: 2,
                revoked_grant_ids: BTreeSet::from([grant.grant.grant_id.clone()]),
            },
            1_000,
            31_000,
        );
        let verifier = FinalUseRevocationConvergenceVerifier::new([
            FinalUseRevocationNodeTrust {
                node_id: "node-a".into(),
                keys: vec![FinalUseTrustKey {
                    key_id: "node-a-key".into(),
                    verifying_key: node_a.verifying_key().to_bytes(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 20,
                }],
            },
            FinalUseRevocationNodeTrust {
                node_id: "node-b".into(),
                keys: vec![FinalUseTrustKey {
                    key_id: "node-b-key".into(),
                    verifying_key: node_b.verifying_key().to_bytes(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 20,
                }],
            },
        ])
        .unwrap();

        let ack_a = FinalUseRevocationAck::for_update("node-a".into(), &update, 2_000).unwrap();
        let signed_a = SignedFinalUseRevocationAck {
            signature: node_a
                .sign(&ack_a.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            ack: ack_a,
        };
        let partial = verifier.verify(&update, &[signed_a.clone()], 2_100).unwrap();
        assert!(!partial.converged());
        assert_eq!(partial.missing_nodes, vec!["node-b"]);

        let ack_b = FinalUseRevocationAck::for_update("node-b".into(), &update, 2_050).unwrap();
        let signed_b = SignedFinalUseRevocationAck {
            signature: node_b
                .sign(&ack_b.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            ack: ack_b,
        };
        let full = verifier
            .verify(&update, &[signed_a, signed_b], 2_100)
            .unwrap();
        assert!(full.converged());
        assert!(full.missing_nodes.is_empty());

        let signed_update = SignedFinalUseRevocationUpdate {
            signature: distributor
                .sign(&update.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            update,
        };
        assert_eq!(signed_update.update.head.revision, full.revision);
    }

    #[test]
    fn convergence_rejects_unknown_duplicate_and_stale_acks() {
        let (_authority, grant, _directory, _approver, _distributor) = fixture();
        let node = SigningKey::from_bytes(&[73; 32]);
        let update = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 11,
                revision: 2,
                revoked_grant_ids: BTreeSet::from([grant.grant.grant_id.clone()]),
            },
            1_000,
            2_000,
        );
        let verifier = FinalUseRevocationConvergenceVerifier::new([
            FinalUseRevocationNodeTrust {
                node_id: "node-a".into(),
                keys: vec![FinalUseTrustKey {
                    key_id: "node-key".into(),
                    verifying_key: node.verifying_key().to_bytes(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 20,
                }],
            },
        ])
        .unwrap();
        let ack = FinalUseRevocationAck::for_update("node-a".into(), &update, 1_500).unwrap();
        let signed = SignedFinalUseRevocationAck {
            signature: node
                .sign(&ack.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            ack,
        };
        assert_eq!(
            verifier.verify(&update, &[signed.clone(), signed.clone()], 1_600),
            Err(FinalUseControlError::InvalidRevocationAck)
        );
        assert_eq!(
            verifier.verify(&update, &[signed], 2_000),
            Err(FinalUseControlError::RevocationFeedStale)
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
            1_000,
            31_000,
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
            verifier.apply(&authority, &signed, 2_000),
            Err(FinalUseControlError::InvalidSignature)
        );
        assert!(authority.claim(&grant, &grant.grant.binding).is_ok());
    }
}
