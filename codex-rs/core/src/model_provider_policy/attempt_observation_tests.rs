use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;

use codex_api::EncodedRequestBodyObserver;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::sync::oneshot::error::TryRecvError;

use super::LeaseFinalRequestObserver;
use super::ProviderAttemptOwner;
use super::lend_lease_for_observation;
use super::observation_stopped_error;

type ObservationResult = Result<(), ModelProviderPolicyError>;

struct GatedLease {
    requests: mpsc::UnboundedSender<Vec<u8>>,
    gates: Mutex<VecDeque<oneshot::Receiver<ObservationResult>>>,
    terminal: oneshot::Sender<ModelProviderTerminal>,
}

impl ModelProviderAttemptLease for GatedLease {
    fn requires_final_request_observation(&self) -> bool {
        true
    }

    fn observe_final_request<'a>(&'a self, body: &'a [u8]) -> ModelProviderPolicyFuture<'a, ()> {
        let gate = self
            .gates
            .lock()
            .map_err(|_| fixture_error("observation gate mutex poisoned"))
            .and_then(|mut gates| {
                gates
                    .pop_front()
                    .ok_or_else(|| fixture_error("unexpected additional observation"))
            });
        let requests = self.requests.clone();
        Box::pin(async move {
            let gate = gate?;
            requests
                .send(body.to_vec())
                .map_err(|_| fixture_error("request observation receiver dropped"))?;
            gate.await
                .map_err(|_| fixture_error("observation gate sender dropped"))?
        })
    }

    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        let result = self
            .terminal
            .send(terminal)
            .map_err(|_| fixture_error("terminal observation receiver dropped"));
        Box::pin(std::future::ready(result))
    }
}

struct GatedFinishLease {
    started: oneshot::Sender<ModelProviderTerminal>,
    release: oneshot::Receiver<ObservationResult>,
}

impl ModelProviderAttemptLease for GatedFinishLease {
    fn requires_final_request_observation(&self) -> bool {
        true
    }

    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            self.started
                .send(terminal)
                .map_err(|_| fixture_error("terminal start receiver dropped"))?;
            self.release
                .await
                .map_err(|_| fixture_error("terminal persistence gate dropped"))?
        })
    }
}

fn fixture_error(detail: &str) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new("test_observation_fixture", detail)
}

struct LeaseFixture {
    lease: Box<dyn ModelProviderAttemptLease>,
    requests: mpsc::UnboundedReceiver<Vec<u8>>,
    terminal: oneshot::Receiver<ModelProviderTerminal>,
}

fn gated_lease(gates: Vec<oneshot::Receiver<ObservationResult>>) -> LeaseFixture {
    let (requests, observed_requests) = mpsc::unbounded_channel();
    let (terminal, observed_terminal) = oneshot::channel();
    LeaseFixture {
        lease: Box::new(GatedLease {
            requests,
            gates: Mutex::new(gates.into()),
            terminal,
        }),
        requests: observed_requests,
        terminal: observed_terminal,
    }
}

struct OwnerFixture {
    owner: ProviderAttemptOwner,
    observer: Arc<LeaseFinalRequestObserver>,
    requests: mpsc::UnboundedReceiver<Vec<u8>>,
    terminal: oneshot::Receiver<ModelProviderTerminal>,
}

fn observing_owner(gates: Vec<oneshot::Receiver<ObservationResult>>) -> OwnerFixture {
    let LeaseFixture {
        lease,
        requests,
        terminal,
    } = gated_lease(gates);
    let owner = ProviderAttemptOwner::new_with_dispatch_probe(lease, Box::new(|| false));
    let observer = Arc::new(LeaseFinalRequestObserver {
        commands: owner.commands.downgrade(),
    });
    OwnerFixture {
        owner,
        observer,
        requests,
        terminal,
    }
}

fn rejected_terminal() -> ModelProviderTerminal {
    ModelProviderTerminal::Rejected {
        reason_code: "test_rejected".to_owned(),
    }
}

#[tokio::test]
async fn terminal_waits_for_observation_and_rejects_later_observation() {
    let (release, gate) = oneshot::channel();
    let OwnerFixture {
        owner,
        observer,
        mut requests,
        mut terminal,
    } = observing_owner(vec![gate]);
    let observing = Arc::clone(&observer);
    let observation =
        tokio::spawn(async move { observing.observe_encoded_body(b"exact encoded body").await });
    assert_eq!(requests.recv().await, Some(b"exact encoded body".to_vec()));

    let expected = rejected_terminal();
    let mut finished = Box::pin(owner.finish(expected.clone()));
    assert!(finished.as_mut().now_or_never().is_none());
    assert!(matches!(terminal.try_recv(), Err(TryRecvError::Empty)));

    release.send(Ok(())).expect("release observation");
    observation
        .await
        .expect("observation task")
        .expect("observation succeeds");
    finished.await.expect("terminal acknowledged");
    assert_eq!(terminal.await.expect("terminal observed"), expected);
    assert_eq!(
        observer.observe_encoded_body(b"late body").await,
        Err(observation_stopped_error())
    );
}

