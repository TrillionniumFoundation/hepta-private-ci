//! Stable feature inputs are extracted from the original authenticated support
//! bytes. Renaming an execution or registering another artifact cannot split it.
use super::super::*;
use codex_hepta_agent_components::learning_ledger::original_numeric_input_causes_v1;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

pub(super) fn read(
    sources: &[Source],
    supports: &BTreeMap<Digest32, Digest32>,
) -> HostResult<BTreeSet<Digest32>> {
    if sources.is_empty() || sources.len() > 3 {
        return Err("original G batch and O candidate/baseline numeric archives required".into());
    }
    let bytes = sources
        .iter()
        .map(|source| source.read(4 * 1024 * 1024))
        .collect::<HostResult<Vec<_>>>()?;
    let inputs = original_inputs(bytes.iter().map(Vec::as_slice), supports)?;
    for source in sources {
        source.read(4 * 1024 * 1024)?;
    }
    Ok(inputs)
}

fn original_inputs<'a>(
    archives: impl Iterator<Item = &'a [u8]>,
    supports: &BTreeMap<Digest32, Digest32>,
) -> HostResult<BTreeSet<Digest32>> {
    if supports.is_empty() || supports.len() > 126 || supports.contains_key(&Digest32::ZERO) {
        return Err("actual authenticated original supports required".into());
    }
    let mut joined = BTreeMap::new();
    for archive in archives {
        joined.extend(original_numeric_input_causes_v1(archive, supports)?);
    }
    if !joined.keys().eq(supports.keys()) {
        return Err("actual signed support has no exact original numeric input material".into());
    }
    Ok(joined.into_values().collect())
}

#[cfg(test)]
#[path = "initial_cpu_withdrawal_input_causality_tests.rs"]
mod tests;
