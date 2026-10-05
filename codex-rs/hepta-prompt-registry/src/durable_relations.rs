//! Storage-V4 relation image, using the existing registry lock and publication.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::DurableRegistryError;
use super::parse_id;
use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptFactor;
use crate::PromptFactorRelation;
use crate::PromptFactorRelationKind;
use crate::PromptRegistry;

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
    stored: Vec<StoredRelation>,
    factors: &BTreeMap<StableId, PromptFactor>,
) -> Result<BTreeMap<StableId, PromptFactorRelation>, DurableRegistryError> {
    if stored.len() > crate::MAX_RECORDS {
        return Err(DurableRegistryError::Corrupt);
    }
    let mut relations = BTreeMap::new();
    let mut pairs = BTreeSet::new();
    let mut previous_id = None;
    for record in stored {
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
        if previous_id
            .as_ref()
            .is_some_and(|prior| prior >= &relation.relation_id)
            || relation.left_factor_id >= relation.right_factor_id
            || relation.evidence_digest.is_zero()
            || !pairs.insert((
                relation.left_factor_id.clone(),
                relation.right_factor_id.clone(),
                relation.kind,
            ))
        {
            return Err(DurableRegistryError::Corrupt);
        }
        for endpoint in [&relation.left_factor_id, &relation.right_factor_id] {
            let factor = factors.get(endpoint).ok_or(DurableRegistryError::Corrupt)?;
            // Retired/revoked relations are retained as original history. The
            // authoritative graph projection hides them; reopen cannot revive
            // an endpoint or forget the original relation evidence.
            if factor.source != FactorSource::GovernedInternal
                || factor.lifecycle == Lifecycle::Draft
            {
                return Err(DurableRegistryError::Corrupt);
            }
        }
        previous_id = Some(relation.relation_id.clone());
        relations.insert(relation.relation_id.clone(), relation);
    }
    Ok(relations)
}
