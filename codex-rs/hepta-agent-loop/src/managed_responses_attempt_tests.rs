use super::*;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_protocol::protocol::TokenUsage;
use futures::future::BoxFuture;
use std::sync::Mutex;
use std::time::Duration;
use tokio::sync::Notify;
use tokio::time::timeout;

struct Lease {
    terminal: oneshot::Sender<ModelProviderTerminal>,
    gates: Option<(Arc<Notify>, Arc<Notify>)>,
    fail: bool,
}

impl ModelProviderAttemptLease for Lease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            if let Some((started, proceed)) = self.gates {
                started.notify_one();
                proceed.notified().await;
            }
            let _ = self.terminal.send(terminal);
            if self.fail {
                Err(ModelProviderPolicyError::new(
                    "test_persist_failed",
                    "controlled failure",
                ))
            } else {
                Ok(())
            }
        })
    }
}

#[derive(Debug)]
struct Observer {
    terminal: Mutex<Option<oneshot::Sender<EncodedRequestTerminal>>>,
    gates: Option<(Arc<Notify>, Arc<Notify>)>,
    fail: bool,
}

impl EncodedRequestBodyObserver for Observer {
    fn observe_encoded_body<'a>(
        &'a self,
        _body: &'a [u8],
    ) -> BoxFuture<'a, std::result::Result<(), String>> {
        Box::pin(async { Ok(()) })
    }

    fn observe_terminal<'a>(
        &'a self,
        terminal: EncodedRequestTerminal,
    ) -> BoxFuture<'a, std::result::Result<(), String>> {
        Box::pin(async move {
            if let Some((started, proceed)) = &self.gates {
                started.notify_one();
                proceed.notified().await;
            }
            let sender = self
                .terminal
                .lock()
                .expect("fixture mutex")
                .take()
                .expect("single terminal");
            let _ = sender.send(terminal);
            if self.fail {
                Err("controlled encoded write failure".into())
            } else {
                Ok(())
            }
        })
    }
}

fn observer(
    gates: Option<(Arc<Notify>, Arc<Notify>)>,
    fail: bool,
) -> (
    Arc<dyn EncodedRequestBodyObserver>,
    oneshot::Receiver<EncodedRequestTerminal>,
) {
    let (tx, rx) = oneshot::channel();
    (
        Arc::new(Observer {
            terminal: Mutex::new(Some(tx)),
            gates,
            fail,
        }),
        rx,
    )
}

#[tokio::test]
async fn dropped_uninvoked_attempt_records_both_original_owners() {
    let (tx, rx) = oneshot::channel();
    let (observer, encoded) = observer(None, false);
    let owner = AttemptOwner::new(
        Box::new(Lease {
            terminal: tx,
            gates: None,
            fail: false,
        }),
        RequestDispatchMetadata::new(),
        Some(observer),
    );
    drop(owner);
    let observed = timeout(Duration::from_secs(2), rx)
        .await
        .expect("supervisor deadline")
        .expect("lease terminal");
    assert!(matches!(
        observed,
        ModelProviderTerminal::NotDispatched { .. }
    ));
    let observed = timeout(Duration::from_secs(2), encoded)
        .await
        .expect("encoded terminal deadline")
        .expect("same encoded owner");
    assert!(matches!(observed, EncodedRequestTerminal::Abandoned { .. }));
}

#[tokio::test]
async fn aborting_terminal_waiter_does_not_cancel_the_original_lease_write() {
    let (tx, rx) = oneshot::channel();
    let (observer, encoded) = observer(None, false);
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    let owner = AttemptOwner::new(
        Box::new(Lease {
            terminal: tx,
            gates: Some((started.clone(), proceed.clone())),
            fail: false,
        }),
        RequestDispatchMetadata::new(),
        Some(observer),
    );
    let waiter = tokio::spawn(owner.finish(
        ModelProviderTerminal::Rejected {
            reason_code: "controlled_rejection".into(),
        },
        EncodedRequestTerminal::Rejected {
            reason_code: "controlled_rejection".into(),
        },
    ));
    timeout(Duration::from_secs(2), started.notified())
        .await
        .expect("write started");
    assert!(!waiter.is_finished(), "both terminal ACKs are required");
    waiter.abort();
    proceed.notify_one();
    let observed = timeout(Duration::from_secs(2), rx)
        .await
        .expect("write completion deadline")
        .expect("same original lease");
    assert!(
        matches!(observed, ModelProviderTerminal::Rejected { reason_code }
        if reason_code == "controlled_rejection")
    );
    let observed = timeout(Duration::from_secs(2), encoded)
        .await
        .expect("encoded terminal deadline")
        .expect("same encoded owner");
    assert!(
        matches!(observed, EncodedRequestTerminal::Rejected { reason_code }
        if reason_code == "controlled_rejection")
    );
}

struct ContinuationOwner;

