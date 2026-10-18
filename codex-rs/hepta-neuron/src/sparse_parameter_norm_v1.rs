//! Original exact Q32 norm over the supported sparse Q24 operand.
use crate::SparseConfig;
pub fn sparse_parameter_norm_denominator_v1(
    baseline: &SparseConfig,
) -> Result<u128, Box<dyn std::error::Error>> {
    [
        baseline.temporal_decay_q24,
        baseline.inhibition_gain_q24,
        baseline.activity_decay_q24,
        baseline.target_activity_q24,
        baseline.threshold_rate_q24,
        baseline.threshold_min_q24,
        baseline.threshold_max_q24,
        baseline.eligibility_decay_q24,
    ]
    .into_iter()
    .try_fold(0_u128, |total, value| {
        let q32 = i128::from(value) * 256;
        total
            .checked_add(q32.unsigned_abs().pow(2))
            .ok_or_else(|| Box::<dyn std::error::Error>::from("sparse compiler norm overflow"))
    })
}
