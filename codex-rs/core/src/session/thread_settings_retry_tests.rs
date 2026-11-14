use super::*;
use crate::agent::AgentStatus;
use crate::session::FinishRetryState;
use crate::session::session_loop_termination_from_handle;
use crate::session::tests::make_session_and_context_with_rx;
use crate::session::thread_settings;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalizationKind;
use codex_features::Feature;
use codex_protocol::protocol::EventMsg;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::time::Duration;
use test_case::test_case;
use tokio::sync::watch;

fn settings() -> ThreadSettingsOverrides {
    ThreadSettingsOverrides {
        model: Some("gpt-5.5".to_string()),
        ..Default::default()
    }
}

fn trace() -> Option<W3cTraceContext> {
    Some(W3cTraceContext {
        traceparent: Some("00-00000000000000000000000000000011-0000000000000022-01".to_string()),
        tracestate: None,
    })
}

fn install_fence(
    session: &Session,
    kind: TaskTerminalizationKind,
) -> Arc<StartTransitionCompletion> {
    let completion = StartTransitionCompletion::new();
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalization registry")
        .push((
            Arc::new(()),
            Arc::clone(&completion),
            kind,
            None,
            None,
            None,
        ));
    completion
}

fn finish_fence(session: &Session, completion: &Arc<StartTransitionCompletion>) {
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalization registry")
        .retain(|(_, current, _, _, _, _)| !Arc::ptr_eq(current, completion));
    completion.complete();
}

async fn route(session: &Arc<Session>, submission: Submission) -> String {
    assert_eq!(submission.trace, trace());
    let Op::ThreadSettings {
        thread_settings: actual,
    } = submission.op
    else {
        panic!("expected the ordered settings operation");
    };
    assert_eq!(actual, settings());
    let id = submission.id;
    thread_settings::update(session, id.clone(), actual).await;
    id
}

#[tokio::test]
async fn finish_snapshot_retains_exact_completions_after_registry_retirement() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let first = install_fence(&session, TaskTerminalizationKind::Finish);
    let second = install_fence(&session, TaskTerminalizationKind::Finish);
    let fences = {
        let active = session.active_turn.lock().await;
        let FinishRetryState::Finishing(fences) = session.finish_retry_state(active.as_ref())
        else {
            panic!("capture both exact owners under one registry lock");
        };
        assert_eq!(fences.len(), 2);
        assert!(Arc::ptr_eq(&fences[0], &first));
        assert!(Arc::ptr_eq(&fences[1], &second));
        // Retirement does not need the held active-turn lock. Captured witnesses
        // remain valid, while a fresh observation must recognize the clear state.
        finish_fence(&session, &first);
        assert!(!fences[1].is_complete());
        finish_fence(&session, &second);
        assert!(matches!(
            session.finish_retry_state(active.as_ref()),
            FinishRetryState::Clear
        ));
        fences
    };
    for completion in fences {
        tokio::time::timeout(Duration::from_secs(2), completion.wait())
            .await
            .expect("retirement before waiting must not lose the completion");
    }
}

#[test_case(false; "ordinary_finish")]
#[test_case(true; "recovery_enabled")]
#[tokio::test]
async fn settings_after_retired_finish_applies_once(recovery_enabled: bool) {
    let (mut session, _context, rx_event) = make_session_and_context_with_rx().await;
    if recovery_enabled {
        Arc::get_mut(&mut session)
            .expect("unique fresh session")
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable recovery");
    }
    let completion = install_fence(&session, TaskTerminalizationKind::Finish);
    finish_fence(&session, &completion);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("settings")).await;
        }
    });
    let io = SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    };
    let id = tokio::time::timeout(
        Duration::from_secs(2),
        io.submit_thread_settings_after_terminalization(&session, settings(), trace()),
    )
    .await
    .expect("a retired owner cannot reject the update")
    .expect("settings routing");
    assert_eq!(session.thread_config_snapshot().await.model, "gpt-5.5");
    let event = io.rx_event.recv().await.expect("one final settings result");
    assert_eq!(event.id, id);
    assert!(matches!(event.msg, EventMsg::ThreadSettingsApplied(_)));
    while let Ok(event) = io.rx_event.try_recv() {
        assert_ne!(event.id, id, "one applied result after a retired fence");
    }
}

