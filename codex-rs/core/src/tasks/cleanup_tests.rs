use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

use futures::FutureExt;
use pretty_assertions::assert_eq;

use crate::session::tests::make_session_and_context;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalizationKind;

#[tokio::test]
async fn cleanup_snapshot_waits_for_captured_owners_without_retiring_their_fences() {
    let (session, _) = make_session_and_context().await;
    let session = Arc::new(session);
    let start = StartTransitionCompletion::new();
    let finish = StartTransitionCompletion::new();
    session
        .pending_start_transition_completions
        .lock()
        .expect("start registry")
        .push((Arc::new(()), Arc::clone(&start), Default::default()));
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("finish registry")
        .push((
            Arc::new(()),
            Arc::clone(&finish),
            TaskTerminalizationKind::Finish,
            None,
            None,
            None,
        ));
    let (generation, mut wait) = session
        .pending_cleanup_snapshot(futures::future::pending::<()>().boxed().shared())
        .expect("owned cleanup snapshot");
    assert_eq!(generation, 0);
    finish.complete();
    assert!(
        tokio::time::timeout(Duration::from_millis(20), wait.as_mut())
            .await
            .is_err()
    );
    assert!(session.has_pending_admission_fence());
    start.complete();
    assert!(
        tokio::time::timeout(Duration::from_secs(2), wait)
            .await
            .expect("exact owner completion")
    );
    // Observing completion is not permission to delete the exact owner's
    // registry entry or to bypass Core's atomic admission checks.
    assert!(session.has_pending_admission_fence());
}

#[tokio::test]
async fn cleanup_snapshot_rejects_a_changed_generation_and_shutdown() {
    for shutdown in [false, true] {
        let (session, _) = make_session_and_context().await;
        let session = Arc::new(session);
        let finish = StartTransitionCompletion::new();
        session
            .pending_task_terminalization_completions
            .lock()
            .expect("finish registry")
            .push((
                Arc::new(()),
                Arc::clone(&finish),
                TaskTerminalizationKind::Finish,
                None,
                None,
                None,
            ));
        let (_, wait) = session
            .pending_cleanup_snapshot(futures::future::pending::<()>().boxed().shared())
            .expect("owned cleanup snapshot");
        if shutdown {
            session.begin_shutdown();
        } else {
            session.turn_epoch.fetch_add(1, Ordering::AcqRel);
        }
        finish.complete();
        assert!(!wait.await);
        assert!(session.has_pending_admission_fence());
    }
}

#[tokio::test]
async fn session_termination_cancels_only_the_wake_up_not_the_owner_fence() {
    let (session, _) = make_session_and_context().await;
    let session = Arc::new(session);
    let finish = StartTransitionCompletion::new();
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("finish registry")
        .push((
            Arc::new(()),
            Arc::clone(&finish),
            TaskTerminalizationKind::Finish,
            None,
            None,
            None,
        ));
    let (stop, stopped) = tokio::sync::oneshot::channel::<()>();
    let (_, wait) = session
        .pending_cleanup_snapshot(
            async move {
                let _ = stopped.await;
            }
            .boxed()
            .shared(),
        )
        .expect("owned cleanup snapshot");
    stop.send(()).expect("signal stopped session");
    assert!(!wait.await);
    assert!(!finish.is_complete());
    assert!(session.has_pending_admission_fence());
}
