use std::fs;
use std::time::Instant;

use serde_json::json;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::LedgerSourceKind;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::RetrievalRequest;
use crate::SourceDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

const DEFAULT_WRITES: usize = 256;
const ENTITIES_PER_WRITE: usize = 16;
const RELATIONS_PER_WRITE: usize = 128;
const DEFAULT_QUERY_SAMPLES: usize = 20;
const DEFAULT_REOPEN_SAMPLES: usize = 5;

fn configured_count(name: &str, default: usize, maximum: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0 && *value <= maximum)
        .unwrap_or(default)
}

fn facts() -> KgFactSetDraft {
    let entities = (0..ENTITIES_PER_WRITE)
        .map(|index| KgEntityFactDraft {
            key: format!("bench-node-{index:02}"),
            entity_type: "benchmark_entity".to_string(),
            label: format!("Benchmark Graph Node {index:02}"),
        })
        .collect::<Vec<_>>();
    let relations = (0..RELATIONS_PER_WRITE)
        .map(|index| KgRelationFactDraft {
            key: format!("bench-relation-{index:03}"),
            from_entity_key: format!("bench-node-{:02}", index % ENTITIES_PER_WRITE),
            to_entity_key: format!(
                "bench-node-{:02}",
                (index.wrapping_mul(7).wrapping_add(1)) % ENTITIES_PER_WRITE
            ),
            relation: format!("benchmark_relation_{index:03}"),
        })
        .collect();
    KgFactSetDraft {
        entities,
        relations,
    }
}

fn percentile_ns(samples: &[u64], percentile: usize) -> u64 {
    assert!(!samples.is_empty());
    let mut ordered = samples.to_vec();
    ordered.sort_unstable();
    let numerator = (ordered.len() - 1).saturating_mul(percentile);
    let index = numerator.saturating_add(99) / 100;
    ordered[index.min(ordered.len() - 1)]
}

fn elapsed_ns(start: Instant) -> u64 {
    u64::try_from(start.elapsed().as_nanos()).unwrap_or(u64::MAX)
}

fn file_size(path: &std::path::Path) -> u64 {
    fs::metadata(path).map(|value| value.len()).unwrap_or(0)
}

#[cfg(target_os = "linux")]
fn linux_rss_kib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        let rest = line.strip_prefix("VmRSS:")?;
        rest.split_whitespace().next()?.parse().ok()
    })
}

#[cfg(not(target_os = "linux"))]
fn linux_rss_kib() -> Option<u64> {
    None
}

#[cfg(target_os = "linux")]
fn linux_cpu_ticks() -> Option<u64> {
    let stat = fs::read_to_string("/proc/self/stat").ok()?;
    let close = stat.rfind(')')?;
    let fields = stat
        .get(close + 1..)?
        .split_whitespace()
        .collect::<Vec<_>>();
    let user = fields.get(11)?.parse::<u64>().ok()?;
    let system = fields.get(12)?.parse::<u64>().ok()?;
    user.checked_add(system)
}

#[cfg(not(target_os = "linux"))]
fn linux_cpu_ticks() -> Option<u64> {
    None
}

