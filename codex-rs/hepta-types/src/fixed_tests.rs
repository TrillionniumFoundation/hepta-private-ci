use super::*;

#[test]
fn multiplication_and_division_are_deterministic() {
    let half = FixedQ32::from_raw(1_i64 << 31);
    let product = half.checked_mul(half);
    assert_eq!(product, Ok(FixedQ32::from_raw(1_i64 << 30)));
    let quotient = half.checked_div(FixedQ32::from_raw(1_i64 << 30));
    assert_eq!(quotient, Ok(FixedQ32::from_raw(2_i64 << 32)));
}

#[test]
fn probability_and_clamp_fail_closed() {
    assert_eq!(
        ProbabilityQ32::from_raw((1_u64 << 32) + 1),
        Err(FixedQ32Error::ProbabilityOutOfRange((1_u64 << 32) + 1))
    );
    assert_eq!(
        FixedQ32::ZERO.clamp(FixedQ32::ONE, FixedQ32::ZERO),
        Err(FixedQ32Error::InvalidRange)
    );
}
