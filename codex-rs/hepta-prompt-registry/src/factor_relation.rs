//! Immutable relation withdrawal lineage under the registry owner.

use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::Error;
use crate::MutationDisposition;
use crate::PromptRegistry;
use crate::RegistryReceipt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RelationWithdrawal {
    pub(crate) relation_id: StableId,
    pub(crate) revision: Revision,
    pub(crate) relation_digest: Digest32,
    pub(crate) actor_id: StableId,
    pub(crate) scope_digest: Digest32,
    pub(crate) reason_digest: Digest32,
    pub(crate) grant_id: StableId,
    pub(crate) withdrawal_digest: Digest32,
}

impl RelationWithdrawal {
    pub(crate) fn compute_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-registry.relation-withdrawal.v1".to_vec();
        crate::push_id(&mut bytes, &self.relation_id);
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
        bytes.extend_from_slice(self.relation_digest.as_array());
        crate::push_id(&mut bytes, &self.actor_id);
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(self.reason_digest.as_array());
        crate::push_id(&mut bytes, &self.grant_id);
        Digest32::of_bytes(&bytes)
    }
}

impl PromptRegistry {
    pub(crate) fn revoke_factor_relation_governed(
        &mut self,
        relation_id: &StableId,
        actor_id: &StableId,
        scope_digest: Digest32,
        reason_digest: Digest32,
        grant_id: &StableId,
    ) -> Result<RegistryReceipt, Error> {
        if scope_digest.is_zero() || reason_digest.is_zero() {
            return Err(Error::EmptyDigest("relation withdrawal"));
        }
        if self.relation_withdrawals.contains_key(relation_id) {
            return Err(Error::InvalidTransition);
        }
        let relation = self
            .relations
            .get(relation_id)
            .ok_or_else(|| Error::RelationConflict(relation_id.to_string()))?;
        let mut relation_bytes = Vec::new();
        crate::push_relation(&mut relation_bytes, relation);
        let revision = self.next_revision()?;
        let mut withdrawal = RelationWithdrawal {
            relation_id: relation_id.clone(),
            revision,
            relation_digest: Digest32::of_bytes(&relation_bytes),
            actor_id: actor_id.clone(),
            scope_digest,
            reason_digest,
            grant_id: grant_id.clone(),
            withdrawal_digest: Digest32::ZERO,
        };
        withdrawal.withdrawal_digest = withdrawal.compute_digest();
        self.relation_withdrawals
            .insert(relation_id.clone(), withdrawal);
        self.commit_revision(revision, /*revocation*/ true);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }
}
