use futures::poll;
use pretty_assertions::assert_eq;

use super::HttpRequestScopes;
use super::MAX_ACTIVE_HTTP_STREAMS;
use super::ScopedHttpFuture;
use crate::protocol::HttpRequestCancelResponse;

#[tokio::test]
async fn cancellation_waits_for_original_owner_and_does_not_cancel_another_scope() {
    let scopes = HttpRequestScopes::default();
    let original = scopes.reserve("original").expect("original scope");
    let other = scopes.reserve("other").expect("independent scope");
    let mut cancellation = Box::pin(scopes.cancel("original"));
    assert!(poll!(cancellation.as_mut()).is_pending());
    assert!(original.cancellation().is_cancelled());
    assert!(!other.cancellation().is_cancelled());
    drop(original);
    assert_eq!(cancellation.await, HttpRequestCancelResponse::Cancelled);
    assert_eq!(
        scopes.cancel("original").await,
        HttpRequestCancelResponse::NotActive
    );
    assert!(!other.cancellation().is_cancelled());
}

#[test]
fn admission_is_bounded_and_owner_drop_releases_capacity() {
    let scopes = HttpRequestScopes::default();
    let mut owners = (0..MAX_ACTIVE_HTTP_STREAMS)
        .map(|id| scopes.reserve(&format!("http-{id}")).expect("capacity"))
        .collect::<Vec<_>>();
    assert!(scopes.reserve("http-0").is_err());
    assert!(scopes.reserve("extra").is_err());
    assert!(scopes.reserve(&"x".repeat(129)).is_err());
    drop(owners.pop());
    assert!(scopes.reserve("extra").is_ok());
}

#[tokio::test]
async fn unpolled_producer_drops_network_before_completion_acknowledgement() {
    struct Network(tokio_util::sync::CancellationToken);
    impl Drop for Network {
        fn drop(&mut self) {
            assert!(
                !self.0.is_cancelled(),
                "network must drop before finished token"
            );
        }
    }
    let scopes = HttpRequestScopes::default();
    let scope = scopes.reserve("unpolled").expect("scope");
    let finished = scope.state.finished.clone();
    let network = Network(finished.clone());
    let producer = ScopedHttpFuture::new(
        async move {
            std::future::pending::<()>().await;
            drop(network);
        },
        scope,
    );
    let mut cancel = Box::pin(scopes.cancel("unpolled"));
    assert!(poll!(cancel.as_mut()).is_pending());
    drop(producer);
    assert!(finished.is_cancelled());
    assert_eq!(cancel.await, HttpRequestCancelResponse::Cancelled);
}
