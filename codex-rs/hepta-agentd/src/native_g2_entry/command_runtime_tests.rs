use super::block_on_original;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::future::Future;
use std::marker::PhantomPinned;
use std::panic::AssertUnwindSafe;
use std::pin::Pin;
use std::task::Context;
use std::task::Poll;
use tokio::runtime::Handle;
use tokio::runtime::Runtime;
use tokio::runtime::RuntimeFlavor;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
enum ActiveContext {
    #[default]
    Absent,
    CurrentThread,
    MultiThread,
    Other,
}

fn current_context() -> ActiveContext {
    match Handle::try_current().map(|handle| handle.runtime_flavor()) {
        Ok(RuntimeFlavor::CurrentThread) => ActiveContext::CurrentThread,
        Ok(RuntimeFlavor::MultiThread) => ActiveContext::MultiThread,
        Ok(_) => ActiveContext::Other,
        Err(_) => ActiveContext::Absent,
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
enum Reentry {
    #[default]
    NoHandle,
    Allowed,
    Rejected,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Mode {
    Ready,
    Error,
    PollPanic,
    DropPanic,
    Pending,
}

#[derive(Clone, Copy)]
enum Route {
    Original,
    SharedPoll,
}

#[derive(Clone, Copy)]
enum OuterContext {
    Absent,
    ForeignHandle,
}

#[derive(Clone, Copy)]
enum Scheduler {
    CurrentThread,
    MultiThread,
}

fn runtime(scheduler: Scheduler) -> std::io::Result<Runtime> {
    match scheduler {
        Scheduler::CurrentThread => tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build(),
        Scheduler::MultiThread => tokio::runtime::Builder::new_multi_thread()
            .worker_threads(/* val */ 1)
            .enable_all()
            .build(),
    }
}

fn foreign_runtime(scheduler: Scheduler) -> std::io::Result<Runtime> {
    runtime(match scheduler {
        Scheduler::CurrentThread => Scheduler::MultiThread,
        Scheduler::MultiThread => Scheduler::CurrentThread,
    })
}

#[derive(Default)]
struct Events {
    polls: Cell<usize>,
    drops: Cell<usize>,
    context_on_drop: Cell<ActiveContext>,
    reentry: Cell<Reentry>,
    sequence: Cell<usize>,
    future_drop_order: Cell<usize>,
    output_drops: Cell<usize>,
    output_drop_order: Cell<usize>,
    ready: Cell<usize>,
    first_poll_address: Cell<usize>,
    moved_while_pinned: Cell<bool>,
}

struct Output<'a> {
    events: &'a Events,
    value: Result<usize, &'static str>,
}

impl Drop for Output<'_> {
    fn drop(&mut self) {
        let order = self.events.sequence.get() + 1;
        self.events.sequence.set(order);
        self.events.output_drop_order.set(order);
        self.events
            .output_drops
            .set(self.events.output_drops.get() + 1);
    }
}

struct Probe<'a, const N: usize> {
    events: &'a Events,
    mode: Mode,
    expected_context: ActiveContext,
    _padding: [u8; N],
    _pinned: PhantomPinned,
}

impl<'a, const N: usize> Future for Probe<'a, N> {
    type Output = Output<'a>;

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.as_ref().get_ref();
        assert_eq!(current_context(), this.expected_context);
        let address = std::ptr::from_ref(this) as usize;
        if this.events.first_poll_address.get() == 0 {
            this.events.first_poll_address.set(address);
        } else if this.events.first_poll_address.get() != address {
            this.events.moved_while_pinned.set(/* val */ true);
        }
        let previous = this.events.polls.get();
        this.events.polls.set(previous + 1);
        if this.mode == Mode::Pending {
            return Poll::Pending;
        }
        if previous == 0 {
            context.waker().wake_by_ref();
            return Poll::Pending;
        }
        assert!(this.mode != Mode::PollPanic, "intentional poll panic");
        this.events.ready.set(this.events.ready.get() + 1);
        Poll::Ready(Output {
            events: this.events,
            value: if this.mode == Mode::Error {
                Err("probe-error")
            } else {
                Ok(17)
            },
        })
    }
}

