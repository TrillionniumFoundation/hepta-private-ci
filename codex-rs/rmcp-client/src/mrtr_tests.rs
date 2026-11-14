use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;

#[test]
fn whole_batch_reservation_is_atomic_and_cumulative() {
    let owner = InputRequestOwner::new();
    let reference = owner.reference();
    assert!(reference.reserve(/*count*/ 63).is_ok());
    assert!(reference.reserve(/*count*/ 2).is_err());
    assert!(reference.reserve(/*count*/ 1).is_ok());
    assert!(reference.reserve(/*count*/ 1).is_err());
}

#[test]
fn concurrent_batches_share_one_budget_and_other_owners_are_independent() {
    let owner = InputRequestOwner::new();
    let attempts = std::thread::scope(|scope| {
        let first = owner.reference();
        let second = owner.reference();
        let first = scope.spawn(move || first.reserve(/*count*/ 40).is_ok());
        let second = scope.spawn(move || second.reserve(/*count*/ 40).is_ok());
        [first.join().unwrap(), second.join().unwrap()]
    });
    assert_eq!(attempts.into_iter().filter(|accepted| *accepted).count(), 1);
    assert!(
        InputRequestOwner::new()
            .reference()
            .reserve(/*count*/ 64)
            .is_ok()
    );
}

#[tokio::test]
async fn unknown_expired_and_cancelled_owners_do_not_start_callbacks() {
    let started = AtomicUsize::new(0);
    let owner = InputRequestOwner::new();
    let reference = owner.reference();
    let input = reference.reserve(/*count*/ 1).unwrap();
    input.cancellation.cancel();
    assert!(
        input
            .run(CancellationToken::new(), || async {
                started.fetch_add(/*val*/ 1, Ordering::SeqCst);
                Ok(())
            })
            .await
            .is_err()
    );
    drop(owner);
    for input in [
        input,
        OwnedInputContext {
            owner: Weak::new(),
            cancellation: CancellationToken::new(),
        },
    ] {
        assert!(
            input
                .run(CancellationToken::new(), || async {
                    started.fetch_add(/*val*/ 1, Ordering::SeqCst);
                    Ok(())
                })
                .await
                .is_err()
        );
    }
    assert_eq!(started.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn dropping_parent_cancels_and_drops_the_pending_callback() {
    struct PendingGuard(Arc<AtomicUsize>);
    impl Drop for PendingGuard {
        fn drop(&mut self) {
            self.0.fetch_sub(/*val*/ 1, Ordering::SeqCst);
        }
    }

    let pending = Arc::new(AtomicUsize::new(0));
    let owner = InputRequestOwner::new();
    let reference = owner.reference();
    let input = reference.reserve(/*count*/ 1).unwrap();
    let observed = Arc::clone(&pending);
    let (started, ready) = tokio::sync::oneshot::channel();
    let response = tokio::spawn(async move {
        // Even an independent caller token cannot detach work from its owner.
        input
            .run(CancellationToken::new(), || async move {
                observed.fetch_add(/*val*/ 1, Ordering::SeqCst);
                let _guard = PendingGuard(observed);
                started.send(()).unwrap();
                std::future::pending::<Result<(), ErrorData>>().await
            })
            .await
    });
    ready.await.unwrap();
    assert_eq!(pending.load(Ordering::SeqCst), 1);
    drop(owner);
    assert!(
        tokio::time::timeout(Duration::from_secs(5), response)
            .await
            .unwrap()
            .unwrap()
            .is_err()
    );
    assert_eq!(pending.load(Ordering::SeqCst), 0);
    assert!(reference.reserve(/*count*/ 1).is_err());
}

#[tokio::test]
async fn cancellation_removes_a_backpressured_prompt_before_it_can_be_published() {
    let (sender, mut receiver) = tokio::sync::mpsc::channel(1);
    sender.send("occupied").await.unwrap();
    let owner = InputRequestOwner::new();
    let reference = owner.reference();
    let input = reference.reserve(/*count*/ 1).unwrap();
    let response = input.run(CancellationToken::new(), || async {
        sender.send("prompt").await.unwrap();
        Ok(())
    });
    tokio::pin!(response);
    assert!(futures::poll!(&mut response).is_pending());
    drop(owner);
    assert!(response.await.is_err());
    assert_eq!(receiver.recv().await, Some("occupied"));
    assert!(receiver.try_recv().is_err());
}

#[tokio::test]
async fn modern_elicitation_requires_a_live_private_owner_and_legacy_keeps_its_contract() {
    use crate::rmcp_client::ElicitationPauseState;
    use crate::rmcp_client::ElicitationResponse;
    use futures::FutureExt;
    use rmcp::model::ClientCapabilities;
    use rmcp::model::ClientInfo;
    use rmcp::model::ElicitationAction;
    use rmcp::model::Implementation;
    use rmcp::model::ProtocolVersion;
    use rmcp::model::ServerCapabilities;
    use rmcp::model::ServerInfo;

    let started = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&started);
    let service = ElicitationClientService::new(
        ClientInfo::new(
            ClientCapabilities::default(),
            Implementation::new("owner-test", "1"),
        ),
        Box::new(move |_, _| {
            observed.fetch_add(/*val*/ 1, Ordering::SeqCst);
            async {
                Ok(ElicitationResponse {
                    action: ElicitationAction::Accept,
                    content: None,
                    meta: None,
                })
            }
            .boxed()
        }),
        ElicitationPauseState::new(),
    );
    let (transport, _remote) = tokio::io::duplex(1024);
    let running = rmcp::service::serve_directly(
        service,
        transport,
        Some(
            ServerInfo::new(ServerCapabilities::default())
                .with_protocol_version(ProtocolVersion::V_2026_07_28)
                .into(),
        ),
    );
    let request = || {
        serde_json::from_value::<ServerRequest>(serde_json::json!({
            "method": "elicitation/create",
            "params": {
                "mode": "form", "message": "Confirm?",
                "requestedSchema": {"type": "object", "properties": {}},
                "_meta": {"owner": "remote-owner", "requestId": "remote-request"},
            },
        }))
        .unwrap()
    };
    let context = || {
        RequestContext::new(
            NumberOrString::String("remote-owner".into()),
            running.peer().clone(),
        )
    };
    assert!(
        running
            .service()
            .handle_request(request(), context())
            .await
            .is_err()
    );
    let owner = InputRequestOwner::new();
    let reference = owner.reference();
    let input = reference.reserve(/*count*/ 1).unwrap();
    let mut expired = context();
    expired.extensions.insert(input);
    drop(owner);
    assert!(
        running
            .service()
            .handle_request(request(), expired)
            .await
            .is_err()
    );
    let owner = InputRequestOwner::new();
    let mut cancelled = context();
    cancelled
        .extensions
        .insert(owner.reference().reserve(/*count*/ 1).unwrap());
    cancelled.ct.cancel();
    assert!(
        running
            .service()
            .handle_request(request(), cancelled)
            .await
            .is_err()
    );
    assert_eq!(started.load(Ordering::SeqCst), 0);
    running.peer().set_peer_info(
        ServerInfo::new(ServerCapabilities::default())
            .with_protocol_version(ProtocolVersion::V_2025_06_18)
            .into(),
    );
    assert!(
        running
            .service()
            .handle_request(request(), context())
            .await
            .is_ok()
    );
    assert_eq!(started.load(Ordering::SeqCst), 1);
    running.cancel().await.unwrap();
}
