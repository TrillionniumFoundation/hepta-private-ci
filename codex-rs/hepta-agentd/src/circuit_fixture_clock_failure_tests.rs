use super::*;
use pretty_assertions::assert_eq;

#[test]
fn successful_clock_reads_preserve_values() -> anyhow::Result<()> {
    let clock = FixtureClock::default();
    assert_eq!(clock.wall_millis_from(|| Ok::<_, ()>(123)), 123);
    assert_eq!(clock.elapsed_micros(Duration::from_micros(456)), 466);
    clock.check()
}

#[test]
fn wall_failure_expires_callback_and_reaches_owner_after_later_success() {
    let owner = FixtureClock::default();
    let callback = owner.clone();
    assert_eq!(callback.wall_millis_from(|| Err::<u64, _>(())), u64::MAX);
    assert_eq!(callback.wall_millis_from(|| Ok::<_, ()>(123)), 123);
    assert!(owner.check().is_err());
    assert!(callback.check().is_err());
}

#[test]
fn elapsed_conversion_overflow_expires_callback_and_reaches_owner() {
    let owner = FixtureClock::default();
    let callback = owner.clone();
    assert_eq!(
        callback.elapsed_micros(Duration::from_secs(u64::MAX)),
        u64::MAX
    );
    assert!(owner.check().is_err());
}

#[test]
fn elapsed_origin_addition_overflow_is_not_a_successful_clock() {
    let clock = FixtureClock::default();
    assert_eq!(
        clock.elapsed_micros(Duration::from_micros(u64::MAX - 9)),
        u64::MAX
    );
    assert!(clock.check().is_err());
}

#[test]
fn first_failure_survives_later_callback_errors() {
    let clock = FixtureClock::default();
    assert_eq!(clock.wall_millis_from(|| Err::<u64, _>(())), u64::MAX);
    assert_eq!(
        clock.elapsed_micros(Duration::from_secs(u64::MAX)),
        u64::MAX
    );
    let result = clock.check();
    assert!(matches!(result, Err(error) if error.to_string() == "fixture wall clock unavailable"));
}
