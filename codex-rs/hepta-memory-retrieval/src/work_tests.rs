use std::time::Duration;
use std::time::Instant;

use super::*;

#[test]
fn clones_share_budget_and_cancellation_never_renews_it() {
    let control = RecallWorkControlV1::bounded(Instant::now() + Duration::from_secs(60), 2);
    let other = control.clone();
    assert_eq!(control.checkpoint(), Ok(()));
    assert_eq!(other.checkpoint(), Ok(()));
    assert_eq!(
        control.checkpoint(),
        Err(RecallErrorV1::Interrupted(
            RecallInterruptionV1::WorkLimitExceeded
        ))
    );
    other.cancel();
    assert_eq!(
        control.checkpoint(),
        Err(RecallErrorV1::Interrupted(RecallInterruptionV1::Cancelled))
    );
}

#[test]
fn expired_and_zero_budget_controls_reject_before_work() {
    let expired = RecallWorkControlV1::bounded(Instant::now(), 100);
    assert_eq!(
        expired.checkpoint(),
        Err(RecallErrorV1::Interrupted(
            RecallInterruptionV1::DeadlineExceeded
        ))
    );
    let empty = RecallWorkControlV1::bounded(Instant::now() + Duration::from_secs(60), 0);
    assert_eq!(
        empty.checkpoint(),
        Err(RecallErrorV1::Interrupted(
            RecallInterruptionV1::WorkLimitExceeded
        ))
    );
}
