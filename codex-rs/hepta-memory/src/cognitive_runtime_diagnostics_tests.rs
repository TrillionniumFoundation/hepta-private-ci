use std::future::Future;
use std::task::Context;
use std::task::Waker;
use std::time::Instant;

use pretty_assertions::assert_eq;

use super::FederationV2Error;
use super::Stage;
use super::Trace;

#[test]
fn dropping_a_pending_phase_future_keeps_the_last_entered_phase() {
    for stage in Stage::ALL {
        let trace = Trace::new(
            /*owner_index*/ 4,
            /*attempt_index*/ Some(2),
            Instant::now(),
        );
        let mut future = Box::pin(async {
            let _phase = trace.enter(stage);
            std::future::pending::<()>().await;
        });
        let mut context = Context::from_waker(Waker::noop());
        assert!(future.as_mut().poll(&mut context).is_pending());
        drop(future);
        trace.finish_attempt(&Err(FederationV2Error::DeadlineExpired));

        let observed = trace.snapshot();
        assert_eq!(observed.last_entered, Some(stage.name()));
        assert_eq!(observed.terminal, Some("deadline_expired"));
        let phases = observed.phases.map(|phase| (phase.phase, phase.state));
        let expected = Stage::ALL.map(|candidate| {
            (
                candidate.name(),
                if candidate.index() == stage.index() {
                    "ended_without_success"
                } else {
                    "not_entered"
                },
            )
        });
        assert_eq!(phases, expected);
        let active = &trace.snapshot().phases[stage.index()];
        assert!(active.entered_us.is_some());
        assert!(active.ended_us >= active.entered_us);
        assert!(active.duration_us.is_some());
    }
}

#[test]
fn completed_preflight_does_not_hide_a_dropped_postflight() {
    let trace = Trace::new(
        /*owner_index*/ 5,
        /*attempt_index*/ Some(3),
        Instant::now(),
    );
    trace.enter_authority().finish(/*success*/ true);
    trace.enter(Stage::Transport).finish(/*success*/ true);
    let mut future = Box::pin(async {
        let _phase = trace.enter_authority();
        std::future::pending::<()>().await;
    });
    let mut context = Context::from_waker(Waker::noop());
    assert!(future.as_mut().poll(&mut context).is_pending());
    drop(future);
    trace.finish_attempt(&Err(FederationV2Error::DeadlineExpired));

    let observed = trace.snapshot();
    assert_eq!(observed.last_entered, Some("postflight"));
    assert_eq!(observed.authority_calls, 2);
    assert_eq!(
        observed.phases.map(|phase| phase.state),
        [
            "not_entered",
            "completed",
            "completed",
            "ended_without_success"
        ]
    );
}

#[test]
fn deadline_before_dispatch_does_not_fabricate_phase_entry() {
    let trace = Trace::new(
        /*owner_index*/ 6,
        /*attempt_index*/ Some(4),
        Instant::now(),
    );
    trace.finish_attempt(&Err(FederationV2Error::DeadlineExpired));
    let observed = trace.snapshot();
    assert_eq!(observed.last_entered, None);
    assert_eq!(observed.terminal, Some("deadline_expired"));
    assert_eq!(
        observed
            .phases
            .map(|phase| (phase.state, phase.entered_us, phase.ended_us)),
        [("not_entered", None, None); 4]
    );
}