#[tokio::test]
async fn cancelling_active_observation_returns_lease_to_dropped_owner() {
    let (_release, gate) = oneshot::channel();
    let OwnerFixture {
        owner,
        observer,
        mut requests,
        mut terminal,
    } = observing_owner(vec![gate]);
    let observing = Arc::clone(&observer);
    let observation =
        tokio::spawn(async move { observing.observe_encoded_body(b"cancelled body").await });
    assert_eq!(requests.recv().await, Some(b"cancelled body".to_vec()));

    drop(owner);
    assert!(matches!(terminal.try_recv(), Err(TryRecvError::Empty)));
    assert_eq!(
        observer
            .observe_encoded_body(b"after owner drop")
            .now_or_never(),
        Some(Err(observation_stopped_error()))
    );
    observation.abort();
    assert!(
        observation
            .await
            .expect_err("task cancelled")
            .is_cancelled()
    );
    assert_eq!(
        terminal.await.expect("fallback terminal"),
        ModelProviderTerminal::NotDispatched {
            reason_code: "model_provider_policy_owner_dropped_before_dispatch".to_owned(),
        }
    );
    assert_eq!(
        observer.observe_encoded_body(b"retained observer").await,
        Err(observation_stopped_error())
    );
}

#[tokio::test]
async fn observation_error_preserves_reason_and_returns_lease_for_terminal() {
    let (release, gate) = oneshot::channel();
    let OwnerFixture {
        owner,
        observer,
        mut requests,
        terminal,
    } = observing_owner(vec![gate]);
    release
        .send(Err(ModelProviderPolicyError::new(
            "test_observation_denied",
            "exact request was rejected",
        )))
        .expect("provide observation rejection");
    assert_eq!(
        observer.observe_encoded_body(b"rejected body").await,
        Err("test_observation_denied: exact request was rejected".to_owned())
    );
    assert_eq!(requests.recv().await, Some(b"rejected body".to_vec()));
    let expected = rejected_terminal();
    owner
        .finish(expected.clone())
        .await
        .expect("terminal acknowledged");
    assert_eq!(terminal.await.expect("terminal observed"), expected);
}

#[tokio::test]
async fn cancelled_queued_observer_does_not_consume_lease_or_run_callback() {
    let (release, gate) = oneshot::channel();
    let OwnerFixture {
        owner,
        observer,
        mut requests,
        terminal,
    } = observing_owner(vec![gate]);
    let observing = Arc::clone(&observer);
    let observation =
        tokio::spawn(async move { observing.observe_encoded_body(b"first body").await });
    assert_eq!(requests.recv().await, Some(b"first body".to_vec()));

    let mut queued = observer.observe_encoded_body(b"cancelled queued body");
    assert!(queued.as_mut().now_or_never().is_none());
    drop(queued);
    release.send(Ok(())).expect("release first observation");
    observation
        .await
        .expect("observation task")
        .expect("first observation succeeds");
    let expected = rejected_terminal();
    owner
        .finish(expected.clone())
        .await
        .expect("terminal after cancelled waiter");
    assert_eq!(terminal.await.expect("terminal observed"), expected);
    assert!(requests.try_recv().is_err());
}

#[tokio::test]
async fn cancelled_grant_receiver_returns_lease_before_and_after_send() {
    for cancel_after_send in [false, true] {
        let LeaseFixture {
            lease,
            requests: _requests,
            terminal,
        } = gated_lease(Vec::new());
        let (acknowledge, acknowledged) = oneshot::channel();
        let returned = if cancel_after_send {
            let mut lending = Box::pin(lend_lease_for_observation(lease, acknowledge));
            assert!(lending.as_mut().now_or_never().is_none());
            drop(acknowledged);
            lending.await
        } else {
            drop(acknowledged);
            lend_lease_for_observation(lease, acknowledge).await
        }
        .expect("cancelled grant returns the same lease");
        let expected = rejected_terminal();
        returned
            .finish(expected.clone())
            .await
            .expect("returned lease still completes");
        assert_eq!(terminal.await.expect("same lease terminal"), expected);
    }
}

#[tokio::test]
async fn stopped_supervisor_drops_returned_lease_without_false_terminal() {
    let LeaseFixture {
        lease,
        requests: _requests,
        terminal,
    } = gated_lease(Vec::new());
    let (acknowledge, acknowledged) = oneshot::channel();
    let mut lending = Box::pin(lend_lease_for_observation(lease, acknowledge));
    assert!(lending.as_mut().now_or_never().is_none());
    let observation = acknowledged.await.expect("loan was delivered");

    drop(lending);
    drop(observation);
    assert!(terminal.await.is_err());
}

#[tokio::test]
async fn stopped_supervisor_rejects_observation_with_live_sender() {
    let (commands, receiver) = mpsc::unbounded_channel();
    let observer = LeaseFinalRequestObserver {
        commands: commands.downgrade(),
    };
    drop(receiver);
    assert_eq!(
        observer.observe_encoded_body(b"no supervisor").await,
        Err(observation_stopped_error())
    );
}

#[tokio::test]
async fn terminal_persistence_does_not_delay_rejection_of_later_observation() {
    let (started, observed_terminal) = oneshot::channel();
    let (release, persist) = oneshot::channel();
    let owner = ProviderAttemptOwner::new_with_dispatch_probe(
        Box::new(GatedFinishLease {
            started,
            release: persist,
        }),
        Box::new(|| false),
    );
    let observer = LeaseFinalRequestObserver {
        commands: owner.commands.downgrade(),
    };
    let expected = rejected_terminal();
    let finish = tokio::spawn(owner.finish(expected.clone()));
    assert_eq!(
        observed_terminal
            .await
            .expect("terminal persistence started"),
        expected
    );
    assert_eq!(
        observer
            .observe_encoded_body(b"after terminal selection")
            .now_or_never(),
        Some(Err(observation_stopped_error()))
    );
    release.send(Ok(())).expect("commit terminal");
    finish
        .await
        .expect("terminal task")
        .expect("terminal acknowledged");
}
