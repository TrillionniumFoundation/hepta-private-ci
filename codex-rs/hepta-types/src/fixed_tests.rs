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
fn arithmetic_boundaries_reject_overflow_and_division_by_zero() {
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
fn explicit_toward_zero_methods_match_legacy_compatibility_methods() {
    let half = FixedQ32::from_raw(1_i64 << 31);
    for raw in [-7, -1, 1, 7] {
        let value = FixedQ32::from_raw(raw);
        assert_eq!(value.checked_mul(half), value.checked_mul_toward_zero(half));
        assert_eq!(value.checked_div(half), value.checked_div_toward_zero(half));
    }
    assert_eq!(
        FixedQ32::arithmetic_profile_id(),
        FIXED_Q32_ARITHMETIC_PROFILE_V1
    );
}

#[test]
fn checked_arithmetic_rejects_overflow_and_zero_division() {
    assert_eq!(
        FixedQ32::from_raw(i64::MAX).checked_add(FixedQ32::ONE),
        Err(FixedQ32Error::Overflow)
    );
    assert_eq!(
        FixedQ32::ONE.checked_div(FixedQ32::ZERO),
        Err(FixedQ32Error::DivisionByZero)
    );
}
