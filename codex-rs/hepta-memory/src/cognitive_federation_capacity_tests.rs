//! Explicit local fan-out measurement; not a production or cross-host SLO.
use crate::CognitiveAccess;
use crate::CognitiveRuntime;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::FederatedRevalidationStatus;
use crate::FederationConsumerAccess;
use crate::FederationGrantRequest;
use crate::FederationGrantScope;
use crate::MemoryDraft;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;
use std::time::Instant;
use tempfile::TempDir;

#[tokio::test]
#[ignore = "explicit local fan-out measurement with real SQLite owners"]
async fn federation_product_local_capacity_measurement() {
    let temp = TempDir::new().expect("temporary owners");
    let consumer_id = agent_id(240);
    let consumer = CognitiveStore::open(&layout(&temp, &consumer_id))
        .await
        .expect("consumer");
    let workspace = workspace("federation-capacity");
    let access = FederationConsumerAccess::new(consumer_id.clone(), workspace.clone());
    let mut owners = Vec::new();
    let mut layouts = Vec::new();
    for count in 1_u8..=16 {
        let owner_id = agent_id(count);
        let owner_layout = layout(&temp, &owner_id);
        let store = CognitiveStore::open(&owner_layout).await.expect("owner");
        let owner_access = CognitiveAccess::agent_private(owner_id);
        for record in 0..8 {
            let key = format!("capacity-{record}");
            let citation = store
                .append_source(
                    &owner_access,
                    &source(
                        CognitiveScope::AgentPrivate,
                        &key,
                        "Federation capacity measured evidence.",
                    ),
                )
                .await
                .expect("source");
            store
                .remember_memory(
                    &owner_access,
                    &MemoryDraft {
                        stable_key: key,
                        revision: memory_revision(
                            CognitiveScope::AgentPrivate,
                            "Federation capacity measured evidence.",
                            citation,
                        ),
                    },
                )
                .await
                .expect("memory");
        }
        store
            .grant_federated_recall(
                &owner_access,
                &FederationGrantRequest {
                    consumer_agent_id: consumer_id.clone(),
                    scope: FederationGrantScope::new(
                        CognitiveScope::AgentPrivate,
                        workspace.clone(),
                    ),
                    effective_at_unix_seconds: 100,
                    expires_at_unix_seconds: 1000,
                },
            )
            .await
            .expect("grant");
        layouts.push(owner_layout);
        owners.push(store);
        if ![1, 4, 16].contains(&count) {
            continue;
        }
        let runtime = CognitiveRuntime::from_open_result(Ok(consumer.clone()))
            .with_federation_sources(consumer_id.clone(), layouts.clone());
        let mut recall_us = Vec::new();
        let mut final_use_us = Vec::new();
        for _ in 0..5 {
            let start = Instant::now();
            let (batch, coverage) = runtime
                .retrieve_product_federated(
                    &access,
                    &RetrievalRequest::new("Federation capacity", 150),
                )
                .await
                .expect("recall");
            recall_us.push(start.elapsed().as_micros());
            assert_eq!(coverage.completed_peers, u32::from(count));
            assert_eq!(coverage.failed_peers, 0);
            assert!(!batch.candidates.is_empty());
            let bindings = batch
                .candidates
                .iter()
                .map(|c| c.revalidation.clone())
                .collect::<Vec<_>>();
            let start = Instant::now();
            let statuses = runtime
                .revalidate_product_federated_batch(&access, &bindings, 150)
                .await
                .expect("final-use revalidation");
            final_use_us.push(start.elapsed().as_micros());
            assert_eq!(statuses.len(), bindings.len());
            assert!(
                statuses
                    .iter()
                    .all(|s| matches!(s, FederatedRevalidationStatus::Current(_)))
            );
        }
        recall_us.sort_unstable();
        final_use_us.sort_unstable();
        println!(
            "FEDERATION_LOCAL_MEASUREMENT {}",
            serde_json::json!({
                "profile":"local-sqlite-debug-smoke-not-production-slo",
                "peers":count,"records_per_peer":8,"samples":5,
                "recall_us":recall_us,"final_use_us":final_use_us,
                "recall_median_us":recall_us[2],"recall_max_us":recall_us[4],
                "final_use_median_us":final_use_us[2],"final_use_max_us":final_use_us[4],
                "all_peers_completed":true,"failed_peers":0
            })
        );
    }
    drop(owners);
}
