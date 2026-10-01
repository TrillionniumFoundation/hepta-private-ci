//! Operation-bound relation admission and durable relation metadata.

use std::collections::BTreeSet;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::DurablePromptRegistry;
use super::DurableRegistryError;
use super::parse_id;
use crate::AdmissionError;
use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptFactorRelation;
use crate::PromptFactorRelationKind;
use crate::PromptRegistry;
use crate::RegistryReceipt;
use crate::admission::map_final_use_error;
use crate::factor_relation::RelationWithdrawal;

/// Binds one relation to the current owner snapshot, exact evidence and scope.
/// The relation carries no execution or mutation authority into its graph view.
pub fn final_use_factor_relation_binding(
    registry: &PromptRegistry,
    actor_id: &StableId,
    scope_digest: Digest32,
    relation: &PromptFactorRelation,
) -> Result<FinalUseBinding, AdmissionError> {
    if scope_digest.is_zero() || relation.evidence_digest.is_zero() {
        return Err(AdmissionError::ScopeMismatch);
    }
    if registry
        .relation_withdrawals
        .contains_key(&relation.relation_id)
    {
        return Err(AdmissionError::InvalidGrant);
    }
    if relation.left_factor_id >= relation.right_factor_id {
        return Err(AdmissionError::InvalidGrant);
    }
    for factor_id in [&relation.left_factor_id, &relation.right_factor_id] {
        let factor = registry
            .factor(factor_id)
            .ok_or(AdmissionError::FactorBindingMismatch)?;
        if factor.source != FactorSource::GovernedInternal
            || factor.lifecycle != Lifecycle::Admitted
        {
            return Err(AdmissionError::UntrustedFactor);
        }
    }
    let mut request = b"hepta.prompt-registry.final-use-factor-relation.v1\0".to_vec();
    request.extend_from_slice(registry.snapshot_digest().as_array());
    crate::push_relation(&mut request, relation);
    Ok(FinalUseBinding {
        subject_id: actor_id.to_string(),
        destination_id: "prompt.registry:factor-relation".to_owned(),
        request_sha256: Digest32::of_bytes(&request).into_array(),
        scope_sha256: scope_digest.into_array(),
        payload_sha256: relation.evidence_digest.into_array(),
    })
}

/// Binds terminal withdrawal to the current owner cut and original relation fact.
pub fn final_use_factor_relation_revocation_binding(
    registry: &PromptRegistry,
    actor_id: &StableId,
    scope_digest: Digest32,
    relation_id: &StableId,
    reason_digest: Digest32,
) -> Result<FinalUseBinding, AdmissionError> {
    if scope_digest.is_zero() || reason_digest.is_zero() {
        return Err(AdmissionError::ScopeMismatch);
    }
    if registry.relation_withdrawals.contains_key(relation_id) {
        return Err(AdmissionError::InvalidGrant);
    }
    let relation = registry
        .relations
        .get(relation_id)
        .ok_or(AdmissionError::FactorBindingMismatch)?;
    let mut request = b"hepta.prompt-registry.final-use-factor-relation-revoke.v1\0".to_vec();
    request.extend_from_slice(registry.snapshot_digest().as_array());
    crate::push_relation(&mut request, relation);
    Ok(FinalUseBinding {
        subject_id: actor_id.to_string(),
        destination_id: "prompt.registry:factor-relation-revoke".to_owned(),
        request_sha256: Digest32::of_bytes(&request).into_array(),
        scope_sha256: scope_digest.into_array(),
        payload_sha256: reason_digest.into_array(),
    })
}

impl DurablePromptRegistry {
    pub fn revoke_factor_relation_final_use(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        actor_id: &StableId,
        scope_digest: Digest32,
        relation_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.ensure_available()?;
        let expected = final_use_factor_relation_revocation_binding(
            &self.registry,
            actor_id,
            scope_digest,
            relation_id,
            reason_digest,
        )
        .map_err(DurableRegistryError::Admission)?;
        let grant_id = StableId::new(&signed.grant.grant_id)
            .map_err(|_| DurableRegistryError::Admission(AdmissionError::InvalidGrant))?;
        let token = authority
            .claim(signed, &expected)
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?;
        authority
            .with_verified_use(token, &expected, || {
                self.commit(|registry| {
                    registry.revoke_factor_relation_governed(
                        relation_id,
                        actor_id,
                        scope_digest,
                        reason_digest,
                        &grant_id,
                    )
                })
            })
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?
    }

