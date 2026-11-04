//! Explicit PQ control constructors use the same durable authority transitions.

use super::*;
use crate::PqAuthorityTrustKey;
use crate::authority_authentication::pin_pq_keys;

fn control_keys(
    keys: Vec<PqAuthorityTrustKey>,
) -> Result<Vec<PinnedControlKey>, FinalUseControlError> {
    pin_pq_keys(keys)
        .map_err(|()| FinalUseControlError::InvalidTrust)
        .map(|keys| {
            keys.into_iter()
                .map(|key| PinnedControlKey {
                    key_id: key.key_id,
                    key: key.key,
                    not_before_authority_epoch: key.not_before_authority_epoch,
                    not_after_authority_epoch: key.not_after_authority_epoch,
                })
                .collect()
        })
}

impl FinalUseApprovalVerifier {
    pub fn new_pq_with_keys(
        approver_id: String,
        keys: Vec<PqAuthorityTrustKey>,
    ) -> Result<Self, FinalUseControlError> {
        if !identifier(&approver_id) {
            return Err(FinalUseControlError::InvalidTrust);
        }
        Ok(Self {
            approver_id,
            keys: control_keys(keys)?,
            profile: FinalUseAuthenticationProfile::MlDsa65V2,
        })
    }
}

impl FinalUseRevocationFeedVerifier {
    /// Authenticate a fresh presentation of the exact durable head, or apply a
    /// strict monotonic successor. Confirmation never writes a new frontier and
    /// never bypasses signature, profile, or feed lifetime verification.
    pub fn apply_or_confirm_current(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseRevocationUpdate,
        now_unix_ms: u64,
    ) -> Result<FinalUseRevocationReceipt, FinalUseControlError> {
        if self.profile != authority.authentication_profile() {
            return Err(FinalUseControlError::InvalidTrust);
        }
        let key_id = self.verify_signed(signed, now_unix_ms)?.to_owned();
        let current = authority
            .revocation_head()
            .map_err(FinalUseControlError::Authority)?;
        if current != signed.update.head {
            authority
                .update_revocations(signed.update.head.clone())
                .map_err(FinalUseControlError::Authority)?;
        }
        Ok(FinalUseRevocationReceipt {
            distributor_id: self.distributor_id.clone(),
            trust_key_id: key_id,
            authority_epoch: signed.update.head.authority_epoch,
            revision: signed.update.head.revision,
            update_sha256: revocation_update_digest(&signed.update)?,
            valid_until_unix_ms: signed.update.expires_at_unix_ms,
        })
    }

    pub fn new_pq_with_keys(
        distributor_id: String,
        keys: Vec<PqAuthorityTrustKey>,
    ) -> Result<Self, FinalUseControlError> {
        if !identifier(&distributor_id) {
            return Err(FinalUseControlError::InvalidTrust);
        }
        Ok(Self {
            distributor_id,
            keys: control_keys(keys)?,
            profile: FinalUseAuthenticationProfile::MlDsa65V2,
        })
    }
}

impl FinalUseRevocationUpdate {
    pub fn new_pq(
        distributor_id: String,
        head: FinalUseRevocations,
        issued_at_unix_ms: u64,
        expires_at_unix_ms: u64,
    ) -> Self {
        Self {
            schema_version: 3,
            distributor_id,
            head,
            issued_at_unix_ms,
            expires_at_unix_ms,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PqFinalUseRevocationNodeTrust {
    pub node_id: String,
    pub keys: Vec<PqAuthorityTrustKey>,
}

impl FinalUseRevocationConvergenceVerifier {
    pub fn new_pq(
        nodes: impl IntoIterator<Item = PqFinalUseRevocationNodeTrust>,
    ) -> Result<Self, FinalUseControlError> {
        let mut pinned = BTreeMap::new();
        for node in nodes {
            if !identifier(&node.node_id)
                || pinned.len() >= MAX_REVOCATION_NODES
                || pinned
                    .insert(node.node_id, control_keys(node.keys)?)
                    .is_some()
            {
                return Err(FinalUseControlError::InvalidRevocationNodeTrust);
            }
        }
        if pinned.is_empty() {
            return Err(FinalUseControlError::InvalidRevocationNodeTrust);
        }
        Ok(Self {
            nodes: pinned,
            profile: FinalUseAuthenticationProfile::MlDsa65V2,
        })
    }
}