impl<const N: usize> Drop for Probe<'_, N> {
    fn drop(&mut self) {
        let address = std::ptr::from_ref(self) as usize;
        let first_poll = self.events.first_poll_address.get();
        if first_poll != 0 && first_poll != address {
            self.events.moved_while_pinned.set(/* val */ true);
        }
        self.events.context_on_drop.set(current_context());
        let reentry = match Handle::try_current() {
            Err(_) => Reentry::NoHandle,
            Ok(handle) => {
                let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
                    handle.block_on(std::future::ready(()));
                }));
                if result.is_ok() {
                    Reentry::Allowed
                } else {
                    Reentry::Rejected
                }
            }
        };
        self.events.reentry.set(reentry);
        let order = self.events.sequence.get() + 1;
        self.events.sequence.set(order);
        self.events.future_drop_order.set(order);
        self.events.drops.set(self.events.drops.get() + 1);
        assert!(
            self.mode != Mode::DropPanic,
            "intentional future-drop panic"
        );
    }
}

#[derive(Debug, Eq, PartialEq)]
enum Completion {
    Returned(Result<usize, &'static str>),
    Panicked,
    TimedOut,
}

#[derive(Debug, Eq, PartialEq)]
struct Observation {
    completion: Completion,
    context_on_drop: ActiveContext,
    reentry: Reentry,
    future_drops: usize,
    ready: usize,
    future_drop_order: usize,
    output_drops: usize,
    output_drop_order: usize,
}

fn observation(events: &Events, completion: Completion) -> Observation {
    assert_eq!(events.drops.get(), 1);
    assert!(!events.moved_while_pinned.get());
    assert_eq!(events.future_drop_order.get(), 1);
    Observation {
        completion,
        context_on_drop: events.context_on_drop.get(),
        reentry: events.reentry.get(),
        future_drops: events.drops.get(),
        ready: events.ready.get(),
        future_drop_order: events.future_drop_order.get(),
        output_drops: events.output_drops.get(),
        output_drop_order: events.output_drop_order.get(),
    }
}

fn probe<'a, const N: usize>(events: &'a Events, mode: Mode, runtime: &Runtime) -> Probe<'a, N> {
    let expected_context = match runtime.handle().runtime_flavor() {
        RuntimeFlavor::CurrentThread => ActiveContext::CurrentThread,
        RuntimeFlavor::MultiThread => ActiveContext::MultiThread,
        _ => ActiveContext::Other,
    };
    Probe {
        events,
        mode,
        expected_context,
        _padding: [0; N],
        _pinned: PhantomPinned,
    }
}

fn drive<F: Future>(runtime: &Runtime, future: F, route: Route) -> F::Output {
    match route {
        Route::Original => runtime.block_on(future),
        Route::SharedPoll => block_on_original(runtime, future),
    }
}

fn complete<const N: usize>(runtime: &Runtime, mode: Mode, route: Route) -> Observation {
    let outer = current_context();
    let events = Events::default();
    let future = probe::<N>(&events, mode, runtime);
    let result = std::panic::catch_unwind(AssertUnwindSafe(|| drive(runtime, future, route)));
    let completion = match result {
        Ok(output) => {
            assert_eq!(events.drops.get(), 1);
            assert_eq!(events.output_drops.get(), 0);
            let value = output.value;
            drop(output);
            Completion::Returned(value)
        }
        Err(_) => Completion::Panicked,
    };
    assert_eq!(current_context(), outer);
    assert_eq!(events.polls.get(), 2);
    match mode {
        Mode::Ready | Mode::Error => {
            let value = if mode == Mode::Error {
                Err("probe-error")
            } else {
                Ok(17)
            };
            assert_eq!(completion, Completion::Returned(value));
            assert_eq!(events.output_drops.get(), 1);
            assert_eq!(events.output_drop_order.get(), 2);
        }
        Mode::PollPanic => {
            assert_eq!(completion, Completion::Panicked);
            assert_eq!(events.output_drops.get(), 0);
        }
        Mode::DropPanic => {
            assert_eq!(completion, Completion::Panicked);
            // The original return-place cleanup can leave Output undropped
            // when F::drop panics. Compare to its actual behavior below.
        }
        Mode::Pending => unreachable!("pending futures use the timeout case"),
    }
    observation(&events, completion)
}