    pub fn register_factor_relation_final_use(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        actor_id: &StableId,
        scope_digest: Digest32,
        relation: PromptFactorRelation,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.ensure_available()?;
        let expected =
            final_use_factor_relation_binding(&self.registry, actor_id, scope_digest, &relation)
                .map_err(DurableRegistryError::Admission)?;
        let token = authority
            .claim(signed, &expected)
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?;
        authority
            .with_verified_use(token, &expected, || {
                self.commit(|registry| registry.register_factor_relation(relation))
            })
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredRelation {
    relation_id: String,
    left_factor_id: String,
    right_factor_id: String,
    kind: u8,
    evidence_digest: [u8; 32],
}

impl StoredRelation {
    pub(super) fn encode(relation: &PromptFactorRelation) -> Self {
        Self {
            relation_id: relation.relation_id.to_string(),
            left_factor_id: relation.left_factor_id.to_string(),
            right_factor_id: relation.right_factor_id.to_string(),
            kind: match relation.kind {
                PromptFactorRelationKind::Complements => 0,
                PromptFactorRelationKind::Substitutes => 1,
                PromptFactorRelationKind::Conflicts => 2,
            },
            evidence_digest: relation.evidence_digest.into_array(),
        }
    }

    pub(super) fn decode(self) -> Result<PromptFactorRelation, DurableRegistryError> {
        Ok(PromptFactorRelation {
            relation_id: parse_id(self.relation_id)?,
            left_factor_id: parse_id(self.left_factor_id)?,
            right_factor_id: parse_id(self.right_factor_id)?,
            kind: match self.kind {
                0 => PromptFactorRelationKind::Complements,
                1 => PromptFactorRelationKind::Substitutes,
                2 => PromptFactorRelationKind::Conflicts,
                _ => return Err(DurableRegistryError::Corrupt),
            },
            evidence_digest: Digest32::from_array(self.evidence_digest),
        })
    }
}

pub(super) fn validate_restored_relations(
    registry: &PromptRegistry,
) -> Result<(), DurableRegistryError> {
    let mut identities = BTreeSet::new();
    for relation in registry.relations.values() {
        if relation.left_factor_id >= relation.right_factor_id
            || relation.evidence_digest.is_zero()
            || (!registry
                .relation_withdrawals
                .contains_key(&relation.relation_id)
                && !identities.insert((
                    &relation.left_factor_id,
                    &relation.right_factor_id,
                    relation.kind,
                )))
        {
            return Err(DurableRegistryError::Corrupt);
        }
        // Retired/revoked endpoint records remain for audit. They are omitted
        // by factor_graph_source_v1, rather than deleting their relation facts.
        for factor_id in [&relation.left_factor_id, &relation.right_factor_id] {
            let factor = registry
                .factors
                .get(factor_id)
                .ok_or(DurableRegistryError::Corrupt)?;
            if factor.source != FactorSource::GovernedInternal
                || factor.lifecycle == Lifecycle::Draft
            {
                return Err(DurableRegistryError::Corrupt);
            }
        }
    }
    let mut revisions = BTreeSet::new();
    for withdrawal in registry.relation_withdrawals.values() {
        let relation = registry
            .relations
            .get(&withdrawal.relation_id)
            .ok_or(DurableRegistryError::Corrupt)?;
        let mut bytes = Vec::new();
        crate::push_relation(&mut bytes, relation);
        if withdrawal.revision.get() > registry.revision.get()
            || withdrawal.scope_digest.is_zero()
            || withdrawal.reason_digest.is_zero()
            || withdrawal.relation_digest != Digest32::of_bytes(&bytes)
            || withdrawal.withdrawal_digest != withdrawal.compute_digest()
            || !revisions.insert(withdrawal.revision)
            || registry
                .lifecycle_events
                .iter()
                .any(|event| event.revision == withdrawal.revision)
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    Ok(())
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredWithdrawal {
    relation_id: String,
    revision: u64,
    relation_digest: [u8; 32],
    actor_id: String,
    scope_digest: [u8; 32],
    reason_digest: [u8; 32],
    grant_id: String,
    withdrawal_digest: [u8; 32],
}

impl StoredWithdrawal {
    pub(super) fn encode(value: &RelationWithdrawal) -> Self {
        Self {
            relation_id: value.relation_id.to_string(),
            revision: value.revision.get(),
            relation_digest: value.relation_digest.into_array(),
            actor_id: value.actor_id.to_string(),
            scope_digest: value.scope_digest.into_array(),
            reason_digest: value.reason_digest.into_array(),
            grant_id: value.grant_id.to_string(),
            withdrawal_digest: value.withdrawal_digest.into_array(),
        }
    }

    pub(super) fn decode(self) -> Result<RelationWithdrawal, DurableRegistryError> {
        Ok(RelationWithdrawal {
            relation_id: parse_id(self.relation_id)?,
            revision: Revision::new(self.revision).map_err(|_| DurableRegistryError::Corrupt)?,
            relation_digest: Digest32::from_array(self.relation_digest),
            actor_id: parse_id(self.actor_id)?,
            scope_digest: Digest32::from_array(self.scope_digest),
            reason_digest: Digest32::from_array(self.reason_digest),
            grant_id: parse_id(self.grant_id)?,
            withdrawal_digest: Digest32::from_array(self.withdrawal_digest),
        })
    }
}