/// Capacity receipt for the currently selected durable algorithm.
///
/// This is intentionally ignored in ordinary unit lanes. It executes real
/// CognitiveStore writes, product retrieval and ordinary reopen. It reports
/// measurements rather than inventing a host-independent latency threshold.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "qualification: knowledge.graph PERF-LIBRARY capacity receipt"]
async fn qualification_knowledge_graph_capacity_receipt() {
    let writes = configured_count("HEPTA_KG_BENCH_WRITES", DEFAULT_WRITES, DEFAULT_WRITES);
    let query_samples =
        configured_count("HEPTA_KG_BENCH_QUERY_SAMPLES", DEFAULT_QUERY_SAMPLES, 100);
    let reopen_samples =
        configured_count("HEPTA_KG_BENCH_REOPEN_SAMPLES", DEFAULT_REOPEN_SAMPLES, 20);

    eprintln!("KG_PHASE open writes={writes} queries={query_samples} reopens={reopen_samples}");
    let benchmark_started = Instant::now();
    let temp = TempDir::new().expect("KG benchmark temp dir");
    let owner = agent_id(185);
    let owner_layout = layout(&temp, &owner);
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("KG benchmark store");
    eprintln!(
        "KG_PHASE write start elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );
    let facts = facts();

    let cpu_before = linux_cpu_ticks();
    let rss_before = linux_rss_kib();
    let total_write_start = Instant::now();
    let mut mutation_ns = Vec::with_capacity(writes);
    for index in 0..writes {
        let content = format!("Benchmark graph memory {index:04}");
        let started = Instant::now();
        store
            .remember_with_kg(
                &access,
                &SourceDraft {
                    scope: scope.clone(),
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: format!("kg-benchmark-source-{index:04}"),
                    content: content.as_bytes().to_vec(),
                    observed_at_unix_seconds: 100,
                },
                &MemoryDraft {
                    stable_key: format!("kg-benchmark-memory-{index:04}"),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content,
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: Vec::new(),
                    },
                },
                &facts,
            )
            .await
            .expect("KG benchmark mutation");
        mutation_ns.push(elapsed_ns(started));
        if (index + 1).is_power_of_two() || index + 1 == writes {
            eprintln!(
                "KG_PHASE write completed={} total_ms={} last_ns={}",
                index + 1,
                total_write_start.elapsed().as_millis(),
                mutation_ns.last().copied().unwrap_or(0)
            );
        }
    }
    let total_write_ns = elapsed_ns(total_write_start);

    let current_generation: i64 =
        sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
            .bind(scope.projection_key())
            .fetch_one(&store.pool)
            .await
            .expect("KG benchmark current generation");
    let physical_counts: (i64, i64) = sqlx::query_as(
        "SELECT
            (SELECT COUNT(*) FROM kg_nodes
             WHERE projection_scope = ? AND generation = ?),
            (SELECT COUNT(*) FROM kg_edges
             WHERE projection_scope = ? AND generation = ?)",
    )
    .bind(scope.projection_key())
    .bind(current_generation)
    .bind(scope.projection_key())
    .bind(current_generation)
    .fetch_one(&store.pool)
    .await
    .expect("KG benchmark current-generation physical counts");
    assert_eq!(
        physical_counts,
        (
            i64::try_from(writes * ENTITIES_PER_WRITE).expect("bounded node count"),
            i64::try_from(writes * RELATIONS_PER_WRITE).expect("bounded edge count"),
        ),
    );
    let historical_physical_counts: (i64, i64) = sqlx::query_as(
        "SELECT
            (SELECT COUNT(*) FROM kg_nodes WHERE projection_scope = ?),
            (SELECT COUNT(*) FROM kg_edges WHERE projection_scope = ?)",
    )
    .bind(scope.projection_key())
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("KG benchmark historical physical counts");
    assert!(
        historical_physical_counts.0 >= physical_counts.0
            && historical_physical_counts.1 >= physical_counts.1,
        "historical append-only rows cannot be smaller than the selected generation"
    );

    eprintln!(
        "KG_PHASE query elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );
    let mut query_ns = Vec::with_capacity(query_samples);
    for _ in 0..query_samples {
        let started = Instant::now();
        let result = store
            .retrieve_memory_candidates(&access, &RetrievalRequest::new("Benchmark Graph", 200))
            .await
            .expect("KG benchmark retrieval");
        assert!(
            !result.candidates.is_empty(),
            "KG benchmark query returned empty"
        );
        query_ns.push(elapsed_ns(started));
    }

    let database_path = store.path().to_path_buf();
    let wal_path = database_path.with_extension("sqlite3-wal");
    let database_bytes = file_size(&database_path);
    let wal_bytes = file_size(&wal_path);
    eprintln!(
        "KG_PHASE close elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );
    store.pool.close().await;
    eprintln!(
        "KG_PHASE reopen elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );

    let mut reopen_ns = Vec::with_capacity(reopen_samples);
    for _ in 0..reopen_samples {
        let started = Instant::now();
        let reopened = CognitiveStore::open(&owner_layout)
            .await
            .expect("KG benchmark reopen");
        reopen_ns.push(elapsed_ns(started));
        reopened.pool.close().await;
        eprintln!(
            "KG_PHASE reopened={} elapsed_ms={}",
            reopen_ns.len(),
            benchmark_started.elapsed().as_millis()
        );
    }

    let cpu_after = linux_cpu_ticks();
    let rss_after = linux_rss_kib();
    let cpu_ticks_delta = cpu_before
        .zip(cpu_after)
        .and_then(|(before, after)| after.checked_sub(before));

    let receipt = json!({
        "schema": "hepta.knowledge-graph-perf-library.v1",
        "algorithm": "complete_generation_per_logical_mutation",
        "writes": writes,
        "currentGeneration": current_generation,
        "physicalNodes": physical_counts.0,
        "physicalEdges": physical_counts.1,
        "historicalPhysicalNodeRows": historical_physical_counts.0,
        "historicalPhysicalEdgeRows": historical_physical_counts.1,
        "querySamples": query_samples,
        "reopenSamples": reopen_samples,
        "mutationNs": {
            "p50": percentile_ns(&mutation_ns, 50),
            "p95": percentile_ns(&mutation_ns, 95),
            "p99": percentile_ns(&mutation_ns, 99),
            "total": total_write_ns,
            "throughputMilliOpsPerSecond": u64::try_from(writes)
                .unwrap_or(u64::MAX)
                .saturating_mul(1_000_000_000_000)
                / total_write_ns.max(1),
        },
        "queryNs": {
            "p50": percentile_ns(&query_ns, 50),
            "p95": percentile_ns(&query_ns, 95),
            "p99": percentile_ns(&query_ns, 99),
        },
        "reopenNs": {
            "p50": percentile_ns(&reopen_ns, 50),
            "p95": percentile_ns(&reopen_ns, 95),
            "p99": percentile_ns(&reopen_ns, 99),
        },
        "storage": {
            "databaseBytes": database_bytes,
            "walBytes": wal_bytes,
        },
        "process": {
            "rssKiBBefore": rss_before,
            "rssKiBAfter": rss_after,
            "linuxCpuTicksDelta": cpu_ticks_delta,
        },
        "claim": "measurement_only_no_host_independent_latency_threshold",
    });
    println!(
        "HEPTA_KNOWLEDGE_GRAPH_PERF_RECEIPT={}",
        serde_json::to_string(&receipt).expect("serialize KG performance receipt")
    );
}
