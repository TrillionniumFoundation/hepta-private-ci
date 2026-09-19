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

#[test]
fn arithmetic_boundaries_fail_without_saturation() {
    assert_eq!(
        FixedQ32::from_raw(i64::MAX).checked_add(FixedQ32::from_raw(1)),
        Err(FixedQ32Error::Overflow)
    );
    assert_eq!(
        FixedQ32::from_raw(i64::MIN).checked_sub(FixedQ32::from_raw(1)),
        Err(FixedQ32Error::Overflow)
    );
    assert_eq!(
        FixedQ32::ONE.checked_div(FixedQ32::ZERO),
        Err(FixedQ32Error::DivisionByZero)
    );
    assert_eq!(ProbabilityQ32::from_raw(0), Ok(ProbabilityQ32::ZERO));
    assert_eq!(
        ProbabilityQ32::from_raw(1_u64 << 32),
        Ok(ProbabilityQ32::ONE)
    );
}

#[test]
fn checked_add_sub_round_trip_for_small_property_grid() {
    let values = [
        -(3_i64 << 32),
        -(1_i64 << 32),
        0,
        1_i64 << 31,
        1_i64 << 32,
        3_i64 << 32,
    ];
    for left in values {
        for right in values {
            let left = FixedQ32::from_raw(left);
            let right = FixedQ32::from_raw(right);
            let sum = left.checked_add(right).expect("small grid cannot overflow");
            assert_eq!(sum.checked_sub(right), Ok(left));
        }
    }
}
