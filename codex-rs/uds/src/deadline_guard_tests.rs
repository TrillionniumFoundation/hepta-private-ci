use super::guard_future_before_deadline_with_clock;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::future::Future;
use std::pin::Pin;
use std::rc::Rc;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;
use std::time::Duration;
use std::time::Instant;

#[derive(Clone, Copy)]
enum Behavior {
    Ready { value: usize },
    Pending,
}

struct ObservedFuture {
    behavior: Behavior,
    polls: Rc<Cell<usize>>,
    drops: Rc<Cell<usize>>,
}

impl Future for ObservedFuture {
    type Output = usize;

    fn poll(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Self::Output> {
        self.polls.set(self.polls.get() + 1);
        match self.behavior {
            Behavior::Ready { value } => Poll::Ready(value),
            Behavior::Pending => Poll::Pending,
        }
    }
}

impl Drop for ObservedFuture {
    fn drop(&mut self) {
        self.drops.set(self.drops.get() + 1);
    }
}

fn observed(
    behavior: Behavior,
    polls: &Rc<Cell<usize>>,
    drops: &Rc<Cell<usize>>,
) -> ObservedFuture {
    ObservedFuture {
        behavior,
        polls: Rc::clone(polls),
        drops: Rc::clone(drops),
    }
}

#[test]
fn expired_ready_future_is_dropped_without_being_polled() {
    let deadline = Instant::now();
    let polls = Rc::new(Cell::default());
    let drops = Rc::new(Cell::default());
    let inner = observed(Behavior::Ready { value: 17 }, &polls, &drops);
    let mut guarded = std::pin::pin!(guard_future_before_deadline_with_clock(
        deadline,
        inner,
        move || deadline,
    ));
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(guarded.as_mut().poll(&mut context), Poll::Ready(None));
    assert_eq!(polls.get(), 0);
    assert_eq!(drops.get(), 1);
}

#[test]
fn pending_future_is_not_polled_again_after_deadline_and_is_dropped() {
    let start = Instant::now();
    let deadline = start + Duration::from_secs(/*secs*/ 1);
    let now = Rc::new(Cell::new(start));
    let clock = Rc::clone(&now);
    let polls = Rc::new(Cell::default());
    let drops = Rc::new(Cell::default());
    let inner = observed(Behavior::Pending, &polls, &drops);
    let mut guarded = std::pin::pin!(guard_future_before_deadline_with_clock(
        deadline,
        inner,
        move || clock.get(),
    ));
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(guarded.as_mut().poll(&mut context), Poll::Pending);
    assert_eq!(polls.get(), 1);
    assert_eq!(drops.get(), 0);
    now.set(deadline);
    assert_eq!(guarded.as_mut().poll(&mut context), Poll::Ready(None));
    assert_eq!(polls.get(), 1);
    assert_eq!(drops.get(), 1);
}

#[test]
fn early_completion_preserves_the_original_result() {
    let start = Instant::now();
    let deadline = start + Duration::from_secs(/*secs*/ 1);
    let polls = Rc::new(Cell::default());
    let drops = Rc::new(Cell::default());
    let inner = observed(Behavior::Ready { value: 37 }, &polls, &drops);
    let mut guarded = std::pin::pin!(guard_future_before_deadline_with_clock(
        deadline,
        inner,
        move || start,
    ));
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(guarded.as_mut().poll(&mut context), Poll::Ready(Some(37)));
    assert_eq!(polls.get(), 1);
    assert_eq!(drops.get(), 1);
}

#[test]
fn early_error_result_is_not_reinterpreted_as_expiry() {
    let start = Instant::now();
    let deadline = start + Duration::from_secs(/*secs*/ 1);
    let mut guarded = std::pin::pin!(guard_future_before_deadline_with_clock(
        deadline,
        std::future::ready(Err::<(), _>("inner error")),
        move || start,
    ));
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(
        guarded.as_mut().poll(&mut context),
        Poll::Ready(Some(Err("inner error")))
    );
}

#[test]
fn external_cancellation_drops_the_pending_inner_future() {
    let start = Instant::now();
    let deadline = start + Duration::from_secs(/*secs*/ 1);
    let polls = Rc::new(Cell::default());
    let drops = Rc::new(Cell::default());
    {
        let inner = observed(Behavior::Pending, &polls, &drops);
        let mut guarded = std::pin::pin!(guard_future_before_deadline_with_clock(
            deadline,
            inner,
            move || start,
        ));
        let mut context = Context::from_waker(Waker::noop());
        assert_eq!(guarded.as_mut().poll(&mut context), Poll::Pending);
        assert_eq!(polls.get(), 1);
        assert_eq!(drops.get(), 0);
    }
    assert_eq!(polls.get(), 1);
    assert_eq!(drops.get(), 1);
}

#[test]
fn public_monotonic_entry_rejects_expired_ready_future_before_polling() {
    let polls = Rc::new(Cell::default());
    let drops = Rc::new(Cell::default());
    let inner = observed(Behavior::Ready { value: 53 }, &polls, &drops);
    let deadline = Instant::now();
    let mut guarded = std::pin::pin!(crate::guard_future_before_deadline(deadline, inner));
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(guarded.as_mut().poll(&mut context), Poll::Ready(None));
    assert_eq!(polls.get(), 0);
    assert_eq!(drops.get(), 1);
}
