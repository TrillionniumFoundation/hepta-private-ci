//! A monotonic per-poll admission gate, without a timer or trust authority.

use std::future::Future;
use std::future::poll_fn;
use std::task::Poll;
use std::time::Instant;

/// Poll `future` only while the monotonic `deadline` has not expired.
///
/// Every poll checks the same deadline before polling the inner future. A
/// completed result is returned unchanged in `Some`; an expired poll returns
/// `None` without polling the inner future.
///
/// This wrapper has no timer and does not wake itself at the deadline. Callers
/// must retain their timer (for example, `timeout_at`) for wakeup and cleanup.
/// It cannot preempt a running synchronous poll, future construction or a
/// blocking destructor. It is not a clock or authority for signed grants.
pub fn guard_future_before_deadline<F>(
    deadline: Instant,
    future: F,
) -> impl Future<Output = Option<F::Output>>
where
    F: Future,
{
    guard_future_before_deadline_with_clock(deadline, future, Instant::now)
}

// Private clock injection is solely for deterministic future-poll unit tests.
// The public production entry always uses std's monotonic Instant::now.
async fn guard_future_before_deadline_with_clock<F, C>(
    deadline: Instant,
    future: F,
    mut clock: C,
) -> Option<F::Output>
where
    F: Future,
    C: FnMut() -> Instant,
{
    let mut future = std::pin::pin!(future);
    poll_fn(move |context| {
        if clock() >= deadline {
            return Poll::Ready(None);
        }
        future.as_mut().poll(context).map(Some)
    })
    .await
}

#[cfg(test)]
#[path = "deadline_guard_tests.rs"]
mod tests;
