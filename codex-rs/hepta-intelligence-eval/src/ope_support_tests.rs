use super::*;

fn must<T>(result: Result<T, OpeError>) -> T {
    result.unwrap_or_else(|error| panic!("bounded support arithmetic must succeed: {error:?}"))
}

fn ratio(evaluation: u64, behavior: u64) -> PropensityRatio {
    PropensityRatio { evaluation, behavior }
}

#[test]
fn original_ratio_and_prefix_bounds_round_outward() {
    let first = must(WeightBounds::UNIT.advance(ratio(/*evaluation*/ 1, /*behavior*/ 3)));
    assert_eq!(first, WeightBounds { lower: SCALE / 3, upper: SCALE / 3 + 1 });
    assert_eq!(
        must(first.advance(ratio(/*evaluation*/ 3, /*behavior*/ 1))),
        WeightBounds { lower: SCALE - 1, upper: SCALE + 2 }
    );
}

#[test]
fn certificates_distinguish_margin_failure_and_numerical_uncertainty() {
    let mut exact = SupportAccumulator::default();
    must(exact.add(WeightBounds { lower: SCALE, upper: SCALE }));
    must(exact.add(WeightBounds { lower: 2 * SCALE, upper: 2 * SCALE }));
    assert_eq!(must(exact.certify(SCALE)), SupportCertification::Supported);
    assert_eq!(must(exact.certify(2 * SCALE)), SupportCertification::RequiresEquality);
    assert_eq!(must(exact.certify(2 * SCALE - 1)), SupportCertification::Insufficient);
    let mut uncertain = SupportAccumulator::default();
    let fractional = must(WeightBounds::UNIT.advance(ratio(/*evaluation*/ 2, /*behavior*/ 3)));
    for _ in 0..400 {
        must(uncertain.add(fractional));
    }
    assert_eq!(must(uncertain.certify(399 * SCALE)), SupportCertification::Supported);
    assert_eq!(must(uncertain.certify(400 * SCALE - 1)), SupportCertification::Unresolved);
    assert_eq!(must(uncertain.certify(400 * SCALE)), SupportCertification::RequiresEquality);
    assert_eq!(must(uncertain.certify(401 * SCALE)), SupportCertification::Insufficient);
}

#[test]
fn a_wide_upper_ess_bound_is_uncertainty_without_scaled_overflow() {
    let mut uncertain = SupportAccumulator::default();
    for index in 0..4096 {
        must(uncertain.add(WeightBounds { lower: i128::from(index == 0), upper: 50 * SCALE }));
    }
    assert_eq!(must(uncertain.certify(SCALE)), SupportCertification::Unresolved);
}

#[test]
fn equality_uses_math_ratios_and_can_recover_after_unequal_prefixes() {
    assert!(ratio(/*evaluation*/ 2, /*behavior*/ 3).same_positive_ratio(ratio(/*evaluation*/ 4, /*behavior*/ 6)));
    assert!(!ratio(/*evaluation*/ 0, /*behavior*/ 3).same_positive_ratio(ratio(/*evaluation*/ 0, /*behavior*/ 6)));
    let mut products = RatioProductEquality::new();
    must(products.advance(ratio(/*evaluation*/ 1, /*behavior*/ 3), ratio(/*evaluation*/ 1, /*behavior*/ 1)));
    assert!(!products.equal_positive());
    must(products.advance(ratio(/*evaluation*/ 3, /*behavior*/ 1), ratio(/*evaluation*/ 1, /*behavior*/ 1)));
    assert!(products.equal_positive());
}

#[test]
fn full_horizon_cross_products_fit_the_fixed_limb_budget() {
    let unit = ratio(/*evaluation*/ 1 << 32, /*behavior*/ 1 << 32);
    let mut products = RatioProductEquality::new();
    for _ in 0..128 {
        must(products.advance(unit, unit));
        assert!(products.equal_positive());
    }
    assert_eq!(products.left.len, PRODUCT_LIMBS);
    assert_eq!(products.left.limbs[PRODUCT_LIMBS - 1], 1);
    assert_eq!(products.advance(unit, unit), Err(OpeError::Arithmetic));
}
