use crate::contract::CreditRule;
use crate::contract::Phase;
use crate::contract::Request;
use crate::native::Receipt;
use crate::settlement::Body;
use crate::settlement::Observation;
use crate::settlement::Terminal;
use crate::settlement::validate_outcome;

fn request() -> Request {
    serde_json::from_str(include_str!("fixture.json")).expect("typed fixture")
}

#[test]
fn initial_refractory_is_not_an_unobserved_spike() {
    let mut r = request();
    assert!(r.validate(None).is_ok());
    r.checkpoint.level = r.config.model.reset_gap;
    r.checkpoint.phase = Phase::Refractory { until_us: 50 };
    assert_eq!(r.validate(None), Err("invalid initial state".to_owned()));
}

#[test]
fn cancellation_sample_is_fixed_and_not_a_price() {
    let mut r = request();
    r.config.model.cancel_rate = 0.5;
    r.checkpoint.cancellation.at_us = Some(50);
    assert!(r.validate(None).is_err());
    r.checkpoint.cancellation.counter = 1;
    assert!(r.validate(None).is_ok());
    let mut next = r.clone();
    next.sequence = 2;
    next.owner_monotonic_us = 2;
    next.checkpoint.time_us = 50;
    next.checkpoint.rng_counter = 1;
    assert!(next.validate(Some(&r)).is_ok());
    next.checkpoint.cancellation.at_us = Some(51);
    assert_eq!(
        next.validate(Some(&r)),
        Err("immutable model/cancel identity or clock changed".to_owned())
    );
}

#[test]
fn refractory_event_order_and_expiry_are_exact() {
    let r = request();
    let mut next = r.clone();
    next.sequence = 2;
    next.owner_monotonic_us = 2;
    next.hit_times_us = vec![5];
    next.checkpoint.time_us = 10;
    next.checkpoint.events = 1;
    next.checkpoint.level = 0.9;
    next.checkpoint.phase = Phase::Refractory { until_us: 60005 };
    assert!(next.validate(Some(&r)).is_ok());
    next.hit_times_us.push(10);
    next.checkpoint.events = 2;
    assert_eq!(
        next.validate(Some(&r)),
        Err("event order/refractory/cancellation violated".to_owned())
    );
}

#[test]
fn unchanged_time_cannot_advance_the_rng() {
    let r = request();
    let mut next = r.clone();
    next.sequence = 2;
    next.owner_monotonic_us = 2;
    next.checkpoint.rng_counter = 1;
    assert_eq!(
        next.validate(Some(&r)),
        Err("event count or phase continuation changed".to_owned())
    );
}

#[test]
fn projected_price_has_finite_bounds_for_both_actions() {
    let rule: CreditRule = request().config.credit;
    let mut price = (rule.initial_micros, 0);
    for _ in 0..256 {
        price = rule.next(price.0, price.1, 1, 0);
    }
    assert_eq!(price, (rule.maximum_micros, 0));
    for _ in 0..256 {
        price = rule.next(price.0, price.1, 0, 1_000_000);
    }
    assert_eq!(price, (0, 0));
}

#[test]
fn zero_elapsed_wait_cannot_reduce_price_or_fraction() {
    let rule = request().config.credit;
    assert_eq!(rule.next(100, 3_999_999, 0, 0), (100, 3_999_999));
}

#[test]
fn physical_time_partition_keeps_every_fraction() {
    let mut rule = request().config.credit;
    rule.step_micros = 7;
    rule.target_quarters = 3;
    let mut partitioned = (1000, 1234567);
    for elapsed in [1, 2, 7, 11] {
        partitioned = rule.next(partitioned.0, partitioned.1, 0, elapsed);
    }
    assert_eq!(partitioned, rule.next(1000, 1234567, 0, 21));
    rule.maximum_read_price_micros = partitioned.0;
    assert!(!rule.permits(partitioned.0, partitioned.1));
    rule.step_micros = 1_000_000_000;
    assert_eq!(
        rule.next(1_000_000_000, 0, 0, crate::contract::DAY_US),
        (0, 0)
    );
}

#[test]
fn self_consistent_hash_does_not_override_outcome_semantics() {
    let r = request();
    let mut body = Body {
        request: r,
        request_digest: "1".repeat(64),
        data_root: "/unused".to_owned(),
        native: Receipt {
            sequence: 1,
            before: "0".repeat(64),
            after: "2".repeat(64),
            abstain: false,
        },
        attempts: 1,
        total_spent: 1,
        price_before_micros: 0,
        price_after_micros: 800000,
        price_before_residue: 0,
        price_after_residue: 0,
        admission_price_micros: 0,
        admission_price_residue: 0,
        terminal: None,
        observation: Observation::Read {
            source_digest: "3".repeat(64),
            bytes: 2,
            answer: Some("ok".to_owned()),
        },
    };
    assert!(validate_outcome(&body, 0).is_ok());
    body.request.action = crate::contract::Action::Stop;
    body.terminal = Some(Terminal::Stopped);
    assert_eq!(
        validate_outcome(&body, 0),
        Err("guarded outcome contradicts action/accounting".to_owned())
    );
    body.attempts = 0;
    body.observation = Observation::None;
    assert!(validate_outcome(&body, 0).is_ok());
}

#[test]
fn endpoint_read_cannot_spend_an_expired_idle_allowance() {
    let mut rule = request().config.credit;
    rule.step_micros = 1_000_000;
    rule.target_quarters = 4;
    for prior in [0, 1_500_000] {
        let idle = rule.next(prior, 0, 0, 1_000_000);
        assert_eq!(
            rule.next(prior, 0, 1, 1_000_000),
            rule.next(idle.0, idle.1, 1, 0)
        );
    }
    assert_eq!(rule.next(0, 0, 1, 1_000_000), (1_000_000, 0));
}

#[test]
fn refractory_release_requires_positive_active_time_before_next_hit() {
    let mut prior = request();
    prior.checkpoint.time_us = 10;
    prior.checkpoint.level = 0.9;
    prior.checkpoint.events = 1;
    prior.checkpoint.rng_counter = 1;
    prior.checkpoint.phase = Phase::Refractory { until_us: 60005 };
    let mut next = prior.clone();
    next.sequence = 2;
    next.owner_monotonic_us = 2;
    next.checkpoint.time_us = 60005;
    next.checkpoint.events = 2;
    next.hit_times_us = vec![60005];
    next.checkpoint.phase = Phase::Refractory { until_us: 120005 };
    assert_eq!(
        next.validate(Some(&prior)),
        Err("event order/refractory/cancellation violated".to_owned())
    );
}
