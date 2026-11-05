use super::*;
use crate::connection_rpc_gate::ConnectionRpcGate;
use crate::request_serialization::QueuedInitializedRequest;
use crate::request_serialization::RequestSerializationAccess;
use crate::request_serialization::RequestSerializationQueueKey;
use crate::request_serialization::RequestSerializationQueues;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::time::timeout;

fn admitted(ms: u32) -> anyhow::Result<(QueuedTermination, TerminationReply)> {
    admit(Instant::now(), ms).map_err(|error| anyhow::anyhow!("{error:?}"))
}

fn confirmed() -> Response {
    Response {
        status: Status::Confirmed,
    }
}

struct MarkDropped(Arc<AtomicUsize>);

impl Drop for MarkDropped {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}

#[tokio::test]
async fn expired_queued_request_never_runs_after_fifo_is_released() -> anyhow::Result<()> {
    let queues = RequestSerializationQueues::default();
    let gate = Arc::new(ConnectionRpcGate::new());
    let key = RequestSerializationQueueKey::Thread {
        thread_id: "blocked-thread".to_string(),
    };
    let (entered, entry) = oneshot::channel();
    let (release, released) = oneshot::channel();
    queues
        .enqueue(
            key.clone(),
            RequestSerializationAccess::Exclusive,
            QueuedInitializedRequest::new(Arc::clone(&gate), async move {
                let _ = entered.send(());
                let _ = released.await;
            }),
        )
        .await;
    timeout(Duration::from_secs(2), entry).await??;

    let (operation, reply) = admitted(20)?;
    let responses = tokio::spawn(reply.wait());
    let effects = Arc::new(AtomicUsize::new(0));
    let effect = Arc::clone(&effects);
    queues
        .enqueue(
            key.clone(),
            RequestSerializationAccess::Exclusive,
            QueuedInitializedRequest::new(
                Arc::clone(&gate),
                operation.run(move |_| async move {
                    effect.fetch_add(1, Ordering::SeqCst);
                    Ok(confirmed())
                }),
            ),
        )
        .await;
    let response = timeout(Duration::from_secs(2), responses)
        .await??
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    assert_eq!(response.status, Status::NotConfirmed);
    assert_eq!(effects.load(Ordering::SeqCst), 0);

    let (tail_done, tail) = oneshot::channel();
    queues
        .enqueue(
            key,
            RequestSerializationAccess::Exclusive,
            QueuedInitializedRequest::new(gate, async move {
                let _ = tail_done.send(());
            }),
        )
        .await;
    release
        .send(())
        .map_err(|_| anyhow::anyhow!("front request lost"))?;
    timeout(Duration::from_secs(2), tail).await??;
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn closed_gate_drops_unpolled_request_and_completes_its_reply() -> anyhow::Result<()> {
    let gate = ConnectionRpcGate::new();
    gate.close().await;
    let (operation, reply) = admitted(1_000)?;
    let effects = Arc::new(AtomicUsize::new(0));
    let effect = Arc::clone(&effects);
    gate.run(operation.run(move |_| async move {
        effect.fetch_add(1, Ordering::SeqCst);
        Ok(confirmed())
    }))
    .await;
    let response = reply
        .wait()
        .await
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    assert_eq!(response.status, Status::NotConfirmed);
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn dropping_reply_cancels_running_future_without_confirming_it() -> anyhow::Result<()> {
    let (operation, reply) = admitted(1_000)?;
    let dropped = Arc::new(AtomicUsize::new(0));
    let drop_marker = Arc::clone(&dropped);
    let (entered, entry) = oneshot::channel();
    let task = tokio::spawn(operation.run(move |_| async move {
        let _guard = MarkDropped(drop_marker);
        let _ = entered.send(());
        std::future::pending::<Outcome>().await
    }));
    timeout(Duration::from_secs(2), entry).await??;
    drop(reply);
    timeout(Duration::from_secs(2), task).await??;
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn same_end_expires_running_work_and_drops_its_guard_once() -> anyhow::Result<()> {
    let (operation, reply) = admitted(1_000)?;
    let original_end = operation.end();
    let dropped = Arc::new(AtomicUsize::new(0));
    let drop_marker = Arc::clone(&dropped);
    let (entered, entry) = oneshot::channel();
    let task = tokio::spawn(operation.run(move |end| async move {
        assert_eq!(end, original_end);
        let _guard = MarkDropped(drop_marker);
        let _ = entered.send(());
        std::future::pending::<Outcome>().await
    }));
    timeout(Duration::from_secs(2), entry).await??;
    let response = timeout(Duration::from_secs(2), reply.wait())
        .await?
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    assert_eq!(response.status, Status::NotConfirmed);
    timeout(Duration::from_secs(2), task).await??;
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn elapsed_ingress_budget_cannot_be_restarted_by_dispatch() -> anyhow::Result<()> {
    let ingress = Instant::now();
    sleep_until(ingress + Duration::from_millis(2)).await;
    let (operation, reply) = admit(ingress, 1).map_err(|error| anyhow::anyhow!("{error:?}"))?;
    let effects = Arc::new(AtomicUsize::new(0));
    let effect = Arc::clone(&effects);
    operation
        .run(move |_| async move {
            effect.fetch_add(1, Ordering::SeqCst);
            Ok(confirmed())
        })
        .await;
    let response = reply
        .wait()
        .await
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    assert_eq!(response.status, Status::NotConfirmed);
    assert_eq!(effects.load(Ordering::SeqCst), 0);
    assert!(admit(Instant::now(), 0).is_err());
    Ok(())
}

#[tokio::test]
async fn recorded_result_survives_delivery_delay_without_late_reclassification()
-> anyhow::Result<()> {
    let (operation, reply) = admitted(100)?;
    let end = operation.end();
    operation.run(|_| async { Ok(confirmed()) }).await;
    sleep_until(end).await;
    let response = reply
        .wait()
        .await
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    assert_eq!(response.status, Status::Confirmed);

    let (operation, reply) = admitted(100)?;
    operation.run(|_| async { Ok(not_confirmed()) }).await;
    let response = reply
        .wait()
        .await
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
    assert_eq!(response.status, Status::NotConfirmed);
    Ok(())
}
