//! The ordinary timed profile uses Unix microseconds and binds the final
//! window to the exact released cohort. The cut is a content commitment; its
//! provenance still requires the original independent Observer signature.
use std::collections::BTreeMap;

use anyhow::{Result, ensure};
use codex_hepta_intelligence_eval as eval;
use codex_hepta_types::Digest32;

use crate::cognitive_process_product_wire::TemporalComparisonInputsV1Raw;

pub(super) fn source_cut(
    inputs: &eval::TemporalComparisonInputsV1,
    plan: &eval::CrossFoldPlanReceiptV1,
) -> Result<Digest32> {
    let encoded = serde_json::to_vec(&TemporalComparisonInputsV1Raw::from(inputs.clone()))?;
    let mut bytes = b"hepta.agentd.timed-final-cohort.v1\0".to_vec();
    bytes.extend_from_slice(plan.plan_digest.as_array());
    bytes.extend_from_slice(plan.final_holdout_digest.as_array());
    bytes.extend_from_slice(&(encoded.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&encoded);
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) fn validate(
    inputs: &eval::TemporalComparisonInputsV1,
    plan: &eval::CrossFoldPlanReceiptV1,
    windows: &[eval::ObservedFutureWindowV1],
    not_before: u64,
) -> Result<()> {
    ensure!(windows.iter().all(|window| window.starts_unix_micros >= not_before),
        "observed window began before the independently acknowledged future boundary");
    let matching: Vec<_> = windows.iter().filter(|window| window.window_id == plan.final_holdout_window_id).collect();
    ensure!(matching.len() == 1, "timed cohort requires exactly one final observation window");
    let window = matching[0];
    ensure!(!inputs.targets.is_empty() && window.observation_count == inputs.targets.len() as u64,
        "final observation count differs from the complete released cohort");
    ensure!(window.observed_source_cut == source_cut(inputs, plan)?,
        "the final Observer statement must bind the exact canonical released cohort cut");
    let targets: BTreeMap<_, _> = inputs.targets.iter().map(|target| (&target.decision_id, target)).collect();
    ensure!(targets.len() == inputs.targets.len(), "duplicate timed cohort target");
    for target in &inputs.targets {
        ensure!(target.window_id == window.window_id && target.decision_at >= window.starts_unix_micros
            && target.decision_at <= window.ends_unix_micros, "target is outside its actual final window");
    }
    for rows in [&inputs.candidate_observations, &inputs.baseline_observations] {
        let joined: BTreeMap<_, _> = rows.iter().map(|row| (&row.decision_id, row)).collect();
        ensure!(rows.len() == targets.len() && joined.len() == targets.len()
            && joined.keys().eq(targets.keys()), "timed outcome cohort does not bijectively join targets");
        for (id, row) in joined {
            let target = targets[&id];
            // The ordinary profile has synchronous, within-window outcomes.
            // A pending row carries no invented terminal time; a separate
            // delayed-outcome profile must retain its own signed cut policy.
            ensure!((row.finalized_outcome.is_none() && row.outcome_observed_at == 0)
                || (row.outcome_observed_at >= target.decision_at && row.outcome_observed_at <= window.ends_unix_micros),
                "outcome is outside its actual final window");
        }
    }
    Ok(())
}
