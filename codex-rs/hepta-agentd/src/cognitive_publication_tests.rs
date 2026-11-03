//! Native durable intents and confirmations around the production transport helper.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::Context;
use std::task::Poll;

use codex_hepta_learning_ledger::RetrievalPublicationStateV2;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::ProbabilityQ32;
use tokio::io::AsyncWrite;

use crate::cognitive_context::read_with_retrieval_context_and_learning;
use crate::cognitive_context_delivery::ContextDeliveryPlan;
use crate::cognitive_context_delivery::PendingContextDelivery;
use crate::cognitive_context_delivery::encode_control_frame;
use crate::cognitive_context_delivery::write_control_frame;
use crate::cognitive_context_issuer::ContextPlanIssuer;

use super::observation;
use super::owner;
use super::sink;

async fn intent(
    request_id: u64,
) -> (
    tempfile::TempDir,
    Arc<crate::CognitiveRetrievalLearningSink>,
    Vec<u8>,
    crate::cognitive_retrieval_learning::PendingTransportConfirmation,
) {
    let (ledger, sink) = sink();
    let sink = Arc::new(sink);
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(fleet)
        .unwrap()
        .layout()
        .agent(&owner());
    let store = CognitiveStore::open(&layout).await.unwrap();
    let mut read = read_with_retrieval_context_and_learning(
        &store,
        &owner(),
        /*body_generation*/ 1,
        "lemon",
        /*limit*/ 4,
        /*ranker*/ None,
        /*current_retrieval*/ None,
        /*learning_sink*/ None,
        /*request_id*/ None,
    )
    .await
    .unwrap();
    read.delivery = Some(PendingContextDelivery::new(ContextDeliveryPlan {
        sink: Arc::clone(&sink),
        owner: owner(),
        body_generation: 1,
        request_id,
        assignment: observation("transport-observation"),
        planned_candidates: Vec::new(),
        downstream_policy_digest: None,
        delivery_propensity: ProbabilityQ32::ONE,
    }));
    let issuer = ContextPlanIssuer::default();
    let mut prepared = read
        .prepare(
            &store,
            &owner(),
            /*body_generation*/ 1,
            &issuer,
            /*ranker*/ None,
            /*current_retrieval*/ None,
        )
        .await
        .unwrap();
    assert!(
        sink.writer
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .is_empty()
    );
    let mut payload = serde_json::to_value(&prepared.snapshot).unwrap();
    payload
        .as_object_mut()
        .unwrap()
        .insert("type".to_string(), "cognitive_context".into());
    let response = serde_json::json!({
        "schema_version": 2, "request_id": request_id, "agent_id": owner(),
        "spawn_generation": 1, "current_generation": 2, "payload": payload,
    });
    let frame = encode_control_frame(&response).unwrap();
    let mut substituted = response;
    substituted["payload"]["read_digest"] = "11".repeat(32).into();
    let wrong = encode_control_frame(&substituted).unwrap();
    assert!(
        prepared
            .publication
            .begin_intent(&owner(), /*body_generation*/ 1, request_id, &wrong)
            .await
            .is_err()
    );
    assert!(
        sink.writer
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .is_empty()
    );
    let confirmation = prepared
        .publication
        .begin_intent(&owner(), /*body_generation*/ 1, request_id, &frame)
        .await
        .unwrap()
        .unwrap();
    (ledger, sink, frame, confirmation)
}

#[derive(Clone, Copy)]
enum TransportFault {
    None,
    PartialFailure,
    PendingAfterPrefix,
    ShutdownFailure,
}

struct Writer {
    fault: TransportFault,
    bytes: Vec<u8>,
}

impl Writer {
    fn new(fault: TransportFault) -> Self {
        Self {
            fault,
            bytes: Vec::new(),
        }
    }
}