#[test_case(false, false; "ordinary_finish")]
#[test_case(true, false; "recovery_enabled")]
#[test_case(false, true; "completed_before_wait")]
#[test_case(true, true; "recovery_enabled_completed_before_wait")]
#[tokio::test]
async fn settings_finish_retry_preserves_identity_and_control_progress(
    recovery_enabled: bool,
    complete_before_wait: bool,
) {
    let (mut session, _context, rx_event) = make_session_and_context_with_rx().await;
    if recovery_enabled {
        Arc::get_mut(&mut session)
            .expect("unique fresh session")
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable recovery");
    }
    let before = session.thread_config_snapshot().await.model;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let (deferred_tx, deferred_rx) = oneshot::channel();
    let (control_tx, control_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        let events = rx_event.clone();
        let fence = Arc::clone(&fence);
        async move {
            let first = rx_sub.recv().await.expect("initial settings");
            let id = first.id.clone();
            deferred_tx.send(id.clone()).expect("initial observer");
            let control = rx_sub.recv().await.expect("control queued after settings");
            assert_eq!(route(&session, first).await, id);
            assert_eq!(session.thread_config_snapshot().await.model, before);
            while let Ok(event) = events.try_recv() {
                assert_ne!(
                    event.id, id,
                    "a deferred attempt must not publish an error or success"
                );
            }
            if complete_before_wait {
                finish_fence(&session, &fence);
            }
            // The settings caller is waiting outside this actor, which can
            // still process control input needed to finish terminalization.
            assert!(matches!(control.op, Op::Interrupt));
            control_tx.send(()).expect("control observer");
            if !complete_before_wait {
                finish_fence(&session, &fence);
            }
            let repeated_id = route(&session, rx_sub.recv().await.expect("retried settings")).await;
            assert_eq!(repeated_id, id);
        }
    });
    let io = Arc::new(SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    });
    let caller = tokio::spawn({
        let io = Arc::clone(&io);
        let session = Arc::clone(&session);
        async move {
            io.submit_thread_settings_after_terminalization(&session, settings(), trace())
                .await
        }
    });
    let id = deferred_rx.await.expect("first settings attempt");
    io.submit(Op::Interrupt).await.expect("control enqueue");
    tokio::time::timeout(Duration::from_secs(2), control_rx)
        .await
        .expect("the actor must remain available")
        .expect("control handled");
    let returned = tokio::time::timeout(Duration::from_secs(2), caller)
        .await
        .expect("settings retry deadline")
        .expect("caller join")
        .expect("settings routing");
    assert_eq!(returned, id);
    assert_eq!(session.thread_config_snapshot().await.model, "gpt-5.5");
    let event = io.rx_event.recv().await.expect("one final settings result");
    assert_eq!(event.id, id);
    assert!(matches!(event.msg, EventMsg::ThreadSettingsApplied(_)));
    while let Ok(event) = io.rx_event.try_recv() {
        assert_ne!(
            event.id, id,
            "retries must publish exactly one final result"
        );
    }
    assert!(
        session
            .pending_thread_settings_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
}

#[test_case(TaskTerminalizationKind::Abort, false; "abort")]
#[test_case(TaskTerminalizationKind::Suspend, false; "suspend")]
#[test_case(TaskTerminalizationKind::Finish, true; "shutdown")]
#[tokio::test]
async fn settings_other_terminalizers_remain_rejected(
    kind: TaskTerminalizationKind,
    shutting_down: bool,
) {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let before = session.thread_config_snapshot().await.model;
    let fence = install_fence(&session, kind);
    if shutting_down {
        session.begin_shutdown();
    }
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("settings")).await;
        }
    });
    let io = SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    };
    let id = tokio::time::timeout(
        Duration::from_secs(2),
        io.submit_thread_settings_after_terminalization(&session, settings(), trace()),
    )
    .await
    .expect("rejection must not wait for an abort or suspension")
    .expect("queued settings ID");
    assert_eq!(session.thread_config_snapshot().await.model, before);
    let event = io.rx_event.recv().await.expect("settings rejection");
    assert_eq!(event.id, id);
    assert!(matches!(event.msg, EventMsg::Error(_)));
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn cancelling_settings_finish_wait_keeps_fence_and_does_not_mutate() {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let before = session.thread_config_snapshot().await.model;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let (deferred_tx, deferred_rx) = oneshot::channel();
    let (stop_tx, stop_rx) = oneshot::channel();
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            route(&session, rx_sub.recv().await.expect("settings")).await;
            deferred_tx.send(()).expect("deferred observer");
            let _ = stop_rx.await;
            assert!(
                rx_sub.try_recv().is_err(),
                "cancelled settings cannot be resubmitted"
            );
        }
    });
    let io = Arc::new(SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    });
    let caller = tokio::spawn({
        let io = Arc::clone(&io);
        let session = Arc::clone(&session);
        async move {
            io.submit_thread_settings_after_terminalization(&session, settings(), trace())
                .await
        }
    });
    deferred_rx.await.expect("fenced settings attempt");
    caller.abort();
    assert!(caller.await.expect_err("cancelled caller").is_cancelled());
    assert_eq!(session.thread_config_snapshot().await.model, before);
    assert!(
        session
            .pending_thread_settings_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(!fence.is_complete());
    assert!(session.has_pending_task_terminalization());
    stop_tx.send(()).expect("stop actor");
    io.session_loop_termination.clone().await;
    finish_fence(&session, &fence);
}

#[test_case(false; "before_ack")]
#[test_case(true; "after_retry_ack")]
#[tokio::test]
async fn settings_finish_wait_ends_when_the_actor_exits(reply_before_exit: bool) {
    let (session, _context, rx_event) = make_session_and_context_with_rx().await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let (tx_sub, rx_sub) = async_channel::bounded::<Submission>(4);
    let actor = tokio::spawn({
        let session = Arc::clone(&session);
        async move {
            let submission = rx_sub.recv().await.expect("settings");
            if reply_before_exit {
                route(&session, submission).await;
            }
        }
    });
    let io = SessionIo {
        tx_sub,
        rx_event,
        agent_status: watch::channel(AgentStatus::PendingInit).1,
        session_loop_termination: session_loop_termination_from_handle(actor),
    };
    let error = tokio::time::timeout(
        Duration::from_secs(2),
        io.submit_thread_settings_after_terminalization(&session, settings(), trace()),
    )
    .await
    .expect("actor exit must release the caller")
    .expect_err("actor terminated");
    assert!(matches!(
        error.details(),
        codex_protocol::error::CodexErrorDetails::InternalAgentDied
    ));
    assert!(
        session
            .pending_thread_settings_retries
            .pending
            .lock()
            .expect("retry registry")
            .is_empty()
    );
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}
