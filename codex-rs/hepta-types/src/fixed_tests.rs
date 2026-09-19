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
fn probability_clamp_and_division_fail_closed() {
    assert_eq!(
        ProbabilityQ32::from_raw((1_u64 << 32) + 1),
        Err(FixedQ32Error::ProbabilityOutOfRange((1_u64 << 32) + 1))
    );
    assert_eq!(
        FixedQ32::ZERO.clamp(FixedQ32::ONE, FixedQ32::ZERO),
        Err(FixedQ32Error::InvalidRange)
    );
    assert_eq!(
        FixedQ32::ONE.checked_div(FixedQ32::ZERO),
        Err(FixedQ32Error::DivisionByZero)
    );
    assert_eq!(
        FixedQ32::from_raw(i64::MAX).checked_add(FixedQ32::ONE),
        Err(FixedQ32Error::Overflow)
    );
    assert_eq!(
        FixedQ32::from_raw(i64::MIN).checked_sub(FixedQ32::ONE),
        Err(FixedQ32Error::Overflow)
    );
}

#[test]
fn checked_add_sub_small_domain_round_trip_property() {
    let samples = [
        i64::MIN + 1,
        -2_i64 << 32,
        -(1_i64 << 32),
        -1,
        0,
        1,
        1_i64 << 32,
        2_i64 << 32,
        i64::MAX - 1,
    ];
    for left in samples {
        for right in samples {
            let left = FixedQ32::from_raw(left);
            let right = FixedQ32::from_raw(right);
            if let Ok(sum) = left.checked_add(right) {
                assert_eq!(sum.checked_sub(right), Ok(left));
            }
        }
    }
}

#[test]
fn probability_accepts_closed_interval_endpoints() {
    assert_eq!(ProbabilityQ32::from_raw(0), Ok(ProbabilityQ32::ZERO));
    assert_eq!(
        ProbabilityQ32::from_raw(1_u64 << 32),
        Ok(ProbabilityQ32::ONE)
    );
}