impl AsyncWrite for Writer {
    fn poll_write(
        mut self: Pin<&mut Self>,
        _cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<std::io::Result<usize>> {
        if !self.bytes.is_empty() {
            match self.fault {
                TransportFault::PartialFailure => {
                    return Poll::Ready(Err(std::io::Error::new(
                        std::io::ErrorKind::BrokenPipe,
                        "injected partial write",
                    )));
                }
                TransportFault::PendingAfterPrefix => return Poll::Pending,
                TransportFault::None | TransportFault::ShutdownFailure => {}
            }
        }
        let count = match self.fault {
            TransportFault::PartialFailure | TransportFault::PendingAfterPrefix => {
                bytes.len().min(8)
            }
            TransportFault::None | TransportFault::ShutdownFailure => bytes.len(),
        };
        self.bytes.extend_from_slice(&bytes[..count]);
        Poll::Ready(Ok(count))
    }
    fn poll_flush(self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        Poll::Ready(Ok(()))
    }
    fn poll_shutdown(self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        if matches!(self.fault, TransportFault::ShutdownFailure) {
            Poll::Ready(Err(std::io::Error::new(
                std::io::ErrorKind::BrokenPipe,
                "injected shutdown failure",
            )))
        } else {
            Poll::Ready(Ok(()))
        }
    }
}

#[tokio::test]
async fn exact_full_write_confirms_the_durable_intent() {
    let (_ledger, sink, frame, confirmation) = intent(77).await;
    let id = confirmation.intent.record_id.clone();
    assert_eq!(
        sink.writer
            .lock()
            .unwrap()
            .retrieval_publication(&id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::Unknown
    );
    let mut writer = Writer::new(TransportFault::None);
    write_control_frame(&mut writer, &frame, Some(confirmation))
        .await
        .unwrap();
    assert_eq!(writer.bytes, frame);
    let writer = sink.writer.lock().unwrap();
    assert_eq!(writer.snapshot().unwrap().records().len(), 2);
    let projection = writer.retrieval_publication(&id).unwrap().unwrap();
    assert_eq!(
        projection.state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
    assert!(projection.ledger_lineage_active);
}

#[tokio::test]
async fn different_frame_cannot_confirm_another_intent_or_write_any_byte() {
    let (_ledger, sink, frame, confirmation) = intent(78).await;
    let id = confirmation.intent.record_id.clone();
    let mut wrong = frame;
    wrong[0] ^= 1;
    let mut writer = Writer::new(TransportFault::None);
    assert!(
        write_control_frame(&mut writer, &wrong, Some(confirmation))
            .await
            .is_err()
    );
    assert!(writer.bytes.is_empty());
    assert_eq!(
        sink.writer
            .lock()
            .unwrap()
            .retrieval_publication(&id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::Unknown
    );
}

#[tokio::test]
async fn partial_write_and_cancelled_write_preserve_unknown_intents() {
    for fault in [
        TransportFault::PartialFailure,
        TransportFault::PendingAfterPrefix,
    ] {
        let (_ledger, sink, frame, confirmation) = intent(79).await;
        let id = confirmation.intent.record_id.clone();
        let mut writer = Writer::new(fault);
        {
            let mut write = Box::pin(write_control_frame(&mut writer, &frame, Some(confirmation)));
            match fault {
                TransportFault::PartialFailure => assert!(write.await.is_err()),
                TransportFault::PendingAfterPrefix => {
                    std::future::poll_fn(|cx| {
                        assert!(write.as_mut().poll(cx).is_pending());
                        Poll::Ready(())
                    })
                    .await;
                }
                TransportFault::None | TransportFault::ShutdownFailure => unreachable!(),
            }
        }
        assert_eq!(writer.bytes, frame[..8]);
        assert_eq!(
            sink.writer
                .lock()
                .unwrap()
                .retrieval_publication(&id)
                .unwrap()
                .unwrap()
                .state,
            RetrievalPublicationStateV2::Unknown
        );
        assert_eq!(
            sink.writer
                .lock()
                .unwrap()
                .snapshot()
                .unwrap()
                .records()
                .len(),
            1
        );
    }
}

#[tokio::test]
async fn shutdown_failure_keeps_the_true_completed_write_confirmation() {
    let (_ledger, sink, frame, confirmation) = intent(80).await;
    let id = confirmation.intent.record_id.clone();
    let mut writer = Writer::new(TransportFault::ShutdownFailure);
    assert!(
        write_control_frame(&mut writer, &frame, Some(confirmation))
            .await
            .is_err()
    );
    assert_eq!(writer.bytes, frame);
    assert_eq!(
        sink.writer
            .lock()
            .unwrap()
            .retrieval_publication(&id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
}

#[tokio::test]
async fn confirmation_failure_after_send_closes_the_learning_sink() {
    let (_ledger, sink, frame, confirmation) = intent(81).await;
    let cloned = Arc::clone(&sink);
    assert!(
        std::thread::spawn(move || {
            let _held = cloned.writer.lock().unwrap();
            panic!("injected owner lock failure");
        })
        .join()
        .is_err()
    );
    let mut writer = Writer::new(TransportFault::None);
    assert!(
        write_control_frame(&mut writer, &frame, Some(confirmation))
            .await
            .is_err()
    );
    assert_eq!(writer.bytes, frame);
    assert!(sink.failed.load(std::sync::atomic::Ordering::Acquire));
}

#[tokio::test]
async fn cancelled_intent_waiter_keeps_the_actual_worker_within_its_slot_budget() {
    let (_ledger, sink, _frame, confirmation) = intent(82).await;
    let retry = confirmation.intent.clone();
    let (held_sender, held_receiver) = tokio::sync::oneshot::channel();
    let (release_sender, release_receiver) = std::sync::mpsc::channel();
    let locked_sink = Arc::clone(&sink);
    let holder = std::thread::spawn(move || {
        let _writer = locked_sink.writer.lock().unwrap();
        held_sender.send(()).unwrap();
        release_receiver
            .recv_timeout(std::time::Duration::from_secs(10))
            .unwrap();
    });
    held_receiver.await.unwrap();

    let reservation = sink.reserve_publication().unwrap();
    let (started_sender, started_receiver) = tokio::sync::oneshot::channel();
    let (finished_sender, finished_receiver) = tokio::sync::oneshot::channel();
    let blocked_sink = Arc::clone(&sink);
    let waiter = tokio::spawn(async move {
        tokio::task::spawn_blocking(move || {
            started_sender.send(()).unwrap();
            // The real append is blocked by the real owner mutex. Its permit
            // must survive cancellation of the async task awaiting this work.
            let retry = blocked_sink.append_intent(retry, reservation).unwrap();
            drop(retry);
            finished_sender.send(()).unwrap();
        })
        .await
        .unwrap();
    });
    started_receiver.await.unwrap();
    waiter.abort();
    assert!(waiter.await.unwrap_err().is_cancelled());
    assert_eq!(sink.publications.available_permits(), 30);

    let remaining: Vec<_> = (0..30)
        .map(|_| sink.reserve_publication().unwrap())
        .collect();
    assert!(sink.reserve_publication().is_err());
    assert!(!sink.failed.load(std::sync::atomic::Ordering::Acquire));
    drop(remaining);
    release_sender.send(()).unwrap();
    holder.join().unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(10), finished_receiver)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(sink.publications.available_permits(), 31);
    assert_eq!(
        sink.writer
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .len(),
        1
    );
    drop(confirmation);
    assert_eq!(sink.publications.available_permits(), 32);
}

#[test]
fn oversized_response_is_rejected_before_any_transport_operation() {
    assert!(encode_control_frame(&serde_json::json!({"content": "x".repeat(65_536)})).is_err());
}
