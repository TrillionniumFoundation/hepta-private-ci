use super::*;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 32;

fn checked<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn path() -> RecursiveUtilityPath {
    let digest = Digest32::of_bytes(b"frozen-context");
    RecursiveUtilityPath {
        objective_digest: digest,
        episode_digest: digest,
        coefficient_digest: digest,
        units_digest: digest,
        terminal_outcome_digest: digest,
        terminal: FixedQ32::ONE,
        lower: FixedQ32::from_raw(-8 * Q),
        upper: FixedQ32::from_raw(8 * Q),
        events: vec![
            UtilityEvent {
                sequence: 1,
                event_digest: Digest32::of_bytes(b"event-1"),
                preference_digest: digest,
                instant: FixedQ32::from_raw(Q / 2),
                discount: FixedQ32::from_raw(3_435_973_837),
            },
            UtilityEvent {
                sequence: 2,
                event_digest: Digest32::of_bytes(b"event-2"),
                preference_digest: digest,
                instant: FixedQ32::from_raw(Q / 4),
                discount: FixedQ32::from_raw(3_435_973_837),
            },
        ],
    }
}

#[test]
fn reproduces_ndu_gv_001_exact_q32_backward_values() {
    let receipt = checked(evaluate_recursive_utility(&path()));
    assert_eq!(
        receipt.values.iter().map(|v| v.raw()).collect::<Vec<_>>(),
        vec![5_755_256_177, 4_509_715_661, Q]
    );
    assert_eq!(receipt.projection_count, 0);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn replay_is_exact_and_input_is_immutable() {
    let input = path();
    let original = input.clone();
    assert_eq!(
        evaluate_recursive_utility(&input),
        evaluate_recursive_utility(&original)
    );
    assert_eq!(input, original);
}

#[test]
fn zero_discount_discards_continuation() {
    let mut input = path();
    for event in &mut input.events {
        event.discount = FixedQ32::ZERO;
    }
    let receipt = checked(evaluate_recursive_utility(&input));
    assert_eq!(
        receipt.values,
        vec![
            FixedQ32::from_raw(Q / 2),
            FixedQ32::from_raw(Q / 4),
            FixedQ32::ONE
        ]
    );
}

#[test]
fn unit_discount_is_allowed_only_as_finite_horizon_arithmetic() {
    let mut input = path();
    for event in &mut input.events {
        event.discount = FixedQ32::ONE;
    }
    let receipt = checked(evaluate_recursive_utility(&input));
    assert_eq!(receipt.values[0], FixedQ32::from_raw(7 * Q / 4));
}

#[test]
fn negative_utility_uses_signed_rounding() {
    let mut input = path();
    input.terminal = FixedQ32::from_raw(-Q);
    for event in &mut input.events {
        event.instant = FixedQ32::from_raw(-event.instant.raw());
    }
    let receipt = checked(evaluate_recursive_utility(&input));
    assert_eq!(receipt.values[0], FixedQ32::from_raw(-5_755_256_177));
}

#[test]
fn utility_projection_is_explicit_and_counted() {
    let mut input = path();
    input.upper = FixedQ32::ONE;
    let receipt = checked(evaluate_recursive_utility(&input));
    assert_eq!(receipt.values, vec![FixedQ32::ONE; 3]);
    assert_eq!(receipt.projection_count, 2);
}

#[test]
fn missing_outcome_or_context_never_becomes_zero_reward() {
    let mut input = path();
    input.terminal_outcome_digest = Digest32::ZERO;
    assert_eq!(
        evaluate_recursive_utility(&input),
        Err(RecursiveUtilityError::MissingDigest)
    );
}

#[test]
fn horizon_is_bounded() {
    let mut input = path();
    input.events.clear();
    assert_eq!(
        evaluate_recursive_utility(&input),
        Err(RecursiveUtilityError::Horizon)
    );
    input.events = vec![path().events[0].clone(); 513];
    assert_eq!(
        evaluate_recursive_utility(&input),
        Err(RecursiveUtilityError::Horizon)
    );
}

#[test]
fn order_and_event_identity_are_validated() {
    let mut input = path();
    input.events.reverse();
    assert_eq!(
        evaluate_recursive_utility(&input),
        Err(RecursiveUtilityError::Sequence)
    );
    input = path();
    input.events[1].event_digest = input.events[0].event_digest;
    assert_eq!(
        evaluate_recursive_utility(&input),
        Err(RecursiveUtilityError::DuplicateEvent)
    );
}

#[test]
fn malformed_numerical_domain_is_rejected() {
    let mut input = path();
    input.lower = input.upper;
    assert_eq!(
        evaluate_recursive_utility(&input),
        Err(RecursiveUtilityError::InvalidBounds)
    );
    input = path();
    input.terminal = FixedQ32::from_raw(i64::MAX);
    assert_eq!(
        evaluate_recursive_utility(&input),
        Err(RecursiveUtilityError::InvalidBounds)
    );
    for raw in [-1, Q + 1] {
        input = path();
        input.events[0].discount = FixedQ32::from_raw(raw);
        assert_eq!(
            evaluate_recursive_utility(&input),
            Err(RecursiveUtilityError::InvalidDiscount)
        );
    }
}

#[test]
fn wide_intermediate_projection_does_not_overflow_i64() {
    let mut input = path();
    input.lower = FixedQ32::from_raw(i64::MIN);
    input.upper = FixedQ32::from_raw(i64::MAX);
    input.terminal = input.upper;
    for event in &mut input.events {
        event.instant = input.upper;
        event.discount = FixedQ32::ONE;
    }
    let receipt = checked(evaluate_recursive_utility(&input));
    assert_eq!(receipt.values, vec![input.upper; 3]);
    assert_eq!(receipt.projection_count, 2);
}

#[test]
fn actual_numbers_and_preference_revision_are_digest_bound() {
    let mut input = path();
    let original = checked(evaluate_recursive_utility(&input));
    input.events[0].instant = FixedQ32::from_raw(Q / 2 + 1);
    assert_ne!(
        checked(evaluate_recursive_utility(&input)).evidence_digest,
        original.evidence_digest
    );
    input = path();
    input.events[0].preference_digest = Digest32::of_bytes(b"other-preference");
    assert_ne!(
        checked(evaluate_recursive_utility(&input)).evidence_digest,
        original.evidence_digest
    );
}
