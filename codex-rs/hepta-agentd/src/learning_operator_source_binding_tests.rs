use super::*;

fn sources(range: std::ops::Range<usize>) -> Vec<Digest32> {
    range
        .map(|value| Digest32::of_bytes(&value.to_be_bytes()))
        .collect()
}

#[test]
fn bounded_source_independence_is_order_independent_and_rejects_actual_overlap() {
    let mut training = sources(0..MAX_FROZEN_SOURCES);
    let mut evaluation = sources(MAX_FROZEN_SOURCES..MAX_FROZEN_SOURCES * 2);
    assert_eq!(
        validate_disjoint_frozen_sources(&training, &evaluation),
        Ok(())
    );
    training.reverse();
    evaluation.rotate_left(17);
    assert_eq!(
        validate_disjoint_frozen_sources(&training, &evaluation),
        Ok(())
    );
    evaluation[100] = training[1000];
    assert_eq!(
        validate_disjoint_frozen_sources(&training, &evaluation),
        Err("training/evaluation source overlap")
    );
    evaluation.reverse();
    training.rotate_left(73);
    assert_eq!(
        validate_disjoint_frozen_sources(&training, &evaluation),
        Err("training/evaluation source overlap")
    );
}

#[test]
fn oversized_or_duplicated_inputs_fail_before_quadratic_work() {
    let training = sources(0..10_000);
    let evaluation = sources(10_000..20_000);
    assert_eq!(
        validate_disjoint_frozen_sources(&training, &evaluation),
        Err("frozen source bounds")
    );
    assert_eq!(
        validate_disjoint_frozen_sources(&[training[0], training[0]], &evaluation[..2]),
        Err("duplicate frozen sources")
    );
}
