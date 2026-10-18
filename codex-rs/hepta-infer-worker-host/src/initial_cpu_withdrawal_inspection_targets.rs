//! Full native historical lineage determines the required physical denials.
//! This private projection grants no eligibility or publication authority.
use super::super::*;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

pub(super) fn complete(
    registry: &ArtifactRegistry,
    direct: &BTreeSet<StableId>,
    targets: &[String],
    changes: &[ArtifactEvent],
) -> HostResult<BTreeMap<StableId, &'static str>> {
    if direct.is_empty() || direct.iter().any(|id| !registry.is_eligible(id)) {
        return Err("withdrawal native source membership disappeared".into());
    }
    let mut affected: BTreeMap<StableId, &'static str> =
        direct.iter().cloned().map(|id| (id, "source")).collect();
    for record in registry.records() {
        if let ArtifactEvent::Register { manifest, .. } = &record.event
            && registry.is_eligible(&manifest.artifact_id)
            && manifest
                .predecessor_id
                .as_ref()
                .is_some_and(|id| affected.contains_key(id))
        {
            // Inherited V2 membership still needs its own original Revoke.
            affected.insert(manifest.artifact_id.clone(), "descendant");
        }
    }
    let named = targets
        .iter()
        .map(|value| id(value))
        .collect::<HostResult<BTreeSet<_>>>()?;
    let revoked: BTreeSet<_> = changes
        .iter()
        .filter_map(|event| match event {
            ArtifactEvent::Revoke(change) => Some(change.artifact_id.clone()),
            _ => None,
        })
        .collect();
    if affected.len() > 64
        || named.len() != targets.len()
        || named != affected.keys().cloned().collect()
        || &revoked != direct
        || revoked.len() != changes.len()
    {
        return Err(
            "withdrawal omitted native source/descendant delivery targets or original suffix"
                .into(),
        );
    }
    Ok(affected)
}

#[cfg(test)]
#[path = "initial_cpu_withdrawal_inspection_targets_tests.rs"]
mod tests;
