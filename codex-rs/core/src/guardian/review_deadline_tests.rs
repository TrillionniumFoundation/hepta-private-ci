//! Deadline and cancellation admission for Guardian review results.

use std::cell::Cell;
use std::future;
use std::time::Duration;

use pretty_assertions::assert_eq;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::GuardianReviewSessionOutcome;
use super::run_before_review_deadline;
use super::run_before_review_deadline_with_cancel;

struct DropSignal<'a>(&'a Cell<bool>);

impl Drop for DropSignal<'_> {
    fn drop(&mut self) {
        self.0.set(true);
    }
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn result_at_deadline_is_rejected_and_dropped_after_the_same_poll() {
    let deadline = Instant::now() + Duration::from_millis(10);
    let dropped = Cell::new(false);
    let cancel = CancellationToken::new();
    let outcome = run_before_review_deadline_with_cancel(
        deadline,
        /*external_cancel*/ None,
        &cancel,
        async {
            // Polling advance once moves the clock and then yields. Keeping that
            // yield inside this poll makes the result ready in the same poll
            // that crossed the deadline, regardless of select branch order.
            let mut advance = std::pin::pin!(tokio::time::advance(Duration::from_millis(10)));
            assert!(futures::poll!(advance.as_mut()).is_pending());
            assert_eq!(Instant::now(), deadline);
            DropSignal(&dropped)
        },
    )
    .await;

    assert!(matches!(
        outcome,
        Err(GuardianReviewSessionOutcome::TimedOut)
    ));
    assert!(dropped.get(), "a rejected completed result must be dropped");
    assert!(cancel.is_cancelled());
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn result_before_deadline_is_admitted_without_cancelling_review() {
    let deadline = Instant::now() + Duration::from_millis(10);
    let cancel = CancellationToken::new();
    let outcome = run_before_review_deadline_with_cancel(
        deadline,
        /*external_cancel*/ None,
        &cancel,
        async {
            let mut advance = std::pin::pin!(tokio::time::advance(Duration::from_millis(9)));
            assert!(futures::poll!(advance.as_mut()).is_pending());
            assert!(Instant::now() < deadline);
            42
        },
    )
    .await;

    assert_eq!(outcome.expect("result before deadline"), 42);
    assert!(!cancel.is_cancelled());
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn cancellation_during_result_poll_rejects_and_drops_the_result() {
    let external_cancel = CancellationToken::new();
    let cancel = CancellationToken::new();
    let dropped = Cell::new(false);
    let outcome = run_before_review_deadline_with_cancel(
        Instant::now() + Duration::from_secs(1),
        Some(&external_cancel),
        &cancel,
        async {
            external_cancel.cancel();
            DropSignal(&dropped)
        },
    )
    .await;

    assert!(matches!(
        outcome,
        Err(GuardianReviewSessionOutcome::Aborted)
    ));
    assert!(
        dropped.get(),
        "a cancelled completed result must be dropped"
    );
    assert!(cancel.is_cancelled());
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn expired_deadline_drops_the_future_without_polling_it() {
    let polled = Cell::new(false);
    let dropped = Cell::new(false);
    let guard = DropSignal(&dropped);
    let future = async {
        let _guard = guard;
        polled.set(true);
    };
    let outcome = run_before_review_deadline(Instant::now(), None, future).await;

    assert!(matches!(
        outcome,
        Err(GuardianReviewSessionOutcome::TimedOut)
    ));
    assert!(!polled.get());
    assert!(dropped.get());
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn existing_cancellation_drops_the_future_without_polling_it() {
    let external_cancel = CancellationToken::new();
    external_cancel.cancel();
    let polled = Cell::new(false);
    let dropped = Cell::new(false);
    let guard = DropSignal(&dropped);
    let future = async {
        let _guard = guard;
        polled.set(true);
    };
    let outcome = run_before_review_deadline(
        Instant::now() + Duration::from_secs(1),
        Some(&external_cancel),
        future,
    )
    .await;

    assert!(matches!(
        outcome,
        Err(GuardianReviewSessionOutcome::Aborted)
    ));
    assert!(!polled.get());
    assert!(dropped.get());
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn timeout_drops_a_pending_review_and_cancels_its_token() {
    let dropped = Cell::new(false);
    let guard = DropSignal(&dropped);
    let cancel = CancellationToken::new();
    let outcome = run_before_review_deadline_with_cancel(
        Instant::now() + Duration::from_millis(10),
        /*external_cancel*/ None,
        &cancel,
        async {
            let _guard = guard;
            future::pending::<()>().await;
        },
    )
    .await;

    assert!(matches!(
        outcome,
        Err(GuardianReviewSessionOutcome::TimedOut)
    ));
    assert!(dropped.get());
    assert!(cancel.is_cancelled());
}
