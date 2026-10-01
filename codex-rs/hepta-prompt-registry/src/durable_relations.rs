//! Relation metadata in the existing prompt owner and V2/V3 storage envelope.
//! Historical records survive retirement/revocation; the owner's graph source
//! exposes only relations whose endpoints remain admitted.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::DurablePromptRegistry;
use super::DurableRegistryError;
use super::parse_id;
use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptFactorRelation;
use crate::PromptFactorRelationKind;
use crate::PromptRegistry;
use crate::RegistryReceipt;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

impl DurablePromptRegistry {
    /// Registers governed factor interaction evidence through the same atomic
    /// owner commit as factor lifecycle and realization metadata.
    pub fn register_factor_relation(
        &mut self,
        relation: PromptFactorRelation,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| registry.register_factor_relation(relation))
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

pub(super) fn encode(registry: &PromptRegistry) -> Vec<StoredRelation> {
    registry
        .relations
        .values()
        .map(|relation| StoredRelation {
            relation_id: relation.relation_id.to_string(),
            left_factor_id: relation.left_factor_id.to_string(),
            right_factor_id: relation.right_factor_id.to_string(),
            kind: match relation.kind {
                PromptFactorRelationKind::Complements => 0,
                PromptFactorRelationKind::Substitutes => 1,
                PromptFactorRelationKind::Conflicts => 2,
            },
            evidence_digest: relation.evidence_digest.into_array(),
        })
        .collect()
}

pub(super) fn decode(
    records: Vec<StoredRelation>,
) -> Result<BTreeMap<StableId, PromptFactorRelation>, DurableRegistryError> {
    let mut relations = BTreeMap::new();
    for record in records {
        let relation = PromptFactorRelation {
            relation_id: parse_id(record.relation_id)?,
            left_factor_id: parse_id(record.left_factor_id)?,
            right_factor_id: parse_id(record.right_factor_id)?,
            kind: match record.kind {
                0 => PromptFactorRelationKind::Complements,
                1 => PromptFactorRelationKind::Substitutes,
                2 => PromptFactorRelationKind::Conflicts,
                _ => return Err(DurableRegistryError::Corrupt),
            },
            evidence_digest: Digest32::from_array(record.evidence_digest),
        };
        if relations
            .insert(relation.relation_id.clone(), relation)
            .is_some()
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    Ok(relations)
}

pub(super) fn validate(registry: &PromptRegistry) -> Result<(), DurableRegistryError> {
    let admitted = registry
        .lifecycle_events
        .iter()
        .filter(|event| event.to == Lifecycle::Admitted)
        .map(|event| &event.factor_id)
        .collect::<BTreeSet<_>>();
    let mut identities = BTreeSet::new();
    for relation in registry.relations.values() {
        if relation.evidence_digest.is_zero()
            || relation.left_factor_id >= relation.right_factor_id
            || !identities.insert((
                &relation.left_factor_id,
                &relation.right_factor_id,
                relation.kind,
            ))
        {
            return Err(DurableRegistryError::Corrupt);
        }
        for endpoint in [&relation.left_factor_id, &relation.right_factor_id] {
            let Some(factor) = registry.factors.get(endpoint) else {
                return Err(DurableRegistryError::Corrupt);
            };
            if factor.source != FactorSource::GovernedInternal || !admitted.contains(endpoint) {
                return Err(DurableRegistryError::Corrupt);
            }
        }
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "durable_relations_tests.rs"]
mod tests;
