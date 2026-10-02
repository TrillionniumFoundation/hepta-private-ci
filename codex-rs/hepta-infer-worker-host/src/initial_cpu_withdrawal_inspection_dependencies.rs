//! Current authority includes the full prefix; statistical causes include only
//! the actual affected registration lineage, not unrelated signed history.
use super::super::*;
use std::collections::BTreeSet;

pub(super) fn current_prefix(
    mut current: DatasetWithdrawalRegistry,
    historical: DatasetWithdrawalRegistry,
    notices: Option<&Vec<super::Notice>>,
) -> HostResult<DatasetWithdrawalRegistry> {
    let Some(notices) = notices else {
        return Ok(historical);
    };
    if notices.is_empty() || notices.len() > 64 {
        return Err("bounded complete current withdrawal prefix required".into());
    }
    for notice in notices {
        current.append(notice.native()?)?;
    }
    let current_snapshot = current.snapshot();
    let historical_snapshot = historical.snapshot();
    if current_snapshot.records().len() != notices.len()
        || current_snapshot
            .records()
            .get(..historical_snapshot.records().len())
            != Some(historical_snapshot.records())
    {
        return Err(
            "current withdrawal prefix omitted, forked or repeated original history".into(),
        );
    }
    Ok(current)
}

pub(super) fn artifact_events<'a>(
    registry: &ArtifactRegistry,
    targets: impl Iterator<Item = &'a StableId>,
) -> HostResult<BTreeSet<Digest32>> {
    let mut ids = BTreeSet::new();
    for target in targets {
        let mut cursor = Some(target.clone());
        while let Some(id) = cursor {
            if !ids.insert(id.clone()) {
                break;
            }
            if ids.len() > 126 {
                return Err("withdrawal causal lineage capacity".into());
            }
            cursor = registry
                .manifest(&id)
                .ok_or("original causal artifact missing")?
                .predecessor_id
                .clone();
        }
    }
    let events: BTreeSet<_> = registry
        .records()
        .iter()
        .filter_map(|record| match &record.event {
            ArtifactEvent::Register { manifest, .. } if ids.contains(&manifest.artifact_id) => {
                Some(record.event_digest)
            }
            _ => None,
        })
        .collect();
    if events.is_empty() || events.len() != ids.len() || events.contains(&Digest32::ZERO) {
        return Err("original causal registration event missing".into());
    }
    Ok(events)
}

/// Only the actual source episode/correction ancestry is causal. Other
/// authenticated decisions in this same Dataset/frontier do not join it.
pub(super) fn source_events(
    snapshot: &codex_hepta_agent_components::learning_ledger::LedgerSnapshot,
    source: &StableId,
) -> HostResult<(BTreeSet<Digest32>, BTreeSet<Digest32>)> {
    use codex_hepta_agent_components::learning_ledger::LedgerEvent;
    let mut pending = vec![source.clone()];
    let mut visited = BTreeSet::new();
    let mut events = BTreeSet::new();
    let mut supports = BTreeSet::new();
    while let Some(id) = pending.pop() {
        if !visited.insert(id.clone()) {
            continue;
        }
        if visited.len() > 126 {
            return Err("source causal lineage capacity".into());
        }
        let record = snapshot
            .records()
            .iter()
            .find(|record| record.event.record_id() == &id)
            .ok_or("original causal source record missing")?;
        events.insert(record.event_digest);
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(decision) => {
                supports.insert(decision.support_digest);
            }
            LedgerEvent::AuthenticatedOutcomeV2(outcome) => {
                supports.insert(outcome.support_digest);
                if let Some(predecessor) = &outcome.correction_predecessor {
                    let predecessor = snapshot
                        .records()
                        .iter()
                        .find_map(|record| match &record.event {
                            LedgerEvent::AuthenticatedOutcomeV2(previous)
                                if &previous.outcome_id == predecessor
                                    && previous.episode_id == outcome.episode_id =>
                            {
                                Some(previous.record_id.clone())
                            }
                            _ => None,
                        })
                        .ok_or("original source correction predecessor missing")?;
                    pending.push(predecessor);
                }
                let decisions: Vec<_> = snapshot
                    .records()
                    .iter()
                    .filter_map(|record| match &record.event {
                        LedgerEvent::AuthenticatedDecisionV2(decision)
                            if decision.episode_id == outcome.episode_id =>
                        {
                            Some(decision.record_id.clone())
                        }
                        _ => None,
                    })
                    .collect();
                if decisions.len() != 1 {
                    return Err("source outcome lacks its exact original decision".into());
                }
                pending.extend(decisions);
            }
            _ => {
                return Err(
                    "V2 withdrawal source requires authenticated native decision/outcome lineage"
                        .into(),
                );
            }
        }
    }
    if events.is_empty()
        || events.contains(&Digest32::ZERO)
        || supports.is_empty()
        || supports.contains(&Digest32::ZERO)
    {
        return Err("original causal source/support event missing".into());
    }
    Ok((events, supports))
}

#[cfg(test)]
#[path = "initial_cpu_withdrawal_inspection_dependencies_tests.rs"]
mod tests;