impl ResponsesContinuationOwner for ContinuationOwner {
    async fn retain(
        &mut self,
        _binding: &TurnBinding,
        _request: &ModelRequest,
        continuation: ResponsesContinuation,
    ) -> Result<Digest32> {
        assert_eq!(continuation.provider_response_id, "response:original");
        Ok(Digest32::of_bytes(b"fixture retained full continuation"))
    }
}

#[tokio::test]
async fn cancellation_during_encoded_write_keeps_both_original_terminal_owners() {
    let (tx, rx) = oneshot::channel();
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    let (observer, encoded) = observer(Some((started.clone(), proceed.clone())), false);
    let attempt = AttemptOwner::new(
        Box::new(Lease {
            terminal: tx,
            gates: None,
            fail: false,
        }),
        RequestDispatchMetadata::new(),
        Some(observer),
    );
    let waiter = tokio::spawn(async move {
        let mut retained = ContinuationOwner;
        let mut completion = CompletionOwner {
            continuation_owner: &mut retained,
            attempt: Some(attempt),
        };
        let binding = TurnBinding {
            run_id: StableId::new("run:original").expect("run ID"),
            turn_id: StableId::new("turn:original").expect("turn ID"),
            generation: Generation::new(1).expect("generation"),
            admission_digest: Digest32::of_bytes(b"fixture admitted request"),
            deadline_unix_ms: u64::MAX,
        };
        let request = ModelRequest {
            request_id: StableId::new("request:original").expect("request ID"),
            payload: "compiled payload".into(),
            context_digest: Digest32::of_bytes(b"compiled payload"),
            input_tokens: 1,
            maximum_provider_input_tokens: 16,
            maximum_output_tokens: 16,
        };
        completion
            .retain(
                &binding,
                &request,
                ResponsesContinuation {
                    provider_response_id: "response:original".into(),
                    server_model: None,
                    items: Vec::new(),
                    usage: TokenUsage::default(),
                    provider_rollout_budget_units: None,
                    end_turn: Some(true),
                },
            )
            .await
    });
    timeout(Duration::from_secs(2), started.notified())
        .await
        .expect("encoded write started");
    let policy = timeout(Duration::from_secs(2), rx)
        .await
        .expect("policy ACK deadline")
        .expect("original lease committed first");
    assert!(matches!(policy, ModelProviderTerminal::Completed { .. }));
    assert!(
        !waiter.is_finished(),
        "completion cannot precede the encoded terminal ACK"
    );
    waiter.abort();
    assert!(waiter.await.expect_err("caller aborted").is_cancelled());
    proceed.notify_one();
    let observed = timeout(Duration::from_secs(2), encoded)
        .await
        .expect("supervised encoded write deadline")
        .expect("original encoded owner retained");
    assert!(
        matches!(observed, EncodedRequestTerminal::Completed { response_id }
        if response_id == "response:original")
    );
}

#[tokio::test]
async fn a_failed_policy_write_still_observes_encoded_terminal_without_acknowledging_completion() {
    let (tx, rx) = oneshot::channel();
    let (observer, encoded) = observer(None, false);
    let owner = AttemptOwner::new(
        Box::new(Lease {
            terminal: tx,
            gates: None,
            fail: true,
        }),
        RequestDispatchMetadata::new(),
        Some(observer),
    );
    let result = owner
        .finish(
            ModelProviderTerminal::NotDispatched {
                reason_code: "controlled_no_send".into(),
            },
            EncodedRequestTerminal::Abandoned {
                reason_code: "controlled_no_send".into(),
            },
        )
        .await;
    assert!(matches!(result, Err(Error::Owner(_))));
    assert!(matches!(
        rx.await.expect("observed attempt"),
        ModelProviderTerminal::NotDispatched { .. }
    ));
    assert!(matches!(
        encoded.await.expect("encoded owner still observed"),
        EncodedRequestTerminal::Abandoned { .. }
    ));
}

#[tokio::test]
async fn a_failed_encoded_write_never_acknowledges_completion() {
    let (tx, rx) = oneshot::channel();
    let (observer, encoded) = observer(None, true);
    let owner = AttemptOwner::new(
        Box::new(Lease {
            terminal: tx,
            gates: None,
            fail: false,
        }),
        RequestDispatchMetadata::new(),
        Some(observer),
    );
    let result = owner
        .finish(
            ModelProviderTerminal::NotDispatched {
                reason_code: "controlled_no_send".into(),
            },
            EncodedRequestTerminal::Abandoned {
                reason_code: "controlled_no_send".into(),
            },
        )
        .await;
    assert!(matches!(result, Err(Error::Owner(_))));
    assert!(matches!(
        rx.await.expect("observed attempt"),
        ModelProviderTerminal::NotDispatched { .. }
    ));
    assert!(matches!(
        encoded.await.expect("attempted encoded write"),
        EncodedRequestTerminal::Abandoned { .. }
    ));
}
