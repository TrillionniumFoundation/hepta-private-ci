//! Component tests for actual task/FD custody. These do not construct a
//! successful AppServerJoined, Root intent, business receipt, or daemon exit.

use super::*;
use pretty_assertions::assert_eq;
use tokio::sync::oneshot;

#[tokio::test]
async fn never_started_owner_cannot_report_joined_app_server() {
    let original = OriginalAppServerOwnerCustody::new();
    assert!(OriginalAppServerOwnerCustody::join_original_app_server(&original).await.is_err());
    assert!(original.state().main.is_none());
    assert!(original.state().processor_cleanup.is_none());
}

#[cfg(unix)]
#[tokio::test]
async fn cancelled_job_waiter_retains_actual_task_and_fd_until_join() {
    use tokio::io::AsyncReadExt;

    let (owned, mut peer) = tokio::net::UnixStream::pair().expect("actual socketpair");
    let (entered_tx, entered_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let job = OriginalAppServerJob::unit(tokio::spawn(async move {
        entered_tx.send(()).expect("entered receiver");
        release_rx.await.expect("release actual task");
        drop(owned);
    }));
    let mut waiting = Box::pin(OriginalAppServerJob::join_original(&job));
    tokio::select! {
        biased;
        result = &mut waiting => panic!("blocked actual task was reported joined: {result:?}"),
        result = entered_rx => result.expect("actual task started"),
    }
    drop(waiting);
    assert!(job.terminal.get().is_none());
    assert!(job.handle.lock().await.is_some());
    release_tx.send(()).expect("same actual task still retained");
    OriginalAppServerJob::join_original(&job).await.expect("actual task joined");
    let mut byte = [0_u8; 1];
    assert_eq!(peer.read(&mut byte).await.expect("actual EOF"), 0);
    // The recorded terminal result is observed again without polling a completed handle.
    OriginalAppServerJob::join_original(&job).await.expect("same terminal observation");
    assert!(job.handle.lock().await.is_none());
}

#[tokio::test]
async fn real_task_panic_keeps_the_original_join_error_after_reobservation() {
    let job = OriginalAppServerJob::unit(tokio::spawn(async {
        panic!("actual original App Server component panic");
    }));
    let first = OriginalAppServerJob::join_original(&job).await.expect_err("real panic");
    let second = OriginalAppServerJob::join_original(&job).await.expect_err("recorded panic");
    assert!(first.error.as_ref().downcast_ref::<tokio::task::JoinError>()
        .expect("original JoinError source").is_panic());
    assert!(Arc::ptr_eq(&first.error, &second.error));
    assert!(job.handle.lock().await.is_none());
}

#[tokio::test]
async fn original_io_failure_is_not_replaced_by_a_successful_join() {
    let job = OriginalAppServerJob::result(tokio::spawn(async {
        Err(io::Error::new(io::ErrorKind::PermissionDenied, "actual component refusal"))
    }));
    let failure = OriginalAppServerJob::join_original(&job).await.expect_err("original error");
    let actual = failure.error.as_ref().downcast_ref::<io::Error>().expect("actual IO source");
    assert_eq!(actual.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(actual.to_string(), "actual component refusal");
    assert!(job.require_original_success().is_err());
}

#[tokio::test]
async fn sealed_background_admission_keeps_admitted_job_and_never_runs_late_future() {
    let original = OriginalAppServerOwnerCustody::new();
    let (entered_tx, entered_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    OriginalAppServerOwnerCustody::spawn_original_background(&original, async move {
        entered_tx.send(()).expect("entered receiver");
        release_rx.await.expect("actual background release");
    });
    entered_rx.await.expect("actual admitted callback");
    OriginalAppServerOwnerCustody::seal_original_background(&original);
    let (late_tx, late_rx) = oneshot::channel();
    OriginalAppServerOwnerCustody::spawn_original_background(&original, async move {
        let _ = late_tx.send(());
    });
    assert!(late_rx.await.is_err());
    let mut joining = Box::pin(OriginalAppServerOwnerCustody::join_original_group(
        &original,
        OriginalAppServerTaskKind::PluginRefresh,
    ));
    tokio::select! {
        biased;
        result = &mut joining => panic!("actual admitted job has not ended: {result:?}"),
        () = std::future::ready(()) => {},
    }
    release_tx.send(()).expect("actual admitted task retained");
    joining.await.expect("actual admitted callback join");
}

#[tokio::test]
async fn actual_connection_cleanup_panic_reaches_owner_even_after_local_waiter_drops() {
    let original = OriginalAppServerOwnerCustody::new();
    let mut cleanup = crate::connection_cleanup::ConnectionCleanupTasks::new_original(
        Arc::clone(&original),
    );
    cleanup.spawn(async { panic!("actual connection cleanup failed") });
    drop(cleanup);
    let error = OriginalAppServerOwnerCustody::join_original_group(
        &original,
        OriginalAppServerTaskKind::ConnectionCleanup,
    )
    .await
    .expect_err("same actual cleanup job must still be observed");
    assert!(error.to_string().contains("actual connection cleanup failed"));
}

#[cfg(unix)]
#[tokio::test]
async fn actual_queue_close_does_not_discard_an_admitted_drain_or_its_fd() {
    use crate::request_serialization::RequestSerializationAccess;
    use crate::request_serialization::RequestSerializationQueueKey;
    use crate::request_serialization::RequestSerializationQueues;
    use tokio::io::AsyncReadExt;

    let original = OriginalAppServerOwnerCustody::new();
    let queues = RequestSerializationQueues::new_original_owner(Arc::clone(&original));
    let (owned, mut peer) = tokio::net::UnixStream::pair().expect("actual socketpair");
    let (entered_tx, entered_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    queues.enqueue_background(
        RequestSerializationQueueKey::Global("original-component"),
        RequestSerializationAccess::Exclusive,
        async move {
            entered_tx.send(()).expect("entered receiver");
            release_rx.await.expect("release actual queued work");
            drop(owned);
        },
    ).await;
    entered_rx.await.expect("actual queued work entered");
    queues.seal_original_queues().await;
    let (late_tx, late_rx) = oneshot::channel();
    queues.enqueue_background(
        RequestSerializationQueueKey::Global("original-component"),
        RequestSerializationAccess::Exclusive,
        async move { let _ = late_tx.send(()); },
    ).await;
    assert!(late_rx.await.is_err());
    let mut joining = Box::pin(OriginalAppServerOwnerCustody::join_original_group(
        &original,
        OriginalAppServerTaskKind::SerializedQueue,
    ));
    tokio::select! {
        biased;
        result = &mut joining => panic!("actual queue job still owns its FD: {result:?}"),
        () = std::future::ready(()) => {},
    }
    release_tx.send(()).expect("same actual queue job retained");
    joining.await.expect("actual queue drain joined");
    queues.require_original_queues_drained().await.expect("actual drain removed queue");
    let mut byte = [0_u8; 1];
    assert_eq!(peer.read(&mut byte).await.expect("actual EOF"), 0);
    assert!(!original.state().failures.is_empty());
}

#[cfg(unix)]
#[tokio::test]
async fn cancelled_main_wrapper_keeps_actual_job_and_never_restarts_it() {
    use tokio::io::AsyncReadExt;

    let original = OriginalAppServerOwnerCustody::new();
    let drain = AppServerDrainHandle::new();
    let (owned, mut peer) = tokio::net::UnixStream::pair().expect("actual socketpair");
    let (entered_tx, entered_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let mut main = Box::pin(OriginalAppServerOwnerCustody::run_original_main(
        &original,
        drain.clone(),
        async move {
            entered_tx.send(()).expect("entered receiver");
            release_rx.await.expect("release actual main component");
            drop(owned);
            Err(io::Error::other("incomplete component invocation"))
        },
    ));
    tokio::select! {
        biased;
        result = &mut main => panic!("actual main is still blocked: {result:?}"),
        result = entered_rx => result.expect("actual main started"),
    }
    drop(main);
    drain.wait_requested().await;
    let first = original.state().main.clone().expect("same actual main retained");
    assert!(first.terminal.get().is_none());
    let (restarted_tx, restarted_rx) = oneshot::channel();
    assert!(OriginalAppServerOwnerCustody::run_original_main(
        &original,
        drain,
        async move {
            let _ = restarted_tx.send(());
            Ok(())
        },
    ).await.is_err());
    assert!(restarted_rx.await.is_err());
    release_tx.send(()).expect("actual main handle still present");
    assert!(OriginalAppServerOwnerCustody::join_original_app_server(&original).await.is_err());
    let mut byte = [0_u8; 1];
    assert_eq!(peer.read(&mut byte).await.expect("actual owner released"), 0);
    assert!(first.terminal.get().is_some());
}
