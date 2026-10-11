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
