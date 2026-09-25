use super::*;

fn dispatched() -> AgentRunCoordinator {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");
    coordinator
        .mark_dispatched(300, "run.1", 2)
        .expect("dispatch");
    coordinator
}

#[test]
fn lost_ack_retry_keeps_original_revision_and_does_not_renew_deadline() {
    let mut c = dispatched();
    let (_, first) = c.cancel_run(400, "run.1", 3, "user_stop").expect("cancel");
    let (_, retry) = c.cancel_run(500, "run.1", 3, "user_stop").expect("retry");
    assert_eq!(
        retry,
        RunReceipt {
            idempotent: true,
            ..first
        }
    );
    let (_, unknown) = c
        .cancel_run(3_400, "run.1", 3, "user_stop")
        .expect("timeout");
    assert_eq!(unknown.phase, RunPhase::Indeterminate);
    assert!(!unknown.terminal_observed);
    let (_, retry) = c
        .cancel_run(3_500, "run.1", 3, "user_stop")
        .expect("retry unknown");
    assert_eq!(
        retry,
        RunReceipt {
            idempotent: true,
            ..unknown
        }
    );
    assert_eq!(
        c.mark_dispatched(3_500, "run.1", retry.revision),
        Err(AgentRunError::InvalidTransition)
    );
}

#[test]
fn monitor_and_cancel_timeout_preserve_identical_reconciliation_state() {
    let mut observed = Vec::new();
    for monitor_first in [false, true] {
        let mut c = dispatched();
        c.cancel_run(400, "run.1", 3, "user_stop").expect("cancel");
        if monitor_first {
            c.expire_deadlines(3_400).expect("monitor");
        }
        let (_, mut r) = c.cancel_run(3_400, "run.1", 3, "user_stop").expect("retry");
        assert_eq!(r.idempotent, monitor_first);
        r.idempotent = false;
        observed.push(r);
    }
    assert_eq!(observed[0], observed[1]);
}

#[test]
fn conflicting_cancel_retry_does_not_change_state() {
    let mut c = dispatched();
    c.cancel_run(400, "run.1", 3, "user_stop").expect("cancel");
    let before = c.run("run.1");
    assert_eq!(
        c.cancel_run(500, "run.1", 3, "other"),
        Err(AgentRunError::StaleRevision)
    );
    assert_eq!(
        c.cancel_run(500, "run.1", 4, "other"),
        Err(AgentRunError::Conflict)
    );
    assert_eq!(
        c.cancel_run(500, "run.1", 2, "user_stop"),
        Err(AgentRunError::StaleRevision)
    );
    assert_eq!(c.run("run.1"), before);
}

#[test]
fn pre_dispatch_and_terminal_retries_preserve_original_cancel_identity() {
    let mut c = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    c.start_run(100, snapshot()).expect("admit");
    let (_, first) = c.cancel_run(200, "run.1", 1, "user_stop").expect("cancel");
    let (kind, retry) = c.cancel_run(300, "run.1", 1, "user_stop").expect("retry");
    assert_eq!(kind, CancellationDisposition::AlreadyTerminal);
    assert_eq!(
        retry,
        RunReceipt {
            idempotent: true,
            ..first
        }
    );
    let mut c = dispatched();
    c.cancel_run(400, "run.1", 3, "user_stop").expect("cancel");
    let terminal = c
        .observe_terminal("run.1", 4, RunPhase::Cancelled, true)
        .expect("stop ACK");
    let (_, retry) = c
        .cancel_run(500, "run.1", 3, "user_stop")
        .expect("terminal retry");
    assert_eq!(
        retry,
        RunReceipt {
            idempotent: true,
            ..terminal
        }
    );
}

#[test]
fn revision_overflow_leaves_the_original_run_unchanged() {
    let mut c = dispatched();
    c.runs.get_mut("run.1").expect("run").revision = u64::MAX;
    let before = c.run("run.1");
    assert_eq!(
        c.cancel_run(400, "run.1", u64::MAX, "user_stop"),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(c.run("run.1"), before);
}
