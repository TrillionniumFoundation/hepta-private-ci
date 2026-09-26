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
    let records_per_peer = std::env::var("HEPTA_FEDERATION_MEASUREMENT_RECORDS")
        .map_or(8, |value| value.parse::<usize>().expect("record count"));
    assert!((1..=128).contains(&records_per_peer));
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
        for record in 0..records_per_peer {
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
        for _ in 0..100 {
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
        let database_bytes: u64 = owners
            .iter()
            .map(|owner| {
                std::fs::metadata(owner.path())
                    .expect("owner database size")
                    .len()
            })
            .sum();
        let wal_bytes: u64 = owners
            .iter()
            .map(|owner| {
                let mut path = owner.path().as_os_str().to_os_string();
                path.push("-wal");
                std::fs::metadata(std::path::PathBuf::from(path)).map_or(0, |m| m.len())
            })
            .sum();
        let peak_rss_kib = std::fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|status| {
                status
                    .lines()
                    .find(|line| line.starts_with("VmHWM:"))
                    .and_then(|line| line.split_whitespace().nth(1))
                    .and_then(|value| value.parse::<u64>().ok())
            });
        println!(
            "FEDERATION_LOCAL_MEASUREMENT {}",
            serde_json::json!({
                "profile":"local-sqlite-debug-smoke-not-production-slo",
                "peers":count,"records_per_peer":records_per_peer,"samples":100,
                "recall_us":recall_us,"final_use_us":final_use_us,
                "recall_p50_us":recall_us[49],"recall_p95_us":recall_us[94],
                "recall_p99_us":recall_us[98],"recall_max_us":recall_us[99],
                "final_use_p50_us":final_use_us[49],"final_use_p95_us":final_use_us[94],
                "final_use_p99_us":final_use_us[98],"final_use_max_us":final_use_us[99],
                "all_peers_completed":true,"failed_peers":0,
                "database_bytes":database_bytes,"wal_bytes":wal_bytes,"peak_rss_kib":peak_rss_kib,
                "os":std::env::consts::OS,"arch":std::env::consts::ARCH
            })
        );
    }
    drop(owners);
}
