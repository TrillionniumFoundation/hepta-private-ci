//! Measured concurrency and cancellation at the product discovery seam.
use super::ProductDiscoveryFuture;
use super::retrieve_federated_product_with_discoverer;
use crate::FederationConsumerAccess;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::workspace;
use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaAgentLayout;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tempfile::TempDir;

#[tokio::test]
async fn discovery_caps_active_owners_and_drops_every_pending_attempt() {
    static ACTIVE: AtomicUsize = AtomicUsize::new(0);
    static PEAK: AtomicUsize = AtomicUsize::new(0);
    struct Active;
    impl Drop for Active {
        fn drop(&mut self) {
            ACTIVE.fetch_sub(1, Ordering::SeqCst);
        }
    }
    fn stalled<'a>(_: &'a HeptaAgentLayout, _: &'a AgentId, _: i64) -> ProductDiscoveryFuture<'a> {
        Box::pin(async {
            let _guard = Active;
            let current = ACTIVE.fetch_add(1, Ordering::SeqCst) + 1;
            PEAK.fetch_max(current, Ordering::SeqCst);
            std::future::pending().await
        })
    }
    let temp = TempDir::new().expect("temporary owner paths");
    let consumer = agent_id(250);
    let owners = (1..=128)
        .map(|id| layout(&temp, &agent_id(id)))
        .collect::<Vec<_>>();
    let access = FederationConsumerAccess::new(consumer.clone(), workspace("bounded-discovery"));
    let (batch, coverage) = retrieve_federated_product_with_discoverer(
        &consumer,
        &owners,
        0,
        &access,
        &RetrievalRequest::new("bounded", 150),
        Duration::from_millis(100),
        stalled,
    )
    .await
    .expect("pending owners produce bounded failed coverage");
    assert!(batch.candidates.is_empty());
    assert_eq!(coverage.requested_peers, 16);
    assert_eq!(coverage.failed_peers, 16);
    assert_eq!(coverage.completed_peers, 0);
    assert_eq!(coverage.truncated_peers, 112);
    assert_eq!(coverage.failures.deadline_or_cancelled, 16);
    assert_eq!(ACTIVE.load(Ordering::SeqCst), 0);
    assert_eq!(PEAK.load(Ordering::SeqCst), 8);
}

#[tokio::test]
async fn timed_out_first_wave_does_not_starve_queued_healthy_owner() {
    static HEALTHY: AtomicUsize = AtomicUsize::new(0);
    fn discover<'a>(
        owner: &'a HeptaAgentLayout,
        _: &'a AgentId,
        _: i64,
    ) -> ProductDiscoveryFuture<'a> {
        Box::pin(async move {
            if owner.agent_id() == &agent_id(9) {
                HEALTHY.fetch_add(1, Ordering::SeqCst);
                Ok(Vec::new())
            } else {
                std::future::pending().await
            }
        })
    }
    let temp = TempDir::new().expect("temporary owner paths");
    let consumer = agent_id(250);
    let owners = (1..=9)
        .map(|id| layout(&temp, &agent_id(id)))
        .collect::<Vec<_>>();
    let access = FederationConsumerAccess::new(consumer.clone(), workspace("queued-discovery"));
    let (batch, coverage) = retrieve_federated_product_with_discoverer(
        &consumer,
        &owners,
        0,
        &access,
        &RetrievalRequest::new("queued", 150),
        Duration::from_secs(1),
        discover,
    )
    .await
    .expect("later healthy owner remains observable");
    assert!(batch.candidates.is_empty());
    assert_eq!(HEALTHY.load(Ordering::SeqCst), 1);
    assert_eq!(coverage.requested_peers, 8);
    assert_eq!(coverage.failed_peers, 8);
    assert_eq!(coverage.failures.deadline_or_cancelled, 8);
    assert_eq!(coverage.truncated_peers, 0);
}
