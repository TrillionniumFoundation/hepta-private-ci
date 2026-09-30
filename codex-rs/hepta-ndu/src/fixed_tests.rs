use std::fmt::Debug;

use codex_hepta_types::FixedQ32;
use pretty_assertions::assert_eq;

use super::mul_q32_ties_even;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

#[test]
fn multiplication_rounds_half_to_even_for_positive_and_negative_values() {
    let one_raw = FixedQ32::from_raw(1);
    let half = FixedQ32::from_raw(1_i64 << 31);
    assert_eq!(must(mul_q32_ties_even(one_raw, half)), FixedQ32::ZERO);

    let three_raw = FixedQ32::from_raw(3);
    assert_eq!(
        must(mul_q32_ties_even(three_raw, half)),
        FixedQ32::from_raw(2)
    );
    assert_eq!(
        must(mul_q32_ties_even(FixedQ32::from_raw(-3), half)),
        FixedQ32::from_raw(-2)
    );
}

#[test]
fn signed_q32_matches_independent_euclidean_integer_oracle() {
    let values = [
        i64::MIN,
        i64::MIN + 1,
        -(1_i64 << 33),
        -(1_i64 << 32),
        -3,
        -1,
        0,
        1,
        3,
        (1_i64 << 31) - 1,
        1_i64 << 31,
        (1_i64 << 31) + 1,
        1_i64 << 32,
        i64::MAX - 1,
        i64::MAX,
    ];
    let scale = 1_i128 << 32;
    for left in values {
        for right in values {
            let product = i128::from(left) * i128::from(right);
            // Signed floor division, independently of the implementation's
            // sign/magnitude rounding. Ties choose an even signed neighbor.
            let floor = product.div_euclid(scale);
            let remainder = product.rem_euclid(scale);
            let rounded = floor
                + i128::from(2 * remainder > scale || (2 * remainder == scale && floor % 2 != 0));
            let actual = mul_q32_ties_even(FixedQ32::from_raw(left), FixedQ32::from_raw(right));
            match i64::try_from(rounded) {
                Ok(expected) => assert_eq!(must(actual).raw(), expected),
                Err(_) => assert_eq!(actual, Err(crate::NduError::Arithmetic)),
            }
        }
    }
}
