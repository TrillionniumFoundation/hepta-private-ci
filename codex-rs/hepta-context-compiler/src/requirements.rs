use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompilationRequest;
use crate::ContextCompilationReceipt;
use crate::ContextItem;
use crate::ContextRole;
use crate::Error;
use crate::MAX_ITEMS;
use crate::Requirements;
use crate::compile_internal;
use crate::push_id;

/// An indivisible required provenance/contradiction group. Each member binds the
/// exact caller-approved item, including role, source/content digests and cost.
/// Overlapping groups share members without double-charging their token cost.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MandatoryContextGroup {
    pub group_id: StableId,
    pub items: Vec<ContextItem>,
}

/// Native compilation profile v1, bound to an explicit frozen snapshot/objective.
/// The caller authenticates these requirements and the supplied token counts.
/// This contract neither authenticates a source nor observes model delivery.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompilationRequirementsV1 {
    pub run_snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub mandatory_groups: Vec<MandatoryContextGroup>,
}

/// Reserve every instruction and required group before packing optional items.
/// Failure to fit the floor returns `InsufficientContext`, never a partial group.
pub fn compile_with_requirements(
    request: CompilationRequest,
    requirements: CompilationRequirementsV1,
) -> Result<ContextCompilationReceipt, Error> {
    compile_internal(request, Requirements::Explicit(requirements))
}

pub(crate) fn validate_and_digest(
    request: &CompilationRequest,
    mut requirements: CompilationRequirementsV1,
) -> Result<(BTreeSet<StableId>, Digest32), Error> {
    if requirements.run_snapshot_digest != request.run_snapshot_digest {
        return Err(Error::RequirementSnapshotMismatch);
    }
    if requirements.objective_digest != request.objective_digest {
        return Err(Error::RequirementObjectiveMismatch);
    }
    if requirements.mandatory_groups.len() > MAX_ITEMS {
        return Err(Error::RequirementLimitExceeded);
    }
    let references = requirements
        .mandatory_groups
        .iter()
        .try_fold(0_usize, |count, group| count.checked_add(group.items.len()))
        .ok_or(Error::RequirementLimitExceeded)?;
    if references > MAX_ITEMS {
        return Err(Error::RequirementLimitExceeded);
    }
    let items: BTreeMap<_, _> = request
        .items
        .iter()
        .map(|item| (&item.item_id, item))
        .collect();
    requirements
        .mandatory_groups
        .sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut groups = BTreeSet::new();
    let mut required = BTreeSet::new();
    let mut bytes = b"hepta.context.requirements.v1".to_vec();
    bytes.extend_from_slice(requirements.run_snapshot_digest.as_array());
    bytes.extend_from_slice(requirements.objective_digest.as_array());
    bytes.extend_from_slice(&(requirements.mandatory_groups.len() as u64).to_be_bytes());
    for mut group in requirements.mandatory_groups {
        if !groups.insert(group.group_id.clone()) {
            return Err(Error::DuplicateRequirementGroup(group.group_id.to_string()));
        }
        if group.items.is_empty() {
            return Err(Error::EmptyRequirementGroup(group.group_id.to_string()));
        }
        group
            .items
            .sort_by(|left, right| left.item_id.cmp(&right.item_id));
        push_id(&mut bytes, &group.group_id);
        bytes.extend_from_slice(&(group.items.len() as u64).to_be_bytes());
        let mut members = BTreeSet::new();
        for expected in group.items {
            if !members.insert(expected.item_id.clone()) {
                return Err(Error::DuplicateRequirementItem(
                    expected.item_id.to_string(),
                ));
            }
            let actual = items
                .get(&expected.item_id)
                .ok_or_else(|| Error::UnknownRequiredItem(expected.item_id.to_string()))?;
            if **actual != expected {
                return Err(Error::RequiredItemMismatch(expected.item_id.to_string()));
            }
            push_id(&mut bytes, &expected.item_id);
            bytes.push(match expected.role {
                ContextRole::TrustedInstruction => 0,
                ContextRole::UntrustedEvidence => 1,
            });
            bytes.extend_from_slice(expected.content_digest.as_array());
            bytes.extend_from_slice(expected.source_digest.as_array());
            bytes.extend_from_slice(&expected.token_count.to_be_bytes());
            required.insert(expected.item_id);
        }
    }
    Ok((required, Digest32::of_bytes(&bytes)))
}

#[cfg(test)]
#[path = "requirements_tests.rs"]
mod tests;