fn cancel<const N: usize>(runtime: &Runtime, route: Route) -> Observation {
    let outer = current_context();
    let events = Events::default();
    let future = probe::<N>(&events, Mode::Pending, runtime);
    let timeout = {
        let _context = runtime.enter();
        tokio::time::timeout(std::time::Duration::from_millis(1), future)
    };
    let result = drive(runtime, timeout, route);
    assert!(result.is_err());
    drop(result);
    assert_eq!(current_context(), outer);
    // The timer may cause a different number of polls; both paths must poll
    // the still-pending future and drop it exactly once under the same guards.
    assert!(events.polls.get() >= 1);
    assert_eq!(events.ready.get(), 0);
    assert_eq!(events.output_drops.get(), 0);
    observation(&events, Completion::TimedOut)
}

fn reject_nested<const N: usize>(runtime: &Runtime, route: Route) -> Observation {
    let outer = current_context();
    let events = Events::default();
    let future = probe::<N>(&events, Mode::Ready, runtime);
    let result = std::panic::catch_unwind(AssertUnwindSafe(|| drive(runtime, future, route)));
    assert!(result.is_err());
    assert_eq!(current_context(), outer);
    assert_eq!(events.polls.get(), 0);
    assert_eq!(events.ready.get(), 0);
    assert_eq!(events.output_drops.get(), 0);
    observation(&events, Completion::Panicked)
}

#[test]
fn completion_and_unwind_keep_the_original_drop_context() -> Result<(), Box<dyn std::error::Error>>
{
    for scheduler in [Scheduler::CurrentThread, Scheduler::MultiThread] {
        let active = runtime(scheduler)?;
        let foreign = foreign_runtime(scheduler)?;
        for context in [OuterContext::Absent, OuterContext::ForeignHandle] {
            let _outer = match context {
                OuterContext::Absent => None,
                OuterContext::ForeignHandle => Some(foreign.enter()),
            };
            for mode in [Mode::Ready, Mode::Error, Mode::PollPanic, Mode::DropPanic] {
                assert_eq!(
                    complete::<0>(&active, mode, Route::SharedPoll),
                    complete::<0>(&active, mode, Route::Original),
                );
                assert_eq!(
                    complete::<16_500>(&active, mode, Route::SharedPoll),
                    complete::<16_500>(&active, mode, Route::Original),
                );
            }
        }
    }
    Ok(())
}

#[test]
fn pending_cancellation_keeps_the_original_drop_context() -> Result<(), Box<dyn std::error::Error>>
{
    for scheduler in [Scheduler::CurrentThread, Scheduler::MultiThread] {
        let active = runtime(scheduler)?;
        let foreign = foreign_runtime(scheduler)?;
        for context in [OuterContext::Absent, OuterContext::ForeignHandle] {
            let _outer = match context {
                OuterContext::Absent => None,
                OuterContext::ForeignHandle => Some(foreign.enter()),
            };
            assert_eq!(
                cancel::<0>(&active, Route::SharedPoll),
                cancel::<0>(&active, Route::Original),
            );
            assert_eq!(
                cancel::<16_500>(&active, Route::SharedPoll),
                cancel::<16_500>(&active, Route::Original),
            );
        }
    }
    Ok(())
}

#[test]
fn runtime_entry_rejection_keeps_the_original_drop_context()
-> Result<(), Box<dyn std::error::Error>> {
    for scheduler in [Scheduler::CurrentThread, Scheduler::MultiThread] {
        let active = runtime(scheduler)?;
        let foreign = foreign_runtime(scheduler)?;
        foreign.block_on(async {
            assert_eq!(
                reject_nested::<0>(&active, Route::SharedPoll),
                reject_nested::<0>(&active, Route::Original),
            );
            assert_eq!(
                reject_nested::<16_500>(&active, Route::SharedPoll),
                reject_nested::<16_500>(&active, Route::Original),
            );
        });
    }
    Ok(())
}
