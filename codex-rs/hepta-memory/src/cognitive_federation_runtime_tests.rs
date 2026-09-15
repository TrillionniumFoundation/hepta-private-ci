use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::FederatedRecallSet;
use crate::FederationConsumerAccess;
use crate::FederationGrantRequest;
use crate::FederationGrantScope;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn deadline_preserves_completed_reads() {
    let batch = bounded(
        vec![0, 1],
        Instant::now() + Duration::from_millis(100),
        |value| async move {
            if value == 1 {
                std::future::pending::<()>().await;
            }
            value
        },
    )
    .await;
    assert_eq!(batch.values, vec![0]);
    assert!(batch.incomplete);
}

#[tokio::test]
async fn concurrency_is_bounded_and_output_order_is_stable() {
    let active = Arc::new(AtomicUsize::new(0));
    let peak = Arc::new(AtomicUsize::new(0));
    let batch = bounded(
        (0..12).collect(),
        Instant::now() + Duration::from_secs(5),
        |value| {
            let active = Arc::clone(&active);
            let peak = Arc::clone(&peak);
            async move {
                let concurrent = active.fetch_add(1, Ordering::SeqCst) + 1;
                peak.fetch_max(concurrent, Ordering::SeqCst);
                tokio::time::sleep(Duration::from_millis(2)).await;
                active.fetch_sub(1, Ordering::SeqCst);
                value
            }
        },
    )
    .await;
    assert_eq!(batch.values, (0..12).collect::<Vec<_>>());
    assert!(!batch.incomplete);
    assert!(peak.load(Ordering::SeqCst) <= MAX_IN_FLIGHT);
    assert_eq!(active.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn cached_connections_do_not_cache_grants_or_revocations() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(84);
    let consumer_id = agent_id(85);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout).await.expect("store");
    let scope = workspace("pooled-reader");
    let access = CognitiveAccess::agent_private(owner_id.clone());
    let consumer = FederationConsumerAccess::new(consumer_id.clone(), scope.clone());
    let set = FederatedRecallSet::discover(consumer_id.clone(), vec![owner_layout], 100).await;
    let request = RetrievalRequest::new("example", 150);
    let before = set.retrieve(&consumer, &request).await.expect("before grant");
    assert!(before.discovery_complete);
    assert_eq!(before.queried_sources, 0);
    let grant = owner
        .grant_federated_recall(
            &access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id,
                scope: FederationGrantScope::new(CognitiveScope::AgentPrivate, scope),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1000,
            },
        )
        .await
        .expect("grant");
    let during = set
        .retrieve(&consumer, &request)
        .await
        .expect("new grant is visible");
    assert!(during.discovery_complete);
    assert_eq!((during.queried_sources, during.unavailable_sources), (1, 0));
    owner
        .revoke_federated_recall(&access, &grant, 150)
        .await
        .expect("revoke");
    let after = set
        .retrieve(&consumer, &request)
        .await
        .expect("revocation is visible");
    assert!(after.discovery_complete);
    assert_eq!(after.queried_sources, 0);
}

#[tokio::test]
async fn missing_source_is_not_reported_as_complete_empty_recall() {
    let temp = TempDir::new().expect("temp dir");
    let consumer_id = agent_id(86);
    let missing = layout(&temp, &agent_id(87));
    let set = FederatedRecallSet::discover(consumer_id.clone(), vec![missing], 100).await;
    let access = FederationConsumerAccess::new(consumer_id, workspace("consumer"));
    let batch = set
        .retrieve(&access, &RetrievalRequest::new("example", 150))
        .await
        .expect("degraded recall");
    assert!(batch.candidates.is_empty());
    assert!(!batch.discovery_complete);
}
