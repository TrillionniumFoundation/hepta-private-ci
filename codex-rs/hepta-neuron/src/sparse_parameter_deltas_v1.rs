//! Sole original sparse parameter delta rules; factual computation grants no use.
use crate::SparseConfig;
use codex_hepta_plasticity::ParameterDeltaV2;
use codex_hepta_types::Generation;
use std::collections::BTreeSet;
const PARAMETER_LAYER: &str = "neuron.sparse.rates.q24.v1";
pub fn apply_sparse_parameter_deltas_v1(
    baseline: &SparseConfig,
    generation: Generation,
    deltas: &[ParameterDeltaV2],
) -> Result<SparseConfig, Box<dyn std::error::Error>> {
    baseline
        .digest()
        .map_err(|value| Box::<dyn std::error::Error>::from(value.to_string()))?;
    if baseline.generation.next() != Ok(generation) || deltas.is_empty() || deltas.len() > 8 {
        return Err(Box::<dyn std::error::Error>::from(
            "sparse compiler generation or delta count",
        ));
    }
    let mut result = baseline.clone();
    result.generation = generation;
    let mut seen = BTreeSet::new();
    for delta in deltas {
        if delta.layer_id.as_str() != PARAMETER_LAYER
            || !seen.insert(delta.parameter_id.clone())
            || delta.evidence_digest.is_zero()
            || delta.delta.raw() == 0
            || delta.delta < delta.lower_bound
            || delta.delta > delta.upper_bound
            || delta.delta.raw() % 256 != 0
        {
            return Err(Box::<dyn std::error::Error>::from(
                "sparse compiler unbound or inexact Q32 delta",
            ));
        }
        let target = match delta.parameter_id.as_str() {
            "temporal_decay_q24" => &mut result.temporal_decay_q24,
            "inhibition_gain_q24" => &mut result.inhibition_gain_q24,
            "activity_decay_q24" => &mut result.activity_decay_q24,
            "target_activity_q24" => &mut result.target_activity_q24,
            "threshold_rate_q24" => &mut result.threshold_rate_q24,
            "threshold_min_q24" => &mut result.threshold_min_q24,
            "threshold_max_q24" => &mut result.threshold_max_q24,
            "eligibility_decay_q24" => &mut result.eligibility_decay_q24,
            _ => {
                return Err(Box::<dyn std::error::Error>::from(
                    "sparse compiler parameter is outside installed grammar",
                ));
            }
        };
        *target = target.checked_add(delta.delta.raw() / 256).ok_or_else(|| {
            Box::<dyn std::error::Error>::from("sparse compiler parameter overflow")
        })?;
    }
    result
        .digest()
        .map_err(|value| Box::<dyn std::error::Error>::from(value.to_string()))?;
    Ok(result)
}
