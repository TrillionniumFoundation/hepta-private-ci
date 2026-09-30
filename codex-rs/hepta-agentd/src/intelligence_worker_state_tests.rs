use std::sync::Barrier;

use super::*;

#[derive(Debug, Eq, PartialEq)]
struct LifecycleCounters {
    active: u64,
    timed_out_active: u64,
    timeouts: u64,
    late_completions: u64,
    permit_observations: u64,
}

fn counters(telemetry: &AgentdIntelligenceTelemetryV1) -> LifecycleCounters {
    let snapshot = telemetry.snapshot();
    LifecycleCounters {
        active: snapshot.active_workers,
        timed_out_active: snapshot.timed_out_active_workers,
        timeouts: snapshot.request_timeouts,
        late_completions: snapshot.late_worker_completions,
        permit_observations: snapshot.permit_hold_observations,
    }
}

#[test]
fn timeout_then_completion_balances_the_shared_gauge_once() {
    let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(1));
    let guard = telemetry.worker_started();
    let state = guard.state();
    assert!(state.mark_timed_out());
    assert!(!state.mark_timed_out());
    assert_eq!(
        counters(&telemetry),
        LifecycleCounters {
            active: 1,
            timed_out_active: 1,
            timeouts: 1,
            late_completions: 0,
            permit_observations: 0,
        }
    );
    drop(guard);
    assert!(!state.mark_timed_out());
    assert!(state.finished());
    assert!(state.timed_out());
    assert_eq!(
        counters(&telemetry),
        LifecycleCounters {
            active: 0,
            timed_out_active: 0,
            timeouts: 1,
            late_completions: 1,
            permit_observations: 1,
        }
    );
}

#[test]
fn completion_then_request_timeout_never_creates_an_active_timeout() {
    let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(1));
    let guard = telemetry.worker_started();
    let state = guard.state();
    drop(guard);
    assert!(state.mark_timed_out());
    assert!(!state.mark_timed_out());
    assert!(state.finished());
    assert!(state.timed_out());
    assert_eq!(
        counters(&telemetry),
        LifecycleCounters {
            active: 0,
            timed_out_active: 0,
            timeouts: 1,
            late_completions: 0,
            permit_observations: 1,
        }
    );
}

#[test]
fn concurrent_request_and_watchdog_timeouts_are_counted_once() {
    let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(1));
    let guard = telemetry.worker_started();
    let state = guard.state();
    let barrier = Arc::new(Barrier::new(3));
    // Start both observers before the main thread joins the barrier.
    let observers: [_; 2] = std::array::from_fn(|_| {
        let state = Arc::clone(&state);
        let barrier = Arc::clone(&barrier);
        std::thread::spawn(move || {
            barrier.wait();
            state.mark_timed_out()
        })
    });
    barrier.wait();
    let observed = observers
        .into_iter()
        .map(|observer| usize::from(observer.join().expect("timeout observer")))
        .sum::<usize>();
    assert_eq!(observed, 1);
    drop(guard);
    assert_eq!(
        counters(&telemetry),
        LifecycleCounters {
            active: 0,
            timed_out_active: 0,
            timeouts: 1,
            late_completions: 1,
            permit_observations: 1,
        }
    );
}

#[test]
fn racing_timeout_and_completion_leave_only_valid_terminal_accounting() {
    let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(1));
    let guard = telemetry.worker_started();
    let state = guard.state();
    let barrier = Arc::new(Barrier::new(3));
    let timeout_barrier = Arc::clone(&barrier);
    let timeout_state = Arc::clone(&state);
    let timeout_observer = std::thread::spawn(move || {
        timeout_barrier.wait();
        timeout_state.mark_timed_out()
    });
    let completion_barrier = Arc::clone(&barrier);
    let completion = std::thread::spawn(move || {
        completion_barrier.wait();
        drop(guard);
    });
    barrier.wait();
    assert!(timeout_observer.join().expect("timeout observer"));
    completion.join().expect("worker completion");
    assert!(state.finished());
    assert!(state.timed_out());
    let observed = counters(&telemetry);
    assert!(
        [0, 1]
            .map(|late_completions| LifecycleCounters {
                active: 0,
                timed_out_active: 0,
                timeouts: 1,
                late_completions,
                permit_observations: 1,
            })
            .contains(&observed),
        "invalid lifecycle accounting: {observed:?}",
    );
}

#[test]
fn completing_one_worker_preserves_another_workers_timeout_gauge() {
    let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(2));
    let first = telemetry.worker_started();
    let second = telemetry.worker_started();
    assert!(first.state().mark_timed_out());
    assert!(second.state().mark_timed_out());
    drop(first);
    assert_eq!(
        counters(&telemetry),
        LifecycleCounters {
            active: 1,
            timed_out_active: 1,
            timeouts: 2,
            late_completions: 1,
            permit_observations: 1,
        }
    );
    drop(second);
    assert_eq!(
        counters(&telemetry),
        LifecycleCounters {
            active: 0,
            timed_out_active: 0,
            timeouts: 2,
            late_completions: 2,
            permit_observations: 2,
        }
    );
}
