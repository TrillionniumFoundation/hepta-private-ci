use super::passes_99_at_95;

#[test]
fn exact_zero_failure_boundary_requires_more_than_two_hundred_families() {
    assert!(!passes_99_at_95(/*good*/ 200, /*total*/ 200));
    assert!(!passes_99_at_95(/*good*/ 298, /*total*/ 298));
    assert!(passes_99_at_95(/*good*/ 299, /*total*/ 299));
    assert!(passes_99_at_95(/*good*/ 360, /*total*/ 360));
}

#[test]
fn point_precision_is_not_a_lower_confidence_bound() {
    assert!(!passes_99_at_95(/*good*/ 357, /*total*/ 360));
    assert!(!passes_99_at_95(/*good*/ 990, /*total*/ 1000));
    assert!(passes_99_at_95(/*good*/ 999, /*total*/ 1000));
}

#[test]
fn reject_vacuous_inconsistent_and_unbounded_samples() {
    assert!(!passes_99_at_95(/*good*/ 0, /*total*/ 0));
    assert!(!passes_99_at_95(/*good*/ 101, /*total*/ 100));
    assert!(!passes_99_at_95(/*good*/ 20_001, /*total*/ 20_001));
    assert!(!passes_99_at_95(/*good*/ 0, /*total*/ 360));
}

#[test]
fn more_failures_cannot_improve_the_decision() {
    let mut rejected = false;
    for good in (0..=1000).rev() {
        let accepted = passes_99_at_95(good, /*total*/ 1000);
        assert!(!(rejected && accepted));
        rejected |= !accepted;
    }
}
